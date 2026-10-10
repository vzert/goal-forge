"""Shared terminal-action detection + content exemption + operative-verdict reading.

ONE source of truth for THREE enforcement points that must never drift apart:
  * hooks/precheck-terminal-push.sh (PreToolUse) — blocks a push/merge/deploy BEFORE it runs.
  * hooks/gate-goal-close.sh (Stop) — the goal-spec-presence precondition itself, AND a staleness
    backstop for when the PreToolUse hook above is bypassed, disabled, or its content-exemption
    call turns out wrong.
  * hooks/check-usage-budget.sh (Stop, opt-in) — same goal-spec-presence precondition as the gate.

Why this exists as a real shared file instead of N copies of the same regex list: the incident
that motivated it (2026-08-01, worker-cloudflare) was a completion-review declared correctly
BEFORE a merge, silently left standing as "satisfied" through the merge+deploy that followed in
the next turn — nothing re-checked it. If a memory-only-commit exemption is added to one enforcement
point and not the others, a checkpoint push starts tripping (or a real push starts NOT tripping)
only SOME of the consumers, and that asymmetry is invisible until someone hits it live — this
happened TWICE while shipping this very file (a `goal-adversary` round found the goal-spec-via-
checkpoint-file signal missing from gate-goal-close.sh's own precondition and from
check-usage-budget.sh after it had already been added here and to precheck-terminal-push.sh; the
fix was adding the two missing call sites, not duplicating the logic). See CHANGELOG for the
version that added this and the rounds that found the gaps.

Fail-open is a caller responsibility, not this module's: every function here returns None / False /
empty on its own internal errors (git missing, path unreadable, malformed transcript) rather than
raising, so a caller can treat "could not determine" as "do not block" without a try/except at
every call site. What a caller does with an unknown result is a POLICY decision (this module states
in each docstring which direction is safe) — this module only ever reports what it found.
"""
import json
import os
import re
import shlex
import subprocess
import tempfile

# --- content exemption ---------------------------------------------------------------------------
# Paths considered low-blast-radius regardless of which terminal command touches them — a
# memory/docs checkpoint commit is not what this gate exists to catch (real transcript evidence:
# /checkpoint-3t pushes session notes to main in repos that also run goalspec on real code).
#
# KNOWN, ACCEPTED GAP — read before widening this list or trusting it for more than it claims:
# this is a PATH exemption, and "routine session checkpoint" vs. "an unconfirmed conclusion
# written into shared/durable state" (SKILL.md's own terminal-action list names the latter
# explicitly) are a CONTENT distinction that commonly share the exact same paths — a wrong
# conclusion lands in memory/learnings/ or memory/_pendientes.md exactly like a routine session
# log does. references/mid-session-retrigger.md documents a real incident of that second shape
# and explains why this project does not believe a matcher can chase it (three prior attempts —
# a model-id string matcher, a verdict-text dedup, a loop-boundary counter — each lost that
# arms race). This module does not attempt to. A push this module exempts is evidence about
# CODE risk only; it is never evidence that a conclusion inside the exempted files was reviewed.
EXEMPT_PREFIXES = ("memory/", "docs/", ".goalspec/")


def is_path_exempt(path):
    path = path.strip()
    if not path:
        return True  # a blank line from a trailing newline carries no content
    if path.startswith(EXEMPT_PREFIXES):
        return True
    if "/" not in path and path.endswith(".md"):
        return True  # root-level CHANGELOG.md, README.md, etc.
    return False


def all_exempt(paths):
    """None/empty input is NOT exempt — 'could not determine what changed' must fall through to
    the terminal-action policy, never silently wave a push through."""
    if not paths:
        return False
    return all(is_path_exempt(p) for p in paths)


# --- terminal command classification --------------------------------------------------------------
FORCE_FLAG_RE = re.compile(r"(^|\s)(-f|--force|--force-with-lease(=\S*)?|--force-if-includes)(\s|$)")
# git's own global options, which sit BETWEEN `git` and the subcommand: `git -C <dir> push`,
# `git -c user.name=x push`, `git --git-dir=.git push`. Until 0.45.0 PUSH_RE/GIT_MERGE_RE required
# the subcommand to follow `git` directly, so every one of those forms classified as None — and a
# field report (VPS, 4 devs, 2026-09-08..29) found `/push` and `/release` skills that push ONLY as
# `SKILL_AUTHORIZED=1 git -C /home/<dev>/workspace/<proj> push ...`. A CLOSED list of the options
# git actually defines, not an open `(-\S+\s+\S+)*`: the project's own rule against free text is
# "require a canonical form, not a smarter regex", and an open pattern would let `git log --grep
# push` read as a push. An option not on this list still makes the command classify as None — the
# same fail direction as before, now narrower. A leading `VAR=val` needs nothing: search() already
# finds `git` anywhere in the line.
_GIT_ARG = r"(?:\"[^\"]*\"|'[^']*'|\S+)"
_GIT_GLOBAL_OPT = (
    r"(?:-C\s+" + _GIT_ARG + r"|-c\s+" + _GIT_ARG +
    r"|--(?:git-dir|work-tree|namespace|super-prefix|config-env)(?:=" + _GIT_ARG + r"|\s+" + _GIT_ARG + r")"
    r"|--exec-path=" + _GIT_ARG +
    r"|--no-pager|--paginate|-p|-P|--bare|--no-replace-objects|--literal-pathspecs"
    r"|--glob-pathspecs|--noglob-pathspecs|--icase-pathspecs|--no-optional-locks"
    r"|--no-lazy-fetch|--no-advice)"
)
_GIT_PREFIX = r"\bgit(?:\s+" + _GIT_GLOBAL_OPT + r")*\s+"
PUSH_RE = re.compile(_GIT_PREFIX + r"push\b")
GH_MERGE_RE = re.compile(r"\bgh\s+pr\s+merge\b")
# `merge(?![\w-])`, not `merge\b`: \b also stops at the hyphen, so the read-only `git merge-base`
# (and merge-tree/merge-file) classified as a merge and the precheck denied it (measured
# 2026-10-05 in live transcripts). git_calls() already compares the whole token, so only the regex
# needed this.
GIT_MERGE_RE = re.compile(_GIT_PREFIX + r"merge(?![\w-])")
DEPLOY_RE = re.compile(
    r"\bwrangler\s+deploy\b"
    r"|\bvercel\b[^\n]*--prod\b"
    r"|\bnpm\s+publish\b"
    r"|\byarn\s+publish\b"
    r"|\bpnpm\s+publish\b"
    r"|\bterraform\s+apply\b"
    r"|\bkubectl\s+(apply|delete)\b"
)
DESTRUCTIVE_RE = re.compile(
    # rm -rf, -rfv, -xrf: one lowercase flag cluster with r before f, then an arg. NOT -fr, -Rf,
    # `-r -f` or --recursive --force (until 0.55.0 this comment claimed -fr and -Rf; it never
    # matched them). Measured 2026-10-10 over 156,054 real Bash commands: 0 used -fr/-Rf/--recursive.
    r"\brm\s+-\w*r\w*f\w*\s"
    r"|\bwrangler\s+d1\s+migrations\s+apply\b"
    r"|\bprisma\s+migrate\s+deploy\b"
    r"|\bknex\s+migrate:latest\b"
    r"|\balembic\s+upgrade\b"
)

# 0.55.0 (p-ff03d9a39d, p-a23bf3418e): one canonical form of deleting your own mktemp directory is
# not terminal. Measured 2026-10-10 over the 159 real `destructive` denials on one machine: 76-77
# were a local delete of a temp dir the session itself made (two blind labelers, kappa 0.97), the
# one SKILL.md does not call terminal ("undoing it would be hard or harmful"); and the denial
# pushed agents to move the delete into a script, the evasion the deny text warns about. A form,
# not a smarter matcher: the WHOLE command must be `rm -rf <abs path> [...]` with no shell syntax
# at all, and each path, symlinks resolved, must sit inside a first-level `name.XXXXXX` dir
# (mktemp's shape) under the real temp root. Measured on this macOS: `rm -rf <symlink>/` deletes
# the link's TARGET, so the textual path is never trusted. Chained, `$VAR`, globbed or relative
# forms stay terminal, which is why /checkpoint-3t must print the literal path and run it alone.
_TEMP_CLEANUP_SHELL = re.compile(r"[;&|<>()$`\\*?\[\]{}~\n]")
_MKTEMP_NAME = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_]{6,}")


def _temp_roots():
    roots = set()
    for r in (tempfile.gettempdir(), os.environ.get("TMPDIR") or "", "/tmp"):
        if r:
            real = os.path.realpath(r)
            if real != os.sep:
                roots.add(real)
    return roots


def is_temp_cleanup(command):
    """True only for the canonical own-temp-dir delete described above."""
    if not command or _TEMP_CLEANUP_SHELL.search(command.strip()):
        return False
    try:
        toks = shlex.split(command)
    except ValueError:
        return False
    if len(toks) < 3 or toks[0] != "rm" or toks[1] not in ("-rf", "-fr"):
        return False
    roots = _temp_roots()
    for p in toks[2:]:
        if not p.startswith("/"):  # the hook's cwd need not be the shell's
            return False
        real = os.path.realpath(p)
        if not any(real.startswith(root + os.sep)
                   and _MKTEMP_NAME.fullmatch(real[len(root) + 1:].split(os.sep)[0])
                   for root in roots):
            return False
    return True


def classify_all(command):
    """Every kind present in `command`, in classify()'s priority order (0.45.0: `git push origin
    feat && gh pr merge` classified as push only, the push was out of scope as a feature push, and
    the merge in the same command ran unchecked)."""
    if not command or is_temp_cleanup(command):
        return []
    kinds = []
    if PUSH_RE.search(command):
        kinds.append("push")
    if GH_MERGE_RE.search(command) or GIT_MERGE_RE.search(command):
        kinds.append("merge")
    if DEPLOY_RE.search(command):
        kinds.append("deploy")
    if DESTRUCTIVE_RE.search(command):
        kinds.append("destructive")
    return kinds


def classify(command):
    """One of 'push' | 'merge' | 'deploy' | 'destructive' | None. Bounded, best-effort list — see
    references/ for the list this was ratified against; it is NOT exhaustive by design (a Bash
    command matcher cannot reason about non-Bash terminal actions, e.g. an MCP-tool delete)."""
    if not command or is_temp_cleanup(command):
        return None
    if PUSH_RE.search(command):
        return "push"
    if GH_MERGE_RE.search(command) or GIT_MERGE_RE.search(command):
        return "merge"
    if DEPLOY_RE.search(command):
        return "deploy"
    if DESTRUCTIVE_RE.search(command):
        return "destructive"
    return None


def _run(args, cwd):
    try:
        out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return None
        return out.stdout
    except Exception:
        return None


def current_branch(cwd):
    out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return out.strip() if out else None


def default_remote_branch(cwd):
    out = _run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], cwd)
    if out:
        return out.strip().rsplit("/", 1)[-1]
    return None


def protected_branches(cwd):
    """Best-effort, never empty: main/master are always protected even when origin/HEAD cannot be
    resolved (detached remote, no network, fresh clone)."""
    branches = {"main", "master"}
    d = default_remote_branch(cwd)
    if d:
        branches.add(d)
    return branches


# Token-level twin of _GIT_GLOBAL_OPT above, for the parse that has to know WHICH repo a command
# acts on. Options that take a separate argument, and flags that take none.
_GIT_OPTS_WITH_ARG = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                      "--config-env")
_GIT_FLAGS = ("--no-pager", "--paginate", "-p", "-P", "--bare", "--no-replace-objects",
              "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs",
              "--icase-pathspecs", "--no-optional-locks", "--no-lazy-fetch", "--no-advice")
# (bare `--exec-path` is absent on purpose: without `=` git prints its path and exits, so
# `git --exec-path push` never pushes. `--exec-path=<dir>` is accepted through the `=` rule below.)
_SHELL_SEPARATORS = ("&&", "||", ";", "|", "&", ">", "<")
_SEPARATOR_RE = re.compile(r"(&&|\|\||[;|&<>])")


def git_calls(command, sub, cwd):
    """-> [(repo_dir, args), ...] for every `git [global options] <sub> ...` in `command`.

    repo_dir is `cwd` with every `-C <dir>` applied in order, the way git applies them (a relative
    -C resolves against the previous one; a quoted path with spaces is rejoined). Before 0.45.0 the
    branch/diff checks below always used the HOOK's cwd, so `git -C /other/repo push origin main`
    was judged against whatever repo the session happened to sit in, and only the first push of a
    chained `git push origin feat && git push origin main` was ever looked at. args stops at the
    first shell separator or redirection, attached or not (`main&&echo`, `main;echo`, `main>out`),
    so a trailing command is never read as the push target. `--git-dir`/`--work-tree` are skipped,
    not resolved: a push that names only those is judged against cwd, as before.
    Split on whitespace, not shlex, on purpose: an unbalanced quote (a heredoc in the same command)
    would make shlex raise, and every caller fails open, so a raise would silently ALLOW the push."""
    toks = _SEPARATOR_RE.sub(r" \1 ", command or "").split()
    calls = []
    for i, t in enumerate(toks):
        t = t.lstrip("\"'(")  # `bash -c "git push ..."`, `(git push ...)`
        if t != "git" and not t.endswith("/git"):
            continue
        j, d = i + 1, cwd
        while j < len(toks):
            o = toks[j]
            if o in _GIT_OPTS_WITH_ARG and j + 1 < len(toks):
                k = j + 1
                arg = toks[k]
                q = arg[:1]
                if q in ("'", '"') and not (len(arg) > 1 and arg.endswith(q)):
                    while k + 1 < len(toks) and not toks[k].endswith(q):
                        k += 1
                        arg += " " + toks[k]
                if o == "-C":
                    arg = os.path.expanduser(arg.strip("\"'"))
                    d = os.path.join(d or os.getcwd(), arg)
                j = k + 1
                continue
            if o in _GIT_FLAGS or ("=" in o and o.split("=", 1)[0] in _GIT_OPTS_WITH_ARG + ("--exec-path",)):
                j += 1
                continue
            break
        if j < len(toks) and toks[j] == sub:
            args = []
            for a in toks[j + 1:]:
                if a in _SHELL_SEPARATORS:
                    break
                args.append(a.strip("\"'").rstrip(")"))  # `"main"`, `'+feat'`, `...main")`
            calls.append((d, args))
    return calls


def git_call(command, sub, cwd):
    """The first of git_calls(), or None."""
    calls = git_calls(command, sub, cwd)
    return calls[0] if calls else None


def repo_dir_for(kind, command, cwd):
    """The repo the first push/merge acts on: the `-C` target when the command names one, else cwd."""
    sub = {"push": "push", "merge": "merge"}.get(kind)
    call = git_call(command, sub, cwd) if sub else None
    return call[0] if call else cwd


# Push flags that update every branch at once, protected ones included.
_PUSH_ALL_FLAGS = ("--all", "--mirror", "--branches")


def push_targets(repo, args):
    """-> (branches, forced) for one `git push` call's args. Each refspec's DESTINATION counts
    (`main:refs/heads/main` -> main, `feat:main` -> main); `refs/heads/` is stripped; `HEAD` and a
    bare push resolve to the repo's current branch; a leading `+` is a force push. `--all` /
    `--mirror` / `--branches` return the protected set itself, since they push every branch."""
    if any(a in _PUSH_ALL_FLAGS for a in args):
        return sorted(protected_branches(repo)), False
    positional = [a for a in args if not a.startswith("-")]
    # Force spelled as an arg of THIS call (quotes already stripped by git_calls): `--force`,
    # `--force-with-lease[=...]`, `--force-if-includes`, or a short cluster holding f (`-fu`).
    forced = any(a in ("--force", "--force-if-includes") or a.startswith("--force-with-lease")
                 or (a.startswith("-") and not a.startswith("--") and "f" in a[1:])
                 for a in args)
    branches = []
    for ref in positional[1:]:
        if ref.startswith("+"):
            forced, ref = True, ref[1:]
        dst = ref.split(":")[-1] if ":" in ref else ref
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        if dst == "HEAD" or not dst:
            dst = current_branch(repo)
        if dst:
            branches.append(dst)
    if not positional[1:]:
        b = current_branch(repo)
        if b:
            branches.append(b)
    return branches, forced


def push_target_branch(command, cwd):
    """Best-effort: the first target branch of the first push in `command` (see push_targets), else
    the current branch of cwd."""
    call = git_call(command, "push", cwd)
    if call:
        branches, _ = push_targets(call[0], call[1])
        return branches[0] if branches else None
    return current_branch(cwd)


def is_terminal(command, cwd):
    """-> (is_terminal: bool, kind: str|None, diffable: bool).

    'push' to a branch NOT in protected_branches() is explicitly OUT of scope (a feature-branch
    push headed for review is not the blast radius this gate exists for) UNLESS it force-pushes,
    which SKILL.md already names terminal regardless of branch. Every push in the command is
    checked, each against its own repo.
    """
    kinds = classify_all(command)
    if not kinds:
        return False, None, False
    for other in ("merge", "deploy", "destructive"):
        if other in kinds:  # always terminal, whatever a push beside it targets
            # diffable only when the merge is the ONLY kind: the content exemption diffs one kind,
            # so a memory-only merge must not wave through a push chained to it (round 4).
            return True, other, other == "merge" and len(kinds) == 1
    kind = "push"
    if kind == "push":
        if FORCE_FLAG_RE.search(command):
            return True, kind, True
        calls = git_calls(command, "push", cwd)
        if not calls:  # classify() saw a push the token parse could not rebuild: judge cwd
            branch = current_branch(cwd)
            return bool(branch and branch in protected_branches(cwd)), kind, True
        for repo, args in calls:
            if not os.path.isdir(repo or ""):
                # `-C "$VAR"` or a path that does not exist here: the branch cannot be read, so
                # this cannot be confirmed out of scope. Unknown resolves to terminal, the same
                # direction all_exempt() takes for an undeterminable diff.
                return True, kind, True
            branches, forced = push_targets(repo, args)
            if forced or any(b in protected_branches(repo) for b in branches):
                return True, kind, True
        return False, kind, True
    if kind == "merge":
        return True, kind, True
    return True, kind, False  # deploy / destructive: always terminal, not diffable


def push_diff_paths(cwd):
    """Files in local HEAD not yet on the upstream tracking ref — i.e. what THIS push would send.
    None when undeterminable (no upstream configured, git missing) — caller must treat that as
    NOT exempt (see all_exempt's docstring), not as an error to swallow."""
    out = _run(["git", "diff", "--name-only", "@{upstream}..HEAD"], cwd)
    if out is None:
        return None
    return [p for p in out.splitlines() if p.strip()]


def merge_diff_paths(command, cwd):
    """Best-effort file list for a merge/gh-pr-merge about to run: a `git [-C dir] merge <ref>` gets
    a three-dot diff against the ref in the repo it acts on; anything else (`gh pr merge`) gets
    `gh pr diff` for cwd's current branch. None when that does not resolve."""
    call = git_call(command, "merge", cwd)
    if call is None:  # `gh pr merge`: gh has no -C, the PR is the one for cwd's current branch
        out = _run(["gh", "pr", "diff", "--name-only"], cwd)
        return [p for p in out.splitlines() if p.strip()] if out is not None else None
    # `git [-C dir] merge <ref>`: diff in the repo the merge acts on, never gh in the hook cwd
    # (0.45.0 — gh ran first before, so a `git -C other merge` read cwd's PR).
    refs = [a for a in call[1] if not a.startswith("-")]
    if refs:
        out = _run(["git", "diff", "--name-only", "HEAD..." + refs[0]], call[0])
        if out is not None:
            return [p for p in out.splitlines() if p.strip()]
    return None


def commits_since(cwd, since_ts):
    """-> list of file paths touched by commits on HEAD with committer-date >= since_ts (ISO8601),
    or None if this could not be determined (git error, not a repo, no timestamp given). Best-
    effort and committer-date based — acceptable for the Stop-gate STALENESS BACKSTOP (gate-goal-
    close.sh), which has no clean way to know exactly which files a specific historical push
    carried; NOT used by the live PreToolUse precheck, which diffs the actual prospective push
    directly instead (push_diff_paths / merge_diff_paths above) and needs no such approximation."""
    if not since_ts:
        return None
    out = _run(["git", "log", "--since", since_ts, "--name-only", "--pretty=format:"], cwd)
    if out is None:
        return None
    return [p for p in out.splitlines() if p.strip()]


def staleness_repos(command, cwd):
    """-> the repos whose recent commits the staleness backstop must read for one terminal command
    that already ran: the repo of every `git [-C dir] push|merge` in it (git_calls, the same parse
    the precheck uses), plus cwd when some terminal part of the command is not one of those calls
    (`gh pr merge`, a deploy, a destructive command) or the token parse rebuilt fewer push/merge
    calls than the command contains.
    Before 0.46.1 the backstop always read cwd, so `git -C /other push origin main` was exempted or
    flagged on the SESSION repo's commits, not the ones it pushed (p-adbf311b73)."""
    pushes = git_calls(command, "push", cwd)
    merges = git_calls(command, "merge", cwd)
    repos = []
    for d, _ in pushes + merges:
        if d not in repos:
            repos.append(d)
    kinds = classify_all(command)
    # A push/merge the regex sees but the token parse did not rebuild (`(git -C /y push)`,
    # `bash -c 'git push'`: the subcommand token is `push)` / `push'`) has an unknown repo, so cwd
    # is read too — never fewer repos than 0.46.0, which always read cwd.
    needs_cwd = (not repos
                 or len(list(PUSH_RE.finditer(command))) > len(pushes)
                 or len(list(GIT_MERGE_RE.finditer(command))) > len(merges)
                 or GH_MERGE_RE.search(command)
                 or "deploy" in kinds or "destructive" in kinds)
    if needs_cwd and cwd not in repos:
        repos.append(cwd)
    # `-C "$VAR"` / `-C $(...)` / backticks: the repo the shell pushed from is not knowable here.
    # None marks it unreadable, so the caller exempts nothing (adversary round 2: a literal
    # `$OTHER` directory holding only memory exempted a push whose real repo held code).
    return [None if r and ("$" in r or "`" in r) else r for r in repos]


def diff_paths_for(kind, command, cwd):
    if kind == "push":
        calls = git_calls(command, "push", cwd)
        paths = []
        for repo in ([c[0] for c in calls] or [cwd]):
            p = push_diff_paths(repo)
            if p is None:
                return None  # one undeterminable push makes the whole command not exempt
            paths.extend(p)
        return paths
    if kind == "merge":
        return merge_diff_paths(command, cwd)
    return None  # deploy / destructive: not path-diffable, never content-exempt


# --- transcript reading (mirrors gate-goal-close.sh's own parsing, kept in lockstep) ---------------
GOAL_SPEC_RE = r"(^|\n)#{1,6}\s*Goal-spec\b"
WAIVER_RE = r"\[GOAL-CLOSE-WAIVED\s+reason=[^\]]{20,}\]"
VERDICT_RE = (r"\[ADVERSARY-VERDICT:\s*(break|hold)\s+ungrounded=\d+\s+unfalsified=\d+\s+"
              r"incomplete=\d+\s+autonomy-violations=\d+\s+unsafe=\d+\s*\]")
CR_RE = r"\[COMPLETION-REVIEW:\s*(adversary|none)\b([^\]]*)\]"

# The durable checkpoint's path, session-scoped: `.goalspec/checkpoint.md` (pre-concurrency-fix
# name, still adopted and still read) or `.goalspec/checkpoint-<token>.md` (one file per session,
# so two concurrent sessions in one project stop sharing one — see durable-artifact.md for what
# that does and does not guarantee; this module only recognizes the name, it enforces nothing). Anchored on BOTH sides —
# the `.goalspec/` directory component and the end of the string — so it stays as narrow as the
# `endswith` it replaced: `docs/checkpoint-notes.md` and `.goalspec/checkpoint.md.bak` do not
# match. The token charset excludes `/`, so `.goalspec/checkpoint-x/y.md` does not match either.
# It does NOT require the `.goalspec/` to be the project root's — a nested `sub/.goalspec/…`
# matches, on purpose: this module has no cwd to anchor against and must accept whatever absolute
# `file_path` the transcript recorded, and in a monorepo a spec written under a sub-package is
# still THIS session's spec (only this session's transcript is ever read). `nudge-decompose.sh`
# additionally anchors to its cwd, because its declared contract is the narrower one ("in the
# cwd") — an adversary round caught that hook accepting a nested path its own header disclaimed.
# Keep in lockstep with nudge-decompose.sh's own ownership matcher and with
# references/durable-artifact.md ("Where it lives"), which is the declaration both cite.
CHECKPOINT_PATH_RE = re.compile(r"(^|/)\.goalspec/checkpoint(-[A-Za-z0-9._-]+)?\.md$")


# 0.45.0 — the goalspec ENTRY points: invoking either one promises a `## Goal-spec` (the loop
# writes it; the interview hands off to the loop, which writes it). `goalspec:adversary` is not an
# entry: it verifies a claim and promises no spec. Why this exists: a field report (VPS, 4 devs,
# 2026-09-08..29) found 7 of 10 sessions that pushed or merged with no adversary had started with
# `/goalspec:interview` and never written the spec — and every rail keyed on the spec alone, so
# the session the developer believed was "using goalspec" had all of them off.
ENTRY_SKILLS = ("goalspec", "goalspec:goalspec", "goalspec:interview")
# Anchored at the START of the user text (match, not search): the harness writes the command
# block first, so a user who pastes a transcript excerpt into a longer message is not an entry.
COMMAND_ENTRY_RE = re.compile(r"(?:<command-message>[^<]*</command-message>\s*)?"
                              r"<command-name>/?goalspec(?::(?:goalspec|interview))?</command-name>")
# User events the harness writes that are not the user speaking: they must not end the turn a
# waiver is scoped to (a background task finishing is not the user replying).
HARNESS_TEXT_PREFIXES = ("<task-notification", "<local-command-stdout", "<local-command-stderr",
                         "<system-reminder", "<cross-session-message", "<agent-message",
                         "<bash-stdout", "<bash-stderr", "<bash-input")


# 0.46.7 (p-64783f8057) — where a goal-adversary's final report reaches this session: a background
# hand-back, delivered as an `attachment` of type `queued_command` (observed 2026-10-05,
# agente-coordinador b30f155f lines 1283/1287) when it lands while the session is busy, or as a
# `user` event carrying the same `origin` (report in `origin.body`) when the session is idle (0.46.8;
# measured in this repo's own session 218eff94, and the shape of 72 of 75 adversary hand-backs on
# record), or, for a foreground spawn, the spawn's own tool_result. A user event that merely starts with `<agent-message` is NOT read: the user can type
# or paste that tag (external adversary round on 0.46.7). The
# `queue-operation` enqueue/remove events carry the same text twice more; they are not read, so one
# hand-back is one item. An item keeps the timestamp of the event it came from, which for a
# queued_command is the enqueue time, not the delivery; nothing orders by it (position does).
#
# Only a goal-adversary counts. Any other subagent (an Explore asked where the verdict format is
# defined) can return SKILL.md's example verdict lines, and the deny text would then tell the
# executor to quote a hold no adversary gave. A spawn is an adversary when its subagent_type names
# goal-adversary exactly (is_adversary_type); its agent id comes from the spawn's tool_result (toolUseResult.agentId, or the
# "agentId: <id>" line of the text). A queued_command counts only when the harness marked it a
# hand-back (`origin.kind == "peer"`, `origin.handback`; a typed message has `origin.kind ==
# "human"`) and it comes from a goal-adversary: `origin.name` names it, or `origin.from` / the
# `from=` of the tag is one of those agent ids (a SendMessage that resumes the adversary keeps its
# id). The tool_result of a BACKGROUND launch is only the launch receipt (it may echo the prompt,
# and a delta round's prompt quotes the prior verdict), so its text is read for the agent id only.
RELAY_PREFIXES = ("<agent-message", "<task-notification")
SPAWN_TOOLS = ("Agent", "Task")
RELAY_FROM_RE = re.compile(r'^\s*<agent-message\s+from="([^"]+)"|^\s*<task-notification>\s*<task-id>([^<]+)</task-id>')
AGENT_ID_RE = re.compile(r"agentId:\s*([A-Za-z0-9_-]+)")


def is_adversary_type(name):
    """Exact agent-type match: `goal-adversary`, or it namespaced by a plugin (`goalspec:goal-adversary`).
    A substring test let `not-goal-adversary-example` count (external adversary round on 0.46.7)."""
    return isinstance(name, str) and (name.strip() == "goal-adversary"
                                      or name.strip().endswith(":goal-adversary"))


def _relayed_verdict_item(text, ts):
    """-> a "relayed_verdict" item for the LAST verdict line in an adversary's report, or None."""
    last = None
    for m in re.finditer(VERDICT_RE, text, re.I):
        last = m
    if last is None:
        return None
    return {"kind": "relayed_verdict", "timestamp": ts, "text": "",
            "verdict": last.group(1).lower(), "line": last.group(0)}


def _relay_from_adversary(att, prompt, state):
    origin = att.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != "peer" or origin.get("handback") is not True:
        return False
    if is_adversary_type(origin.get("name")):
        return True
    m = RELAY_FROM_RE.match(prompt)
    ids = {origin.get("from"), (m.group(1) or m.group(2) or "").strip() if m else None}
    return any(isinstance(i, str) and i in state["adversary_agents"] for i in ids)


def _tool_result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") for b in content
                         if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def read_transcript_text(transcript_path):
    """-> the transcript's assistant text, all of it, joined — the text-only view of
    read_transcript_items() for callers that only need to grep prose (goal-spec / waiver / verdict
    presence) and don't care about tool_use ordering. Empty string on any error (missing path,
    unparseable lines) — same fail-open contract gate-goal-close.sh already relies on for an
    unreadable transcript."""
    return "\n".join(it["text"] for it in read_transcript_items(transcript_path) if it["kind"] == "text")


def _collect_event(ev, items, state=None):
    """Append the items one transcript event contributes (see read_transcript_items). `state`
    carries, across events, the tool_use ids of goal-adversary spawns and their agent ids, so a
    report is read for a relayed verdict only when it comes from a goal-adversary (see
    RELAY_PREFIXES): a Bash tool_result or another subagent can carry any text."""
    if state is None:
        state = {"adversary_spawns": set(), "adversary_agents": set(), "background_spawns": set()}
    if ev.get("type") == "attachment":
        att = ev.get("attachment") or {}
        prompt = att.get("prompt") if isinstance(att, dict) else None
        if att.get("type") == "queued_command" and isinstance(prompt, str) \
                and prompt.lstrip().startswith(RELAY_PREFIXES) \
                and _relay_from_adversary(att, prompt, state):
            rv = _relayed_verdict_item(prompt, ev.get("timestamp"))
            if rv:
                items.append(rv)
        return
    if ev.get("type") == "user":
        # 0.46.8 (p-1f14f32fb1): the same hand-back, delivered while the session is idle, is a user
        # event with the harness `origin` on the event itself, and the report in `origin.body` (its
        # message.content starts "Another Claude session sent a message:"). 72 of the 75 goal-adversary
        # hand-backs in the maintainer's transcripts have this shape; 0.46.7 read only the other one.
        # Same checks as the queued_command: origin.kind/handback set by the harness, exact type or a
        # known adversary agent id. The message text is never read.
        uorigin = ev.get("origin")
        ubody = uorigin.get("body") if isinstance(uorigin, dict) else None
        if isinstance(ubody, str) and _relay_from_adversary(ev, ubody, state):
            rv = _relayed_verdict_item(ubody, ev.get("timestamp"))
            if rv:
                items.append(rv)
        ucontent0 = (ev.get("message") or {}).get("content")
        for blk in (ucontent0 if isinstance(ucontent0, list) else []):
            # 0.51.0 (p-5b005aba6e): a checkpoint Write/Edit whose result is an error never wrote the
            # spec, so read_transcript_items drops its goal_spec_file item. Measured over the last
            # 400 local transcripts: all 24 failed Write/Edit results (permission or hook denied,
            # file not read, tool disabled) carry is_error true; the 913 that succeeded do not. A
            # call with no result yet still counts: a parallel call's hook can run before it lands.
            if isinstance(blk, dict) and blk.get("type") == "tool_result" and blk.get("is_error") is True:
                state.setdefault("failed_tool_uses", set()).add(blk.get("tool_use_id"))
            if isinstance(blk, dict) and blk.get("type") == "tool_result" \
                    and blk.get("tool_use_id") in state["adversary_spawns"]:
                rtext = _tool_result_text(blk.get("content"))
                tur = ev.get("toolUseResult")
                aid = tur.get("agentId") if isinstance(tur, dict) else None
                if not isinstance(aid, str):
                    am = AGENT_ID_RE.search(rtext)
                    aid = am.group(1) if am else None
                if aid:
                    state["adversary_agents"].add(aid)
                is_async = (isinstance(tur, dict) and tur.get("isAsync") is True) \
                    or blk.get("tool_use_id") in state["background_spawns"]
                # 0.51.0: a spawn whose result is an error delivered no report, whatever text it
                # carries (external adversary round on the Write quote, which this now gates).
                failed = blk.get("is_error") is True
                rv = None if (is_async or failed) else _relayed_verdict_item(rtext, ev.get("timestamp"))
                if rv:
                    items.append(rv)
        # 0.45.0: a TYPED `/goalspec:interview` or `/goalspec:goalspec` lives only in a
        # user event, as the harness's own `<command-name>` tag. Only that exact tag
        # counts — never prose, and never a tool_result (which can carry any text,
        # including a grep over another transcript).
        ucontent = (ev.get("message") or {}).get("content")
        utexts = [ucontent] if isinstance(ucontent, str) else [
            b.get("text") for b in (ucontent or [])
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ] if isinstance(ucontent, list) else []
        entry = next((m for m in (COMMAND_ENTRY_RE.match(u.lstrip()) for u in utexts) if m), None)
        if entry:
            items.append({"kind": "goalspec_entry", "timestamp": ev.get("timestamp"), "text": "",
                          "skill": "interview" if "interview" in entry.group(0) else "goalspec"})
        elif utexts and not ev.get("isMeta") and not all(
                u.lstrip().startswith(HARNESS_TEXT_PREFIXES) for u in utexts):
            # A real user prompt (not a tool_result, not a harness-injected meta
            # message): the turn boundary waiver_covers_command() scopes to.
            items.append({"kind": "user_prompt", "timestamp": ev.get("timestamp"), "text": ""})
        return
    if ev.get("type") != "assistant":
        return
    ts = ev.get("timestamp")
    msg = ev.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        if content:
            items.append({"kind": "text", "timestamp": ts, "text": content})
        return
    if not isinstance(content, list):
        return
    for blk in content:
        if not isinstance(blk, dict):
            continue
        if blk.get("type") == "text" and blk.get("text"):
            items.append({"kind": "text", "timestamp": ts, "text": blk["text"]})
        elif blk.get("type") == "tool_use" and blk.get("name") in SPAWN_TOOLS:
            st = (blk.get("input") or {}).get("subagent_type")
            if blk.get("id") and is_adversary_type(st):
                state["adversary_spawns"].add(blk["id"])
                if (blk.get("input") or {}).get("run_in_background") is True:
                    state["background_spawns"].add(blk["id"])
        elif blk.get("type") == "tool_use" and blk.get("name") == "Skill":
            # 0.45.0: the same entry, invoked by the model through the Skill tool.
            sk = (blk.get("input") or {}).get("skill")
            if isinstance(sk, str) and sk.strip() in ENTRY_SKILLS:
                items.append({"kind": "goalspec_entry", "timestamp": ts, "text": "",
                              "skill": "interview" if sk.strip().endswith("interview") else "goalspec"})
        elif blk.get("type") == "tool_use" and blk.get("name") == "Bash":
            cmd = (blk.get("input") or {}).get("command")
            if isinstance(cmd, str) and cmd:
                items.append({"kind": "bash", "timestamp": ts, "command": cmd, "id": blk.get("id")})
        elif blk.get("type") == "tool_use" and blk.get("name") in ("Write", "Edit"):
            # Every Write/Edit leaves a text-free "edit" item (0.46.0), so interview_handoff_pending
            # can tell work done after an interview from a conversation that simply went on.
            items.append({"kind": "edit", "timestamp": ts, "text": ""})
            # A ## Goal-spec can be written to disk (.goalspec/checkpoint.md, per
            # SKILL.md step 5's own checkpoint pattern for long-running tasks) instead
            # of posted as chat text. Confirmed live (goal-adversary, 2026-07-31): a
            # real session's spec existed only inside Write tool_use blocks, never as
            # assistant text, so the text-only scan below missed it — has_goal_spec()
            # returned False against the real transcript, and the precheck hook
            # silently ALLOWED the exact push it exists to gate.
            #
            # The filename is session-scoped since the concurrency fix (two sessions
            # in one project used to clobber a single fixed path — see
            # references/durable-artifact.md, "Where it lives"), so this matches
            # `.goalspec/checkpoint.md` AND `.goalspec/checkpoint-<token>.md`. It stays
            # session-scoped by construction either way: this function reads only THIS
            # session's transcript, so another session's checkpoint can never reach it
            # — the widening admits no foreign file, only this session's own new name.
            #
            # NARROWLY scoped to that one path and that one marker on purpose — a
            # first attempt captured ANY Write/Edit content as text and broke
            # immediately: SKILL.md and CHANGELOG.md are FULL of literal example
            # marker text (`[GOAL-CLOSE-WAIVED reason=…]`, sample verdicts) written
            # as documentation, and editing either file made has_waiver()/
            # operative_verdict() see those examples as genuine declarations — a
            # false positive far worse than the gap being closed. Only a Write/Edit
            # whose `file_path` ends in `.goalspec/checkpoint.md` contributes text
            # here (`checkpoint.md` or `checkpoint-<token>.md`, and only directly
            # inside a `.goalspec/` directory) — and only for the goal-spec-presence
            # check below (has_goal_spec) —
            # NOT tagged into the general text-marker scan, so it can never satisfy
            # has_waiver/operative_verdict/completion-review, which SKILL.md itself
            # requires to be authored in the executor's OWN turn text, not a file.
            ti = blk.get("input") or {}
            fp = ti.get("file_path")
            # Backslashes normalized before matching: on Windows the transcript
            # records `...\.goalspec\checkpoint.md` and the POSIX-separator pattern
            # would never match, leaving the gate blind to a spec written to disk on
            # that platform — the same blindness this whole signal exists to fix,
            # just platform-shaped. Inherited from the `endswith` this replaced, found
            # by the decision-log sweep on this change, fixed here on the user-s call.
            # Not observed on a real Windows host; the suites assert it synthetically.
            if isinstance(fp, str) and CHECKPOINT_PATH_RE.search(fp.replace("\\", "/")):
                for key in ("content", "new_string"):
                    v = ti.get(key)
                    if isinstance(v, str) and re.search(GOAL_SPEC_RE, v, re.I):
                        items.append({"kind": "goal_spec_file", "timestamp": ts, "text": v,
                                      "path": fp.replace("\\", "/"), "id": blk.get("id")})
                # 0.51.0: the executor quoting a hand-back verdict with a tool call, into its own
                # checkpoint (file_quoted_hold). The LAST verdict line of what it wrote is the quote;
                # earlier lines are history. Never tagged as text: has_waiver, operative_verdict and
                # the Stop gate still read only visible text.
                for key in ("content", "new_string"):
                    v = ti.get(key)
                    last_v = None
                    for mv in re.finditer(VERDICT_RE, v if isinstance(v, str) else "", re.I):
                        last_v = mv
                    if last_v:
                        items.append({"kind": "verdict_file", "timestamp": ts, "text": "",
                                      "path": fp.replace("\\", "/"), "id": blk.get("id"),
                                      "verdict": last_v.group(1).lower(), "line": last_v.group(0)})


def read_transcript_items(transcript_path):
    """-> list of {"kind": "text"|"bash", "timestamp": str|None, "text"|"command": str}, in the
    SAME order the content blocks appear (file order, and within a message, block order) — a text
    block and a tool_use block from the same assistant turn are NOT collapsed into one event, so
    'did a terminal Bash call happen after the completion-review text in this same turn' is
    answerable, not just 'in a later turn'. Empty list on any error (missing path, unparseable
    lines) — the staleness check must treat that the same way gate-goal-close.sh already treats an
    unreadable transcript: fail open, do not flag.
    """
    items = []
    state = {"adversary_spawns": set(), "adversary_agents": set(), "background_spawns": set()}
    try:
        if not transcript_path or not os.path.isfile(transcript_path):
            return items
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                # One malformed event is skipped, not allowed to wipe every signal read so far (0.45.0 —
                # an external adversary round showed a single odd event emptied the list, and the precheck
                # then allowed a merge in a session that had a spec).
                try:
                    _collect_event(ev, items, state)
                except Exception:
                    continue
    except Exception:
        return []
    failed = state.get("failed_tool_uses") or set()
    return [it for it in items
            if not (it["kind"] in ("goal_spec_file", "verdict_file")
                    and it.get("id") is not None and it["id"] in failed)]


def last_completion_review_index(items):
    """Index (into `items`) of the LAST text item containing a completion-review marker, or None."""
    idx = None
    for i, it in enumerate(items):
        if it["kind"] == "text" and re.search(CR_RE, it["text"], re.I):
            idx = i
    return idx


def terminal_bash_after(items, index):
    """-> list of {"timestamp", "command", "kind"} for every Bash item AFTER `items[index]` that
    classifies as terminal — using classify() only (no cwd/branch check: at Stop time we are
    looking back at commands that already ran, not deciding whether to allow one; a push that
    landed on a feature branch never reaches origin's protected branch either way, so this
    deliberately over-includes relative to is_terminal()'s live branch check — a caller applying
    the content exemption on top is the intended narrowing, not a branch re-check here)."""
    out = []
    for it in items[index + 1:]:
        if it["kind"] != "bash":
            continue
        kind = classify(it["command"])
        if kind is not None:
            out.append({"timestamp": it.get("timestamp"), "command": it["command"], "kind": kind})
    return out


def has_goal_spec(text):
    return bool(re.search(GOAL_SPEC_RE, text, re.I))


def has_waiver(text):
    return bool(re.search(WAIVER_RE, text, re.I))


def interview_handoff_pending(items, require_work=False):
    """0.46.0 — True when the session's most recent `/goalspec:interview` has not yet been followed
    by the goalspec loop being invoked or a `## Goal-spec` being written (chat text or the
    checkpoint file). Field numbers behind it: on the VPS, 11 of 23 interview sessions never wrote a
    spec, and in all 11 the loop was never invoked; on the maintainer machine, 10 of 70, 8 of which
    never invoked the loop and went on to run Bash or edit files. The interview told the agent to rely on the loop auto-triggering, and it often did
    not. False on any doubt (no interview, or anything after it that starts the spec).

    require_work=True (the UserPromptSubmit path) also requires a Bash, Write or Edit call after the
    interview: an interview that concluded "nothing to do" and a conversation that just goes on is
    not the failure, and nudging on every later message there is noise (external adversary round on
    0.46.0). The PostToolUse(AskUserQuestion) path does not require it: that is the handoff moment.

    What counts as starting the spec is the plugin-wide signal (has_goal_spec on assistant text, a
    checkpoint Write, a Skill call to the loop), read from the transcript as written: a Skill call
    that then failed still counts; a checkpoint Write whose result is an error does not (0.51.0).
    For an advisory nudge that errs toward silence."""
    last_iv = None
    for i, it in enumerate(items):
        if it["kind"] == "goalspec_entry" and it.get("skill") == "interview":
            last_iv = i
    if last_iv is None:
        return False
    worked = False
    for it in items[last_iv + 1:]:
        if it["kind"] in ("bash", "edit"):
            worked = True
        if it["kind"] == "goalspec_entry" and it.get("skill") == "goalspec":
            return False
        if it["kind"] == "goal_spec_file":
            return False
        if it["kind"] == "text" and has_goal_spec(it["text"]):
            return False
    return worked or not require_work


# Agent-facing text for hooks/nudge-interview-handoff.sh. Kept here, not in the hook, because that
# hook runs python inside a single-quoted bash string, where one apostrophe breaks it silently.
INTERVIEW_HANDOFF_NUDGE = (
    "goalspec: this session ran /goalspec:interview and no ## Goal-spec exists yet. The interview "
    "does not end at the last answer: when it is done, invoke the Skill tool with "
    "goalspec:goalspec (pass the settled decisions as args), or, if the goalspec loop is what "
    "routed you into the interview, continue that loop, and write the ## Goal-spec BEFORE any "
    "other work. Until it exists, a push to a protected branch, a merge or a deploy is denied by "
    "the terminal-push precheck. If the interview concluded that nothing should be done, say so "
    "plainly and do no work; this reminder only returns once work starts without a spec."
)

# 0.48.0 — emitted by hooks/nudge-spec-on-entry.sh right after the goalspec loop is loaded through
# the Skill tool in a session with no spec yet. Measured: 25 of 275 real sessions loaded the loop
# and never posted a visible spec; one wrote it only in its thinking, another went straight to tools.
SPEC_ON_ENTRY_NUDGE = (
    "goalspec: the loop is loaded and this session has no ## Goal-spec yet. Before your next tool "
    "call, post the ## Goal-spec as a visible text block (Asked line, then the six answers). A spec "
    "you only plan in your thinking does not count: thinking is not read, even when your screen "
    "shows it like a message. A brief or ticket that already lists criteria is input to the spec, "
    "not the spec. If you ask clarifying questions first, write the spec right after the answers."
)


# 0.49.0 (p-718231fa66) — the brake behind SPEC_ON_ENTRY_NUDGE. Measured 2026-10-07 with an
# isolated `claude -p` replica (fresh copy per run, no MCP, N=6 per arm): with a shell available
# the agent posted no visible spec before its first Bash in 0 of 6 runs on 0.47.0 and on 0.44.0,
# and in 1 of 6 on 0.48.0 — the nudge above fired in all 6 and changed nothing at entry. Two of
# those agents then wrote "I already posted the Goal-spec at the start; the hook does not see it":
# false, no visible text held one (where they wrote it cannot be seen: thinking is redacted in
# those transcripts). Without a shell the same agents posted it 6 of 6.
# A reminder cannot fix an agent that believes it already complied; holding the work can.
SPEC_BRAKE_REASON = (
    "goalspec: the loop is loaded and this session has no ## Goal-spec yet, so this tool call is "
    "held until it has one. Do ONE of these, then call the tool again in a LATER message (a "
    "message reaches the transcript only after its tool calls run): (1) use the Write tool to "
    "create {path} with the ## Goal-spec in it (Asked line, then the six answers) -- it is shown "
    "to the human as soon as you write it; or (2) post the ## Goal-spec as a text block in your "
    "reply. A spec you wrote or planned only in your thinking does not count, even if you believe "
    "you already posted it: this hook reads your visible text and your Write calls, and neither "
    "has a spec. Read, Grep and Glob are not held -- use them if you need to ground the spec first."
)


SPEC_BRAKE_MIN_BODY = 100  # non-whitespace characters under the heading; a real spec has six answers
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")


def spec_has_body(text):
    """A `## Goal-spec` heading followed by at least SPEC_BRAKE_MIN_BODY non-whitespace characters
    before the next same-or-higher heading. 0.49.0 release round (external adversary): the brake
    released on a bare heading. The gate and precheck keep their heading-only detector; only the
    brake, which exists to make the plan exist, asks for a body."""
    for m in re.finditer(GOAL_SPEC_RE, text or "", re.I):
        rest = text[m.end():]
        nxt = re.search(r"\n#{1,2}\s", rest)
        body = rest[:nxt.start()] if nxt else rest
        if len(re.sub(r"\s", "", body)) >= SPEC_BRAKE_MIN_BODY:
            return True
    return False


def own_checkpoint_re(session_id):
    """The checkpoint paths this session may release the brake with: checkpoint-<its id>.md, or the
    plain checkpoint.md. Another session's checkpoint never counts (release round: a Write to a
    foreign checkpoint, denied by the overwrite precheck, still released the brake)."""
    sid = session_id if isinstance(session_id, str) and SESSION_ID_RE.fullmatch(session_id) else None
    tail = r"(-%s)?" % re.escape(sid) if sid else ""
    return re.compile(r"(^|/)\.goalspec/checkpoint%s\.md$" % tail)


def own_checkpoint_roots(cwd):
    """The directories whose .goalspec/ may hold this session's checkpoint: the working directory
    and the git top level above it. Release round 3 (external adversary): a Write to
    `../../elsewhere/.goalspec/checkpoint-<id>.md` or `/tmp/.goalspec/...` released the brake,
    because the path regex matched any directory."""
    roots = set()
    base = cwd if isinstance(cwd, str) and cwd else os.getcwd()
    try:
        roots.add(os.path.realpath(base))
    except Exception:
        return roots
    top = _run(["git", "rev-parse", "--show-toplevel"], base)
    if top and top.strip():
        roots.add(os.path.realpath(top.strip()))
    return roots


def _in_own_root(path, cwd, roots):
    try:
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path))
    except Exception:
        return False
    return os.path.dirname(os.path.dirname(full)) in roots


def spec_brake_armed(items, session_id=None, cwd=None):
    """True when this session entered the goalspec LOOP (the Skill tool or a typed
    /goalspec[:goalspec]) and has no `## Goal-spec` with a body yet, neither in the assistant's
    visible text nor in a Write/Edit to THIS session's .goalspec/ checkpoint, in the working directory
    or the git top level above it.

    v3 (ronda 6 of p-718231fa66): v1 and v2 accepted only visible text, and 2 of 6 agents stayed
    stuck in both -- they believed they had posted a spec that existed nowhere visible, and no
    deny wording moved them. A Write call is a tool call, not a claim about their own output, so
    it is accepted; hooks/show-checkpoint-spec.sh puts what they wrote in front of the human.
    The interview alone does not arm it (it hands off to the loop, and the loop arms it), and
    neither does goalspec:adversary, which is not an entry. Since 0.51.0 a Write whose result is
    an error does not count (read_transcript_items drops it); one with no result yet still does.
    Limiting it to this session's own path stays: a Write to another session's file that succeeds
    is still not this session's spec."""
    if not any(it["kind"] == "goalspec_entry" and it.get("skill") == "goalspec" for it in items):
        return False
    own = own_checkpoint_re(session_id)
    roots = own_checkpoint_roots(cwd)
    if any(it["kind"] == "goal_spec_file" and own.search(it.get("path") or "")
           and _in_own_root(it.get("path") or "", cwd, roots)
           and spec_has_body(it["text"]) for it in items):
        return False
    return not spec_has_body("\n".join(it["text"] for it in items if it["kind"] == "text"))


def spec_brake_evidence(items):
    """What the agent actually posted, quoted back in the deny. Measured 2026-10-07 (ronda 4 of
    p-718231fa66): with the reason alone, 2 of 6 agents answered every deny with "the spec is
    already posted above, the hook must be broken" -- it never was. An assertion about their own
    output did not move them; this shows them the output instead."""
    texts = [it["text"] for it in items if it["kind"] == "text" and it["text"].strip()]
    if not texts:
        return (" Evidence: this session has no visible text from you at all -- everything you "
                "wrote so far was thinking or tool calls.")
    last = " ".join(texts[-1].split())[:160]
    return (" Evidence: you have posted %d visible text block(s) in this session, and none has a "
            "line that starts with `## Goal-spec`. The most recent one begins: \"%s\"."
            % (len(texts), last))


# v3 — what hooks/show-checkpoint-spec.sh shows the human when the spec reaches them only through
# the checkpoint file. Bounded: the reader needs the plan, not a wall.
def checkpoint_spec_excerpt(content, limit=1800):
    m = re.search(GOAL_SPEC_RE, content or "", re.I)
    if not m:
        return None
    body = content[m.start():].lstrip("\n")
    nxt = re.search(r"\n#{1,2}\s+(?!Goal-spec)\S", body[3:])
    if nxt:
        body = body[:nxt.start() + 3]
    body = body.rstrip()
    return body if len(body) <= limit else body[:limit].rstrip() + "\n[...]"


def waiver_covers_command(items, command, tool_use_id=None):
    """0.45.0 — the PreToolUse precheck's waiver: honored only if a `[GOAL-CLOSE-WAIVED ...]` was
    written AFTER the last terminal Bash call on record AND after the last user prompt, so one
    waiver lets ONE terminal command through, in the same turn — not every one after it. Before
    0.45.0 the precheck used has_waiver() — anywhere in the transcript — and a field session
    (0.41.1) got its `gh pr merge` denied, wrote a waiver in the same minute, then ran three more
    merges over the next four hours with no adversary. The turn bound matters for that very
    session: its first merge after the waiver came three hours later, so "next command" alone would
    still have let it through. Cost: a user reply between the waiver and the retry voids it.

    The call being decided is dropped first if the harness already logged it, so it does not consume
    the waiver written for it. With the PreToolUse payload's tool_use_id that drop is exact. Without
    one, the fallback drops a final item carrying the same command, and then an identical command
    re-run right after it executed, with no text between, is indistinguishable and passes twice.
    "Terminal" here is classify(), which over-includes (a feature-branch push also consumes the
    waiver): the strict direction, costing at most one more waiver.

    The Stop gate's waiver (has_waiver, below) is a DIFFERENT contract — close the goal over a
    residual break — and stays transcript-wide. Do not route it through this."""
    seq = list(items)
    if tool_use_id:
        seq = [it for it in seq if not (it["kind"] == "bash" and it.get("id") == tool_use_id)]
    elif seq and seq[-1]["kind"] == "bash" and seq[-1]["command"].strip() == (command or "").strip():
        seq.pop()
    last_terminal = -1
    for i, it in enumerate(seq):
        if it["kind"] == "user_prompt" or (it["kind"] == "bash" and classify(it["command"]) is not None):
            last_terminal = i
    return any(it["kind"] == "text" and re.search(WAIVER_RE, it["text"], re.I)
               for it in seq[last_terminal + 1:])


def operative_verdict(text):
    verdicts = re.findall(VERDICT_RE, text, re.I)
    return verdicts[-1].lower() if verdicts else None


def transcript_signals(transcript_path):
    """One parse, the signals a caller like precheck-terminal-push.sh needs together:
    goal_spec (bool), goalspec_entered (bool), verdict (str|None), text (str, the plain
    assistant-authored prose only), items (the parsed list, for waiver_covers_command). Deliberately the ONE place that combines the checkpoint-file goal-spec signal
    (kind="goal_spec_file", scoped narrowly in read_transcript_items — see its docstring for why)
    with the ordinary text scan: goal_spec is the union of both, but waiver/verdict are checked
    ONLY against `text` — a file write can prove a spec exists, but per SKILL.md a waiver or a
    verdict must be authored in the executor's own turn text, never merely present in a file."""
    items = read_transcript_items(transcript_path)
    text = "\n".join(it["text"] for it in items if it["kind"] == "text")
    goal_spec = has_goal_spec(text) or any(it["kind"] == "goal_spec_file" for it in items)
    # goalspec_entered (0.45.0) is kept SEPARATE from goal_spec on purpose: "the method was
    # entered" and "a spec exists" are different facts, and the Stop gate / usage-budget hook read
    # only goal_spec. `items` is returned so a caller can scope a waiver (waiver_covers_command).
    entered = any(it["kind"] == "goalspec_entry" for it in items)
    # No "waiver" key since 0.45.0: its one consumer (the precheck) now scopes the waiver per
    # command through waiver_covers_command(items, ...); a transcript-wide flag here would invite
    # the next caller to reintroduce the session-wide waiver. The Stop gate has its own scan.
    return {"goal_spec": goal_spec, "goalspec_entered": entered,
            "verdict": operative_verdict(text), "text": text, "items": items,
            "relayed_hold": relayed_hold_line(items)}


def relayed_hold_line(items):
    """0.46.7 (p-64783f8057) — the verdict line of a hold that reached this session as a
    subagent's report and was never quoted as the executor's own text after it; None otherwise.
    It never makes `verdict` a hold: per SKILL.md the executor quotes the verdict in its own text,
    where the user sees it. Its one use is the deny text, which then gives the exact line to quote.
    Field case (agente-coordinador b30f155f, 2026-10-05): two holds arrived as background hand-backs
    while an AskUserQuestion was open, the executor quoted them only in its thinking, four pushes
    were denied, and it told the user the transcript was dropping its quotes."""
    last_relay = last_text = None
    for i, it in enumerate(items):
        if it["kind"] == "relayed_verdict":
            last_relay = i
        elif it["kind"] == "text" and re.search(VERDICT_RE, it["text"], re.I):
            last_text = i
    if last_relay is None or items[last_relay]["verdict"] != "hold":
        return None
    if last_text is not None and last_text > last_relay:
        return None
    return items[last_relay]["line"]


def _is_verdict_item(it):
    return it["kind"] in ("relayed_verdict", "verdict_file") or (
        it["kind"] == "text" and re.search(VERDICT_RE, it["text"], re.I))


def file_quoted_hold(items, session_id=None, cwd=None):
    """0.51.0 — a goal-adversary hold that reached this session as a subagent result, quoted by the
    executor with a Write/Edit to its own checkpoint instead of in visible text. -> the verdict line,
    or None. It counts as the quote does on the visible-text path, no more: any command, no check of
    later changes (operative_verdict does neither).

    Field case (2026-10-08, VPS session f8f10a20, 0.50.0): four holds arrived as hand-backs, the
    executor wrote the quote only in its thinking, the precheck denied ten `gh pr merge` calls with a
    deny text that already said thinking does not count, and the executor concluded the tool was
    deleting its messages; the PRs were merged by hand, outside the gate. Precedent for the way out:
    the spec brake (0.49.0 v3) stopped trapping agents that believed they had posted a spec once a
    Write to the checkpoint counted -- a tool call is on record, a belief about one's own text is not.
    Not measured for verdicts; the field case had no such Write.

    An earlier cut of 0.51.0 accepted the hand-back with no quote at all, deciding from the command
    text and the git commands after the hold; four adversary rounds kept finding commands that read
    one way to it and another to bash. This path reads no command text.

    Counts only when all hold, mirroring the visible-text quote (which passes while the most recent
    verdict is not a break):
      * a verdict_file in THIS session's checkpoint (own_checkpoint_re, under the cwd or the git top
        level -- as the spec brake), from a Write/Edit whose result was not an error
        (read_transcript_items), whose last verdict line is a hold;
      * that line is the same line as the most recent hand-back verdict before the Write, and that
        verdict is a hold: a hold written with no adversary behind it, or an old hold left in the
        file's history after a later break, does not count. Two all-zero holds are the same string,
        so this ties the quote to "the latest report was this hold", not to one report;
      * no verdict after that hand-back hold (hand-back, visible text, or another such Write) is a
        break -- including a break quoted in text between the hold and the Write, which the
        visible-text path would also stop at (external adversary round on this design)."""
    own = own_checkpoint_re(session_id)
    roots = own_checkpoint_roots(cwd)
    seq = [it for it in items if _is_verdict_item(it) and (
        it["kind"] != "verdict_file"
        or (own.search(it.get("path") or "") and _in_own_root(it.get("path") or "", cwd, roots)))]
    verdict_of = lambda it: it["verdict"] if it["kind"] != "text" else operative_verdict(it["text"])
    quote = None
    for i, it in enumerate(seq):
        if it["kind"] != "verdict_file" or it["verdict"] != "hold":
            continue
        relays = [j for j in range(i) if seq[j]["kind"] == "relayed_verdict"]
        if relays and seq[relays[-1]]["verdict"] == "hold" and seq[relays[-1]]["line"] == it["line"]:
            quote = (relays[-1], i)
    if quote is None or any(verdict_of(it) == "break" for it in seq[quote[0] + 1:]):
        return None
    return seq[quote[1]]["line"]


def relayed_break_after_text_hold(items):
    """0.51.0 — True when the most recent verdict on record is a break that came back as a
    goal-adversary's report, after a hold the executor quoted. Before, the quoted hold passed the
    precheck over it (external adversary round on the first cut of 0.51.0)."""
    seq = [it for it in items if _is_verdict_item(it) and it["kind"] != "verdict_file"]
    return bool(seq and seq[-1]["kind"] == "relayed_verdict" and seq[-1]["verdict"] == "break")


def checkpoint_name_for(session_id):
    sid = session_id if isinstance(session_id, str) and SESSION_ID_RE.fullmatch(session_id) else None
    return ".goalspec/checkpoint-%s.md" % sid if sid else ".goalspec/checkpoint.md"


# What the human sees when the precheck passes on a file-quoted hold (systemMessage): the quote went
# to a file, so the hook puts the line in front of them.
FILE_QUOTE_ALLOW = (
    "goalspec terminal-push precheck: proceeding on a goal-adversary hold that reached this session "
    "as a subagent result and that the agent quoted into its checkpoint ({path}): {line}"
)

# Agent-facing deny text for an unquoted hand-back hold. Kept here, not in the hook, for the same
# apostrophe reason as INTERVIEW_HANDOFF_NUDGE. 0.51.0 adds way (1): the field executor read the
# visible-text way ten times and never took it.
RELAYED_HOLD_NOTE = (
    "A goal-adversary hold DID reach this session, but as a subagent result, not as your own "
    "text: {line} -- a subagent result is not a quote. Thinking does not count either: thinking is "
    "not read, even when your screen shows it like a message. Your own visible text has no hold "
    "after it. Do ONE of these, then run this command again in a LATER message: (1) use the Write or "
    "Edit tool to put that exact line, on a line of its own, in {path}, after any older verdict "
    "line in it -- a tool call is "
    "on record even when a quote you believe you wrote is not; or (2) write that exact line as visible "
    "text in one message. The next message is enough, the turn does not need to end. You do not need "
    "a new adversary round, unless the change moved after that hold. The transcript is not losing "
    "your text."
)

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
import subprocess

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
GIT_MERGE_RE = re.compile(_GIT_PREFIX + r"merge\b")
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
    r"\brm\s+-\w*r\w*f\w*\s"  # rm -rf / -fr / -Rf etc, requires a following arg
    r"|\bwrangler\s+d1\s+migrations\s+apply\b"
    r"|\bprisma\s+migrate\s+deploy\b"
    r"|\bknex\s+migrate:latest\b"
    r"|\balembic\s+upgrade\b"
)


def classify_all(command):
    """Every kind present in `command`, in classify()'s priority order (0.45.0: `git push origin
    feat && gh pr merge` classified as push only, the push was out of scope as a feature push, and
    the merge in the same command ran unchecked)."""
    if not command:
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
    if not command:
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


def read_transcript_text(transcript_path):
    """-> the transcript's assistant text, all of it, joined — the text-only view of
    read_transcript_items() for callers that only need to grep prose (goal-spec / waiver / verdict
    presence) and don't care about tool_use ordering. Empty string on any error (missing path,
    unparseable lines) — same fail-open contract gate-goal-close.sh already relies on for an
    unreadable transcript."""
    return "\n".join(it["text"] for it in read_transcript_items(transcript_path) if it["kind"] == "text")


def _collect_event(ev, items):
    """Append the items one transcript event contributes (see read_transcript_items)."""
    if ev.get("type") == "user":
        # 0.45.0: a TYPED `/goalspec:interview` or `/goalspec:goalspec` lives only in a
        # user event, as the harness's own `<command-name>` tag. Only that exact tag
        # counts — never prose, and never a tool_result (which can carry any text,
        # including a grep over another transcript).
        ucontent = (ev.get("message") or {}).get("content")
        utexts = [ucontent] if isinstance(ucontent, str) else [
            b.get("text") for b in (ucontent or [])
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        ] if isinstance(ucontent, list) else []
        if any(COMMAND_ENTRY_RE.match(u.lstrip()) for u in utexts):
            items.append({"kind": "goalspec_entry", "timestamp": ev.get("timestamp"), "text": ""})
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
        elif blk.get("type") == "tool_use" and blk.get("name") == "Skill":
            # 0.45.0: the same entry, invoked by the model through the Skill tool.
            sk = (blk.get("input") or {}).get("skill")
            if isinstance(sk, str) and sk.strip() in ENTRY_SKILLS:
                items.append({"kind": "goalspec_entry", "timestamp": ts, "text": ""})
        elif blk.get("type") == "tool_use" and blk.get("name") == "Bash":
            cmd = (blk.get("input") or {}).get("command")
            if isinstance(cmd, str) and cmd:
                items.append({"kind": "bash", "timestamp": ts, "command": cmd, "id": blk.get("id")})
        elif blk.get("type") == "tool_use" and blk.get("name") in ("Write", "Edit"):
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
                        items.append({"kind": "goal_spec_file", "timestamp": ts, "text": v})


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
                    _collect_event(ev, items)
                except Exception:
                    continue
    except Exception:
        return []
    return items


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
            "verdict": operative_verdict(text), "text": text, "items": items}

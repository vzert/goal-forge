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
FORCE_FLAG_RE = re.compile(r"(^|\s)(-f|--force|--force-with-lease)(\s|$)")
PUSH_RE = re.compile(r"\bgit\s+push\b")
GH_MERGE_RE = re.compile(r"\bgh\s+pr\s+merge\b")
GIT_MERGE_RE = re.compile(r"\bgit\s+merge\b")
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


def push_target_branch(command, cwd):
    """Best-effort: explicit `git push <remote> <branch>` ref if present, else the current branch
    (the implicit target of a bare `git push` with upstream tracking configured)."""
    tokens = [t for t in command.split() if not t.startswith("-")]
    if len(tokens) >= 4 and tokens[0] == "git" and tokens[1] == "push":
        candidate = tokens[-1]
        if candidate not in ("push", "git"):
            if ":" in candidate:
                candidate = candidate.split(":")[-1]
            return candidate
    return current_branch(cwd)


def is_terminal(command, cwd):
    """-> (is_terminal: bool, kind: str|None, diffable: bool).

    'push' to a branch NOT in protected_branches() is explicitly OUT of scope (a feature-branch
    push headed for review is not the blast radius this gate exists for) UNLESS it force-pushes,
    which SKILL.md already names terminal regardless of branch.
    """
    kind = classify(command)
    if kind is None:
        return False, None, False
    if kind == "push":
        if FORCE_FLAG_RE.search(command):
            return True, kind, True
        branch = push_target_branch(command, cwd)
        if branch and branch in protected_branches(cwd):
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
    """Best-effort file list for a merge/gh-pr-merge about to run. Tries `gh pr diff` (works for a
    bare `gh pr merge` on the current branch's PR) first, then a `git merge <ref>` three-dot diff
    against the extracted ref. None when neither resolves."""
    out = _run(["gh", "pr", "diff", "--name-only"], cwd)
    if out is not None:
        return [p for p in out.splitlines() if p.strip()]
    m = re.search(r"\bgit\s+merge\s+(?:--\S+\s+)*(\S+)", command)
    if m:
        ref = m.group(1)
        out = _run(["git", "diff", "--name-only", "HEAD..." + ref], cwd)
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
        return push_diff_paths(cwd)
    if kind == "merge":
        return merge_diff_paths(command, cwd)
    return None  # deploy / destructive: not path-diffable, never content-exempt


# --- transcript reading (mirrors gate-goal-close.sh's own parsing, kept in lockstep) ---------------
GOAL_SPEC_RE = r"(^|\n)#{1,6}\s*Goal-spec\b"
WAIVER_RE = r"\[GOAL-CLOSE-WAIVED\s+reason=[^\]]{20,}\]"
VERDICT_RE = (r"\[ADVERSARY-VERDICT:\s*(break|hold)\s+ungrounded=\d+\s+unfalsified=\d+\s+"
              r"incomplete=\d+\s+autonomy-violations=\d+\s+unsafe=\d+\s*\]")
CR_RE = r"\[COMPLETION-REVIEW:\s*(adversary|none)\b([^\]]*)\]"


def read_transcript_text(transcript_path):
    """-> the transcript's assistant text, all of it, joined — the text-only view of
    read_transcript_items() for callers that only need to grep prose (goal-spec / waiver / verdict
    presence) and don't care about tool_use ordering. Empty string on any error (missing path,
    unparseable lines) — same fail-open contract gate-goal-close.sh already relies on for an
    unreadable transcript."""
    return "\n".join(it["text"] for it in read_transcript_items(transcript_path) if it["kind"] == "text")


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
                if ev.get("type") != "assistant":
                    continue
                ts = ev.get("timestamp")
                msg = ev.get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    if content:
                        items.append({"kind": "text", "timestamp": ts, "text": content})
                    continue
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "text" and blk.get("text"):
                        items.append({"kind": "text", "timestamp": ts, "text": blk["text"]})
                    elif blk.get("type") == "tool_use" and blk.get("name") == "Bash":
                        cmd = (blk.get("input") or {}).get("command")
                        if isinstance(cmd, str) and cmd:
                            items.append({"kind": "bash", "timestamp": ts, "command": cmd})
                    elif blk.get("type") == "tool_use" and blk.get("name") in ("Write", "Edit"):
                        # A ## Goal-spec can be written to disk (.goalspec/checkpoint.md, per
                        # SKILL.md step 5's own checkpoint pattern for long-running tasks) instead
                        # of posted as chat text. Confirmed live (goal-adversary, 2026-07-31): a
                        # real session's spec existed only inside Write tool_use blocks, never as
                        # assistant text, so the text-only scan below missed it — has_goal_spec()
                        # returned False against the real transcript, and the precheck hook
                        # silently ALLOWED the exact push it exists to gate.
                        #
                        # NARROWLY scoped to that one path and that one marker on purpose — a
                        # first attempt captured ANY Write/Edit content as text and broke
                        # immediately: SKILL.md and CHANGELOG.md are FULL of literal example
                        # marker text (`[GOAL-CLOSE-WAIVED reason=…]`, sample verdicts) written
                        # as documentation, and editing either file made has_waiver()/
                        # operative_verdict() see those examples as genuine declarations — a
                        # false positive far worse than the gap being closed. Only a Write/Edit
                        # whose `file_path` ends in `.goalspec/checkpoint.md` contributes text
                        # here, and only for the goal-spec-presence check below (has_goal_spec) —
                        # NOT tagged into the general text-marker scan, so it can never satisfy
                        # has_waiver/operative_verdict/completion-review, which SKILL.md itself
                        # requires to be authored in the executor's OWN turn text, not a file.
                        ti = blk.get("input") or {}
                        fp = ti.get("file_path")
                        if isinstance(fp, str) and fp.endswith(".goalspec/checkpoint.md"):
                            for key in ("content", "new_string"):
                                v = ti.get(key)
                                if isinstance(v, str) and re.search(GOAL_SPEC_RE, v, re.I):
                                    items.append({"kind": "goal_spec_file", "timestamp": ts, "text": v})
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


def operative_verdict(text):
    verdicts = re.findall(VERDICT_RE, text, re.I)
    return verdicts[-1].lower() if verdicts else None


def transcript_signals(transcript_path):
    """One parse, the four signals a caller like precheck-terminal-push.sh needs together:
    goal_spec (bool), waiver (bool), verdict (str|None), text (str, the plain assistant-authored
    prose only). Deliberately the ONE place that combines the checkpoint-file goal-spec signal
    (kind="goal_spec_file", scoped narrowly in read_transcript_items — see its docstring for why)
    with the ordinary text scan: goal_spec is the union of both, but waiver/verdict are checked
    ONLY against `text` — a file write can prove a spec exists, but per SKILL.md a waiver or a
    verdict must be authored in the executor's own turn text, never merely present in a file."""
    items = read_transcript_items(transcript_path)
    text = "\n".join(it["text"] for it in items if it["kind"] == "text")
    goal_spec = has_goal_spec(text) or any(it["kind"] == "goal_spec_file" for it in items)
    return {"goal_spec": goal_spec, "waiver": has_waiver(text), "verdict": operative_verdict(text), "text": text}

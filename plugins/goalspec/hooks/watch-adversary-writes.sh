#!/usr/bin/env bash
# watch-adversary-writes.sh — SubagentStart/SubagentStop hook. The MEASURING half of the read-only
# rail for the SUBAGENT backend; the rule itself is a paragraph in agents/goal-adversary.md.
#
# The problem it fixes: the goal-adversary subagent holds `Bash` (it needs it — re-deriving a figure
# means running the query, the suite, the git command). Nothing stopped it from also WRITING, and
# some adversary runs take the initiative to fix what they find. An adversary that repairs the work
# then verifies a state it created — principle 1 turned on the verifier — and the resulting clean
# `hold` is indistinguishable from an honest one. The external backend got the same rail in
# hooks/external-adversary.sh; this is the subagent half, so the rule exists on BOTH carriers with a
# consumer on each rather than as prose on one of them.
#
# WHY THESE TWO EVENTS AND NOT THE Task HOOKS. The obvious seam looked like the PreToolUse/PostToolUse
# pair already registered on `Task|Agent` (route-external-adversary.sh, remind-quote-verdict.sh). It
# does not work: since Claude Code v2.1.198 subagents run in the BACKGROUND by default, so the Task
# tool result is a handle and PostToolUse fires at LAUNCH, not at completion — measured and documented
# at length in remind-quote-verdict.sh. A snapshot pair around the Task call would bracket the spawn,
# not the run: an instrument that measures nothing, which is the exact defect this rail exists to
# catch. SubagentStart/SubagentStop bracket the actual run and carry `agent_type` + `agent_id`, so the
# attribution is structural rather than guessed.
#
# What it does:
#   start -> fingerprint the repository CONTENT, stash it under $TMPDIR keyed by agent_id.
#   stop  -> fingerprint again, diff, RE-ARM the snapshot, and if anything changed RECORD the paths
#            to a per-session findings file. It emits NOTHING.
#
# IT EMITS NOTHING, AND THAT IS THE POINT (0.44.1). A SubagentStop hook's output goes to the subagent
# that just stopped, never to the executor — measured, see the long note at the bottom of this file.
# 0.44.0 emitted here, so the warning reached only the party it was about, written in the second
# person, and one goal-adversary read it as a role change and started editing. The reporting half now
# lives in hooks/report-adversary-writes.sh, on `Stop`, whose output does reach the executor.
#
# Deliberately NOT a revert and NOT a block: SubagentStop cannot un-write anything, undoing a change
# the human may have made themselves is precisely the no-harm violation this checks for, and the
# external half already refuses remove-verbs on artifacts it does not own. Naming the paths is the
# whole job.
#
# Fail-open everywhere: no git, no repo, no writable TMPDIR, unparseable payload, missing snapshot ->
# exit 0, silent. It never blocks a subagent and never blocks a close.
#
# Registered by hooks/hooks.json on SubagentStart and SubagentStop, matcher "(^|:)goal-adversary$".
# The matcher is belt; the agent_type re-check below is braces — a harness that passes the matcher
# loosely must not turn this into a fingerprint of every subagent in the session.
#
# Usage: watch-adversary-writes.sh start|stop   (payload JSON on stdin)

MODE="${1:-}"
[ "$MODE" = "start" ] || [ "$MODE" = "stop" ] || exit 0

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

# Pull the three fields we need. Prints "agent_id<TAB>cwd" only for a real goal-adversary; anything
# else -> empty, and this hook goes silent.
FIELDS=$(printf '%s' "$INPUT" | "$PY" -c '
import json, sys, re
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
at = d.get("agent_type") or ""
# Same anchor remind-quote-verdict.sh uses: "goal-adversary" and "goalspec:goal-adversary" match,
# "not-goal-adversary-example" does not. That fabricated form slipped a bare substring check once.
if not (isinstance(at, str) and re.search(r"(^|:)goal-adversary$", at.strip().lower())):
    sys.exit(0)
aid = d.get("agent_id") or d.get("session_id") or ""
cwd = d.get("cwd") or ""
sid = d.get("session_id") or ""
if not aid:
    sys.exit(0)
# Keys must be filesystem-safe: ids are harness-generated, so this is hygiene, not distrust.
safe = lambda v: re.sub(r"[^A-Za-z0-9_.-]", "_", str(v))[:120]
print(safe(aid) + "\t" + str(cwd) + "\t" + safe(sid))
' 2>/dev/null)

[ -z "$FIELDS" ] && exit 0
AGENT_KEY=$(printf '%s' "$FIELDS" | cut -f1)
PAYLOAD_CWD=$(printf '%s' "$FIELDS" | cut -f2)
SESSION_KEY=$(printf '%s' "$FIELDS" | cut -f3)
[ -n "$SESSION_KEY" ] || SESSION_KEY="$AGENT_KEY"

# Resolve the repo from the payload cwd, not from this process cwd: a hook runs wherever the harness
# puts it, and the payload states where the session actually is.
[ -n "$PAYLOAD_CWD" ] && [ -d "$PAYLOAD_CWD" ] || PAYLOAD_CWD=$PWD
REPO_ROOT=$(git -C "$PAYLOAD_CWD" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$REPO_ROOT" ] || exit 0

# Snapshots live OUTSIDE the repository — writing them inside would make this instrument trip on
# itself, the most embarrassing way for a change-detector to fail.
SNAP_DIR="${TMPDIR:-/tmp}/goalspec-adversary-snap"
mkdir -p "$SNAP_DIR" 2>/dev/null || exit 0
SNAP="$SNAP_DIR/$AGENT_KEY.fp"

# CONTENT, not `git status`. The tree under review is almost always ALREADY dirty (the uncommitted
# work being verified), so a partner that appends one line to an already-modified file leaves the
# byte-identical " M path" porcelain line before and after. Hash the blobs instead.
# KNOWN GAPS, stated rather than left to be discovered: gitignored paths are invisible to
# `--exclude-standard` (`.goalspec/` is the one that matters and is hashed explicitly below; others
# are out of reach), writes outside the repo root are out of scope by design (that is where scratch
# belongs), and a file changed and changed back reads as unchanged — correctly, nothing was left
# modified. This mirrors hooks/external-adversary.sh so the two backends measure the same thing; when
# one changes, change both.
fingerprint() {
  printf 'HEAD %s\n' "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unborn)"
  printf 'staged %s\n' "$(git -C "$REPO_ROOT" diff --cached 2>/dev/null | git hash-object --stdin 2>/dev/null || echo none)"
  git -C "$REPO_ROOT" ls-files -m -o -d --exclude-standard -z 2>/dev/null \
    | while IFS= read -r -d '' p; do
        if [ -f "$REPO_ROOT/$p" ]; then
          printf '%s %s\n' "$(git -C "$REPO_ROOT" hash-object -- "$REPO_ROOT/$p" 2>/dev/null || echo unreadable)" "$p"
        else
          printf 'absent %s\n' "$p"
        fi
      done
  for f in "$REPO_ROOT"/.goalspec/*; do
    [ -f "$f" ] || continue
    printf '%s %s\n' "$(git -C "$REPO_ROOT" hash-object -- "$f" 2>/dev/null || echo unreadable)" "${f#"$REPO_ROOT"/}"
  done
}

if [ "$MODE" = "start" ]; then
  fingerprint > "$SNAP" 2>/dev/null || true
  exit 0
fi

# stop: no snapshot means this hook did not see the start (installed mid-run, unwritable TMPDIR,
# a harness that skipped the event). Silence is correct — claiming "no writes detected" from a
# measurement that never ran is the broken instrument this whole rail is about.
[ -f "$SNAP" ] || exit 0

AFTER=$(fingerprint 2>/dev/null || true)
BEFORE=$(cat "$SNAP" 2>/dev/null || true)
# RE-ARM, do not delete. A subagent can stop and then keep going (a harness that resumes it, a
# teammate message, a hook that hands it more context), and 0.44.0 deleted the snapshot on the first
# stop — so everything the agent did afterwards was unmeasured, silently. That is exactly what
# happened in the recorded 2026-09-12 incident: the writes this rail exists to catch landed AFTER
# the first stop and no second firing could see them. Making AFTER the new baseline means the next
# stop measures only the new delta.
printf '%s\n' "$AFTER" > "$SNAP" 2>/dev/null || true

[ "$BEFORE" = "$AFTER" ] && exit 0

# Name the path column of every line present in exactly one capture. A changed blob yields two
# differing lines for the same path; sort -u collapses them. The two HEADER lines carry no path, so
# they get NAMED rather than stripped: without this the generic rule prints their bare hash as if it
# were a filename, which is how case 05 (a staged change) first came back reporting a 40-char hex
# string as a modified file. Keep this in step with the identical extractor in external-adversary.sh.
CHANGED=$(diff <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$AFTER") 2>/dev/null \
          | grep -E '^[<>]' \
          | sed -E -e 's/^[<>] HEAD .*/(HEAD moved: a commit or checkout happened during the run)/' \
                   -e 's/^[<>] staged .*/(the git index: content was staged or unstaged)/' \
                   -e 's/^[<>] [^ ]+ ?//' \
          | grep -v '^$' | sort -u || true)
[ -z "$CHANGED" ] && CHANGED="(content changed but no path could be named — inspect \`git status\` by hand)"

# DO NOT EMIT HERE. This is the half of 0.44.0 that was wrong, and it was worse than useless.
# MEASURED on 2026-09-12 in a real session (3-tier-memory, session 035edc21): a SubagentStop hook
# emitting `systemMessage`/`additionalContext` has its output delivered to the SUBAGENT THAT JUST
# STOPPED, not to the executor — it lands in that agent's own transcript as
# `type: attachment, isSidechain: true`, and the executor's transcript contains it ZERO times. So the
# party that needed the warning never saw it, and the party the warning is ABOUT received a text
# written in the second person ("YOU edited under an in-flight verifier... decide what to keep or
# revert"). The goal-adversary read it as addressed to itself, concluded it had become the executor,
# and wrote to five files in the repo under review. The detector of adversary writes had become their
# trigger.
#
# So the finding is RECORDED here and REPORTED from a hook whose output does reach the executor:
# hooks/report-adversary-writes.sh, on `Stop`. That routing is measured too, in the same transcript:
# a `hookName: "Stop"` attachment lands with `isSidechain: false` in the executor's own file.
#
# One record per firing, append-only, keyed by SESSION so a different session never picks it up. The
# reporter reads, emits, and deletes.
FINDINGS="$SNAP_DIR/$SESSION_KEY.findings"
{
  printf 'ts=%s agent=%s repo=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$AGENT_KEY" "$REPO_ROOT"
  printf '%s\n' "$CHANGED" | sed 's/^/path /'
  printf 'end\n'
} >> "$FINDINGS" 2>/dev/null || true
exit 0

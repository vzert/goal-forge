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
#   stop  -> fingerprint again, diff, and if anything changed, tell the executor which paths and
#            what the two readings of that fact are.
#
# TWO READINGS, BOTH FINDINGS — the message says so rather than accusing:
#   (a) the adversary wrote to the tree it was reviewing; or
#   (b) the executor edited under an in-flight verifier, which the project discipline forbids for the
#       same reason (the verdict then describes a state that no longer exists).
# A background round genuinely can produce (b) as a false alarm for the rail but not for the method:
# a synchronous closing round cannot.
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
if not aid:
    sys.exit(0)
# Key must be filesystem-safe: agent ids are harness-generated, so this is hygiene, not distrust.
print(re.sub(r"[^A-Za-z0-9_.-]", "_", str(aid))[:120] + "\t" + str(cwd))
' 2>/dev/null)

[ -z "$FIELDS" ] && exit 0
AGENT_KEY=${FIELDS%%	*}
PAYLOAD_CWD=${FIELDS#*	}

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
rm -f "$SNAP" 2>/dev/null || true

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

MSG="A goal-adversary subagent just finished, and the repository content changed while it was running. Paths whose bytes differ between the start and the end of its run:
$(printf '%s\n' "$CHANGED" | sed 's/^/  - /')

There are exactly two readings and both are findings, so do not wave it through. (1) The adversary WROTE to the work it was sent to measure — it was told not to, and a verdict it returns now describes a state it created, so treat that verdict as UNVERIFIED rather than a pass: decide what to keep or revert, then re-run the review over a tree nobody edited mid-flight. (2) YOU edited under an in-flight verifier — which the executor discipline forbids for the same reason: its verdict is about a tree that no longer exists. A background round can produce (2) innocently; a synchronous closing round cannot. Say in your close which of the two it was, with the evidence, instead of leaving it implied. This hook never reverts anything and never blocks: it only reports what it measured."

printf '%s' "$MSG" | "$PY" -c '
import json, sys
m = sys.stdin.read()
print(json.dumps({"systemMessage": m,
                  "hookSpecificOutput": {"hookEventName": "SubagentStop", "additionalContext": m}}))
' 2>/dev/null || true
exit 0

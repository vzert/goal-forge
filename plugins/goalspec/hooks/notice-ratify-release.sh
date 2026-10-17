#!/usr/bin/env bash
# notice-ratify-release.sh — UserPromptSubmit hook (0.61.0).
#
# Why: the ratify brake (precheck-spec-before-work.sh) tells an agent when it is held, and nothing
# told it when it was not. Measured 2026-10-16 (3-tier-memory session 69eb8c3a, supervised by
# lookout): the brake denied a Bash, the human's approval reached the agent by a cross-session
# message the brake does not read, a note lookout typed in the pane then released the brake, and
# the agent waited 7 hours for a typed approval it no longer needed.
#
# What it does: when the brake is armed, has denied a call since the spec it waits on, and the
# message being submitted is one that releases it (typed, not harness-written, not a goalspec
# command), it adds one note for the agent: the tools are free again, and whether it has the
# human's approval is its own call (terminal_actions.ratify_release_notice).
#
# What it does NOT do: block anything, judge who typed the message, or read what it says. Silent
# when no deny happened (the agent never believed it was held). Fail-open: any error prints nothing.

INPUT=$(cat)

[ "${GOAL_SPEC_BRAKE:-}" = "0" ] && exit 0
[ "${GOAL_RATIFY_BRAKE:-}" = "0" ] && exit 0

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | LIBDIR="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib" "$PY" -c '
import json, os, sys

libdir = os.environ.get("LIBDIR", "")
if libdir and libdir not in sys.path:
    sys.path.insert(0, libdir)
try:
    import terminal_actions as ta
except Exception:
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

if data.get("hook_event_name") != "UserPromptSubmit":
    sys.exit(0)

items = ta.read_transcript_items(data.get("transcript_path"), ratify_denies=True)
sid = str(data.get("session_id") or "").strip()
msg = ta.ratify_release_notice(items, sid, data.get("cwd") or os.getcwd(), data.get("prompt"))
if not msg:
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                         "additionalContext": msg}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

#!/usr/bin/env bash
# nudge-interview-handoff.sh — UserPromptSubmit hook, and PostToolUse hook (matcher: AskUserQuestion).
#
# Why: the interview (skills/interview/SKILL.md) ends by handing off to the goalspec loop, which
# writes the `## Goal-spec`. Field data (0.46.0): on one team VPS, 11 of 23 interview sessions never
# wrote a spec and never invoked the loop; on the maintainer machine, 10 of 70. The agent finished
# the interview and went straight to editing, pushing and merging. The skill text relied on the
# loop auto-triggering; 0.46.0 changes it to an explicit Skill call, and this hook is the reminder
# that reaches the agent at the two moments the handoff is decided:
#   * PostToolUse on AskUserQuestion — right after an interview round is answered, which is where
#     the agent moves from the last answer into work, usually in the SAME turn;
#   * UserPromptSubmit — on a later user message, while the spec is still missing AND work (a Bash,
#     Write or Edit call) has happened since the interview. An interview that concluded "nothing
#     to do" followed by plain conversation gets no reminder.
#
# What it does: if the most recent /goalspec:interview in this transcript has not been followed by
# the goalspec loop being invoked or a `## Goal-spec` being written, it adds one agent-facing line
# of context (terminal_actions.INTERVIEW_HANDOFF_NUDGE). Otherwise it prints nothing.
#
# What it does NOT do: block anything. It is advisory by design (the user chose reminder over a hard
# block of edits, 2026-09-29). The hard stop at the point of harm is precheck-terminal-push.sh, which
# since 0.45.0 denies a protected push, a merge or a deploy in an interview session with no spec.
# It cannot tell a round that is mid-interview from the last one, so it can fire after each round;
# the text says "when it is done", so an early reminder asks for nothing premature.
#
# Fail-open, like every hook here: any error prints nothing. Registered by hooks/hooks.json.

INPUT=$(cat)

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

event = data.get("hook_event_name") or ""
if event == "PostToolUse":
    if data.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
elif event != "UserPromptSubmit":
    sys.exit(0)

items = ta.read_transcript_items(data.get("transcript_path"))
if not ta.interview_handoff_pending(items, require_work=(event == "UserPromptSubmit")):
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                         "additionalContext": ta.INTERVIEW_HANDOFF_NUDGE}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

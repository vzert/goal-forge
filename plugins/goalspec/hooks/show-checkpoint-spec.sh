#!/usr/bin/env bash
# show-checkpoint-spec.sh — PostToolUse hook (matcher: Write|Edit).
#
# Why (v3 of the spec brake, p-718231fa66): precheck-spec-before-work.sh accepts a `## Goal-spec`
# written with Write/Edit to this session's .goalspec/checkpoint, because 2 of 6 agents could not
# be brought to post it as text (they believed they already had). A spec in a file the human never
# opens is still invisible to them, so this hook puts it in front of the human: a systemMessage,
# which the harness shows to the user, with the spec section of what was just written.
#
# Fires only when: the written path is a goalspec checkpoint (terminal_actions.CHECKPOINT_PATH_RE),
# the written text carries a `## Goal-spec`, the call was made by the main agent (no agent_id), and
# the session has no visible-text spec yet -- once the spec is on screen as text, repeating it on
# every checkpoint update would be noise.
#
# Fail-open: any error prints nothing. Registered by hooks/hooks.json.

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | LIBDIR="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib" "$PY" -c '
import json, os, re, sys

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

if data.get("hook_event_name") != "PostToolUse" or data.get("tool_name") not in ("Write", "Edit"):
    sys.exit(0)
if data.get("agent_id"):
    sys.exit(0)
inp = data.get("tool_input") or {}
fp = str(inp.get("file_path") or "").replace("\\", "/")
if not ta.CHECKPOINT_PATH_RE.search(fp):
    sys.exit(0)
excerpt = ta.checkpoint_spec_excerpt(inp.get("content") or inp.get("new_string") or "")
if not excerpt:
    sys.exit(0)
items = ta.read_transcript_items(data.get("transcript_path"))
if ta.has_goal_spec("\n".join(it["text"] for it in items if it["kind"] == "text")):
    sys.exit(0)

print(json.dumps({"systemMessage": "goalspec -- the agent wrote its plan to " + fp +
                  " instead of posting it. Here it is:\n\n" + excerpt}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

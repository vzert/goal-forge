#!/usr/bin/env bash
# name-session.sh — UserPromptSubmit hook (0.56.0).
#
# Why: with several agents open, each session should show what it is doing, and SendMessage
# addresses a session by that same name. The Skill tool refuses /rename ("a UI command, not a
# skill", measured 2026-10-14), but a hook can set
# `sessionTitle`, which has the same effect. The goalspec loop asks the agent to put one line in the
# `## Goal-spec`, `Session name: <slug>` (project + short task), and this hook applies it on the next
# user message.
#
# Measured 2026-10-14 with claude -p and a probe plugin: the field works inside hookSpecificOutput
# and is ignored at the top level; the input carries `session_title` when a hook or --name set one.
#
# What it does: if a spec in this transcript names a session and the session has no title, or has a
# title an earlier spec of this session set, it sets the newest one (terminal_actions.
# session_title_to_set). A title the user, lookout or --name set is never touched.
#
# What it does NOT do: block anything, or rename in the same turn the spec is written — the next
# user message is the first moment a hook can act. Fail-open: any error prints nothing.

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
# Claude Code writes the payload as UTF-8, but on Windows python reads stdin, prints and open()s
# with the system code page (cp1252): an accent in a path or prompt arrived garbled, or made
# json.load fail and the hook go silent (p-ee6150b00b). Force UTF-8 for every python started here.
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

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

items = ta.read_transcript_items(data.get("transcript_path"))
title = ta.session_title_to_set(items, data.get("session_title"))
if not title:
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                         "sessionTitle": title}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

#!/usr/bin/env bash
# precheck-spec-before-work.sh — PreToolUse hook (matcher: Bash|Write|Edit|MultiEdit|NotebookEdit).
#
# Why (0.49.0, p-718231fa66): an isolated replica (`claude -p`, a fresh copy per run, no MCP, N=6
# per arm, 2026-10-07) found the cause of the skipped spec. With a shell available, an agent that
# loads the goalspec loop reads one or two files and goes straight to Bash: no visible spec before
# the first Bash in 0 of 6 runs on 0.47.0, 0 of 6 on 0.44.0, 0 of 6 on another task, and 1 of 6 on
# 0.48.0, whose entry nudge (nudge-spec-on-entry.sh) fired in all six. Two agents then claimed in
# writing they had posted the spec at the start; it existed only in their thinking. Without a shell
# the same agents posted it 6 of 6. A reminder does not reach an agent that believes it complied.
#
# What it does: while this session has entered the goalspec loop and posted no `## Goal-spec` as
# visible text (terminal_actions.spec_brake_armed), it denies Bash, Write, Edit, MultiEdit and
# NotebookEdit, with a reason that says how to release it. It does NOT hold: Read/Grep/Glob (not
# matched — grounding the spec needs them), a write under .goalspec/ (the checkpoint), any tool
# call made inside a subagent (the payload carries agent_id; its transcript_path is the parent's,
# so without this an explorer spawned before the spec would be held for the parent's missing spec),
# a session that only ran /goalspec:interview or goalspec:adversary, or a session with no goalspec.
#
# Escape hatch for the human: GOAL_SPEC_BRAKE=0 in the environment Claude Code runs in.
#
# Fail-open, like every hook here: an unreadable payload, a missing module or transcript allows.
# Registered by hooks/hooks.json.

INPUT=$(cat)

[ "${GOAL_SPEC_BRAKE:-}" = "0" ] && exit 0

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

if data.get("hook_event_name") != "PreToolUse":
    sys.exit(0)
tool = data.get("tool_name")
if tool not in ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"):
    sys.exit(0)
if data.get("agent_id"):
    sys.exit(0)

inp = data.get("tool_input") or {}
if tool != "Bash":
    path = str(inp.get("file_path") or inp.get("notebook_path") or "").replace(os.sep, "/")
    if path.startswith(".goalspec/") or "/.goalspec/" in path:
        sys.exit(0)

items = ta.read_transcript_items(data.get("transcript_path"))
if not ta.spec_brake_armed(items):
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "deny",
                                         "permissionDecisionReason": ta.SPEC_BRAKE_REASON + ta.spec_brake_evidence(items)}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

#!/usr/bin/env bash
# precheck-spec-before-work.sh — PreToolUse hook (matcher: Bash|Write|Edit|MultiEdit|NotebookEdit).
#
# Why (0.49.0, p-718231fa66): an isolated replica (`claude -p`, a fresh copy per run, no MCP, N=6
# per arm, 2026-10-07) found the cause of the skipped spec. With a shell available, an agent that
# loads the goalspec loop reads one or two files and goes straight to Bash: no visible spec before
# the first Bash in 0 of 6 runs on 0.47.0, 0 of 6 on 0.44.0, 0 of 6 on another task, and 1 of 6 on
# 0.48.0, whose entry nudge (nudge-spec-on-entry.sh) fired in all six. Two agents then claimed in
# writing they had posted the spec at the start; no visible text held one. Without a shell
# the same agents posted it 6 of 6. A reminder does not reach an agent that believes it complied.
#
# What it does: while this session has entered the goalspec loop and has no `## Goal-spec` -- in
# visible text or written to its .goalspec/ checkpoint (terminal_actions.spec_brake_armed) -- it
# denies Bash, Write, Edit, MultiEdit and NotebookEdit, with a reason that names the exact
# checkpoint path to write (from the payload session_id; absolute since 0.67.2). v1/v2 accepted
# visible text only and left 2 of 6 agents stuck; a Write call is a tool call they do make, and
# show-checkpoint-spec.sh shows its spec to the human. It does NOT hold: Read/Grep/Glob (not
# matched — grounding the spec needs them), a write under .goalspec/ (the checkpoint), any tool
# call made inside a subagent (the payload carries agent_id; its transcript_path is the parent's,
# so without this an explorer spawned before the spec would be held for the parent's missing spec),
# a session that only ran /goalspec:interview or goalspec:adversary, or a session with no goalspec.
#
# 0.60.0 — the same hook then holds the same tools a second time: once the spec exists, in an
# interactive session (entrypoint cli or claude-vscode), until the human has been asked to ratify
# it (an answered AskUserQuestion after the first spec of the cycle, or a typed prompt; a spec
# written after a [COMPLETION-REVIEW] starts a new cycle) -- terminal_actions.ratify_brake_armed.
# Measured 2026-10-15: since 0.49.0, 5 of 67 interactive
# sessions with a spec asked before their first Bash, Write or Edit. Same exemptions as above
# (Read-class tools, .goalspec/ writes, subagents); headless (sdk-*) sessions are never held.
#
# 0.68.2 (issue #1) -- native plan mode: a write to the plan file (a .md directly in
# $CLAUDE_CONFIG_DIR/plans or ~/.claude/plans) is held by neither, a spec written there counts, and
# an ExitPlanMode whose result is the approval ratifies the spec (terminal_actions.is_plan_file).
#
# Escape hatches for the human: GOAL_SPEC_BRAKE=0 turns off both holds; GOAL_RATIFY_BRAKE=0 only
# the second.
#
# Fail-open, like every hook here: an unreadable payload, a missing module or transcript allows.
# Registered by hooks/hooks.json.

INPUT=$(cat)

[ "${GOAL_SPEC_BRAKE:-}" = "0" ] && exit 0

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
# Claude Code writes the payload as UTF-8, but on Windows python reads stdin, prints and open()s
# with the system code page (cp1252): an accented path arrived garbled and the hook went silent,
# and a file with an accent was misread or rewritten (p-ee6150b00b). Force UTF-8 for every python.
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
    # 0.68.2 (issue #1): the plan-mode plan file is the only file plan mode lets the agent write.
    if ta.is_plan_file(str(inp.get("file_path") or inp.get("notebook_path") or "")):
        sys.exit(0)

items = ta.read_transcript_items(data.get("transcript_path"))
sid = str(data.get("session_id") or "").strip()
cwd = data.get("cwd") or os.getcwd()
if not ta.spec_brake_armed(items, sid, cwd):
    if os.environ.get("GOAL_RATIFY_BRAKE") != "0" and ta.ratify_brake_armed(items, sid, cwd):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": ta.RATIFY_BRAKE_REASON}}))
    sys.exit(0)

path = ".goalspec/checkpoint-%s.md" % sid if ta.SESSION_ID_RE.fullmatch(sid) else ".goalspec/checkpoint.md"
# 0.67.2 (issue #2): absolute, under the directory the session started in. A relative path read
# against a cwd the agent has since left named a file that the brake did not count.
path = os.path.join(ta.session_start_cwd(items) or cwd, path).replace(os.sep, "/")
reason = ta.SPEC_BRAKE_REASON.format(path=path) + ta.spec_brake_evidence(items)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "deny",
                                         "permissionDecisionReason": reason}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

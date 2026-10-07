#!/usr/bin/env bash
# nudge-spec-on-entry.sh — PostToolUse hook (matcher: Skill).
#
# Why (0.48.0): measured 2026-10-06 over 275 real sessions (maintainer Mac + team VPS), 25 loaded the
# goalspec skill and never posted a visible `## Goal-spec`. Two shapes were seen in the agents' own
# transcripts: the spec was written only in the agent's thinking and believed visible (one agent's
# own reasoning said so, and its adversary broke on it), or it was never written at all — the agent
# loaded the skill with an already-concrete task in the same turn, planned in its thinking and went
# straight to tools. A controlled replication reproduced the second shape without any supervisor
# brief (2 of 2 clean runs). The skill text already says to post the spec "at the start of the run";
# what was missing is a reminder at the one moment the decision is made: right after the skill
# loads, before the first tool call of the work.
#
# What it does: on a Skill call that loads the goalspec LOOP (goalspec:goalspec), if this session has
# no spec yet (no `## Goal-spec` in assistant text, none in this session's .goalspec/checkpoint),
# it adds one agent-facing line of context. Otherwise it prints nothing — a re-entry after a spec
# already exists, /goalspec:interview and goalspec:adversary get no reminder.
#
# What it does NOT do: block anything. The Stop gate (gate-goal-close.sh, step 2b) is the backstop
# at the end of the turn, also advisory. Whether the agent then writes the spec is behavior outside
# the hook and needs live observation.
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

if data.get("hook_event_name") != "PostToolUse" or data.get("tool_name") != "Skill":
    sys.exit(0)
skill = ((data.get("tool_input") or {}).get("skill") or "").strip()
if skill not in ("goalspec:goalspec", "goalspec"):
    sys.exit(0)

if ta.transcript_signals(data.get("transcript_path")).get("goal_spec"):
    sys.exit(0)

print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                         "additionalContext": ta.SPEC_ON_ENTRY_NUDGE}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

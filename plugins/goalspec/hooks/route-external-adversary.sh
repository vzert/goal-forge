#!/usr/bin/env bash
# route-external-adversary.sh — PreToolUse hook. Gives the `adversary.backend: "external"` config a
# MECHANICAL consumer.
#
# The problem it fixes: choosing the external backend (codex / a different vendor) is, in the SKILL,
# a prose instruction the executing agent must remember to read every run. Nothing enforced it, so an
# agent (and the fleet) would default to the zero-config subagent path and silently never route to the
# configured external adversary — a self-report/config emission with no consumer, the exact
# instrument-validity defect the method warns about (references/instrument-validity-own-tools.md).
#
# What it does: fires just before a `goal-adversary` subagent is spawned (Task/Agent tool). If the
# per-key-resolved config says backend=external, it injects a one-line reminder to route the verification
# through hooks/external-adversary.sh (the configured external_cmd) — at exactly the moment it matters.
#
# Deliberately NON-BLOCKING and fail-open, in the method's spirit:
#   * It never denies the spawn. The subagent is still a valid adversary (context-independent), and
#     "run BOTH backends" is strictly better; blocking could also leave a host with no adversary at all
#     if codex is unreachable (e.g. sanitized daemon PATH). The nudge is mechanical, not coercive.
#   * Only fires for a goal-adversary spawn AND backend=external. Every other tool call → silent.
#   * Any parse error / missing input / not-our-tool → exit 0, no output.
#
# Registered as a PreToolUse hook (matcher Task|Agent) by hooks/hooks.json.

INPUT=$(cat)

# Portable interpreter: python3 (macOS/Linux) then python (Windows / Git Bash), python3 first so
# Mac/Linux never fall back. The code targets Python 3 (the only Python shipping in 2026); on a
# py2-only host the config read raises and the hook degrades fail-open (silent, never blocks).
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

# PLUGIN_ROOT must be set on the PYTHON process (not on printf) or os.environ never sees it.
RESULT=$(printf '%s' "$INPUT" | PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-}" "$PY" -c '
import json, sys, os, re

def silent():
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    silent()

# 1. Only our tool + only a goal-adversary spawn.
if data.get("tool_name") not in ("Task", "Agent"):
    silent()
ti = data.get("tool_input") or {}
# subagent_type is the canonical field; be defensive about a couple of aliases.
subagent = ""
for k in ("subagent_type", "subagentType", "agent_type", "agentType"):
    v = ti.get(k)
    if isinstance(v, str) and v:
        subagent = v; break
if "goal-adversary" not in subagent.lower():
    silent()

# 2. Resolve adversary.backend per key: project .claude/goal.config.json OVERRIDES user-global
#    ~/.claude/goal.config.json — the SAME precedence external-adversary.sh applies to external_cmd,
#    so the hook that nudges and the command that runs never disagree.
def read_key(path, key):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            adv = (json.load(fh).get("adversary") or {})
        v = adv.get(key)
        return v if isinstance(v, str) and v.strip() else ""
    except Exception:
        return ""

proj = os.environ.get("GOAL_CONFIG_PATH") or ".claude/goal.config.json"
home = os.environ.get("HOME") or ""
glob = os.path.join(home, ".claude", "goal.config.json") if home else ""

backend = read_key(proj, "backend") or (read_key(glob, "backend") if glob else "")
if backend.lower() != "external":
    silent()

ext_cmd = read_key(proj, "external_cmd") or (read_key(glob, "external_cmd") if glob else "") or "codex exec"
root = os.environ.get("PLUGIN_ROOT") or ""
hook_path = os.path.join(root, "hooks", "external-adversary.sh") if root else "hooks/external-adversary.sh"

msg = ("goalspec config resolves adversary.backend=external (" + ext_cmd + "). Route this "
       "goal-adversary verification through the external backend — pipe the goal-spec + outcome + ask "
       "record to `" + hook_path + "` (it runs `" + ext_cmd + "`, a different vendor) and read its "
       "[ADVERSARY-VERDICT:]/[ADVERSARY-MODEL:] from there. Running the subagent too is fine (both "
       "backends is stronger); routing to ONLY the subagent silently skips the independence you "
       "configured. If the external binary is unreachable it fails open to an UNVERIFIED hold — not a block.")

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg},
}))
' 2>/dev/null)

# Fail-open: empty output → allow the spawn silently.
[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

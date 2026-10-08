#!/usr/bin/env bash
# precheck-subagent-model.sh — PreToolUse hook (matcher: Task|Agent), new in 0.50.0.
#
# Why: a field session (auditoria-turismo, 2026-10-08) ran the goalspec loop, split its execution
# into 5 parallel general-purpose subagents ("Decompose execution") and passed no `model` on any
# of them, so all 5 inherited the session's Opus tier for reading and classifying work; the
# largest read ~18M cached tokens. SKILL.md gave the grounding explorer a cheaper tier and said
# nothing about execution workers. Asked afterwards, the agent defended its own tier.
#
# What it does: in a session that entered goalspec (the loop or /goalspec:interview), the FIRST
# Task/Agent spawn with no `model` is denied, once, with a reason carrying SKILL.md's
# "Subagent model by task" table. The agent relaunches with a tier it chose; passing its own tier
# explicitly is a valid choice and passes. After one model-less spawn on record (denied or not)
# the next one passes, so the agent is never stuck. A goal-adversary spawn has its own counter
# and its own reason (independence, not cost: SKILL.md step 6, "Different model on every run").
#
# Why deny and not a reminder: a PreToolUse reminder arrives with the tool result, after the
# subagent already started; the 5 spawns above went out in ONE message and a reminder would have
# reached none of them. Parallel spawns in one message are each denied here, because a message
# reaches the transcript only after its tool calls run.
#
# Silent (allows) on: a spawn that carries `model`; subagent_type "fork" (the tool ignores
# `model` for it); a spawn made inside a subagent (agent_id in the payload: transcript_path is
# the parent's); a session that never entered goalspec; GOAL_SUBAGENT_MODEL_CHECK=0.
# Threat model: catches a FORGOTTEN model on a spawn. It does not catch a deliberate evasion, a
# wrong tier chosen on purpose, or an agent type whose definition pins its own model (it cannot
# see agent frontmatter, so its reason says "unless its agent type pins one").
#
# Fail-open, like every hook here: an unreadable payload, a missing module or transcript allows.
# Registered by hooks/hooks.json.

INPUT=$(cat)

[ "${GOAL_SUBAGENT_MODEL_CHECK:-}" = "0" ] && exit 0

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

if data.get("hook_event_name") != "PreToolUse" or data.get("tool_name") not in ("Task", "Agent"):
    sys.exit(0)
if data.get("agent_id"):
    sys.exit(0)

def has_model(inp):
    v = inp.get("model")
    return isinstance(v, str) and v.strip() != ""

def kind_of(inp):
    st = inp.get("subagent_type")
    st = st.strip() if isinstance(st, str) else ""
    if st == "fork":
        return None
    return "adversary" if ta.is_adversary_type(st) else "worker"

inp = data.get("tool_input") or {}
if not isinstance(inp, dict) or has_model(inp):
    sys.exit(0)
kind = kind_of(inp)
if kind is None:
    sys.exit(0)

# One pass over the transcript: was goalspec entered, and after that entry, is a model-less spawn
# of the same kind already on record? (_collect_event is the parser every other hook here uses.)
entered = False
bounced = False
items, state = [], None
try:
    with open(data.get("transcript_path") or "", "r", encoding="utf-8") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if not isinstance(ev, dict):
                continue
            before = len(items)
            if state is None:
                state = {"adversary_spawns": set(), "adversary_agents": set(), "background_spawns": set()}
            try:
                ta._collect_event(ev, items, state)
            except Exception:
                pass
            if any(it.get("kind") == "goalspec_entry" for it in items[before:]):
                entered = True
            if not entered or ev.get("type") != "assistant":
                continue
            content = (ev.get("message") or {}).get("content")
            for blk in content if isinstance(content, list) else []:
                if (isinstance(blk, dict) and blk.get("type") == "tool_use"
                        and blk.get("name") in ("Task", "Agent")):
                    bi = blk.get("input") or {}
                    if isinstance(bi, dict) and not has_model(bi) and kind_of(bi) == kind:
                        bounced = True
except Exception:
    sys.exit(0)

if not entered or bounced:
    sys.exit(0)

if kind == "adversary":
    reason = ("goalspec: this goal-adversary spawn carries no `model`, so unless its agent type pins "
              "one it runs on YOUR model, and the verification loses its model-independence lever "
              "(SKILL.md step 6, \"Different model on every run\"). Relaunch it with a `model` "
              "override on a different tier: above Sonnet-class -> model: sonnet; Sonnet-class or "
              "below -> model: opus. Then check its [ADVERSARY-MODEL: ...] self-report, not the "
              "parameter. This is denied once per session; a second model-less adversary spawn passes "
              "(then close with model=same).")
else:
    reason = ("goalspec: this subagent spawn carries no `model`, so unless its agent type pins one it "
              "runs on your own model, whatever its task. Choose the tier by the task (SKILL.md, "
              "\"Subagent model by task\") and relaunch, the same prompt, with `model` and `effort`: "
              "locate / enumerate / read and summarize / extract -> model: haiku, effort: medium; "
              "judgment (classify a finding, weigh evidence, review code, draft a section) -> "
              "model: sonnet, effort: high; your own tier only for work a cheaper tier would get "
              "wrong in a way your re-derivation would not catch, and then pass it explicitly and say "
              "why in one line. This skill authorizes setting `effort`. Relaunch every spawn this "
              "denied, not only the first. Denied once per session: the next model-less spawn passes.")

print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "deny",
                                         "permissionDecisionReason": reason}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

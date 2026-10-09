#!/usr/bin/env bash
# precheck-inline-grounding.sh — PreToolUse hook (matcher: Bash|Read|Grep|Glob|WebFetch|WebSearch),
# new in 0.52.0.
#
# Why: SKILL.md's grounding step sizes the acquisition (targeted -> inline; broad -> delegate a
# bounded exploration to a subagent on a cheap tier), and nothing measured the size. Measured over
# the 217 local claude-vzert transcripts on disk on 2026-10-09 (older ones age out), sessions that
# reached a `## Goal-spec`, from the goalspec entry to that spec: 4 of 12 /goalspec:interview
# sessions and 2 of 67 loop sessions spawned any grounding subagent; 3 and 13 made 20+ inline
# reading calls with none (the three interviews made 27-33: memory sweeps, old session logs, VPS
# checks) on the executor's tier. None of the 12 grounding spawns across all 88 goalspec sessions
# carried `model`.
#
# What it does: in a session that entered goalspec (the loop or the interview) and has no
# `## Goal-spec` with a body yet, once GOAL_GROUNDING_INLINE_MAX (default 15) inline reading calls
# (Bash, Read, Grep, Glob, WebFetch, WebSearch) are on record after the entry with no subagent
# spawned after it, the next one is denied ONCE (a message's parallel reads are all denied together:
# a message reaches the transcript only after its tool calls run, so each call sees the same count), with a reason that asks for the rest of the
# exploration to go to a subagent (goalspec:explorer, haiku, or another type with model + effort
# from SKILL.md's "Subagent model by task"). The deny is recorded as a tool_result carrying
# GROUNDING_MARK; once one is on record the hook is silent for the rest of the session, so it
# never traps the agent. A call this or another hook denied does not count as a read.
#
# Silent (allows) on: a spec with a body in visible text or this session's checkpoint; any
# non-adversary Task/Agent spawn after the entry that a hook did not deny; a call made inside a subagent (agent_id); a
# session that never entered goalspec; GOAL_GROUNDING_CHECK=0.
# Threat model: catches a broad exploration FORGOTTEN in the executor's own context. It does not
# catch a deliberate evasion, a broad exploration that fits under the threshold, or tell a read
# from any other Bash command (it counts every Bash call; that is the proxy).
#
# Fail-open, like every hook here: an unreadable payload, a missing module or transcript allows.
# Registered by hooks/hooks.json.

INPUT=$(cat)

[ "${GOAL_GROUNDING_CHECK:-}" = "0" ] && exit 0

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | LIBDIR="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib" \
    MAXR="${GOAL_GROUNDING_INLINE_MAX:-15}" "$PY" -c '
import json, os, sys

libdir = os.environ.get("LIBDIR", "")
if libdir and libdir not in sys.path:
    sys.path.insert(0, libdir)
try:
    import terminal_actions as ta
except Exception:
    sys.exit(0)

READS = ("Bash", "Read", "Grep", "Glob", "WebFetch", "WebSearch")
MARK = "goalspec: broad grounding"
try:
    limit = max(1, int(os.environ.get("MAXR") or "15"))
except Exception:
    limit = 15

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if data.get("hook_event_name") != "PreToolUse" or data.get("tool_name") not in READS:
    sys.exit(0)
if data.get("agent_id"):
    sys.exit(0)

def result_text(c):
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text") for b in c if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""

entered = False
reads = {}      # tool_use id -> True, inline reads after the entry
denied = set()  # tool_use ids whose result is a hook denial
spawns = set()  # tool_use ids of non-adversary spawns after the entry
bounced = False
spec = False
sid = str(data.get("session_id") or "").strip()
own = ta.own_checkpoint_re(sid)
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
            for it in items[before:]:
                if it.get("kind") == "goalspec_entry":
                    entered = True
                elif entered and it.get("kind") == "text" and ta.spec_has_body(it.get("text") or ""):
                    spec = True
                elif entered and it.get("kind") == "goal_spec_file" and own.search(it.get("path") or "") \
                        and ta.spec_has_body(it.get("text") or ""):
                    spec = True
            content = (ev.get("message") or {}).get("content")
            for blk in content if isinstance(content, list) else []:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "tool_result":
                    txt = result_text(blk.get("content"))
                    if MARK in txt:
                        bounced = True
                    if txt.lstrip().startswith("PreToolUse:") or blk.get("is_error") and "hook" in txt[:80].lower():
                        denied.add(blk.get("tool_use_id"))
                if not entered or ev.get("type") != "assistant" or blk.get("type") != "tool_use":
                    continue
                if blk.get("name") in READS:
                    reads[blk.get("id")] = True
                elif blk.get("name") in ("Task", "Agent"):
                    st = (blk.get("input") or {}).get("subagent_type")
                    if not ta.is_adversary_type(st if isinstance(st, str) else ""):
                        spawns.add(blk.get("id"))
except Exception:
    sys.exit(0)

count = sum(1 for k in reads if k not in denied)
spawned = any(k not in denied for k in spawns)  # a spawn a hook denied never ran
if not entered or spec or spawned or bounced or count < limit:
    sys.exit(0)

reason = ("goalspec: broad grounding in your own context -- %d inline reading calls since goalspec "
          "started and no subagent yet, with no ## Goal-spec written. SKILL.md step 3 sizes this: "
          "targeted -> inline, broad -> delegate a BOUNDED exploration and keep only its synthesis. "
          "Hand the rest to a subagent now, asking for a synthesis with citations, not file dumps: "
          "subagent_type goalspec:explorer (read-only by instruction, haiku pinned) for locate / enumerate / read "
          "and summarize; or a type with model: sonnet, effort: high for judgment-heavy work "
          "(SKILL.md, \"Subagent model by task\"). Several independent questions -> several "
          "explorers in one message. If what is left is genuinely a couple of targeted reads, retry "
          "this call: this is denied once per session (every parallel read in this one message is "
          "denied together).") % count
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                         "permissionDecision": "deny",
                                         "permissionDecisionReason": reason}}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

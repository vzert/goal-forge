#!/usr/bin/env bash
# gate-goal-close.sh — Stop hook. Fail-open, transcript-anchored completion-review gate.
#
# Portable port of the validated fleet gate (gate-audit-close.sh), stripped of any control-plane
# coupling. The original anchored to a "PATCH status:done" API call and read the issue thread over
# a REST API. There is no control plane here, so the anchor is the TURN END (the Stop hook) and the
# source of truth is the SESSION TRANSCRIPT — evasion-resistant in the same spirit: it reads the
# assistant's actual emitted text, not a command string the agent could route around.
#
# Behavior:
#   * Only enforces when this session produced a `## Goal-spec` (the gate is not universal).
#   * If a goal-spec exists but no valid [COMPLETION-REVIEW: ...] was declared -> ADVISORY reminder,
#     the stop is allowed (fail-open). This is deliberate: you cannot gate your way out of
#     specification gaming; a fail-closed marker just relocates the gaming. See
#     references/outcome-loop-beats-gates.md.
#   * Opt-in teeth: GOAL_GATE_ENFORCE=1 turns the advisory into a block (agent must complete the
#     declaration before stopping).
#   * Operator escape: [GOAL-CLOSE-WAIVED reason=<>=20 chars>] anywhere in the turn.
#   * Any parse error / missing input -> exit 0 (fail-open).
#
# Registered as a Stop hook by hooks/hooks.json.

INPUT=$(cat)

# Everything lives in python3 (present on macOS/Linux). Fail-open on any exception.
RESULT=$(ENFORCE="${GOAL_GATE_ENFORCE:-}" printf '%s' "$INPUT" | python3 -c '
import json, sys, os, re

def fail_open():
    print("OK"); sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    fail_open()

# 1. Gather the assistant text for this turn.
#    Prefer last_assistant_message (current turn, never lags). Best-effort append the transcript.
parts = []
lam = data.get("last_assistant_message")
if isinstance(lam, str) and lam:
    parts.append(lam)

tpath = data.get("transcript_path")
if isinstance(tpath, str) and tpath and os.path.isfile(tpath):
    try:
        with open(tpath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("type") != "assistant":
                    continue
                msg = ev.get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for blk in content:
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            parts.append(blk.get("text") or "")
    except Exception:
        pass

text = "\n".join(parts)
if not text.strip():
    fail_open()

# 2. Nothing to enforce unless this session produced a goal-spec.
if not re.search(r"(^|\n)#{1,6}\s*Goal-spec\b", text, re.I):
    fail_open()

# 3. Operator waiver.
if re.search(r"\[GOAL-CLOSE-WAIVED\s+reason=[^\]]{20,}\]", text, re.I):
    fail_open()

# 4. Validate the completion-review declaration.
cr = re.search(r"\[COMPLETION-REVIEW:\s*(adversary|none)\b([^\]]*)\]", text, re.I)
if not cr:
    print("REMIND|completion-review:absent"); sys.exit(0)
mode = cr.group(1).lower()
body = cr.group(2)
if mode == "adversary":
    if not re.search(r"\[ADVERSARY-VERDICT:", text, re.I):
        print("REMIND|completion-review:adversary-claimed-but-no-verdict"); sys.exit(0)
else:  # none
    if not re.search(r"reason=.{20,}", body):
        print("REMIND|completion-review:none-needs-reason>=20"); sys.exit(0)

print("OK")
' 2>/dev/null)

# Fail-open on empty / OK.
[ -z "$RESULT" ] && exit 0
case "$RESULT" in
  OK) exit 0 ;;
  REMIND*) : ;;
  *) exit 0 ;;
esac

DETAIL="${RESULT#REMIND|}"
MSG="Goal-spec present but no valid [COMPLETION-REVIEW] declared (${DETAIL}). Run the inherited-decision sweep + red-team, then declare \`[COMPLETION-REVIEW: none reason=…]\` (≥20 chars) or route to the adversary and declare \`[COMPLETION-REVIEW: adversary …]\` with an [ADVERSARY-VERDICT: …] present. Operator escape: [GOAL-CLOSE-WAIVED reason=…]."

if [ "${GOAL_GATE_ENFORCE:-}" = "1" ]; then
  # Opt-in teeth: block the stop and force completion.
  MSG="$MSG" python3 -c 'import json,os; print(json.dumps({"decision":"block","reason":os.environ["MSG"]}))'
  exit 0
fi

# Default: fail-open advisory. Surface the reminder without blocking the stop.
MSG="$MSG" python3 -c 'import json,os; m=os.environ["MSG"]; print(json.dumps({"systemMessage":m,"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":m}}))'
exit 0

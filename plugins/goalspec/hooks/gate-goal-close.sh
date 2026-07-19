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

# Portable interpreter: python3 on macOS/Linux, python on Windows (Git Bash + python.org). python3 is
# resolved first, so Mac/Linux never fall back to a possible python2; if neither exists the invocation
# just fails and the hook degrades fail-open (empty RESULT -> exit 0).
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

# Everything lives in python. Fail-open on any exception.
RESULT=$(ENFORCE="${GOAL_GATE_ENFORCE:-}" printf '%s' "$INPUT" | "$PY" -c '
import json, sys, os, re

def fail_open():
    print("OK"); sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    fail_open()

# 1. Gather the assistant text for this turn.
#    Prefer last_assistant_message (current turn, never lags). Best-effort append the transcript.
lam = data.get("last_assistant_message")
lam_text = lam if isinstance(lam, str) else ""

tx_parts = []
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
                    tx_parts.append(content)
                elif isinstance(content, list):
                    for blk in content:
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            tx_parts.append(blk.get("text") or "")
    except Exception:
        pass

tx_text = "\n".join(tx_parts)
# Full text for order-independent checks (goal-spec presence, waiver, ADVERSARY-MODEL reports).
text = lam_text + "\n" + tx_text
if not text.strip():
    fail_open()

# 2. Nothing to enforce unless this session produced a goal-spec.
if not re.search(r"(^|\n)#{1,6}\s*Goal-spec\b", text, re.I):
    fail_open()

# 3. Operator waiver.
if re.search(r"\[GOAL-CLOSE-WAIVED\s+reason=[^\]]{20,}\]", text, re.I):
    fail_open()

# 4. Validate the completion-review declaration.
# Operative completion-review = the current-turn declaration if present (last_assistant_message is
# the reliable current-turn source), else the MOST RECENT one in the transcript. Anchoring on the
# *last* declaration — never the first re.search match — is what prevents an earlier exploratory or
# malformed [COMPLETION-REVIEW] from permanently poisoning the check after a correct one is emitted.
cr_pat = r"\[COMPLETION-REVIEW:\s*(adversary|none)\b([^\]]*)\]"
crs = re.findall(cr_pat, lam_text, re.I) or re.findall(cr_pat, tx_text, re.I)
if not crs:
    print("REMIND|completion-review:absent"); sys.exit(0)
mode, body = crs[-1]
mode = mode.lower()
if mode == "adversary":
    if not re.search(r"\[ADVERSARY-VERDICT:", text, re.I):
        print("REMIND|completion-review:adversary-claimed-but-no-verdict"); sys.exit(0)
    # model=different asserts the adversary verified you on a DIFFERENT model; its only ground-truth is
    # the adversary own [ADVERSARY-MODEL:] self-report. We deliberately DO NOT parse the claimed id and
    # re-match it against the self-report: five adversarial rounds (a fresh-context subagent + an external
    # codex on a different vendor) proved that free-text id-matching from an agent-authored transcript is
    # a bottomless proxy — substring collisions ("o3" in "gpt-4o-3-turbo-preview"), sentinel leaks, prose
    # harvesting ("UNKNOWN / requested gpt-5 unavailable"), version dots, and stale cross-run reports each
    # defeated a successively cleverer matcher. You cannot gate your way out of specification gaming
    # (references/outcome-loop-beats-gates.md), so the check is reduced to the one assertion it can make
    # honestly: a model=different claim requires at least one self-report naming a REAL, non-UNKNOWN model
    # id. The canonical id is taken POSITIONALLY — the single token after the last "/" (grammar is
    # "<name> / <exact id, or UNKNOWN>"), well-formed = one whitespace-free token carrying a letter, not
    # the "unknown" sentinel — so a fallback field ("UNKNOWN", "UNKNOWN / requested gpt-5 unavailable")
    # yields no id. If EVERY [ADVERSARY-MODEL:] is UNKNOWN/absent (the harness silently fell back to
    # same-model — the exact honest mistake this guards), model=different is unsupported and must degrade
    # to model=same. Id-precision and cross-run provenance are NOT gated: that is the outcome loop job.
    if re.search(r"model=different\b", body, re.I):
        def has_real_id(field):
            cid = field.rsplit("/", 1)[-1].strip().lower()
            # A real model id: one whitespace-free token, not the "unknown" sentinel, carrying a letter
            # AND a digit/hyphen/dot (a version marker). That last clause keeps every real id
            # (claude-sonnet-5, o3, gpt-4o, gpt-5.1) while rejecting a bare word ("apology", "different")
            # an executor could type to fake a self-report — without re-entering the id-*matching* proxy.
            return (len(cid) >= 2 and not re.search(r"\s", cid) and cid != "unknown"
                    and bool(re.search(r"[a-z]", cid)) and bool(re.search(r"[0-9.-]", cid)))
        reports = re.findall(r"\[ADVERSARY-MODEL:\s*([^\]]*)\]", text, re.I)
        if not any(has_real_id(r) for r in reports):
            print("REMIND|completion-review:model-different-needs-nonunknown-self-report"); sys.exit(0)
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
MSG="Goal-spec present but no valid [COMPLETION-REVIEW] declared (${DETAIL}). Run the inherited-decision sweep + red-team, then declare \`[COMPLETION-REVIEW: none reason=…]\` (≥20 chars) or route to the adversary and declare \`[COMPLETION-REVIEW: adversary …]\` with an [ADVERSARY-VERDICT: …] present. Both marker lines must be in YOUR turn's text, not only in the subagent's output. A model=different close needs the adversary's own [ADVERSARY-MODEL: …] line naming a real, non-UNKNOWN id in your turn; if it self-reported UNKNOWN or same, say model=same. Operator escape: [GOAL-CLOSE-WAIVED reason=…]."

if [ "${GOAL_GATE_ENFORCE:-}" = "1" ]; then
  # Opt-in teeth: block the stop and force completion.
  MSG="$MSG" "$PY" -c 'import json,os; print(json.dumps({"decision":"block","reason":os.environ["MSG"]}))'
  exit 0
fi

# Default: fail-open advisory. Surface the reminder without blocking the stop.
MSG="$MSG" "$PY" -c 'import json,os; m=os.environ["MSG"]; print(json.dumps({"systemMessage":m,"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":m}}))'
exit 0

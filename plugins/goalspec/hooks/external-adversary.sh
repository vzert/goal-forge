#!/usr/bin/env bash
# external-adversary.sh — optional independence backend for the goal-adversary.
#
# Implements the community "partner reviews, never the host" pattern: instead of a same-model
# subagent (structured self-critique with correlated bias), route the adversarial verification to a
# DIFFERENT model/CLI for true independence. Reads the goal-spec + outcome on stdin, pipes them with
# the adversary prompt to the configured external command, and prints the same
# [ADVERSARY-VERDICT: ...] block the subagent backend produces.
#
# Config (.claude/goal.config.json -> adversary.external_cmd), e.g.:
#   "codex exec"      (OpenAI Codex CLI)
#   "gemini -p"       (Google Gemini CLI)
#   "claude -p --model claude-sonnet-5"   (a different Claude model as the partner)
#
# Usage:  printf '%s' "$SPEC_AND_OUTCOME" | external-adversary.sh
# The external command is passed the full prompt on stdin.
#
# Anti-recursion: if this backend routes to another Claude that itself has goalspec
# installed, GOAL_ADVERSARY_ACTIVE=1 is exported so its Stop gate / any nested /goalspec can detect
# the loop and no-op. A nested invocation (already inside an external adversary) exits immediately.

set -euo pipefail

if [ "${GOAL_ADVERSARY_ACTIVE:-}" = "1" ]; then
  echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]" >&2
  echo "external-adversary: recursion guard tripped (GOAL_ADVERSARY_ACTIVE=1) — refusing to re-enter." >&2
  exit 0
fi
export GOAL_ADVERSARY_ACTIVE=1

# Resolve the external command from config, arg, or env. Default: codex exec.
CONFIG="${GOAL_CONFIG_PATH:-.claude/goal.config.json}"
EXT_CMD="${GOAL_ADVERSARY_CMD:-}"
if [ -z "$EXT_CMD" ] && [ -n "${1:-}" ]; then EXT_CMD="$1"; fi
if [ -z "$EXT_CMD" ] && [ -f "$CONFIG" ]; then
  EXT_CMD=$(python3 -c "import json,sys; print((json.load(open('$CONFIG')).get('adversary',{}) or {}).get('external_cmd','') or '')" 2>/dev/null || true)
fi
[ -z "$EXT_CMD" ] && EXT_CMD="codex exec"

# Verify the external binary exists — else fail-open with a hold + a note (never block the host).
BIN=$(printf '%s' "$EXT_CMD" | awk '{print $1}')
if ! command -v "$BIN" >/dev/null 2>&1; then
  echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
  echo "external-adversary: '$BIN' not found on PATH — no independent check ran; treat 'hold' as UNVERIFIED." >&2
  exit 0
fi

PAYLOAD=$(cat)

PROMPT=$(cat <<EOF
You are an INDEPENDENT adversarial verifier. You did not do the work. Your job is to try to BREAK
the claimed outcome against this 5-principle constitution — not to approve it:
  1. Grounding — every load-bearing claim must cite verifiable ground-truth; a proxy is not the thing;
     a broken instrument (empty tracking, bad scope, failing harness) invalidates its evidence.
  2. Falsification — inherited claims must be re-derived, not trusted; numbers that don't reconcile = bad input.
  3. Completeness — done = achieved AND verified, not diagnosed; every surfaced factor needs an owner.
  4. Autonomy — nothing an agent could execute should be handed to a human.
  5. No-harm — don't remove/pause/scale something that works without a validated, reversible replacement.

Attack every load-bearing figure. Default to skeptical: if you cannot verify a claim, count it as a
violation, not a pass. Then output EXACTLY ONE line, and nothing after it:

[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]

Use 'break' if any confirmed count is >=1, else 'hold'. Above that line, list each confirmed
violation with the ground-truth that proves it.

=== GOAL-SPEC + OUTCOME UNDER REVIEW ===
$PAYLOAD
EOF
)

# Pipe the prompt to the external CLI on stdin. Most CLIs (codex exec, gemini -p, claude -p) accept
# a prompt on stdin; if yours needs it as an arg, wrap this in a small adapter.
printf '%s' "$PROMPT" | $EXT_CMD

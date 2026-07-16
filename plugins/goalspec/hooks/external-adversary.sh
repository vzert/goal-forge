#!/usr/bin/env bash
# external-adversary.sh — optional independence backend for the goal-adversary.
#
# Implements the community "partner reviews, never the host" pattern: instead of a same-model
# subagent (structured self-critique with correlated bias), route the adversarial verification to a
# DIFFERENT model/CLI for true independence. Reads the goal-spec + outcome + ask record on stdin,
# pipes them with the adversary prompt to the configured external command, and prints the same
# [ADVERSARY-VERDICT: ...] block the subagent backend produces.
#
# The dead-handoff check (principle 4) needs the session log. Whether this partner can reach it is a
# property of the CLI, NOT of "being external": a file-capable partner on the same host (e.g.
# "claude -p --model ...", or codex/gemini with fs access) can read it and must; one without file
# access reports UNVERIFIABLE-BY-THIS-BACKEND. The prompt tells it to CHECK rather than assume.
# (0.4.0 drafted the assumption "external cannot read the log" as fact; a Sonnet partner falsified it
# by reading the log, before release. Do not re-introduce it.) See references/external-adversary-setup.md.
#
# Config (.claude/goal.config.json -> adversary.external_cmd), e.g.:
#   "codex exec"      (OpenAI Codex CLI)
#   "gemini -p"       (Google Gemini CLI)
#   "claude -p --model claude-sonnet-5"   (a different Claude model as the partner)
#
# Usage:  printf '%s' "$SPEC_OUTCOME_AND_ASK_RECORD" | external-adversary.sh
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
  4. Autonomy — two opposite failures, both count: nothing an agent could execute should be handed to
     a human; AND no decision assigned to the human may go unasked. A decision narrated in prose ("two
     decisions are yours", in any language) with no question ever raised is a DEAD HANDOFF — the human
     cannot answer a paragraph. Judge the act, not a phrase list. The ASK RECORD in the payload is a
     claim the executor authored — a POINTER, never evidence. TEST YOUR REACH FIRST: if you can read
     files on this host, go verify the ask yourself in the session log (Claude Code: the top-level
     <session-id>.jsonl under ~/.claude/projects/<cwd, every non-alphanumeric mapped to a dash>; read
     the parent file, never a subagents/ child, never newest-mtime; match the AskUserQuestion
     tool_use + its user tool_result by STRUCTURE, not by text-grep; confirm it is this run and this
     decision). A claimed ask you can reach and cannot find is a confirmed DEAD HANDOFF. Only if you
     genuinely have no file access, report UNVERIFIABLE-BY-THIS-BACKEND and do NOT count it — do not
     manufacture a violation with an instrument that cannot see; that is principle 1 turned on you.
     Do not assume you cannot reach it: check.
  5. No-harm — don't remove/pause/scale something that works without a validated, reversible replacement.

Attack every load-bearing figure. Default to skeptical: if you cannot verify a claim, count it as a
violation, not a pass — the one exception is the dead-handoff check in principle 4, and ONLY if you
truly cannot reach the session log (an unreachable instrument is not a finding; an unchecked one is
just laziness). Then output EXACTLY ONE line, and nothing after it:

[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]

Use 'break' if any confirmed count is >=1, else 'hold'. Above that line, list each confirmed
violation with the ground-truth that proves it.

=== GOAL-SPEC + OUTCOME + ASK RECORD UNDER REVIEW ===
$PAYLOAD
EOF
)

# Pipe the prompt to the external CLI on stdin. Some CLIs accept a prompt on stdin (codex exec,
# claude -p); others want it as an argument (gemini -p) — wrap those in a small adapter.
#
# Instrument-validity rail: `command -v` only proves a WRAPPER is on PATH, not that the CLI runs. A
# broken install (e.g. codex whose vendored binary is missing) exits non-zero with a stack trace and
# NO verdict — which would hand the caller silence and let it read as "no objection". So capture the
# run and require a FILLED verdict; anything else degrades to an explicit UNVERIFIED hold.
#
# The pattern demands literal counts, NOT the grammar template. This matters: the prompt above contains
# the template `[ADVERSARY-VERDICT: break|hold ungrounded=<n> ...]`, so any CLI that echoes its stdin
# (a debug/verbose wrapper, or a plain `cat`) and exits 0 would satisfy a naive
# `grep '\[ADVERSARY-VERDICT:'` and get its echoed PLACEHOLDER printed back as a real verdict. Requiring
# `(break|hold)` followed by numeric counts rejects both `break|hold` and `<n>`. Take the LAST match, so
# a partner that quotes the template before answering still resolves to its real verdict.
VERDICT_RE='\[ADVERSARY-VERDICT:[[:space:]]*(break|hold)[[:space:]]+ungrounded=[0-9]+[[:space:]]+unfalsified=[0-9]+[[:space:]]+incomplete=[0-9]+[[:space:]]+autonomy-violations=[0-9]+[[:space:]]+unsafe=[0-9]+[[:space:]]*\]'

# NB: `set -euo pipefail` is active. A no-match `grep` exits 1, which under pipefail would kill this
# script on exactly the path that exists to handle a bad partner — so both the run and the match stay
# inside `set +e` and the match is guarded with `|| true`.
set +e
OUT=$(printf '%s' "$PROMPT" | $EXT_CMD 2>&1)
RC=$?
VERDICT=$(printf '%s' "$OUT" | grep -Eo "$VERDICT_RE" | tail -1 || true)
set -e

if [ $RC -ne 0 ] || [ -z "$VERDICT" ]; then
  echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
  {
    echo "external-adversary: '$EXT_CMD' exited $RC without a filled [ADVERSARY-VERDICT:] line —"
    echo "no independent check ran. Treat this 'hold' as UNVERIFIED, not as a pass. Partner output:"
    printf '%s\n' "$OUT" | head -20
  } >&2
  exit 0
fi

printf '%s\n' "$OUT"

#!/usr/bin/env bash
# remind-quote-verdict.sh — PostToolUse hook. Purely additive; does NOT touch gate-goal-close.sh's
# parsing logic in any way.
#
# The problem it fixes: gate-goal-close.sh (by design) only scans ASSISTANT-AUTHORED text for
# [ADVERSARY-MODEL: ...] / [ADVERSARY-VERDICT: ...] — never tool_result content. The verdict from
# the goal-adversary subagent arrives as a tool_result, so it is invisible to the gate until the
# executor personally re-types it into their own turn. Across a long session that is easy to forget
# by the time of actual close, costing a Stop-hook round-trip every time — a recurring,
# previously-unresolved friction observed across most goalspec sessions.
#
# Why THIS fix and not a smarter gate: correlating tool_use/tool_result pairs inside
# gate-goal-close.sh (matching by id, filtering subagent_type, handling precedence) is real parser
# complexity added to a fail-open script with a documented history of silent breakage (the
# model-id matcher broke 5 consecutive adversarial rounds before the project's own ruling was
# "simplify, don't out-clever it" — see memory/learnings). This hook instead nudges at the moment
# the verdict is produced — the cheapest, lowest-risk lever — and changes nothing about how the
# gate itself reads the transcript.
#
# Scope, deliberately narrowed to ONE structurally robust signal: fires after a Task/Agent tool call
# whose subagent_type is (optionally namespace-prefixed) exactly "goal-adversary" — a harness-
# provided field the executor cannot spoof by merely typing text, unlike a freeform Bash command
# string. This hook does NOT also try to detect an external-adversary.sh Bash invocation from its
# command string: that was attempted and reviewed by an external adversary, which broke it twice —
# a fabricated subagent_type substring slipped through once; then, after tightening, real invocation
# forms (a bare `./external-adversary.sh`, `sh -c "..."`) were missed while a plain `cat`/`grep` of
# THAT SOURCE FILE (which itself contains literal fallback verdict text) still risked inducing the
# executor to quote non-evidence into the transcript the Stop gate reads — turning a false-positive
# nudge into manufactured fake evidence. Removed rather than patched a third time (the same
# "simplify, don't out-clever" lesson, applied to this hook's own design). The external-adversary
# case is instead covered at its actual source of truth: hooks/external-adversary.sh itself emits
# the identical reminder, to stderr, from the one code path that only runs after it has already
# validated a real well-formed verdict came back — no guessing from outside required.
#
# What it does: only acts when BOTH are true: (a) tool_name is Task or Agent with subagent_type
# ending in "goal-adversary", AND (b) tool_response actually contains a well-formed
# [ADVERSARY-VERDICT: ...] block (the SAME structured grammar gate-goal-close.sh itself requires —
# no looser, no stricter). If both hold, injects a non-blocking reminder to quote the
# ADVERSARY-MODEL/ADVERSARY-VERDICT lines VERBATIM in the very next assistant message. If a
# [ADVERSARY-MODEL:] line is present but no well-formed verdict is (a malformed or missing verdict),
# it says so instead — useful signal either way, still non-blocking.
#
# Fail-open: any parse error, missing field, or non-matching tool -> exit 0, silent. Never blocks
# (PostToolUse cannot block a completed tool call anyway).
#
# Registered as a PostToolUse hook (matcher "Task|Agent") by hooks/hooks.json.

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | "$PY" -c '
import json, sys, re

def silent():
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    silent()

tool_name = data.get("tool_name") or ""
tool_input = data.get("tool_input") or {}
tool_response = data.get("tool_response")

# 1. Only a plausible goal-adversary spawn. Anchored to the END of the (optionally namespaced) type
#    string -- "goal-adversary" or "goalspec:goal-adversary" match; "not-goal-adversary-example"
#    does not. A bare substring check matched that fabricated example once -- caught by adversary
#    review before this shipped.
if tool_name not in ("Task", "Agent"):
    silent()

is_adversary_spawn = False
for k in ("subagent_type", "subagentType", "agent_type", "agentType"):
    v = tool_input.get(k)
    if isinstance(v, str) and re.search(r"(^|:)goal-adversary$", v.strip().lower()):
        is_adversary_spawn = True
        break

if not is_adversary_spawn:
    silent()

# 2. Flatten tool_response to text regardless of shape (string, or structured object/list).
def flatten(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return " ".join(flatten(x) for x in v.values())
    if isinstance(v, list):
        return " ".join(flatten(x) for x in v)
    return ""

text = flatten(tool_response)
if not text.strip():
    silent()

# 3. Same structured grammar gate-goal-close.sh itself requires -- no looser, no stricter.
verdict_re = (r"\[ADVERSARY-VERDICT:\s*(break|hold)\s+ungrounded=\d+\s+unfalsified=\d+\s+"
              r"incomplete=\d+\s+autonomy-violations=\d+\s+unsafe=\d+\s*\]")
model_re = r"\[ADVERSARY-MODEL:\s*[^\]]*\]"

verdicts = re.findall(verdict_re, text, re.I)
models = re.findall(model_re, text, re.I)

if not verdicts and not models:
    silent()  # this spawn did not return recognizable adversary output

if verdicts:
    # Deliberately does NOT assert this verdict is authentic/genuine adversarial work -- a
    # structured subagent_type only authenticates that a goal-adversary WAS spawned, never that its
    # conclusion is real rather than copied/lazy text. That authenticity question is unsolvable from
    # outside the reasoning the subagent itself did, and this plugin already documents that limitation
    # everywhere else (self-report, not a lie detector; a bare verdict with no evidence is
    # UNVERIFIED, not a pass). Asserting "real" here would overclaim a certainty this hook cannot
    # have, and could make a copied/fake verdict MORE likely to get trusted and quoted forward --
    # caught by adversary review. This message only flags that a verdict-SHAPED block exists and is
    # about to become invisible; it explicitly leaves the "is it genuine" judgment to the executor,
    # who already carries that responsibility for every self-report in this method.
    msg = (
        "A verdict-shaped [ADVERSARY-VERDICT: ...] block just came back in this tool result -- "
        "whether it reflects genuine adversarial work is still yours to judge (a bare verdict with "
        "no evidence above it is UNVERIFIED, not a pass; treat it the same way regardless of this "
        "nudge). If you judge it genuine, quote the [ADVERSARY-MODEL: ...] and "
        "[ADVERSARY-VERDICT: ...] lines VERBATIM in your very next assistant message (not a "
        "paraphrase). The Stop gate cannot see this tool result directly -- it only reads your own "
        "assistant-authored text, this run and all prior turns -- so it stays invisible until you "
        "do this, and it is far easier to forget once you move on to other work."
    )
else:
    msg = (
        "This adversary call returned an [ADVERSARY-MODEL: ...] line but no well-formed "
        "[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> "
        "autonomy-violations=<n> unsafe=<n>] block -- the run may have failed, been truncated, or "
        "returned a bare/malformed verdict. Do not treat this as a pass; re-run it or route to the "
        "other backend before declaring completion-review over it."
    )

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg},
}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

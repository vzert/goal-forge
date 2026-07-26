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
# What it does: acts on the ONE structural fact it can trust — tool_name is Task/Agent and
# subagent_type ends in "goal-adversary" — and then says whatever the response shape supports:
#   * a well-formed [ADVERSARY-VERDICT: ...] came back (the SAME structured grammar
#     gate-goal-close.sh requires, no looser, no stricter) -> quote MODEL+VERDICT verbatim, now;
#   * an [ADVERSARY-MODEL:] line but no well-formed verdict -> malformed/truncated, not a pass;
#   * no adversary output at all in the result -> the spawn was LAUNCHED and its output will arrive
#     later; the reminder still fires, because that is the case where forgetting is likeliest.
#
# 0.18.0 fixed two ways this was dead or wrong in the default spawn path:
#   (1) IT NEVER SAW THE VERDICT. Since Claude Code v2.1.198 subagents run in the background by
#       default, so the tool result is a HANDLE, not the agent's output: `{"isAsync": true, "status":
#       "async_launched", "agentId": ..., "outputFile": ..., "resolvedModel": ..., "prompt": ...}`
#       — no `content` field at all. The old shape gate required verdict-shaped text in the response,
#       so the v0.14.0 feature could not fire on what it was built to catch.
#   (2) AND WHAT IT DID FIRE ON WAS THE EXECUTOR'S OWN TEXT. That handle echoes the spawn `prompt`,
#       which this method fills with prior verdicts — so flattening the whole response matches a
#       verdict the EXECUTOR wrote and announces it as one that "came back". Measured, not reasoned:
#       test/verdict-nudge-branches.py case 04 against the pre-edit copy takes the `verdict` branch.
#       So the old behavior was silent on a first round and actively misleading from the second on —
#       inducing the executor to quote its own prose forward as evidence, the same manufactured-
#       evidence failure that got the Bash-command detection removed from this hook once already.
#       Executor-authored echo fields are now excluded before matching.
#       EVIDENCE STATUS for both: the response SHAPE is observed in the transcript `toolUseResult` of
#       two real goal-adversary spawns (2026-07-25 21:00:40Z and 21:23:55Z) and the branch behavior is
#       measured synthetically against the real hook. UPDATED 0.19.1, and read the PROVENANCE before
#       leaning on it: a dump of a REAL PostToolUse payload showed `prompt` present in the hook's own
#       `tool_response`, in both the sync and the async shape -- so branch (2) does occur and the
#       ECHOED exclusion below is load-bearing rather than defensive. But that measurement was made
#       in an EARLIER session (2026-07-25, temporary sentinel wrapper over the cached hook, since
#       removed and verified restored), its raw dump lives OUTSIDE this repo, and the release that
#       wrote this line did NOT re-derive it -- both adversaries caught exactly that. So this is
#       observed-BY-REPORT, not reproducible from anything committed here; re-capture the payload if
#       you need it firsthand. The WIDER claim -- every field of the harness-synthesized
#       `tool_response` matching the transcript object one-for-one -- stays INFERRED, and nothing in
#       this hook depends on it.
#
# It stays a NUDGE, not a counter. A round counter anchored here would be evasion-shaped anyway:
# PreToolUse can fail an Nth *spawn* of goal-adversary, but nothing available can fail an Nth
# adversarial *round* (spawn `general-purpose` with adversary instructions and the anchor is gone) —
# the same arms race this file already lost twice. See the convergence floor in gate-goal-close.sh
# for where bounding actually lives.
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

# 2. Flatten tool_response to text regardless of shape (string, or structured object/list) — minus
#    the fields that merely echo the executor own spawn input. A backgrounded spawn returns a handle
#    carrying `prompt` (and `description`), and this method has the executor quote prior verdicts
#    INTO that payload, so including them would let the hook report the executor own text as output
#    that "came back". Same lesson as the removed Bash-command detection: a nudge that manufactures
#    evidence is worse than no nudge.
ECHOED = ("prompt", "description", "args", "arguments", "input", "tool_input")

def flatten(v):
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return " ".join(flatten(x) for k, x in v.items() if k.lower() not in ECHOED)
    if isinstance(v, list):
        return " ".join(flatten(x) for x in v)
    return ""

text = flatten(tool_response)

# 3. The verdict grammar is the same one gate-goal-close.sh itself requires -- no looser, no stricter.
verdict_re = (r"\[ADVERSARY-VERDICT:\s*(break|hold)\s+ungrounded=\d+\s+unfalsified=\d+\s+"
              r"incomplete=\d+\s+autonomy-violations=\d+\s+unsafe=\d+\s*\]")
# The model pattern is deliberately EXEMPT from the greedy-to-last-"]" fix 0.19.1 applied to
# gate-goal-close.sh, and the exemption is the point of saying so rather than leaving it silent.
# That fix exists so an id containing brackets (claude-opus-5[1m]) survives CAPTURE and reaches
# has_real_id. This pattern captures nothing: its only consumer is the truthiness of `models`
# below -- presence, for the "model line but no well-formed verdict" branch. A truncated match is
# still a match, so presence detection is unaffected by the truncation, and the narrower class
# keeps this from swallowing a whole line of prose after the marker.
model_re = r"\[ADVERSARY-MODEL:\s*[^\]]*\]"

verdicts = re.findall(verdict_re, text, re.I)
models = re.findall(model_re, text, re.I)

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
        "paraphrase) -- each on its OWN line, in plain text, nothing before it and nothing after "
        "the closing bracket on that same line: no bold or code-span wrapping, no trailing "
        "citation. The gate matches the marker only when its line ends at that bracket, so "
        "decorating it while quoting degrades a genuine model=different to model=same, silently. "
        "The Stop gate cannot see this tool result directly -- it only reads your own "
        "assistant-authored text, this run and all prior turns -- so it stays invisible until you "
        "do this, and it is far easier to forget once you move on to other work."
    )
elif models:
    msg = (
        "This adversary call returned an [ADVERSARY-MODEL: ...] line but no well-formed "
        "[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> "
        "autonomy-violations=<n> unsafe=<n>] block -- the run may have failed, been truncated, or "
        "returned a bare/malformed verdict. Do not treat this as a pass; re-run it or route to the "
        "other backend before declaring completion-review over it."
    )
else:
    # No adversary output in this result. The normal reason is that the spawn was BACKGROUNDED --
    # the result is a handle, the verdict arrives later -- which is precisely when the executor is
    # most likely to move on and never re-type it. Deliberately says nothing about what the verdict
    # will be, and nothing about round counts: this is a reminder about VISIBILITY, not a bound.
    msg = (
        "A goal-adversary spawn just returned no adversary output in its tool result -- normally "
        "because the subagent runs in the background, so this result is a handle and the verdict "
        "arrives later. Two things follow. (1) The Stop gate reads ONLY your own assistant-authored "
        "text, never a tool result: when the [ADVERSARY-MODEL: ...] and [ADVERSARY-VERDICT: ...] "
        "lines come back, quote them VERBATIM in your own next message, each alone on its own "
        "line and unformatted (no bold, no trailing text after the marker), or they do not exist "
        "as far as the gate is concerned. (2) Do not declare a completion-review over a verdict "
        "you have not actually read yet -- a spawn is not a verification."
    )

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg},
}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

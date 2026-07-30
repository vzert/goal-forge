#!/usr/bin/env bash
# nudge-decompose.sh — Stop hook. Advisory, non-blocking consumer for the decomposition/checkpoint
# signal SKILL.md's coverage-floor bullet describes but never mechanically checked (Fase 2 of
# memory/plans/plan-trigger-decomposicion.md; Fase 1, v0.27.0, fixed the trigger's own wording).
#
# What it does: if `.goalspec/checkpoint.md` exists in the cwd AND it carries a `## Coverage-floor
# table` heading whose markdown table has >= 2 data rows, AND the session transcript records ZERO
# entity-worker `Task`/`Agent` tool_use anywhere (the adversary's own step-6 spawn does not count —
# see step 3 below), print a non-blocking nudge asking whether that was intentional.
#
# Why THIS signal and not a broader one: checkpoint.md is optional-by-design (durable-artifact.md —
# "never create it speculatively"; SKILL.md's Execute step only calls for one on a run spanning many
# rounds or per-entity workers). So its mere presence with a populated coverage-floor table is already
# the agent's own claim that it identified >=2 entities worth tracking independently — this hook does
# not try to parse that claim out of freeform turn prose (unreliable, no fixed shape); it looks at the
# one place the method already asks for it structurally. A run that never needed a checkpoint is
# correctly silent here, by design, not by omission.
#
# Why Stop and not PostToolUse(Task|Agent): a PostToolUse hook on that matcher only fires when a
# Task/Agent call DID happen, so it cannot see an absence — only Stop has whole-transcript visibility
# (same shape as check-usage-budget.sh, the other Stop hook that scans transcript_path for text).
#
# What this is NOT: a gate. It never sets `decision:block`, never reads GOAL_GATE_ENFORCE — unlike
# gate-goal-close.sh's teeth, this check has no enforce mode at all, by design (ratified: "cualquier
# gate bloqueante" is explicitly out of scope for this fix). It is also not proof of independence: a
# >=2-row table can enumerate something other than decomposable execution entities (e.g. the carriers
# of a rule-surface enumeration) — the message says so plainly rather than asserting certainty.
#
# Behavior:
#   * No `.goalspec/checkpoint.md` in cwd -> silent exit 0. The overwhelmingly common case.
#   * Checkpoint present but no `## Coverage-floor table` heading, or < 2 data rows under it -> silent.
#   * Checkpoint present, >= 2 rows, but >= 1 entity-worker Task/Agent tool_use in the transcript ->
#     silent (decomposition already happened; nothing to nudge about). A Task/Agent whose
#     subagent_type names the adversary does NOT count here (it verifies, it does not decompose).
#   * Checkpoint present, >= 2 rows, zero entity-worker Task/Agent tool_use -> advisory nudge.
#   * Silent on a re-entrant Stop (`stop_hook_active`) — same guard as every other Stop hook here.
#   * Any read/parse failure is fail-open and silent — never blocks, never raises an error.
#
# Registered as a Stop hook by hooks/hooks.json (alongside gate-goal-close.sh and
# check-usage-budget.sh — three Stop hooks now emitting independently; each fail-opens on its own).
#
# 0.29.0: this hook has no notion of whether checkpoint.md belongs to THIS session — a leftover
# from an already-closed run (v0.28.0, `f148d6c`) false-positived on every turn of a later,
# unrelated session, confirmed live. The fix is write-side, not here: the goalspec skill's close
# step now deletes the file it wrote (references/durable-artifact.md, "When it goes away"). This
# hook's only change is its own message text, naming that fix so a human reading a false-positive
# nudge isn't stuck waiting on a smarter hook. No control-flow branch in this file changed.

INPUT=$(cat)

# Portable interpreter resolver — same as every other hook in this plugin.
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | "$PY" -c '
import json, sys, os, re

def silent():
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    silent()

# 0. Re-entrant Stop: say nothing (mirrors gate-goal-close.sh / check-usage-budget.sh step 0).
if data.get("stop_hook_active"):
    silent()

# 1. The checkpoint is the substrate — no file, no business here.
checkpoint_path = os.path.join(os.getcwd(), ".goalspec", "checkpoint.md")
try:
    with open(checkpoint_path, "r", encoding="utf-8", errors="replace") as fh:
        cp_text = fh.read()
except Exception:
    silent()

# 2. Find the "## Coverage-floor table" section (any heading level, case-insensitive, hyphen or
#    space between "coverage" and "floor") and count markdown table data rows under it, stopping at
#    the next heading or end of file. A data row: starts with "|", is not the header separator
#    ("|---|---|"-shaped) and is not blank.
heading_re = re.compile(r"(?im)^#{1,6}\s*coverage[\s-]*floor\s*table\s*$")
m = heading_re.search(cp_text)
if not m:
    silent()

rest = cp_text[m.end():]
next_heading = re.search(r"(?m)^#{1,6}\s", rest)
section = rest[:next_heading.start()] if next_heading else rest

row_count = 0
header_seen = False
for line in section.splitlines():
    line = line.strip()
    if not line.startswith("|"):
        continue
    if re.match(r"^\|[\s:|-]+\|$", line):
        continue  # the "|---|---|" separator line
    if not header_seen:
        header_seen = True  # first "|...|" line is the column-name header, not data
        continue
    row_count += 1

if row_count < 2:
    silent()

# 3. Scan the transcript for any Task/Agent tool_use that dispatched an ENTITY WORKER, anywhere
#    across the whole session. The adversary spawn is ALSO a Task/Agent tool_use (step 6 of
#    SKILL.md mandates it on exactly the kind of run that populates a checkpoint) but it verifies
#    the outcome, it does not decompose the work across entities -- counting it as "decomposition
#    happened" closes the nudge window the instant the verification step this method always runs
#    eventually fires, i.e. on almost every checkpointed run. So a Task/Agent is excluded from this
#    count ONLY when subagent_type is an EXACT (case-insensitive, whitespace-trimmed) match for a
#    known adversary agent-type name -- never a substring test: an external adversary round on this
#    same release live-caught a substring match on "adversary" wrongly excluding a real worker named
#    e.g. "not-goal-adversary-example", which would silence a real decomposition. Exact match is the
#    same lesson gate-goal-close.sh already applies to ADVERSARY-MODEL id matching (positional/exact,
#    never fabricated-substring).
ADVERSARY_AGENT_TYPES = {"goal-adversary", "goalspec:goal-adversary"}
tpath = data.get("transcript_path")
# A missing/unreadable transcript means "cannot determine whether decomposition happened", not
# "decomposition did not happen" -- silent (fail-open) is the correct answer, matching every other
# read/parse failure in this hook and the fail-open philosophy every hook in this plugin follows.
# An earlier cut of this hook fell through to "assume no decomposition -> nudge" here, caught live
# by an external adversary round on this exact release.
if not (isinstance(tpath, str) and tpath and os.path.isfile(tpath)):
    silent()
saw_decompose = False
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
                if not isinstance(content, list):
                    continue
                for blk in content:
                    if not (isinstance(blk, dict) and blk.get("type") == "tool_use" and blk.get("name") in ("Task", "Agent")):
                        continue
                    subagent_type = str((blk.get("input") or {}).get("subagent_type") or "").strip().lower()
                    if subagent_type in ADVERSARY_AGENT_TYPES:
                        continue
                    saw_decompose = True
                    break
                if saw_decompose:
                    break
    except Exception:
        pass
if saw_decompose:
    silent()

msg = (
    "[DECOMPOSE-NUDGE] .goalspec/checkpoint.md coverage-floor table lists {} entities, and no "
    "Task/Agent subagent call appears anywhere in this session. If those entities are independent "
    "(SKILL.md coverage-floor: decide at enumeration time, not at close), consider one subagent per "
    "entity instead of working through them serially in this context. This is a structural proxy, "
    "not proof of independence — the table can also enumerate something other than decomposable "
    "execution entities (e.g. rule carriers); ignore this if that is the case here. It can also be a "
    "leftover from an earlier, already-closed run in this same directory (a clean close now retires "
    "its own checkpoint — references/durable-artifact.md, \"When it goes away\") — if this session "
    "never wrote this file itself, delete .goalspec/checkpoint.md and re-check."
).format(row_count)

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": msg},
}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

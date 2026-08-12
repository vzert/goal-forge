#!/usr/bin/env bash
# nudge-decompose.sh — Stop hook. Advisory, non-blocking consumer for the decomposition/checkpoint
# signal SKILL.md's coverage-floor bullet describes but never mechanically checked (Fase 2 of
# memory/plans/plan-trigger-decomposicion.md; Fase 1, v0.27.0, fixed the trigger's own wording).
#
# What it does: if a `.goalspec/checkpoint*.md` in the cwd was written BY THIS SESSION (a Write/Edit
# tool_use for that exact path appears in this session's own transcript — see step 1 below) AND it
# carries a `## Coverage-floor table` heading whose markdown table has >= 2 data rows, AND the
# session transcript records ZERO entity-worker `Task`/`Agent` tool_use anywhere (the adversary's
# own step-6 spawn does not count — see step 3 below), print a non-blocking nudge asking whether
# that was intentional.
#
# Why THIS signal and not a broader one: the checkpoint is optional-by-design (durable-artifact.md —
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
# gate bloqueante" is explicitly out of scope for this fix -- a statement about THIS hook, which
# still holds; a different hook, hooks/precheck-checkpoint-overwrite.sh, does block, but on a
# narrower act: overwriting somebody else-s existing checkpoint, never a decomposition judgment).
# It is also not proof of independence: a
# >=2-row table can enumerate something other than decomposable execution entities (e.g. the carriers
# of a rule-surface enumeration) — the message says so plainly rather than asserting certainty.
#
# Behavior:
#   * No checkpoint written by THIS session -> silent exit 0. The overwhelmingly common case, and
#     it now also covers a foreign or leftover `.goalspec/checkpoint*.md` sitting in the cwd.
#   * A checkpoint under a NESTED `.goalspec/` (a sub-package running its own goalspec loop) is
#     not this run's, even when this session wrote it -> silent. "In the cwd" is meant literally.
#   * Owned checkpoint present but no `## Coverage-floor table` heading, or < 2 data rows under it
#     -> silent.
#   * Owned checkpoint, >= 2 rows, but >= 1 entity-worker Task/Agent tool_use in the transcript ->
#     silent (decomposition already happened; nothing to nudge about). A Task/Agent whose
#     subagent_type names the adversary does NOT count here (it verifies, it does not decompose).
#   * Owned checkpoint, >= 2 rows, zero entity-worker Task/Agent tool_use -> advisory nudge.
#   * Silent on a re-entrant Stop (`stop_hook_active`) — same guard as every other Stop hook here.
#   * Any read/parse failure is fail-open and silent — never blocks, never raises an error.
#
# Registered as a Stop hook by hooks/hooks.json (alongside gate-goal-close.sh and
# check-usage-budget.sh — three Stop hooks now emitting independently; each fail-opens on its own).
#
# 0.29.0: this hook had no notion of whether the checkpoint belonged to THIS session — a leftover
# from an already-closed run (v0.28.0, `f148d6c`) false-positived on every turn of a later,
# unrelated session, confirmed live. The fix chosen then was write-side (delete the file at a clean
# close); a session-id content stamp read here was considered and declined, on the record, unless a
# second incident showed up.
#
# 0.38.0, the second incident: two concurrent sessions in one project clobbered
# each other at the single fixed path `.goalspec/checkpoint.md` — live, reported by both agents.
# That moved the file to a per-session name (references/durable-artifact.md, "Where it lives") and
# gave this hook the read-side half it was missing. Ownership is decided WITHOUT a new content
# contract on the file: a checkpoint is this session's iff this session's own transcript records a
# Write/Edit tool_use for that exact path — the same evidence terminal_actions.py already reads for
# a goal-spec written to disk, and the same exact-match discipline this hook applies to
# subagent_type. Two consequences worth naming: an unreadable transcript is now silent rather than
# falling through to a nudge (it means "cannot determine ownership", not "no decomposition"), and a
# checkpoint written by a route this cannot see (a Bash heredoc instead of Write/Edit) is silent
# too — the fail-open direction, chosen over nudging about a file that may not be ours.

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

# 1. Ownership is the substrate, and it comes from the transcript -- not from the filesystem.
#    A `.goalspec/checkpoint*.md` in the cwd belongs to THIS session only if this session wrote it.
#    Anything else in that directory (a file from a concurrent session, a leftover from a run that
#    crashed and was never resumed) belongs to somebody else: this hook reads none of it. The path
#    pattern is kept in lockstep with hooks/lib/terminal_actions.py CHECKPOINT_PATH_RE and with the
#    declaration both cite, references/durable-artifact.md ("Where it lives").
#    A missing/unreadable transcript means "cannot determine ownership", not "no decomposition" --
#    silent (fail-open) is the correct answer, matching every other read/parse failure in this hook
#    and the fail-open philosophy every hook in this plugin follows. An earlier cut of this hook
#    fell through to "assume no decomposition -> nudge" on that path, caught live by an external
#    adversary round on the 0.28.0 release.
CHECKPOINT_RE = re.compile(r"(^|/)\.goalspec/checkpoint(-[A-Za-z0-9._-]+)?\.md$")

# 2. Scan the transcript ONCE for both facts it carries: which checkpoints this session wrote, and
#    whether any entity worker was ever dispatched. The adversary spawn is ALSO a Task/Agent
#    tool_use (step 6 of SKILL.md mandates it on exactly the kind of run that populates a
#    checkpoint) but it verifies the outcome, it does not decompose the work across entities --
#    counting it as "decomposition happened" closes the nudge window the instant the verification
#    step this method always runs eventually fires, i.e. on almost every checkpointed run. So a
#    Task/Agent is excluded from this count ONLY when subagent_type is an EXACT (case-insensitive,
#    whitespace-trimmed) match for a known adversary agent-type name -- never a substring test: an
#    external adversary round on the 0.28.0 release live-caught a substring match on "adversary"
#    wrongly excluding a real worker named e.g. "not-goal-adversary-example", which would silence a
#    real decomposition. Exact match is the same lesson gate-goal-close.sh already applies to
#    ADVERSARY-MODEL id matching (positional/exact, never fabricated-substring).
ADVERSARY_AGENT_TYPES = {"goal-adversary", "goalspec:goal-adversary"}
tpath = data.get("transcript_path")
if not (isinstance(tpath, str) and tpath and os.path.isfile(tpath)):
    silent()

cwd = os.getcwd()
goalspec_dir = os.path.realpath(os.path.join(cwd, ".goalspec"))
owned_ids = {}
ok_ids = set()
saw_decompose = False
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
            msg = ev.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                # A tool_result records whether the request above actually worked, and ownership
                # needs that: a DENIED Write is still a tool_use, and treating a request as an act
                # is the defect an adversary round found in the sibling gate
                # (hooks/precheck-checkpoint-overwrite.sh) and rated unsafe there. The same
                # evidence rule applies here, where the cost of getting it wrong is only a nudge
                # about a file that is not ours.
                if blk.get("type") == "tool_result" and blk.get("tool_use_id"):
                    if not blk.get("is_error"):
                        ok_ids.add(blk.get("tool_use_id"))
                    continue
                if blk.get("type") != "tool_use":
                    continue
                tool = blk.get("name")
                inp = blk.get("input") or {}
                if tool in ("Write", "Edit"):
                    fp = inp.get("file_path")
                    # Backslashes normalized before matching, same reason and same lockstep as
                    # terminal_actions.py: on Windows the transcript records a backslash path and
                    # the POSIX-separator pattern would never match. The rest of the flow (the
                    # dirname anchor, the file read) uses os.path, which is native on Windows, so
                    # this one line is the whole fix. Unobservable from a POSIX host by
                    # construction: a Windows path cannot resolve to a real file here.
                    if isinstance(fp, str) and CHECKPOINT_RE.search(fp.replace("\\", "/")):
                        # realpath, not normpath, on BOTH sides of the comparison below: on
                        # macOS a temp/working dir reached through a symlink (/var -> /private/var)
                        # makes the transcript path and the cwd-derived one differ by prefix
                        # alone. Caught by the suite for this hook the moment the anchor landed.
                        p = os.path.realpath(fp if os.path.isabs(fp) else os.path.join(cwd, fp))
                        # ...and it must be THE checkpoint of the directory this hook runs in, not
                        # any `.goalspec/` anywhere below it. The path pattern alone accepts a
                        # nested `sub/.goalspec/checkpoint-x.md` -- deliberately, in
                        # terminal_actions.py, which has no cwd to anchor against and must accept
                        # an absolute file_path. Here there IS a cwd, the declared contract is "in
                        # the cwd" (see the header and references/durable-artifact.md, "at the root
                        # of the project you are working in"), and an adversary round caught the
                        # code being broader than that claim by live-probing a nested path. Anchor
                        # it rather than widen the claim: a sub-package running its own goalspec
                        # loop is its own run, not this one.
                        if os.path.dirname(p) == goalspec_dir and blk.get("id"):
                            owned_ids[blk.get("id")] = p
                elif tool in ("Task", "Agent"):
                    subagent_type = str(inp.get("subagent_type") or "").strip().lower()
                    if subagent_type not in ADVERSARY_AGENT_TYPES:
                        saw_decompose = True
except Exception:
    silent()

# Only writes that actually succeeded confer ownership (see the tool_result note above).
owned = []
for tid, p in owned_ids.items():
    if tid in ok_ids and p not in owned:
        owned.append(p)

if not owned:
    silent()

# 3. Find the "## Coverage-floor table" section (any heading level, case-insensitive, hyphen or
#    space between "coverage" and "floor") and count markdown table data rows under it, stopping at
#    the next heading or end of file. A data row: starts with "|", is not the header separator
#    ("|---|---|"-shaped) and is not blank. A session that wrote more than one checkpoint (it
#    should not -- durable-artifact.md says one file per run -- but nothing prevents it) is judged
#    on its largest table: the nudge is about whether the enumeration was decomposed, so the
#    biggest enumeration is the one worth asking about.
heading_re = re.compile(r"(?im)^#{1,6}\s*coverage[\s-]*floor\s*table\s*$")
best_path = None
best_rows = 0
for p in owned:
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            cp_text = fh.read()
    except Exception:
        continue

    m = heading_re.search(cp_text)
    if not m:
        continue

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

    if row_count >= 2 and row_count > best_rows:
        best_path = p
        best_rows = row_count

if best_path is None:
    silent()

if saw_decompose:
    silent()

try:
    shown = os.path.relpath(best_path, cwd)
except Exception:
    shown = best_path

msg = (
    "[DECOMPOSE-NUDGE] {} coverage-floor table lists {} entities, and no "
    "Task/Agent subagent call appears anywhere in this session. If those entities are independent "
    "(SKILL.md coverage-floor: decide at enumeration time, not at close), consider one subagent per "
    "entity instead of working through them serially in this context. This is a structural proxy, "
    "not proof of independence — the table can also enumerate something other than decomposable "
    "execution entities (e.g. rule carriers); ignore this if that is the case here. This session "
    "wrote that file itself, so it is not a leftover from an earlier run — a foreign or abandoned "
    "checkpoint in this directory is ignored here by construction, and your own is retired at a "
    "clean close (references/durable-artifact.md, \"When it goes away\")."
).format(shown, best_rows)

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": msg},
}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

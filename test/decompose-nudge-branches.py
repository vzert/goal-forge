#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/nudge-decompose.sh.

Why this exists: the coverage-floor / decomposition trigger in SKILL.md (reframed in v0.27.0 to
fire at enumeration time, not at close) had zero mechanical consumer — gate-goal-close.sh only
mentioned it in comments. This is Fase 2 of memory/plans/plan-trigger-decomposicion.md: a
non-blocking Stop-hook nudge, never a gate (no `decision:block`, no GOAL_GATE_ENFORCE branch at all
in this hook — that is a design property, not an omission, and case 01 below is the only guard this
suite needs against a re-entrant loop, not against blocking).

The signal the hook reads: `.goalspec/checkpoint.md` in the cwd, a `## Coverage-floor table`
heading with >= 2 markdown-table data rows, and zero entity-worker `Task`/`Agent` tool_use blocks
anywhere in the transcript. Checkpoint.md is optional-by-design (durable-artifact.md: "never create
it speculatively"), so its mere presence with a populated table is already the agent's own claim of
>=2 tracked entities — this suite proves the row-count and tool_use-absence checks are both real,
not a hardcoded "checkpoint exists -> nudge" (cases 04/05 are the controls for that).

Cases 07-09 pin a real break an adversary subagent caught live against this exact release: the
adversary's own step-6 spawn is ALSO a Task/Agent tool_use, and step-6 explicitly directs the
executor to write `.goalspec/checkpoint.md` and THEN spawn the adversary pointing at it — so an
earlier version of this hook that counted ANY Task/Agent as "decomposed" had its nudge window close
on the plugin's own mandated verification step, on almost every checkpointed run. A Task/Agent whose
`subagent_type` names the adversary is now excluded from the count.

    python3 test/decompose-nudge-branches.py

Exit code is non-zero if any case does not produce its expected cell.

Case 16 (0.29.0) pins the checkpoint-lifecycle fix's only mechanical surface on THIS hook: the
advisory message now names the leftover-checkpoint mitigation directly. The real fix is write-side
(SKILL.md's close step deletes the file it wrote; durable-artifact.md "When it goes away") — no
control-flow branch in this hook changed, so 01-15 are a no-regression check, not a test of the
fix. Content, not just nudge/silent, is what proves the message actually changed.

WHAT THIS SUITE DOES NOT COVER (stated so a green run does not imply more —
references/instrument-validity-own-tools.md): a real live session where a coverage-floor table was
populated and decomposition was genuinely skipped is not exercised here; every case drives the hook
directly with a synthetic checkpoint file and transcript, the same hermetic pattern
usage-budget-branches.py already uses for its own hook. That live observation stays a documented
open item, not something this suite closes. Nor does anything here exercise whether an executor
actually performs the new close-step deletion in a real multi-round run — that instruction lives in
SKILL.md prose, not in this hook, so no hermetic test can assert it; it stays an open live
observation alongside the decomposition-skip case above.
"""
import json, os, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "nudge-decompose.sh")

CHECKPOINT_2ROW = """# Checkpoint

## Coverage-floor table

| entity | status |
|---|---|
| widget-a | done |
| widget-b | pending |

## Rounds

- Round 1: did stuff.
"""

CHECKPOINT_1ROW = """# Checkpoint

## Coverage-floor table

| entity | status |
|---|---|
| widget-a | done |
"""

CHECKPOINT_0ROW = """# Checkpoint

## Coverage-floor table

| entity | status |
|---|---|
"""

CHECKPOINT_NO_HEADING = """# Checkpoint

## Live goal-spec

Objective: whatever. No coverage-floor section at all.
"""


def transcript_with(tool_calls):
    """Build a synthetic transcript JSONL: one assistant turn per tool_use block requested.

    tool_calls: list of (name, subagent_type_or_None) or bare name strings (subagent_type=None).
    """
    lines = []
    for call in tool_calls:
        name, subagent_type = call if isinstance(call, tuple) else (call, None)
        input_ = {"subagent_type": subagent_type} if subagent_type else {}
        ev = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name, "input": input_}]},
        }
        lines.append(json.dumps(ev))
    return "\n".join(lines) + ("\n" if lines else "")


# (name, checkpoint_text_or_None, tool_calls_in_transcript, extra_payload, expected)
#   tool_calls: list of bare name strings or (name, subagent_type) tuples.
#   expected: "nudge" or "silent"
CASES = [
    # --- re-entrant guard, same discipline as check-usage-budget.sh cases 01-03 ---
    ("01-guard-active-silent", CHECKPOINT_2ROW, [], {"stop_hook_active": True}, "silent"),
    ("02-guard-absent-nudges", CHECKPOINT_2ROW, [], {}, "nudge"),
    ("03-guard-false-nudges", CHECKPOINT_2ROW, [], {"stop_hook_active": False}, "nudge"),

    # --- controls: prove the tool_use-absence check is real, not a hardcoded pass ---
    ("04-decomposed-via-agent-silent", CHECKPOINT_2ROW, ["Agent"], {}, "silent"),
    ("05-decomposed-via-task-silent", CHECKPOINT_2ROW, ["Task"], {}, "silent"),
    ("06-unrelated-tool-still-nudges", CHECKPOINT_2ROW, ["Bash", "Read"], {}, "nudge"),

    # --- the adversary-spawn exclusion (the break the subagent adversary found live, 0.28.0) ---
    # The adversary's own step-6 spawn is ALSO a Task/Agent tool_use. Counting it as
    # "decomposition happened" made the nudge's window close on the plugin's own mandated
    # verification step, in the exact flow SKILL.md prescribes for a checkpointed run (write the
    # checkpoint, THEN spawn the adversary pointing at it) — a live run confirmed the window was
    # zero-width in practice. So a Task/Agent whose subagent_type names the adversary must NOT
    # silence the nudge on its own; a real worker alongside it still does.
    ("07-adversary-spawn-alone-still-nudges", CHECKPOINT_2ROW,
     [("Agent", "goalspec:goal-adversary")], {}, "nudge"),
    ("08-real-worker-plus-adversary-silent", CHECKPOINT_2ROW,
     [("Agent", "general-purpose"), ("Agent", "goalspec:goal-adversary")], {}, "silent"),
    ("09-adversary-named-task-still-nudges", CHECKPOINT_2ROW,
     [("Task", "goal-adversary")], {}, "nudge"),
    # Collision control (caught live by an external adversary round on this exact release): a
    # substring test on "adversary" would wrongly exclude a real worker whose subagent_type merely
    # CONTAINS that word without being one of the two exact known adversary agent-type names. Exact
    # match must classify this as real decomposition -> silent, not nudge.
    ("10-substring-collision-still-silences", CHECKPOINT_2ROW,
     [("Agent", "not-goal-adversary-example")], {}, "silent"),

    # --- controls: prove the row-count check is real ---
    ("11-below-threshold-silent", CHECKPOINT_1ROW, [], {}, "silent"),
    ("12-zero-rows-silent", CHECKPOINT_0ROW, [], {}, "silent"),

    # --- controls: prove the checkpoint/heading gate is real ---
    ("13-no-checkpoint-silent", None, [], {}, "silent"),
    ("14-no-heading-silent", CHECKPOINT_NO_HEADING, [], {}, "silent"),

    # --- fail-open on a missing/unreadable transcript (caught live by a second external-adversary
    #     round on this exact release): "cannot determine whether decomposition happened" must
    #     resolve to silent, never to "assume it didn't happen -> nudge". ---
    ("15-missing-transcript-silent", CHECKPOINT_2ROW, "MISSING_TRANSCRIPT", {}, "silent"),
]


def run_case(name, checkpoint_text, tool_calls, extra, tmp):
    case_dir = os.path.join(tmp, name)
    os.makedirs(case_dir, exist_ok=True)

    if checkpoint_text is not None:
        gs_dir = os.path.join(case_dir, ".goalspec")
        os.makedirs(gs_dir, exist_ok=True)
        with open(os.path.join(gs_dir, "checkpoint.md"), "w", encoding="utf-8") as fh:
            fh.write(checkpoint_text)

    if tool_calls == "MISSING_TRANSCRIPT":
        payload = {"transcript_path": os.path.join(case_dir, "does-not-exist.jsonl")}
    else:
        transcript_path = os.path.join(case_dir, "transcript.jsonl")
        with open(transcript_path, "w", encoding="utf-8") as fh:
            fh.write(transcript_with(tool_calls))
        payload = {"transcript_path": transcript_path}
    payload.update(extra)

    out = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                         capture_output=True, text=True, cwd=case_dir).stdout.strip()
    return "nudge" if out else "silent"


def run_case_raw(name, checkpoint_text, tool_calls, tmp):
    """Like run_case but returns the hook's raw stdout instead of collapsing to nudge/silent —
    needed for the one case (16) that checks message CONTENT, not just presence."""
    case_dir = os.path.join(tmp, name)
    os.makedirs(case_dir, exist_ok=True)
    gs_dir = os.path.join(case_dir, ".goalspec")
    os.makedirs(gs_dir, exist_ok=True)
    with open(os.path.join(gs_dir, "checkpoint.md"), "w", encoding="utf-8") as fh:
        fh.write(checkpoint_text)
    transcript_path = os.path.join(case_dir, "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as fh:
        fh.write(transcript_with(tool_calls))
    payload = {"transcript_path": transcript_path}
    return subprocess.run(["bash", HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=case_dir).stdout.strip()


def main():
    tmp = tempfile.mkdtemp(prefix="decompose-nudge-branches-")
    failures = []
    for name, checkpoint_text, tool_calls, extra, expected in CASES:
        got = run_case(name, checkpoint_text, tool_calls, extra, tmp)
        ok = got == expected
        if not ok:
            failures.append((name, expected, got))
        print("{:<32} {:<8} {}".format(name, got, "" if ok else "  <-- FAIL, expected " + expected))

    # --- 16: message CONTENT, not just nudge/silent (0.29.0 checkpoint-lifecycle fix). This fix's
    # only mechanical surface on THIS hook is the advisory string -- the real fix is write-side
    # (SKILL.md's close step now deletes the file it wrote; see durable-artifact.md "When it goes
    # away"). Every case above collapses output to nudge/silent, so without this the new sentence
    # would ship unasserted. ---
    name16 = "16-message-names-leftover-mitigation"
    out16 = run_case_raw(name16, CHECKPOINT_2ROW, [], tmp)
    ok16 = "already-closed run" in out16 and "durable-artifact.md" in out16
    if not ok16:
        failures.append((name16, "content present", "content missing"))
    print("{:<32} {:<8} {}".format(name16, "content-ok" if ok16 else "content-MISSING",
                                    "" if ok16 else "  <-- FAIL, expected leftover-mitigation text"))

    total = len(CASES) + 1
    print()
    if failures:
        print("{} case(s) FAILED".format(len(failures)))
        return 1
    print("all {} case(s) OK".format(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())

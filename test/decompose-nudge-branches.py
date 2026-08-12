#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/nudge-decompose.sh.

Why this exists: the coverage-floor / decomposition trigger in SKILL.md (reframed in v0.27.0 to
fire at enumeration time, not at close) had zero mechanical consumer — gate-goal-close.sh only
mentioned it in comments. This is Fase 2 of memory/plans/plan-trigger-decomposicion.md: a
non-blocking Stop-hook nudge, never a gate (no `decision:block`, no GOAL_GATE_ENFORCE branch at all
in this hook — that is a design property, not an omission, and case 01 below is the only guard this
suite needs against a re-entrant loop, not against blocking).

The signal the hook reads: a `.goalspec/checkpoint*.md` in the cwd THAT THIS SESSION WROTE (a
Write/Edit tool_use for that exact path in this session's own transcript), a `## Coverage-floor
table` heading with >= 2 markdown-table data rows, and zero entity-worker `Task`/`Agent` tool_use
blocks anywhere in the transcript. The checkpoint is optional-by-design (durable-artifact.md: "never
create it speculatively"), so its mere presence with a populated table is already the agent's own
claim of >=2 tracked entities — this suite proves the row-count, ownership and tool_use-absence
checks are all real, not a hardcoded "checkpoint exists -> nudge" (cases 04/05 are the controls for
the last, 17/19/20 for ownership).

CONTRACT CHANGE, 0.38.0 — the concurrency fix. Two concurrent sessions in one
project used to clobber the single fixed path `.goalspec/checkpoint.md`; the file is now per-session
and this hook decides ownership from the transcript. That means every pre-existing case in this file
changed shape: each now emits a `Write` tool_use for the checkpoint it creates, because a checkpoint
nobody in this session wrote is, correctly, no longer this hook's business. The cases whose
EXPECTATION changed are none — 01-15 keep their expected cells, which is the no-regression check;
what changed is the fixture they run against. Case 16's asserted message text DID change (the
leftover-mitigation sentence it pinned described a mitigation that ownership now performs
mechanically), and that is stated here rather than quietly re-pinned.

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


def transcript_with(tool_calls, writes=()):
    """Build a synthetic transcript JSONL: one assistant turn per tool_use block requested.

    tool_calls: list of (name, subagent_type_or_None) or bare name strings (subagent_type=None).
    writes: list of (tool_name, file_path) emitted FIRST — this is how a session claims ownership
        of a checkpoint under the concurrency fix. A checkpoint with no matching write here belongs
        to somebody else (a concurrent session, a crashed run) and the hook must ignore it.
    """
    lines = []
    for i, entry in enumerate(writes):
        tool, path = entry[0], entry[1]
        outcome = entry[2] if len(entry) > 2 else "ok"
        tid = "toolu_w%d" % i
        ev = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": tid, "name": tool,
                                     "input": {"file_path": path}}]},
        }
        lines.append(json.dumps(ev))
        # The paired result is what turns a REQUEST into an ACT. A denied Write is still a
        # tool_use, so ownership that ignores the result counts a refusal as proof of writing --
        # the defect an adversary round found in the sibling gate and rated unsafe there.
        if outcome != "none":
            lines.append(json.dumps({
                "type": "user",
                "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                         "is_error": outcome == "error",
                                         "content": "denied" if outcome == "error" else "ok"}]},
            }))
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

    # --- ownership (the concurrency fix). The write-side half is a per-session filename; this is
    #     the read-side half, and these are its controls. 17 is the incident itself: a concurrent
    #     session's checkpoint sitting in the same working directory. 19 is the residual v0.29.0
    #     accepted and left open (a leftover from a run that crashed and was never resumed) — now
    #     closed by the same mechanism, at the legacy name, which is why it is pinned separately
    #     rather than assumed to follow from 17. 18/21/22 are the twin controls proving ownership
    #     does not just silence everything: same file, same table, ownership present -> nudge. ---
    ("17-foreign-session-checkpoint-silent", CHECKPOINT_2ROW, [], {}, "silent",
     {"cp_name": "checkpoint-other-session.md", "owned": False}),
    ("18-owned-session-scoped-nudges", CHECKPOINT_2ROW, [], {}, "nudge",
     {"cp_name": "checkpoint-mine.md"}),
    ("19-crash-leftover-legacy-name-silent", CHECKPOINT_2ROW, [], {}, "silent",
     {"owned": False}),
    # A Write to a near-miss path must NOT confer ownership: the matcher is anchored on the
    # `.goalspec/` directory component and on end-of-string, the same narrowness
    # hooks/lib/terminal_actions.py needs to keep SKILL.md/CHANGELOG example text out of the gate.
    # The decoys must EXIST and carry a >= 2-row table of their own, or this case passes for the
    # wrong reason: a loose matcher would resolve a near-miss path to a file that is not there,
    # skip it, and fall silent anyway -- green against the very implementation it must reject.
    # With the decoys real, a loose matcher nudges and this case fails, which is the point.
    ("20-near-miss-write-is-not-ownership", CHECKPOINT_2ROW, [], {}, "silent",
     {"owned": False,
      "decoy_files": ["docs/checkpoint-notes.md", ".goalspec/checkpoint.md.bak",
                      ".goalspec/nested/checkpoint.md"],
      "extra_writes": [("Write", "docs/checkpoint-notes.md"),
                       ("Write", ".goalspec/checkpoint.md.bak"),
                       ("Write", ".goalspec/nested/checkpoint.md")]}),
    # Found by an external adversary round on this very change, by live-probing the hook rather
    # than reading it: the path pattern alone accepts ANY `.goalspec/` below the cwd, while this
    # hook's header and `references/durable-artifact.md` both say the cwd's own. A sub-package
    # running its own goalspec loop is its own run. The checkpoint here is real, owned, and has a
    # >= 2-row table — everything except being at the anchored location.
    ("23-nested-goalspec-dir-is-not-the-cwd-checkpoint", None, [], {}, "silent",
     {"decoy_files": ["sub/.goalspec/checkpoint-mine.md"],
      "extra_writes": [("Write", "sub/.goalspec/checkpoint-mine.md")]}),
    # A write this session ATTEMPTED but that failed or was denied is not a write. Same evidence
    # rule as the sibling gate, where an adversary round rated the missing check unsafe; here the
    # cost is only nudging about a file that is not ours.
    ("24-denied-write-is-not-ownership", CHECKPOINT_2ROW, [], {}, "silent",
     {"cp_name": "checkpoint-mine.md", "write_outcome": "error"}),
    ("25-write-with-no-result-is-not-ownership", CHECKPOINT_2ROW, [], {}, "silent",
     {"cp_name": "checkpoint-mine.md", "write_outcome": "none"}),
    ("21-edit-confers-ownership", CHECKPOINT_2ROW, [], {}, "nudge",
     {"cp_name": "checkpoint-mine.md", "write_tool": "Edit"}),
    # The transcript records whatever path the tool was called with; a relative one must resolve
    # against the cwd the hook runs in, or ownership silently never matches in a real session.
    ("22-relative-write-path-confers-ownership", CHECKPOINT_2ROW, [], {}, "nudge",
     {"cp_name": "checkpoint-mine.md", "relative_write": True}),
]


def _write_checkpoint(case_dir, checkpoint_text, cp_name):
    gs_dir = os.path.join(case_dir, ".goalspec")
    os.makedirs(gs_dir, exist_ok=True)
    path = os.path.join(gs_dir, cp_name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(checkpoint_text)
    return path


def _ownership_writes(cp_path, opts):
    """The (tool, path) writes that claim ownership of cp_path, per this case's options."""
    writes = list(opts.get("extra_writes", []))
    if opts.get("owned", True) and cp_path is not None:
        path = os.path.join(".goalspec", os.path.basename(cp_path)) \
            if opts.get("relative_write") else cp_path
        writes.append((opts.get("write_tool", "Write"), path, opts.get("write_outcome", "ok")))
    return writes


def run_case(name, checkpoint_text, tool_calls, extra, tmp, opts=None):
    opts = opts or {}
    case_dir = os.path.join(tmp, name)
    os.makedirs(case_dir, exist_ok=True)

    cp_path = None
    if checkpoint_text is not None:
        cp_path = _write_checkpoint(case_dir, checkpoint_text, opts.get("cp_name", "checkpoint.md"))

    for rel in opts.get("decoy_files", []):
        decoy = os.path.join(case_dir, rel)
        os.makedirs(os.path.dirname(decoy), exist_ok=True)
        with open(decoy, "w", encoding="utf-8") as fh:
            fh.write(CHECKPOINT_2ROW)

    if tool_calls == "MISSING_TRANSCRIPT":
        payload = {"transcript_path": os.path.join(case_dir, "does-not-exist.jsonl")}
    else:
        transcript_path = os.path.join(case_dir, "transcript.jsonl")
        with open(transcript_path, "w", encoding="utf-8") as fh:
            fh.write(transcript_with(tool_calls, _ownership_writes(cp_path, opts)))
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
    cp_path = _write_checkpoint(case_dir, checkpoint_text, "checkpoint.md")
    transcript_path = os.path.join(case_dir, "transcript.jsonl")
    with open(transcript_path, "w", encoding="utf-8") as fh:
        fh.write(transcript_with(tool_calls, _ownership_writes(cp_path, {})))
    payload = {"transcript_path": transcript_path}
    return subprocess.run(["bash", HOOK], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=case_dir).stdout.strip()


def main():
    tmp = tempfile.mkdtemp(prefix="decompose-nudge-branches-")
    failures = []
    for row in CASES:
        name, checkpoint_text, tool_calls, extra, expected = row[:5]
        opts = row[5] if len(row) > 5 else {}
        got = run_case(name, checkpoint_text, tool_calls, extra, tmp, opts)
        ok = got == expected
        if not ok:
            failures.append((name, expected, got))
        print("{:<32} {:<8} {}".format(name, got, "" if ok else "  <-- FAIL, expected " + expected))

    # --- 16: message CONTENT, not just nudge/silent. Every case above collapses output to
    # nudge/silent, so without this the message would ship unasserted.
    #
    # 0.29.0 pinned a sentence telling the human to delete the file if this session never wrote it
    # -- the manual mitigation for a leftover the hook could not detect. Ownership now performs that
    # check mechanically, so that sentence became false (the hook no longer nudges about a file this
    # session did not write) and the assertion moved with it. What is pinned now: the message names
    # the specific file it read (a per-session name means "the checkpoint" is no longer unambiguous)
    # and still points at the declaration that owns the lifecycle rule. ---
    name16 = "16-message-names-file-and-lifecycle"
    out16 = run_case_raw(name16, CHECKPOINT_2ROW, [], tmp)
    ok16 = (".goalspec/checkpoint.md" in out16
            and "wrote that file itself" in out16
            and "durable-artifact.md" in out16)
    if not ok16:
        failures.append((name16, "content present", "content missing"))
    print("{:<32} {:<8} {}".format(name16, "content-ok" if ok16 else "content-MISSING",
                                    "" if ok16 else "  <-- FAIL, expected file name + lifecycle text"))

    total = len(CASES) + 1
    print()
    if failures:
        print("{} case(s) FAILED".format(len(failures)))
        return 1
    print("all {} case(s) OK".format(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/gate-goal-close.sh.

There is no CI here — the plugin is a skill + hooks + docs. This is the mechanical half of the
acid-test in CLAUDE.md: it drives the Stop gate across every branch it can take, using synthetic
`last_assistant_message` payloads and, where a branch needs history, synthetic multi-turn
`transcript_path` JSONL files.

    python3 test/gate-branches.py                              # run against the repo's gate
    python3 test/gate-branches.py --compare <other-gate.sh>    # regression parity vs another copy
    python3 test/gate-branches.py --compare <g> --expected 16-hold-resets,26-...   # pre-declared diffs
    GOAL_GATE_ENFORCE=1 python3 test/gate-branches.py ...      # same suite through the blocking path

The parity mode is the one that matters when editing the gate: copy the pre-edit script somewhere,
then `--compare` it. Exit code is non-zero if any observed cell differs, so it works in a pipeline.

Columns: case | detail code the gate reported | CONV if the convergence floor fired | how the gate
ANSWERED (`block` under GOAL_GATE_ENFORCE=1, `advisory` otherwise, `silent` when it emitted nothing).

That third observable is not decoration. Until 0.18.0 this harness read `systemMessage or reason`,
which collapses the advisory and blocking paths into one string — so a change to *whether the gate
blocks* was invisible to `--compare`, the one instrument used to certify "no regression" when
editing the gate. Teeth are only teeth if the instrument can see them; that applies to the
verification instrument as much as to the gate it verifies.

A case may also declare `expect` (see CASES), asserted on EVERY run rather than only under
`--compare`. Parity-against-a-copy cannot express "this branch must emit nothing at all", because
the copy is precisely the thing being changed; the 0.18.1 re-entrant-Stop guard needed a test that
failed before the fix, and that is the shape of it.

`--expected` is the pre-commitment channel: name the cases you INTEND to change before you run the
comparison, and the run separates them from regressions instead of leaving you to rationalize a
non-zero exit after the fact. It takes case-name prefixes, is never persisted in this file (a stale
expected-diff list is just a muted alarm), and unexpected diffs still exit non-zero.
"""
import argparse, json, os, re, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_GATE = os.path.join(REPO, "plugins", "goalspec", "hooks", "gate-goal-close.sh")
TMP = tempfile.mkdtemp(prefix="gate-branches-")

SPEC = "## Goal-spec\nObjective: whatever.\n"
V_BREAK_A = "[ADVERSARY-VERDICT: break ungrounded=1 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
V_BREAK_B = "[ADVERSARY-VERDICT: break ungrounded=0 unfalsified=2 incomplete=0 autonomy-violations=0 unsafe=0]"
V_BREAK_C = "[ADVERSARY-VERDICT: break ungrounded=0 unfalsified=0 incomplete=3 autonomy-violations=0 unsafe=0]"
V_HOLD = "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
CR_ADV = "[COMPLETION-REVIEW: adversary model=same]"
CR_ADV_DIFF = "[COMPLETION-REVIEW: adversary model=different (claude-sonnet-5)]"
CR_NONE = "[COMPLETION-REVIEW: none reason=clean close, no mutation and no inherited decision touched]"
CR_NONE_SHORT = "[COMPLETION-REVIEW: none reason=short]"
WAIVER = "[GOAL-CLOSE-WAIVED reason=adversary sandbox limitation, not a defect in the outcome]"
MODEL_REAL = "[ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5]"
MODEL_UNKNOWN = "[ADVERSARY-MODEL: UNKNOWN / UNKNOWN]"

# (name, last_assistant_message, transcript turns or None[, opts])
# opts is an optional dict:
#   "payload" -> extra keys merged into the hook's stdin (e.g. {"stop_hook_active": True})
#   "expect"  -> the `decision` cell this case MUST produce, in BOTH modes. Cases that declare it
#                are asserted on every run, not only under --compare: a guard whose whole job is to
#                emit nothing needs a test that fails when it emits something, and parity-vs-a-copy
#                cannot express that (the copy is the thing being changed).
CASES = [
    # --- the branches that predate the convergence floor ---
    ("01-no-goalspec", "just some text, no spec here", None),
    ("02-spec-no-review", SPEC + "I did the work.", None),
    ("03-none-valid", SPEC + CR_NONE, None),
    ("04-none-short-reason", SPEC + CR_NONE_SHORT, None),
    ("05-adv-no-verdict", SPEC + CR_ADV, None),
    ("06-adv-over-break", SPEC + V_BREAK_A + "\n" + CR_ADV, None),
    ("07-none-over-break", SPEC + CR_NONE, [SPEC, V_BREAK_A]),
    ("08-modeldiff-unknown", SPEC + MODEL_UNKNOWN + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None),
    ("09-modeldiff-real-id", SPEC + MODEL_REAL + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None),
    ("10-waiver", SPEC + V_BREAK_A + "\n" + WAIVER, None),
    ("11-hold-closes", SPEC + V_HOLD + "\n" + CR_ADV, None),

    # --- convergence floor (0.15.0) ---
    # three distinct break rounds, current turn tries to close
    ("12-three-breaks", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C]),
    # two rounds is below the floor
    ("13-two-breaks", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B]),
    # DEDUP: the current turn re-quotes the verdict already recorded as the last turn (i.e. the
    # transcript is NOT lagging). The floor must stay 2 — this is the case that catches double
    # counting of a single round.
    ("14-dedup-lam-equals-tail", V_BREAK_B + "\n" + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B]),
    # the current turn carries a NEW break the transcript has not recorded yet (transcript lagging)
    ("15-lam-new-break", V_BREAK_C + "\n" + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B]),
    # a hold-only turn ends the run
    ("16-hold-resets", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B, V_HOLD, V_BREAK_C]),
    # one turn quoting BOTH backends (subagent hold + external break) is ONE break round, and does
    # not reset the run — which is why the floor's wording says "no hold-ONLY turn between them"
    ("17-mixed-turn", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B, V_HOLD + "\n" + V_BREAK_C]),
    # the floor must also reach the reminder a mid-loop agent actually sees (no completion-review yet)
    ("18-absent-with-3", SPEC + "still working on it.", [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C]),
    # an explicit waiver short-circuits everything, floor included
    ("19-waiver-with-3", SPEC + WAIVER, [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C]),
    # the SAME verdict string in three separate turns collapses to 1 — a deliberate under-count
    # (the fail-open direction), never a false "three breaks, stop editing"
    ("20-identical-requotes", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_A, V_BREAK_A]),

    # --- coverage disclosure (0.16.0) ---
    # `backends=` is an ungated disclosure field, but it lives INSIDE the completion-review bracket,
    # which cr_pat captures as `[^\]]*`. These pin the two ways that could go wrong: an extra field
    # must not break a valid close (21/22), and it must not mask the one check that IS gated (23).
    ("21-backends-both-modeldiff",
     SPEC + MODEL_REAL + "\n" + V_HOLD + "\n[COMPLETION-REVIEW: adversary model=different (claude-sonnet-5) backends=both]", None),
    ("22-backends-single-modelsame",
     SPEC + V_HOLD + "\n[COMPLETION-REVIEW: adversary model=same backends=subagent-only]", None),
    ("23-backends-does-not-mask-modeldiff",
     SPEC + V_HOLD + "\n[COMPLETION-REVIEW: adversary model=different (x) backends=both]", None),

    # --- hold-only reset + floor-as-its-own-branch (0.18.0) ---
    # The bound on the walk: a hold-only turn still ends the run when it is the MOST RECENT
    # verdict-carrying turn — that is convergence, and a floor there would be noise.
    ("24-hold-latest-no-floor", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C, V_HOLD]),
    # ...but an EARLIER hold-only turn no longer extinguishes the count (16-hold-resets is the same
    # rule seen from the other side). This case pins that skipping it does not over-count into a
    # false floor: two break rounds around one hold is still 2, not 3.
    ("25-hold-inside-run-still-2", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_HOLD, V_BREAK_B]),
    # The floor must be able to fire on a path where the gate has NO completion-review complaint —
    # a turn quoting both backends closes on the hold (operative verdict = hold, gate says OK) while
    # the break-round count behind it is 3. Before 0.18.0 the floor could only ride an existing
    # reminder, so this run got silence at streak 3.
    ("26-floor-on-ok-close", V_BREAK_C + "\n" + V_HOLD + "\n" + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B]),

    # --- re-entrant Stop guard (0.18.1) ---
    # `stop_hook_active` is the harness telling the hook "this Stop is itself the product of a
    # previous Stop hook's output". MEASURED, not assumed: it arrives `false` on a first Stop and
    # `true` on the following one — including when the continuation was caused by a purely advisory
    # payload with no `decision:block` anywhere, which is the exact path the worst recorded runaway
    # took (31 Stop records, preventedContinuation:false, zero blocks). Re-asking on that Stop is
    # how one reminder became nine. The guard must therefore precede EVERY branch, teeth included.
    ("27-stop-hook-active-true", SPEC + "I did the work.", None,
     {"payload": {"stop_hook_active": True}, "expect": "silent"}),
    # ...and the control: the same payload without the flag is the ordinary first Stop — the 99%
    # case — and must be untouched. A guard that silences this is a worse defect than the one fixed.
    ("28-stop-hook-active-absent", SPEC + "I did the work.", None,
     {"expect": "advisory-or-block"}),
    # explicit false must behave exactly like absent, not like "key present -> skip"
    ("29-stop-hook-active-false", SPEC + "I did the work.", None,
     {"payload": {"stop_hook_active": False}, "expect": "advisory-or-block"}),
    # the guard runs ahead of the convergence floor too: on a re-entrant Stop the floor has already
    # been said once, and saying it again is the loop it exists to stop.
    ("30-stop-hook-active-true-with-floor", SPEC + "still working on it.",
     [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C],
     {"payload": {"stop_hook_active": True}, "expect": "silent"}),
]


def transcript(turns, name):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for t in turns:
            fh.write(json.dumps({"type": "assistant",
                                 "message": {"content": [{"type": "text", "text": t}]}}) + "\n")
    return p


def run(gate, name, lam, turns, extra=None):
    """-> (detail, conv, decision). `decision` is what the gate ANSWERED, read from the JSON shape
    itself and not from the message text: `{"decision":"block"}` is the enforce path, a
    `systemMessage`/`additionalContext` payload is the advisory path, no output at all is silent.

    `conv` separates CONV (the floor rode along on a reminder some other check raised) from CONV!
    (the floor IS the message). That distinction is not cosmetic: 0.18.0 shipped the floor as its
    own branch but `remind()` returns before it on every path where a declaration check already
    fired, so the floor was still being appended under the reminder it says to read INSTEAD of —
    a message that opens with "run the sweep + red-team" at the moment the method says to stop.
    Without this column `--compare` cannot see that fix at all."""
    payload = {"last_assistant_message": lam}
    if turns is not None:
        payload["transcript_path"] = transcript(turns, name)
    payload.update(extra or {})
    out = subprocess.run(["bash", gate], input=json.dumps(payload),
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return "SILENT", "-", "silent"
    try:
        d = json.loads(out)
        msg = d.get("systemMessage") or d.get("reason") or ""
    except Exception:
        return "UNPARSEABLE", "-", "unparseable"
    decision = "block" if d.get("decision") == "block" else "advisory"
    m = re.search(r"\((completion-review:[^)]+|convergence-floor-only)\)", msg)
    if "Convergence floor" not in msg:
        conv = "-"
    else:
        conv = "CONV!" if msg.lstrip().startswith("Convergence floor") else "CONV"
    return (m.group(1) if m else "NO-DETAIL"), conv, decision


def opts_of(case):
    return case[3] if len(case) > 3 else {}


def suite(gate):
    return [(c[0],) + run(gate, c[0], c[1], c[2], opts_of(c).get("payload")) for c in CASES]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", nargs="?", default=DEFAULT_GATE)
    ap.add_argument("--compare", metavar="OTHER_GATE",
                    help="a second gate script; fails if any observed cell differs")
    ap.add_argument("--expected", default="",
                    help="comma-separated case-name prefixes whose diff is INTENDED (declare them "
                         "before running the comparison, not after reading it)")
    a = ap.parse_args()

    expected = [s.strip() for s in a.expected.split(",") if s.strip()]
    rows = suite(a.gate)
    other = suite(a.compare) if a.compare else None
    failures = []
    for i, (name, detail, conv, decision) in enumerate(rows):
        flag = ""
        want = opts_of(CASES[i]).get("expect")
        if want and not (decision == want or
                         (want == "advisory-or-block" and decision in ("advisory", "block"))):
            failures.append("%s: want %s, got %s" % (name, want, decision))
            flag = "   <-- FAILS ASSERTION (want %s)" % want
        if other and other[i][1:] != (detail, conv, decision):
            tag = "EXPECTED-DIFF" if any(name.startswith(p) for p in expected) else "DIFFERS"
            flag += "   <-- %s: %s" % (tag, " ".join(other[i][1:]))
        print("%-32s %-46s %-5s %-9s%s" % (name, detail, conv, decision, flag))

    if other:
        diffs = [r[0] for r, o in zip(rows, other) if r[1:] != o[1:]]
        unexpected = [d for d in diffs if not any(d.startswith(p) for p in expected)]
        if diffs:
            print("\n%d branch(es) changed: %s" % (len(diffs), ", ".join(diffs)))
        if unexpected:
            print("REGRESSION: %d unexpected: %s" % (len(unexpected), ", ".join(unexpected)))
            return 1
        print("\nparity OK — %d branches, %d intended change(s), 0 unexpected (vs %s)"
              % (len(rows), len(diffs), a.compare))

    if failures:
        print("\nASSERTION FAILURES: %d\n  %s" % (len(failures), "\n  ".join(failures)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

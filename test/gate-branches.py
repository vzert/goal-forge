#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/gate-goal-close.sh.

There is no CI here — the plugin is a skill + hooks + docs. This is the mechanical half of the
acid-test in CLAUDE.md: it drives the Stop gate across every branch it can take, using synthetic
`last_assistant_message` payloads and, where a branch needs history, synthetic multi-turn
`transcript_path` JSONL files.

    python3 test/gate-branches.py                              # run against the repo's gate
    python3 test/gate-branches.py --compare <other-gate.sh>    # regression parity vs another copy
    GOAL_GATE_ENFORCE=1 python3 test/gate-branches.py ...      # same suite through the blocking path

The parity mode is the one that matters when editing the gate: copy the pre-edit script somewhere,
then `--compare` it. Exit code is non-zero if any detail code differs, so it works in a pipeline.

Columns: case | detail code the gate reported | CONV if the convergence floor fired.
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

# (name, last_assistant_message, transcript turns or None)
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
]


def transcript(turns, name):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for t in turns:
            fh.write(json.dumps({"type": "assistant",
                                 "message": {"content": [{"type": "text", "text": t}]}}) + "\n")
    return p


def run(gate, name, lam, turns):
    payload = {"last_assistant_message": lam}
    if turns is not None:
        payload["transcript_path"] = transcript(turns, name)
    out = subprocess.run(["bash", gate], input=json.dumps(payload),
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return "SILENT", "-"
    try:
        d = json.loads(out)
        msg = d.get("systemMessage") or d.get("reason") or ""
    except Exception:
        return "UNPARSEABLE", "-"
    m = re.search(r"\((completion-review:[^)]+)\)", msg)
    return (m.group(1) if m else "NO-DETAIL"), ("CONV" if "Convergence floor" in msg else "-")


def suite(gate):
    return [(n,) + run(gate, n, lam, turns) for n, lam, turns in CASES]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", nargs="?", default=DEFAULT_GATE)
    ap.add_argument("--compare", metavar="OTHER_GATE",
                    help="a second gate script; fails if any detail code differs")
    a = ap.parse_args()

    rows = suite(a.gate)
    other = suite(a.compare) if a.compare else None
    for i, (name, detail, conv) in enumerate(rows):
        flag = ""
        if other and other[i][1] != detail:
            flag = "   <-- DIFFERS: %s" % other[i][1]
        print("%-26s %-56s %s%s" % (name, detail, conv, flag))

    if other:
        diffs = [r[0] for r, o in zip(rows, other) if r[1] != o[1]]
        if diffs:
            print("\nREGRESSION: %d branch(es) changed: %s" % (len(diffs), ", ".join(diffs)))
            return 1
        print("\nparity OK — %d branches identical to %s" % (len(rows), a.compare))
    return 0


if __name__ == "__main__":
    sys.exit(main())

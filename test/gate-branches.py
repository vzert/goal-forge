#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/gate-goal-close.sh.

CI runs this on every push and PR (`.github/workflows/tests.yml`), on Ubuntu and macOS. It is the
mechanical half of the acid-test in CLAUDE.md — the other half, watching an agent actually obey the
rules, stays manual: it drives the Stop gate across every branch it can take, using synthetic
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

# The floor message's opening words, and the only string in this suite that must track the gate's
# own copy. It is Spanish because that message is (0.36.0 — see the branch's comment for why that is
# a decision and not an oversight); matching it is exact, not a heuristic, precisely because the
# message is a fixed string rather than a localized one. Reword the floor's opening and this moves.
FLOOR_OPENERS = ("Piso de convergencia",   # the shipped opening
                 "Convergence floor")      # pre-0.36.0, kept ONLY so --compare can see across the
                                           # rename: with a single opener, every floor case reports
                                           # conv="-" for the OLD gate and six branches read as
                                           # regressions that are really the classifier's own change.
                                           # This is not a second supported message; nothing emits it.

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
# Real ids can contain brackets (the 1M-context variants). See cases 31-33.
MODEL_BRACKET_ID = "[ADVERSARY-MODEL: Claude Opus 5 / claude-opus-5[1m]]"
MODEL_BRACKET_BOTH = "[ADVERSARY-MODEL: Claude Opus 5 [1M context] / claude-opus-5[1m]]"
MODEL_BRACKET_UNKNOWN = "[ADVERSARY-MODEL: Claude Opus 5 [1M context] / UNKNOWN]"
# A real id followed by a same-line citation. The path's own bracket is what a greedy capture
# mistakes for the id. See case 34.
MODEL_TRAILING_CITE = ("[ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5] "
                       "(see plugins/goalspec/hooks/gate-goal-close.sh[283] for the matcher)")
# Forms an agent plausibly writes when quoting the marker "verbatim" but not literally: markdown
# emphasis, or trailing prose with no bracket of its own (unlike MODEL_TRAILING_CITE above, whose
# own "]" is what makes the naive fix unsafe — see cases 35-38). All are DEGRADE-not-MATCH by
# design (2026-07-26): the anchor's false-negative direction is the safe one, so these stay pinned
# as advisory, not "fixed" to silent. See the case-34 comment and the code comment above the regex.
MODEL_BOLD = "**[ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5]**"
MODEL_TRAILING_PLAIN = "[ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5] (verified twice)"
MODEL_TRAILING_PERIOD = "[ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5]."
MODEL_CODE_SPAN = "`[ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5]`"
# Working forms found by the same sweep — pinned as positive controls so a future edit that
# tightens the pattern cannot silently start rejecting an ordinary quoted-bullet or indented reply.
MODEL_LIST_PREFIX = "- [ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5]"
MODEL_INDENTED = "    [ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5]"
# Reported cross-session (2026-09-14, real adversary output, not hypothetical): no "/" at all, and
# an independence caveat written INSIDE the brackets instead of the id field. Unlike cases 34-38
# (trailing content AFTER a well-formed marker), this marker's own inner grammar is broken — the
# id field the gate's regex expects was never there to anchor past. See agents/goal-adversary.md's
# negative example, added alongside this case.
MODEL_CAVEAT_IN_BRACKETS = ("[ADVERSARY-MODEL: claude-opus-5[1m] — Opus 5 (1M context). Aviso de "
    "independencia: el checkpoint pedía \"modelo distinto, Opus\" como adversario; yo soy Opus 5, "
    "así que si el ejecutor también fue Opus 5, la palanca de independencia por modelo NO se "
    "cumple — solo la de contexto fresco.]")

# (name, last_assistant_message, transcript turns or None[, opts])
# opts is an optional dict:
#   "payload" -> extra keys merged into the hook's stdin (e.g. {"stop_hook_active": True})
#   "expect"  -> the `decision` cell this case MUST produce, in BOTH modes. Cases that declare it
#                are asserted on every run, not only under --compare: a guard whose whole job is to
#                emit nothing needs a test that fails when it emits something, and parity-vs-a-copy
#                cannot express that (the copy is the thing being changed).
#   "conv"    -> the CONV cell this case MUST produce ("CONV!", "CONV", or "-"), asserted on every
#                run for the same reason. Added 0.43.0 after the external adversary broke the first
#                version of the streak-change cases: `expect` only pins `decision`, and the streak
#                change moves ONLY the CONV cell (16, 43 and 44 all answer `advisory` before and
#                after), so those cases asserted NOTHING on their own and were visible only as
#                `DIFFERS` under --compare against a pre-edit copy. A suite whose new behavior can
#                only be seen by diffing against a copy of the old script is not a negative control;
#                it is the same class of defect as a carrier sweep that reads one carrier.
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
    # A hold-only turn ends the run — ANY hold-only turn, since 0.43.0. This case is where the name
    # and the code finally agree: under 0.18.0-0.42.1 an EARLIER hold-only turn was skipped, so this
    # cell reported CONV! while its own name said "resets". The skip was a deliberate 0.18.0 trade
    # (two backends, one holding in a turn of its own, is one unconverged loop) and reversing it is
    # the 0.43.0 change — measured on five real transcripts before shipping: the peak count drops
    # 15 -> 10, 8 -> 4, 9 -> 9, and the floor still reaches 3 in every session where it reached it
    # under the old rule. Case 17 pins the half of the 0.18.0 concern that is NOT given up: a turn
    # quoting BOTH backends still does not reset.
    ("16-hold-resets", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B, V_HOLD, V_BREAK_C],
     {"conv": "-"}),
    # one turn quoting BOTH backends (subagent hold + external break) is ONE break round, and does
    # not reset the run — which is why the floor's wording says "no hold-ONLY turn between them"
    ("17-mixed-turn", SPEC + CR_ADV, [SPEC, V_BREAK_A, V_BREAK_B, V_HOLD + "\n" + V_BREAK_C],
     {"conv": "CONV!"}),
    # Was: "the floor must also reach the reminder a mid-loop agent actually sees (no
    # completion-review yet)". 0.36.0 INVERTED this cell to silent, deliberately — see the
    # parked-loop-silence case at the end of this list for the observed session behind it, and case
    # 41 for the turn shape that still speaks. `expect` is asserted on every run, not only under
    # --compare, because the parity copy this was flipped against is a one-time artifact.
    ("18-absent-with-3", SPEC + "still working on it.", [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C],
     {"expect": "silent"}),
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
    # Silent — but since 0.36.0 for a DIFFERENT reason, and the distinction matters: this shape (no
    # close attempted, no verdict in the turn) is now the parked-loop silence, not the re-entrant
    # guard, which no longer applies to the floor branch at all. Case 42 is the case that
    # discriminates the two. The cell is unchanged, which is why it needed a sibling and not an edit.
    ("30-stop-hook-active-true-with-floor", SPEC + "still working on it.",
     [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C],
     {"payload": {"stop_hook_active": True}, "expect": "silent"}),

    # --- bracketed model ids (0.19.1) ---
    # A real production id can contain brackets: `claude-opus-5[1m]` is the 1M-context variant, and
    # it was the executor's own id in the session that found this. The old `[^\]]*` capture stopped
    # at the FIRST "]", so the field the gate handed to has_real_id was truncated.
    # 31 is the realistic shape and is a CONTROL, not a regression test: pre-fix it passed by
    # accident (the truncated tail `claude-opus-5[1m` still carries a letter and a digit and no
    # whitespace), so it must stay passing — the fix must not turn an accidental pass into a fail.
    ("31-bracketed-id-only", SPEC + MODEL_BRACKET_ID + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None),
    # 32 is the one that discriminates. With brackets in the NAME field too, truncation cuts before
    # the "/", so rsplit("/") returns the whole name, whitespace fails has_real_id, and the gate
    # wrongly told a genuinely different-model close to degrade to model=same. `expect` is asserted
    # on every run, not only under --compare: this case fails against the pre-fix gate.
    ("32-bracketed-id-and-name", SPEC + MODEL_BRACKET_BOTH + "\n" + V_HOLD + "\n" + CR_ADV_DIFF,
     None, {"expect": "silent"}),
    # 33 pins that the fix does not LOOSEN the one assertion this check makes honestly: a fallback
    # self-report is still rejected when the name happens to carry brackets. Same cell before and
    # after — greedy capture must not turn "UNKNOWN" into a real id.
    ("33-bracketed-name-unknown-id", SPEC + MODEL_BRACKET_UNKNOWN + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None),
    # 34 came from an adversary breaking the FIRST attempt at 31-33. Going greedy to the last "]" on
    # the line accepted a garbage token sliced out of a trailing citation: cid="gate-goal-close.sh[283"
    # is whitespace-free with a letter and a digit, so has_real_id said True for the wrong reason —
    # failing open on the one assertion this check exists to make. Anchoring the marker to
    # end-of-line means anything appended after it matches nothing and the claim degrades to
    # model=same. `expect` is asserted every run: this case must never go silent.
    ("34-trailing-cite-after-marker",
     SPEC + MODEL_TRAILING_CITE + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "advisory-or-block"}),

    # --- marker-form sweep (2026-07-26) ---
    # Reported live: a session quoted its own [ADVERSARY-MODEL:] "verbatim" by wrapping it in
    # markdown bold, and a second form (trailing prose, no bracket of its own) does the same thing.
    # A fix removing the end-of-line anchor was proposed to recover both — MEASURED to also recover
    # case 34's citation-garbage id as a false "real" id (re.findall confirmed: cid becomes a
    # whitespace-free, letter+digit token sliced out of the citation). Rejected: the anchor's
    # failure direction is an honest degrade to model=same; the unanchored direction is a
    # fabricated proof of independence, and no formatting convenience buys back that asymmetry.
    # These four therefore pin the CURRENT, intentional behavior (degrade, not match) so a third
    # attempt at loosening the pattern has a red test instead of a silent regression.
    ("35-bold-wrapped-marker", SPEC + MODEL_BOLD + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "advisory-or-block"}),
    ("36-trailing-plain-text", SPEC + MODEL_TRAILING_PLAIN + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "advisory-or-block"}),
    ("37-trailing-period", SPEC + MODEL_TRAILING_PERIOD + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "advisory-or-block"}),
    ("38-inline-code-span", SPEC + MODEL_CODE_SPAN + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "advisory-or-block"}),
    # Positive controls from the same sweep: a leading list marker or indentation is NOT trailing
    # content, and must keep matching — a future tightening of the pattern (e.g. requiring the "["
    # to open the line) would silently break an ordinary quoted-bullet reply.
    ("39-list-prefixed-marker", SPEC + MODEL_LIST_PREFIX + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "silent"}),
    ("40-indented-marker", SPEC + MODEL_INDENTED + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "silent"}),
    # 45 pins the real incident, not a synthetic worst-case: no fix to has_real_id is expected here
    # (the comment above it already explains why loosening it is rejected) — this case exists so a
    # FUTURE "helpful" loosening (e.g. splitting on "—" or taking the first bracketed token) has a
    # red test to fail, instead of silently starting to accept a caveat-stuffed id as real.
    ("45-caveat-inside-brackets-no-slash",
     SPEC + MODEL_CAVEAT_IN_BRACKETS + "\n" + V_HOLD + "\n" + CR_ADV_DIFF, None,
     {"expect": "advisory-or-block"}),

    # --- parked-loop silence (0.36.0) ---
    # The other side of case 18. Same streak, same absent declaration — but THIS turn carries a
    # verdict of its own, so a round actually ran here: the floor is news and must still be said,
    # once. Case 18 is the turn that carries no verdict — the checkpoint, the report, the unrelated
    # request — in a session whose loop is parked, and it is the shape that made the floor repeat
    # on every remaining turn of a real session (2026-08-10), burying a checkpoint the human asked
    # for. 18 asserts the silence; this asserts the silence is not blanket.
    ("41-absent-with-3-lam-verdict", V_BREAK_C + "\nstill working on it.",
     [SPEC, V_BREAK_A, V_BREAK_B], {"expect": "advisory-or-block"}),
    # 42 came from adversary round 2 breaking the FIRST version of 41's silence, and it is the case
    # that discriminates the re-entrant guard from the parked-loop silence. Same announcing turn as
    # 41, but the Stop is ALSO re-entrant. Before the fix, step 0 swallowed this announcement and 18
    # then suppressed every later chance, so the human was never told the floor was reached at all —
    # a hole this release would have opened. The guard is about re-asking the MODEL, and the floor
    # branch no longer carries `additionalContext`, so it has nothing here to prevent. This must
    # never go silent: it fails against the first 0.36.0 draft.
    ("42-floor-announced-even-when-reentrant", V_BREAK_C + "\nstill working on it.",
     [SPEC, V_BREAK_A, V_BREAK_B],
     {"payload": {"stop_hook_active": True}, "expect": "advisory-or-block"}),

    # --- the counting WINDOW starts at the last goal-spec (0.43.0) ---
    # Why this exists: before 0.43.0 the walk could reach the first turn of the session, so a session
    # with two goal-spec cycles (a patch, then its release) carried the breaks of the first into the
    # second. Measured on a real transcript: a peak count of 15 in a session with 22 breaks, which is
    # not a streak of anything. These two cases are a matched pair — the first would report CONV!
    # without the window (four break turns in the file), the second must still report CONV! with it,
    # so a window that simply swallowed the count would fail the second.
    ("43-second-goal-spec-restarts-the-window", SPEC + CR_ADV,
     [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C, SPEC, V_BREAK_A], {"conv": "-"}),
    ("44-floor-still-fires-inside-the-second-cycle", SPEC + CR_ADV,
     [SPEC, V_BREAK_A, SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C], {"conv": "CONV!"}),
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
    if not any(o in msg for o in FLOOR_OPENERS):
        conv = "-"
    else:
        conv = "CONV!" if msg.lstrip().startswith(FLOOR_OPENERS) else "CONV"
    return (m.group(1) if m else "NO-DETAIL"), conv, decision


def opts_of(case):
    return case[3] if len(case) > 3 else {}


def suite(gate):
    return [(c[0],) + run(gate, c[0], c[1], c[2], opts_of(c).get("payload")) for c in CASES]


# --- staleness backstop (added alongside hooks/precheck-terminal-push.sh) -------------------------
# Separate from CASES/suite() above on purpose: those are pure-transcript, no filesystem, and stay
# that way so --compare keeps working against a bare copy of the gate with no git repo involved.
# The staleness check reads LIVE git state (hooks/lib/terminal_actions.py's commits_since()), so
# these cases each get their own synthetic repo with a commit stamped at a CONTROLLED committer
# date (GIT_COMMITTER_DATE) rather than real wall-clock time — real-time ordering flaked in manual
# testing (a `sleep 1` between a fixed transcript timestamp and a real `git commit` is exactly the
# kind of test that is fast except when it is not).
STALE_TMP = tempfile.mkdtemp(prefix="gate-branches-stale-")


def _sh(args, cwd, env=None):
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    assert out.returncode == 0, "fixture setup failed: %s\n%s" % (args, out.stderr)
    return out.stdout


def stale_repo(name, files_after_review, committer_date):
    """A repo with one pushed baseline commit, then ONE MORE commit — containing
    `files_after_review` — stamped at `committer_date` (ISO8601). That second commit is what
    commits_since(review_ts) must find when review_ts is BEFORE committer_date."""
    work = os.path.join(STALE_TMP, name, "work")
    bare = os.path.join(STALE_TMP, name, "bare.git")
    os.makedirs(work)
    _sh(["git", "init", "-q", "-b", "main", "."], work)
    _sh(["git", "config", "user.email", "t@t.com"], work)
    _sh(["git", "config", "user.name", "t"], work)
    _sh(["git", "init", "-q", "--bare", bare], STALE_TMP)
    _sh(["git", "remote", "add", "origin", bare], work)
    with open(os.path.join(work, "README.md"), "w") as fh:
        fh.write("init")
    _sh(["git", "add", "-A"], work)
    _sh(["git", "commit", "-qm", "pushed baseline"], work)
    _sh(["git", "push", "-q", "-u", "origin", "main"], work)
    for rel, content in files_after_review.items():
        p = os.path.join(work, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)
    _sh(["git", "add", "-A"], work)
    env = dict(os.environ, GIT_COMMITTER_DATE=committer_date, GIT_AUTHOR_DATE=committer_date)
    _sh(["git", "commit", "-qm", "after the review"], work, env=env)
    return work


def stale_transcript(events, name):
    """events: list of dicts {"timestamp": iso8601, "text": ...} and/or {"timestamp": iso8601,
    "bash": "command"} and/or {"timestamp": iso8601, "write": (file_path, content)} — same
    per-event shape terminal_actions.read_transcript_items() expects."""
    p = os.path.join(STALE_TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            content = []
            if "bash" in ev:
                content.append({"type": "tool_use", "name": "Bash", "input": {"command": ev["bash"]}})
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "name": "Write", "input": {"file_path": fp, "content": body}})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "timestamp": ev.get("timestamp"),
                                 "message": {"content": content}}) + "\n")
    return p


T0 = "2026-01-01T00:00:00Z"   # spec
T1 = "2026-01-01T00:05:00Z"   # completion-review declared here
T2 = "2026-01-02T00:00:00Z"   # committer date used for the post-review commit (well after T1)

STALE_CASES = [
    # code change after the review, current turn has no fresh CR -> STALE
    ("stale-01-code-after-review-STALE",
     lambda: stale_repo("s01", {"src/app.js": "code"}, T2),
     [{"timestamp": T0, "text": SPEC}, {"timestamp": T1, "text": CR_NONE},
      {"timestamp": T2, "bash": "git push origin main", "text": "pushed."}],
     "still working, no fresh review this turn"),
    # memory-only change after the review -> content-exempt, NOT stale
    ("stale-02-memory-only-after-review-NOT-STALE",
     lambda: stale_repo("s02", {"memory/session.md": "notes"}, T2),
     [{"timestamp": T0, "text": SPEC}, {"timestamp": T1, "text": CR_NONE},
      {"timestamp": T2, "bash": "git push origin main", "text": "checkpoint pushed."}],
     "still working, no fresh review this turn"),
    # a FRESH completion-review in the CURRENT turn -> never stale, regardless of what ran earlier
    ("stale-03-fresh-review-this-turn-NOT-STALE",
     lambda: stale_repo("s03", {"src/app.js": "code"}, T2),
     [{"timestamp": T0, "text": SPEC}, {"timestamp": T1, "text": CR_NONE},
      {"timestamp": T2, "bash": "git push origin main"}],
     V_HOLD + "\n" + CR_ADV),   # this IS the lam for the case below — see run_stale()
    # no terminal command at all after the review -> NOT stale
    ("stale-04-no-terminal-command-after-review-NOT-STALE",
     lambda: stale_repo("s04", {"src/app.js": "code"}, T2),
     [{"timestamp": T0, "text": SPEC}, {"timestamp": T1, "text": CR_NONE},
      {"timestamp": T2, "text": "just thinking out loud, no tool call here"}],
     "still working, no fresh review this turn"),
]


# --- primary goal-spec precondition, via a checkpoint-file Write instead of chat text --------------
# Regression pin for a break found by goal-adversary round 2 (2026-08-01), running against THIS
# diff's own real session: the session's `## Goal-spec` lived only inside a `Write` tool_use to
# `.goalspec/checkpoint.md` (SKILL.md step 5's own checkpoint pattern for long tasks), never as
# assistant text — and the gate's PRIMARY "did this session produce a goal-spec at all"
# precondition (not just the staleness check above) is a separate, older regex that only scans
# text. Against the real session it found nothing, so the ENTIRE gate went silent — not just the
# staleness branch. These cases pin the fix (an `ta.transcript_signals()` OR added ahead of that
# precondition) using a repo with no git history at all, since the precondition fires before any
# git command runs.
CHECKPOINT_GOALSPEC_CASES = [
    # spec ONLY in a checkpoint Write, no completion-review anywhere -> the gate must SPEAK
    # (completion-review:absent), not stay silent as it did before this fix.
    ("checkpoint-01-spec-via-write-no-review-SPEAKS",
     [{"write": (".goalspec/checkpoint.md", SPEC)}, {"text": "still working on it."}],
     "completion-review:absent"),
    # same, but with a valid completion-review declared as TEXT in a later turn -> silent (clean
    # close) — a regression control that the new OR does not false-positive on an ordinary clean
    # run. This does NOT by itself prove the checkpoint-file signal stays out of the
    # completion-review check (goal-adversary round 3 caught an earlier comment here overclaiming
    # exactly that: this case passes identically against a gate with no checkpoint-file signal at
    # all, so it cannot be evidence FOR that mechanism). Case 03 below is the one that actually
    # discriminates it.
    ("checkpoint-02-spec-via-write-then-valid-review-SILENT",
     [{"write": (".goalspec/checkpoint.md", SPEC)}, {"text": CR_NONE}],
     None),
    # THE discriminating case for "does a completion-review written to a file ever count": the
    # marker lives ONLY inside the checkpoint Write, never in chat text. It must SPEAK
    # (completion-review:absent), not go silent as a fabricated close would.
    # PRECISION, per goal-adversary round 4 (an earlier version of this comment overclaimed and
    # got caught, same defect class as checkpoint-02's original comment): this does NOT exercise
    # `ta.transcript_signals()` — gate-goal-close.sh's completion-review check never calls it. It
    # has its OWN inline scan (`cr_pat` over `tx_turns`, built from this file's own parsing loop,
    # which only extracts `type=="text"` blocks). This case guards THAT scan staying text-only —
    # confirmed by mutation: making `transcript_signals()` treat `goal_spec_file` content as
    # general text does NOT flip this case; editing gate-goal-close.sh's own tx_turns builder to
    # ingest tool_use content DOES. If a future edit ever makes the completion-review check read
    # from the shared module instead of its own scan, re-verify this case still discriminates.
    ("checkpoint-03-review-only-in-write-not-text-SPEAKS",
     [{"write": (".goalspec/checkpoint.md", SPEC + "\n" + CR_NONE)}, {"text": "still working."}],
     "completion-review:absent"),
    # The checkpoint is per-session since the concurrency fix (two concurrent sessions in one
    # project used to clobber the single fixed path). If this precondition had kept matching only
    # the old exact name, every session writing its spec to the new name would have reproduced the
    # ORIGINAL break this whole block was written for — the entire gate silent — with no test
    # noticing. This is the case that notices: it fails against a gate whose matcher is the
    # pre-fix `endswith(".goalspec/checkpoint.md")`.
    ("checkpoint-04-spec-via-session-scoped-write-SPEAKS",
     [{"write": (".goalspec/checkpoint-a1b2c3.md", SPEC)}, {"text": "still working on it."}],
     "completion-review:absent"),
    # ...and the narrowness control for that widening, the same defect class checkpoint-02 and the
    # precheck suite's case 22 guard: a Write to a file that merely LOOKS checkpoint-ish must not
    # be read as a goal-spec. Both of these carry a real `## Goal-spec` heading, so a matcher that
    # widened to "any path containing checkpoint" (or that dropped the end-of-string anchor) makes
    # this case SPEAK instead of staying silent.
    # Windows separator. The transcript on that platform records `...\\.goalspec\\checkpoint.md`,
    # which a POSIX-separator matcher never sees — the gate blind to a disk-written spec, exactly
    # the break checkpoint-01 exists for, just platform-shaped. Inherited from the `endswith` this
    # replaced (memory/_pendientes.md flagged it 2026-08-01) and fixed on the user's explicit call
    # during this change. Synthetic assertion only: no real Windows host has run this.
    ("checkpoint-06-windows-separator-path-SPEAKS",
     [{"write": ("C:\\proj\\.goalspec\\checkpoint-a1b2c3.md", SPEC)}, {"text": "still working."}],
     "completion-review:absent"),
    ("checkpoint-05-near-miss-paths-are-not-the-checkpoint-SILENT",
     [{"write": ("docs/checkpoint-notes.md", SPEC)},
      {"write": (".goalspec/checkpoint.md.bak", SPEC)},
      {"text": "still working on it."}],
     None),
    # CONFIRMED break (external adversary, GPT-5, 0.44.5 round 1): the general parked-turn silence
    # (see `general_silence` in gate-goal-close.sh) windows itself by finding a `## Goal-spec`
    # heading in TURN TEXT (`_gs_re` over `sig_turns`) — but a disk-only spec, like every case
    # above, never puts that heading in any turn's text (checkpoint-03's own comment: the
    # completion-review scan and this one are both text-only, on purpose). So `_sig_spec_at` stays
    # None here, and a first draft of the fix fell back to "start the window at turn 0" — which
    # let a genuinely PRE-checkpoint parked turn count as "the prior parked turn" and silence the
    # FIRST real post-checkpoint reminder. This case is that exact shape: a parked turn BEFORE the
    # checkpoint, then the checkpoint Write, then the first parked turn after it — which must
    # SPEAK, not go silent. The fix: when no text-based spec turn is found, general_silence is
    # unconditionally OFF (never silence), not "start at 0" — same fail-open, under-count-over-
    # over-count direction as the rest of this file.
    ("checkpoint-07-disk-only-spec-pre-existing-parked-turn-still-SPEAKS",
     [{"text": "an older parked turn, before the checkpoint even exists."},
      {"write": (".goalspec/checkpoint.md", SPEC)},
      {"text": "first parked turn after the disk-only spec."}],
     "completion-review:absent"),
]


def run_checkpoint_goalspec(gate, name, events):
    tx = stale_transcript(events, name)
    payload = {"last_assistant_message": events[-1].get("text", ""), "transcript_path": tx}
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=os.path.join(REPO, "plugins", "goalspec"))
    out = subprocess.run(["bash", gate], input=json.dumps(payload), capture_output=True, text=True,
                         env=env).stdout.strip()
    if not out:
        return "silent", None
    try:
        d = json.loads(out)
    except Exception:
        return "unparseable", None
    msg = d.get("systemMessage") or d.get("reason") or ""
    m = re.search(r"\((completion-review:[^)]+)\)", msg)
    return "spoke", (m.group(1) if m else "NO-DETAIL")


def checkpoint_goalspec_suite(gate):
    return [(name, run_checkpoint_goalspec(gate, name, events))
            for name, events, _ in CHECKPOINT_GOALSPEC_CASES]


# --- payload shape: who the floor talks to (0.36.0, amended 0.43.0) -------------------------------
# Structurally separate from CASES/suite() for the same reason the staleness cases are: this asks a
# question `run()` cannot express. `run()` collapses every non-block payload to "advisory", so the
# presence or absence of `hookSpecificOutput.additionalContext` — the field the harness feeds back to
# the model — is INVISIBLE to it and to `--compare`. That blindness is not hypothetical: the defect
# 0.36.0 fixed was reported by a user watching the agent answer the hook AFTER its own plain-language
# close, and every branch cell stayed identical through it. It is also why the 0.43.0 change below
# needed cases of its own rather than a `--compare` run.
#
# 0.43.0 changes WHAT this section pins, and the change is the reason the hook was touched at all.
# 0.36.0 shipped "at the floor, speak to the HUMAN and never to the model". Combined with the teeth
# branch being guarded `STREAK -lt 3`, that left the floor emitting nothing the agent can read and
# nothing that blocks, in EITHER mode — a check whose only consumer is a human who may not be
# present. Measured on an unattended field session (0.41.1): three streaks of 3, 5 and 3 breaks, the
# Stop hook running throughout, nothing stopped. So the floor now speaks to BOTH audiences, with two
# DIFFERENT strings, and the distinction is what these cases pin:
#   * `systemMessage` — the human line, unchanged, still one short Spanish sentence ending in "La
#     decisión es tuya". That clause is correct for the human and is an authorization to continue if
#     the model reads it, which is exactly the shape 0.18.0 measured RESUMING a loop the executor had
#     already stopped. So it must NEVER be the agent-facing string (asserted below).
#   * `hookSpecificOutput.additionalContext` — an agent-facing line whose only instruction is to stop
#     spending rounds and hand the decision to the human. Emitted ONLY on a non-re-entrant Stop, so
#     it is at most one re-ask per user prompt (the 0.18.1 bound), never the runaway.
#
# What these cannot prove: that the agent then OBEYS the line, or that the harness generates no
# follow-up turn. Both are behavior outside the hook and need live observation.
FLOOR_TX = [SPEC, V_BREAK_A, V_BREAK_B, V_BREAK_C]          # streak 3
BELOW_TX = [SPEC, V_BREAK_A, V_BREAK_B]                     # streak 2
PAYLOAD_SHAPE_CASES = [
    # (name, lam, turns, enforce, reentrant, want) — want: (has_system, has_agent_ctx, is_block)
    # At the floor, non-re-entrant: BOTH audiences, in both modes. This is the 0.43.0 change, and
    # these two cases are the ones that go red if it is reverted.
    ("floor-speaks-to-human-AND-agent", SPEC + CR_ADV, FLOOR_TX, False, False, (True, True, False)),
    ("floor-both-ENFORCE", SPEC + CR_ADV, FLOOR_TX, True, False, (True, True, False)),
    # At the floor, RE-ENTRANT: the human still gets the announcement (the hole 0.36.0's second
    # adversary round found), and the agent-facing half is withheld — the 0.18.1 one-re-ask bound.
    ("floor-reentrant-human-only", SPEC + CR_ADV, FLOOR_TX, False, True, (True, False, False)),
    # Below the floor nothing changes: the advisory still re-enters the turn (that is its consumer),
    # and the opt-in teeth still block. A fix that quietly muted these would be the real regression.
    ("below-floor-still-re-enters", SPEC + CR_ADV, BELOW_TX, False, False, (True, True, False)),
    ("below-floor-ENFORCE-still-blocks", SPEC + CR_ADV, BELOW_TX, True, False, (True, False, True)),
    # Below the floor and re-entrant: total silence, exactly as 0.18.1 shipped it.
    ("below-floor-reentrant-silent", SPEC + CR_ADV, BELOW_TX, False, True, (False, False, False)),
]
# The HUMAN line is one human-readable sentence. This ceiling is the mechanical half of that claim:
# the branch has now been rewritten four times and twice grew back into a wall of model-facing prose,
# so "keep it short" is pinned rather than trusted. It applies to `systemMessage` ONLY — the
# agent-facing line has a different job and its own assertions below.
FLOOR_MSG_MAX = 600
# The agent-facing floor line, pinned by content, not length. Three claims, each a real failure mode:
#   * it must forbid more rounds (that is its whole job);
#   * it must NOT contain the human line's closing clause, which reads as permission to continue;
#   * it must NOT name the waiver. That is the pointer 0.18.0 removed from this branch deliberately:
#     an over-counting floor is safe only while its message routes to "stop and hand back" instead of
#     to the waiver, since a false three-breaks then costs an unnecessary suggestion to stop rather
#     than a nudge toward closing over a break. The counter still over-counts on re-quotes, so the
#     property is live. The first version of this line named the waiver and this entry PINNED it —
#     the suite was asserting the defect. Found by review, not by a suite, which is why it is written
#     down here as a rule rather than left to the next reader of the 0.18.0 bullet.
FLOOR_AGENT_MUST = ["STOP running adversary rounds"]
FLOOR_AGENT_MUST_NOT = ["La decisión es tuya", "GOAL-CLOSE-WAIVED"]


def run_payload_shape(gate, name, lam, turns, enforce, reentrant=False):
    payload = {"last_assistant_message": lam, "transcript_path": transcript(turns, "shape-" + name)}
    if reentrant:
        payload["stop_hook_active"] = True
    env = dict(os.environ)
    env["GOAL_GATE_ENFORCE"] = "1" if enforce else ""
    out = subprocess.run(["bash", gate], input=json.dumps(payload), capture_output=True, text=True,
                         env=env).stdout.strip()
    if not out:
        return (False, False, False), 0, ""
    d = json.loads(out)
    msg = d.get("systemMessage") or d.get("reason") or ""
    ctx = d.get("hookSpecificOutput", {}).get("additionalContext") or ""
    return ((bool(d.get("systemMessage")), bool(ctx), d.get("decision") == "block"), len(msg), ctx)


def run_stale(gate, name, make_repo_fn, events, lam):
    cwd = make_repo_fn()
    tx = stale_transcript(events, name)
    payload = {"last_assistant_message": lam, "transcript_path": tx, "cwd": cwd}
    # CLAUDE_PLUGIN_ROOT must be set for the gate's own LIBDIR-based import of
    # hooks/lib/terminal_actions.py to resolve — without it, step 5b fails to import (silently,
    # by design: an unimportable shared module must never break the checks that came before it)
    # and every staleness case degrades to "silent", indistinguishable from "correctly not stale".
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=os.path.join(REPO, "plugins", "goalspec"))
    out = subprocess.run(["bash", gate], input=json.dumps(payload), capture_output=True, text=True,
                         env=env).stdout.strip()
    if not out:
        return "silent"
    try:
        d = json.loads(out)
    except Exception:
        return "unparseable"
    msg = d.get("systemMessage") or d.get("reason") or ""
    return "STALE" if "stale-terminal-action-after-close" in msg else ("silent" if not msg else "other:" + msg[:40])


def stale_suite(gate):
    return [(name, run_stale(gate, name, repo_fn, events, lam))
            for name, repo_fn, events, lam in STALE_CASES]


# --- audience split: every remind() branch, not just the floor (0.44.5) ----------------------------
# Pins the actual CONTENT split the floor already had and the other branches did not: `systemMessage`
# is a short Spanish sentence for the human, `hookSpecificOutput.additionalContext` (or, under
# ENFORCE, `reason`) is the technical English text the agent reads and acts on. `run()`/`suite()`
# above cannot see this at all — they only ever look at `systemMessage or reason` as ONE string to
# classify the branch, which is exactly why this needs its own section, the same reasoning the
# payload-shape section above already gives for the floor. Reuses run_payload_shape() rather than a
# new subprocess helper — it already extracts systemMessage/additionalContext/reason correctly and is
# tested by the floor cases above; only the assertions here are new.
AUDIENCE_SPLIT_CASES = [
    # (name, lam, turns, enforce, must_be_in_system, must_be_in_agent, unified)
    # unified=False (default, 0.44.5 shape): systemMessage (short, Spanish, human) MUST differ from
    # additionalContext/reason (technical, English, agent) — the original split assumption.
    # unified=True (0.44.8 pilot, two branches only): the split was retired for these — the official
    # hooks reference confirms additionalContext on a Stop hook is ALWAYS shown to the human as
    # "Stop hook feedback", so a separate technical string never hid anything; both fields now carry
    # the SAME short message, pointing at SKILL.md instead of re-deriving the full instruction here.
    # See memory/_pendientes.md p-a95b61154a for the finding this reverses.
    ("audience-absent-default", SPEC + "I did the work.", None, False,
     "Sigue sin haber un cierre formal", "no valid [COMPLETION-REVIEW] declared", False),
    ("audience-absent-ENFORCE", SPEC + "I did the work.", None, True,
     "Sigue sin haber un cierre formal", "no valid [COMPLETION-REVIEW] declared", False),
    ("audience-closed-over-break", SPEC + CR_ADV + V_BREAK_A, None, False,
     "Un revisor independiente marcó un problema sin resolver", "cannot close over it as-is", False),
    ("audience-model-diff-unknown-UNIFIED", SPEC + CR_ADV_DIFF + V_HOLD, None, False,
     "no se pudo confirmar por formato", "SKILL.md, «Completion-review declaration»", True),
]
# audience-stale-terminal-UNIFIED lives with the staleness backstop suite below (run_stale_audience),
# not here — the stale-terminal-action-after-close DETAIL only fires from the real git/transcript
# fixture stale_repo()/stale_transcript() build, not from a bare last_assistant_message string.


def run_audience_split(gate, name, lam, turns, enforce):
    payload = {"last_assistant_message": lam}
    if turns is not None:
        payload["transcript_path"] = transcript(turns, "aud-" + name)
    env = dict(os.environ)
    env["GOAL_GATE_ENFORCE"] = "1" if enforce else ""
    out = subprocess.run(["bash", gate], input=json.dumps(payload), capture_output=True, text=True,
                         env=env).stdout.strip()
    if not out:
        return "", ""
    d = json.loads(out)
    system = d.get("systemMessage") or ""
    agent = d.get("hookSpecificOutput", {}).get("additionalContext") or (d.get("reason") or "")
    return system, agent


def audience_split_suite(gate):
    return [(name,) + run_audience_split(gate, name, lam, turns, enforce)
            for name, lam, turns, enforce, _, _, _ in AUDIENCE_SPLIT_CASES]


# --- general parked-turn silence (0.44.5) -----------------------------------------------------------
# Extends, without touching, the floor's own silence (payload-shape section above) to every OTHER
# remind() branch: a turn that attempts nothing new (no completion-review, no fresh verdict) and
# whose immediately preceding turn ALSO attempted nothing new gets no reminder at all — the same
# unresolved state was already reported the first time it appeared. `turns` = history already
# flushed to the transcript file; `lam` = the current, not-yet-flushed turn — same convention
# run_payload_shape() already uses above.
SILENCE_CASES = [
    # First turn after the spec, nothing has been said yet -> SPEAKS. Regression control: the fix
    # for this exact case is what makes the general silence safe to ship at all (see the hook's own
    # comment by `_sig_spec_at` for why the window must skip the spec-announcement turn itself).
    ("silence-first-parked-after-spec-SPEAKS", "turn A, doing unrelated work.", [SPEC], "spoke"),
    # Second consecutive parked turn -> SILENT: nothing changed since the reminder already said this.
    ("silence-second-parked-SILENT", "turn B, still unrelated work.",
     [SPEC, "turn A, doing unrelated work."], "silent"),
    # Third consecutive parked turn -> still SILENT, not just the second.
    ("silence-third-parked-SILENT", "turn C, still unrelated work.",
     [SPEC, "turn A, doing unrelated work.", "turn B, still unrelated work."], "silent"),
    # A parked turn RIGHT AFTER an active one (a real, if malformed, completion-review attempt) ->
    # SPEAKS again: the active turn reset the run, this parked turn is news.
    ("silence-resets-after-active-turn-SPEAKS", "turn C, back to unrelated work.",
     [SPEC, "turn A, doing unrelated work.", CR_NONE_SHORT], "spoke"),
]


def run_silence(gate, name, lam, turns):
    payload = {"last_assistant_message": lam, "transcript_path": transcript(turns, "sil-" + name)}
    out = subprocess.run(["bash", gate], input=json.dumps(payload), capture_output=True, text=True,
                         env=os.environ).stdout.strip()
    return "silent" if not out else "spoke"


def silence_suite(gate):
    return [(name, run_silence(gate, name, lam, turns)) for name, lam, turns, _ in SILENCE_CASES]


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
        want_conv = opts_of(CASES[i]).get("conv")
        if want_conv and conv != want_conv:
            failures.append("%s: want CONV cell %s, got %s" % (name, want_conv, conv))
            flag += "   <-- FAILS ASSERTION (want conv %s)" % want_conv
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

    # Primary goal-spec precondition via checkpoint-file Write — no git repo needed, runs first.
    print("\n--- goal-spec precondition via .goalspec/checkpoint.md Write (not just chat text) ---")
    ckpt_failures = []
    for i, (name, decision) in enumerate(checkpoint_goalspec_suite(a.gate)):
        want_decision, want_detail = ("spoke", CHECKPOINT_GOALSPEC_CASES[i][2]) if CHECKPOINT_GOALSPEC_CASES[i][2] else ("silent", None)
        got_decision, got_detail = decision
        ok = got_decision == want_decision and (want_detail is None or got_detail == want_detail)
        if not ok:
            ckpt_failures.append("%s: want (%s,%s), got %s" % (name, want_decision, want_detail, decision))
        print("%-52s %-10s %-30s%s" % (name, got_decision, got_detail or "", "" if ok else "   <-- FAILS"))
    if ckpt_failures:
        print("\nCHECKPOINT-GOALSPEC FAILURES: %d\n  %s" % (len(ckpt_failures), "\n  ".join(ckpt_failures)))
        return 1

    # Payload shape — what the floor spends. Not part of --compare parity: the whole point is that
    # parity cannot see this field. Runs before the live-git section so it needs no repo.
    print("\n--- payload shape: who the floor talks to (0.36.0, amended 0.43.0) ---")
    shape_failures = []
    for name, lam, turns, enforce, reentrant, want in PAYLOAD_SHAPE_CASES:
        got, msglen, ctx = run_payload_shape(a.gate, name, lam, turns, enforce, reentrant)
        ok = got == want
        if not ok:
            shape_failures.append("%s: want %s, got %s" % (name, want, got))
        if name.startswith("floor-") and msglen > FLOOR_MSG_MAX:
            ok = False
            shape_failures.append("%s: floor message is %d chars, ceiling is %d — it grew back into "
                                  "a wall" % (name, msglen, FLOOR_MSG_MAX))
        # Content of the agent-facing line, wherever one was emitted at the floor.
        if name.startswith("floor-") and got[1]:
            for needle in FLOOR_AGENT_MUST:
                if needle not in ctx:
                    ok = False
                    shape_failures.append("%s: agent-facing floor line is missing %r" % (name, needle))
            for needle in FLOOR_AGENT_MUST_NOT:
                if needle in ctx:
                    ok = False
                    shape_failures.append("%s: agent-facing floor line contains %r — that clause is "
                                          "the human's, and to the model it reads as permission to "
                                          "continue" % (name, needle))
        print("%-38s sys=%-5s ctx=%-5s block=%-5s len=%-4d ctxlen=%-4d%s"
              % (name, got[0], got[1], got[2], msglen, len(ctx),
                 "" if ok else "   <-- FAILS (want %s)" % (want,)))
    if shape_failures:
        print("\nPAYLOAD-SHAPE FAILURES: %d\n  %s" % (len(shape_failures), "\n  ".join(shape_failures)))
        return 1

    # Staleness backstop — live-git cases, run against a.gate only (not part of --compare parity;
    # see the section header above for why they are structurally separate from CASES/suite()).
    print("\n--- staleness backstop (live git, hooks/lib/terminal_actions.py) ---")
    stale_failures = []
    for name, decision in stale_suite(a.gate):
        want = "silent" if "NOT-STALE" in name else "STALE"
        ok = decision == want
        if not ok:
            stale_failures.append("%s: want %s, got %s" % (name, want, decision))
        print("%-52s %-10s%s" % (name, decision, "" if ok else "   <-- FAILS (want %s)" % want))
    if stale_failures:
        print("\nSTALENESS FAILURES: %d\n  %s" % (len(stale_failures), "\n  ".join(stale_failures)))
        return 1

    # Audience split — every remind() branch, not just the floor (0.44.5).
    print("\n--- audience split: short Spanish systemMessage vs technical additionalContext/reason ---")
    audience_failures = []
    for i, (name, system, agent) in enumerate(audience_split_suite(a.gate)):
        _, _, _, _, want_system, want_agent, unified = AUDIENCE_SPLIT_CASES[i]
        same_check = (system == agent) if unified else (system != agent)
        ok = bool(want_system in system and want_agent in agent and same_check and system)
        if not ok:
            audience_failures.append("%s: system=%r agent=%r" % (name, system[:80], agent[:80]))
        print("%-38s sys=%-60s agentlen=%-4d%s"
              % (name, system[:60], len(agent), "" if ok else "   <-- FAILS"))

    # audience-stale-terminal-UNIFIED — reuses stale-01's own git/transcript fixture, the only way to
    # actually fire completion-review:stale-terminal-action-after-close (see comment above
    # AUDIENCE_SPLIT_CASES). 0.44.8: this branch is the other half of the pilot collapse; systemMessage
    # and additionalContext/reason must now be the SAME short, SKILL.md-pointing text.
    name, _, events, lam = STALE_CASES[0]
    assert name.startswith("stale-01"), "STALE_CASES[0] must stay stale-01 for this reuse to be valid"
    # Own repo dir ("aud-s01"), not stale_suite()'s "s01" — that one is already built by the time
    # this section runs (staleness backstop prints first), and stale_repo() doesn't tolerate a
    # pre-existing work dir.
    repo = stale_repo("aud-s01", {"src/app.js": "code"}, T2)
    tpath = stale_transcript(events, "aud-stale-01")
    payload = {"transcript_path": tpath, "cwd": repo, "last_assistant_message": lam}
    # CLAUDE_PLUGIN_ROOT required for the gate's terminal_actions.py import — see run_stale()'s own
    # comment above; without it step 5b silently no-ops and this always reads "silent".
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=os.path.join(REPO, "plugins", "goalspec"),
              GOAL_GATE_ENFORCE="")
    out = subprocess.run(["bash", a.gate], input=json.dumps(payload), capture_output=True,
                         text=True, env=env).stdout.strip()
    d = json.loads(out) if out else {}
    sys_msg = d.get("systemMessage") or ""
    agent_msg = d.get("hookSpecificOutput", {}).get("additionalContext") or (d.get("reason") or "")
    want = "ese cierre no cubre esta acción"
    ok = bool(want in sys_msg and sys_msg == agent_msg and sys_msg)
    print("%-38s sys=%-60s agentlen=%-4d%s"
          % ("audience-stale-terminal-UNIFIED", sys_msg[:60], len(agent_msg), "" if ok else "   <-- FAILS"))
    if not ok:
        audience_failures.append("audience-stale-terminal-UNIFIED: system=%r agent=%r"
                                 % (sys_msg[:80], agent_msg[:80]))

    if audience_failures:
        print("\nAUDIENCE-SPLIT FAILURES: %d\n  %s" % (len(audience_failures), "\n  ".join(audience_failures)))
        return 1

    # General parked-turn silence — every remind() branch below the floor (0.44.5).
    print("\n--- general parked-turn silence (streak < 3) ---")
    silence_failures = []
    for name, got in silence_suite(a.gate):
        want = dict((n, w) for n, _, _, w in SILENCE_CASES)[name]
        ok = got == want
        if not ok:
            silence_failures.append("%s: want %s, got %s" % (name, want, got))
        print("%-46s %-8s%s" % (name, got, "" if ok else "   <-- FAILS (want %s)" % want))
    if silence_failures:
        print("\nSILENCE FAILURES: %d\n  %s" % (len(silence_failures), "\n  ".join(silence_failures)))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

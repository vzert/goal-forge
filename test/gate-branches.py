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

    return 0


if __name__ == "__main__":
    sys.exit(main())

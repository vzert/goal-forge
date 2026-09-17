#!/usr/bin/env bash
# gate-goal-close.sh — Stop hook. Fail-open, transcript-anchored completion-review gate.
#
# Portable port of the validated fleet gate (gate-audit-close.sh), stripped of any control-plane
# coupling. The original anchored to a "PATCH status:done" API call and read the issue thread over
# a REST API. There is no control plane here, so the anchor is the TURN END (the Stop hook) and the
# source of truth is the SESSION TRANSCRIPT — evasion-resistant in the same spirit: it reads the
# assistant's actual emitted text, not a command string the agent could route around.
#
# Behavior:
#   * Only enforces when this session produced a `## Goal-spec` (the gate is not universal).
#   * If a goal-spec exists but no valid [COMPLETION-REVIEW: ...] was declared -> ADVISORY reminder,
#     the stop is allowed (fail-open). This is deliberate: you cannot gate your way out of
#     specification gaming; a fail-closed marker just relocates the gaming. See
#     references/outcome-loop-beats-gates.md.
#   * A `[COMPLETION-REVIEW: adversary ...]` closed over the operative `[ADVERSARY-VERDICT: break ...]`
#     (and `[COMPLETION-REVIEW: none ...]` closed while one sits unresolved in the transcript) is
#     rejected the same way a malformed declaration is. "Operative" = the SAME current-turn-preferred,
#     else-transcript precedence the completion-review match uses a few lines below — not a literal
#     chronological scan. This is an internal-consistency check (does your closure claim match your
#     own most-recently-declared verdict?), not an outcome check and not a truthfulness check — it
#     cannot catch a fabricated or misremembered self-report in the current turn any more than the
#     completion-review check can (you cannot gate your way out of specification gaming — see
#     references/outcome-loop-beats-gates.md); it catches the honest-but-mistaken close, same as the
#     model=different check below.
#   * Convergence FLOOR (advisory text; since 0.18.0 also its own branch, and never blocking):
#     SKILL.md's convergence guard
#     ("at three consecutive breaks, stop editing — the design is wrong, not the wording") was until
#     0.15.0 observed by nothing but the agent's memory. The gate now counts, and the claim it makes
#     is deliberately weak, and phrased to say exactly what the walk below checks and no more: "at
#     least N of your most recent verdict-carrying turns each contain a break, with no hold-only turn
#     between them" — a statement about turns, NOT a round count. That sentence became TRUE in 0.43.0
#     and was not before it: the walk used to SKIP an earlier hold-only turn, so a hold really could
#     sit inside the counted run. (An earlier wording said "no intervening hold", which the external
#     adversary broke on the mixed-turn case: a turn quoting BOTH backends, one holding and one
#     breaking, is a break round the walk still does not reset on — that half of the looseness is
#     deliberate and survives, which is why the word is hold-ONLY. Case 17 pins it.) It cannot be a round count: the
#     skill instructs the agent to quote every verdict verbatim in its own turn, so a multi-round loop
#     naturally re-quotes earlier rounds when summarizing, and a transcript-wide tally inflates in
#     exactly the scenario the guard exists for. So the count is damped: at most ONE round per
#     assistant turn, identical verdict sets de-duplicated within the trailing run (which under-counts
#     identical consecutive breaks — the fail-open direction), and the message tells the agent to
#     verify its real round count rather than asserting one. Consumer: the message branches below —
#     it adds no new marker and nothing else reads it. Like every other check here it is an
#     internal-consistency signal over the agent's own self-reports, not a lie detector.
#     0.18.0 changed three things about it, and the third is why the first two are safe:
#       (a) an earlier hold-only turn no longer extinguishes the run (only a hold in the most recent
#           verdict-carrying turn does) — running two backends, one holding in a turn of its own,
#           was measured silencing the counter in exactly the runs it exists for. REVERSED in 0.43.0
#           (see the window + hold-reset comments at the walk itself): the skip had turned the count
#           into a session-wide tally of every distinct break turn — a measured peak of 15 in a
#           session with 22 breaks — and re-measuring the honest rule on five real transcripts showed
#           the floor still reaches 3 in every session where it reached it under the skip. The
#           mixed-turn half of the 0.18.0 concern is kept, not given up;
#       (b) it can now fire on its own branch, so a non-converging run whose declaration happens to
#           pass every check is no longer met with silence;
#       (c) it never blocks, and its message routes to "stop and hand back to the human" instead of
#           to the waiver. The original damping rationale — "a false three-breaks would push toward a
#           premature waiver, worse than not counting" — is retired with (c): over-counting now costs
#           an unnecessary suggestion to stop and ask, which is cheap, so (a) and (b) trade in the
#           direction the old rationale forbade only because the old message pointed somewhere worse.
#     0.36.0 changed WHO it talks to and how often, which is the first change to this branch that is
#     not a rewording of it: at the floor the payload became `systemMessage` ONLY (one line, to the
#     human) with NO `additionalContext`, and it stays entirely silent on a turn that neither
#     attempted a close nor carried a verdict of its own (a checkpoint, a report, unrelated work in a
#     session whose loop is parked). Both came from observed sessions, not from theory.
#     0.43.0 keeps the second and AMENDS the first, because the first left the floor with no consumer
#     on the agent side in EITHER mode (the teeth branch below is guarded `STREAK -lt 3`): measured on
#     an unattended field session running 0.41.1, three streaks of 3, 5 and 3 breaks with the Stop
#     hook running throughout and nothing stopped, because the only audience was a human who was not
#     reading. The floor now emits TWO DIFFERENT strings — the same human line as `systemMessage`, and
#     a separate agent-facing line as `additionalContext` whose only instruction is to stop spending
#     rounds — and the agent-facing half is withheld on a re-entrant Stop, so the 0.18.1 one-re-ask
#     bound is intact. What 0.36.0 measured (the floor RESUMING a loop the executor had stopped) was a
#     property of the COPY it sent the model, not of the channel: the human line ends in "the decision
#     is yours", which to a model is permission to continue. That string is now never the agent-facing
#     one, and the suite asserts it cannot become it.
#   * Opt-in teeth: GOAL_GATE_ENFORCE=1 turns the advisory into a block. Since 0.18.1 that means
#     AT MOST ONE block per user prompt, not "may not stop until the declaration is complete":
#     the re-entrant guard at step 0 runs ahead of this branch, so the Stop that follows a block
#     passes. Unbounded teeth were never the design; they were the runaway, and re-asking your own
#     output until the harness cuts you off is not enforcement.
#     0.19.0 measured what that left and states it without the adjective: BOTH branches send the
#     same $MSG and BOTH re-enter the turn once per prompt (the default via additionalContext) —
#     true everywhere EXCEPT the convergence floor since 0.36.0, where neither branch re-enters and
#     both emit the same human-facing line, so
#     "one hard interruption that costs the agent a turn and cannot be ignored" — the wording here
#     until 0.19.0 — described the default equally well and was not a description of the teeth.
#     The whole measured delta is preventedContinuation:true instead of false, plus a systemMessage
#     field the block payload used to omit and now sets. ENFORCE=1 is CONTAINMENT of a promise this
#     harness cannot keep, not the answer to what teeth should be; the non-re-entrant shape
#     (`continue:false`) is named, unshipped, and gated behind a written evidence bar. See the
#     teeth branch near the end of this file and CHANGELOG 0.19.0.
#   * Explicit close-over-break escape, usable by you (the agent) or a human operator alike —
#     it is not gated to either: [GOAL-CLOSE-WAIVED reason=<>=20 chars>] anywhere in the turn. Use it
#     when you've judged a residual break non-actionable and are stuck (e.g. the three-consecutive-
#     breaks convergence limit) rather than reformulating the completion-review to paper over it —
#     the waiver is greppable and honest; a disguised close is neither.
#   * Re-entrant Stop -> silence (0.18.1). If `stop_hook_active` is true, this hook says nothing at
#     all, in either mode. See step 0 for the measurement behind it.
#   * Any parse error / missing input -> exit 0 (fail-open). Read the scope of that promise exactly:
#     it is about the EXIT CODE, and about the DEFAULT advisory mode, which never emits
#     `decision:block`. "Never blocks" is NOT "never re-enters the turn", and until 0.18.1 this
#     header traded on the two being the same thing. Measured: the advisory payload carries
#     `hookSpecificOutput.additionalContext`, which the harness feeds back into the model — the
#     stop is not prevented, and the model is asked again anyway. That is the intended mechanism
#     (the reminder has an agent-facing consumer; a `systemMessage` the agent never sees could not
#     do the job), and it is safe only because step 0 bounds it: one re-ask per turn, then silence.
#     Unbounded, it was the runaway. The convergence floor is the branch with its own rule (0.36.0,
#     amended 0.43.0): it never sends the model the HUMAN line — re-entering with that line cost the
#     human the report the agent had just written, and its closing clause reads as permission to
#     continue — but since 0.43.0 it does send the model a DIFFERENT line, whose only instruction is
#     to stop spending rounds, and only on a non-re-entrant Stop. Floor -> human line always, agent
#     line once per prompt. 0.36.0's "no agent-facing field at all" is what left this check with no
#     consumer on the agent side in either mode, which is the defect 0.43.0 closes. A
#     transcript_path that cannot be opened or parsed is swallowed and the checks proceed on
#     last_assistant_message alone — so under the opt-in GOAL_GATE_ENFORCE=1 an unreadable transcript
#     can still end in a `block`. That is what opting into teeth means, not a fail-open violation
#     (an external adversary read the looser wording as a contradiction; the behavior is unchanged
#     since the first release and identical with the transcript readable or not).
#
# Registered as a Stop hook by hooks/hooks.json.

INPUT=$(cat)

# Portable interpreter: python3 on macOS/Linux, python on Windows (Git Bash + python.org). python3 is
# resolved first, so Mac/Linux never fall back to a possible python2; if neither exists the invocation
# just fails and the hook degrades fail-open (empty RESULT -> exit 0).
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

# Everything lives in python. Fail-open on any exception.
RESULT=$(ENFORCE="${GOAL_GATE_ENFORCE:-}" printf '%s' "$INPUT" | LIBDIR="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib" "$PY" -c '
import json, sys, os, re

# Shared terminal-action detection (hooks/lib/terminal_actions.py) — used below for the staleness
# backstop only (step 5b). Absent/unimportable -> ta stays None and step 5b silently no-ops; every
# check ABOVE and BELOW it in this file is unaffected, by construction (ta is referenced nowhere
# else).
_libdir = os.environ.get("LIBDIR", "")
if _libdir and _libdir not in sys.path:
    sys.path.insert(0, _libdir)
try:
    import terminal_actions as ta
except Exception:
    ta = None

def fail_open():
    print("OK"); sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    fail_open()

# 0. Re-entrant Stop: say nothing. This runs AHEAD of every branch, teeth included — see the
#    header. `stop_hook_active` is the harness telling the hook "the turn you are about to inspect
#    exists BECAUSE a Stop hook spoke last time". Measured on this harness, not assumed: `false` on
#    a first Stop, `true` on the next one — and true even when the continuation came from a purely
#    advisory payload with no `decision:block` anywhere, which is the case that matters, because
#    the worst recorded runaway contained 31 Stop records, all preventedContinuation:false, and not
#    one block. Re-asking here is how one reminder became nine, twice, until the consecutive-stop
#    cap of the harness ended it. The reminder has already been delivered and read; repeating it
#    to a turn that was produced BY it is the loop, not the message.
#    Scope, also measured: the flag resets per USER PROMPT, not per session — two separate probe
#    chains each recorded false on the first Stop and true on the next, under two different
#    prompt_id values. So this is one re-ask per prompt, then silence; the next thing the user says
#    re-arms it. A guard that fired once per session would be a different and much worse trade.
#
#    0.36.0 narrows it to what it is actually for. Every word above is about RE-ASKING: the guard
#    exists because the advisory payload carries `additionalContext`, the harness feeds that back to
#    the model, and asking again the turn that your own asking produced is the runaway. The floor
#    branch carries that field only on a NON-re-entrant Stop (0.43.0; between 0.36.0 and 0.42.1 it
#    carried none at all), so applying the guard HERE would swallow the human announcement to prevent
#    a re-ask the floor branch already prevents by itself, while it
#    still costs something real: the SECOND adversary round on this release constructed the case
#    where the Stop that first reaches the floor is itself re-entrant, the guard swallows the
#    announcement, and the new parked-loop silence below then suppresses every later chance to say
#    it, so the human is never told at all. That is a hole this release would have OPENED. So the
#    guard is deferred rather than applied here: the pipeline runs, and the silence is applied at
#    the payload, to every branch EXCEPT the floor. Nothing about the re-ask bound changes — the
#    branches that re-enter the turn are silenced on a re-entrant Stop exactly as before.
reentrant = bool(data.get("stop_hook_active"))

# 1. Gather the assistant text for this turn.
#    Prefer last_assistant_message (current turn, never lags). Best-effort append the transcript.
lam = data.get("last_assistant_message")
lam_text = lam if isinstance(lam, str) else ""

#    tx_turns holds ONE entry per assistant turn (its text blocks joined) — the unit the convergence
#    floor counts in. tx_text is derived from it and is byte-identical to the flat block join it
#    replaced, so every pre-existing check sees exactly the same string it saw before.
tx_turns = []
tpath = data.get("transcript_path")
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
                blocks = []
                if isinstance(content, str):
                    blocks.append(content)
                elif isinstance(content, list):
                    for blk in content:
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            blocks.append(blk.get("text") or "")
                if blocks:
                    tx_turns.append("\n".join(blocks))
    except Exception:
        pass

tx_text = "\n".join(tx_turns)
# Full text for order-independent checks (goal-spec presence, waiver, ADVERSARY-MODEL reports).
text = lam_text + "\n" + tx_text
if not text.strip():
    fail_open()

# 2. Nothing to enforce unless this session produced a goal-spec — checked two ways, not one.
# The plain-text regex is the original check. It is BLIND to a spec written to disk instead of
# posted as chat text — confirmed live (goal-adversary round 2, 2026-08-01) against THIS diff own
# session: the goal-spec here was written via `Write` to `.goalspec/checkpoint.md` (the checkpoint
# pattern SKILL.md step 5 itself recommends for long tasks), never as assistant text, so this
# regex alone finds nothing and the ENTIRE gate goes silent for the whole session, not just the
# staleness check added below. `ta.transcript_signals()` (hooks/lib/terminal_actions.py) already
# carries the narrowly-scoped fix for this (a Write/Edit whose file_path ends in
# .goalspec/checkpoint.md or the per-session .goalspec/checkpoint-<token>.md, and ONLY those — see
# that module docstring for why a broader scope is a
# worse bug than the one it fixes: SKILL.md and CHANGELOG.md are themselves full of literal
# example marker text).
# `ta` may be None (import failed) — the OR degrades to the original text-only check, unchanged
# behavior, never a regression from this line.
_goal_spec_present = bool(re.search(r"(^|\n)#{1,6}\s*Goal-spec\b", text, re.I))
if ta is not None and not _goal_spec_present:
    try:
        _goal_spec_present = ta.transcript_signals(tpath).get("goal_spec", False)
    except Exception:
        pass
if not _goal_spec_present:
    fail_open()

# 3. Explicit close-over-break waiver (agent- or human-usable — see header).
if re.search(r"\[GOAL-CLOSE-WAIVED\s+reason=[^\]]{20,}\]", text, re.I):
    fail_open()

# 4. Verdict state: the operative verdict (drives the checks below) and the convergence floor
#    (advisory text only). Computed BEFORE the completion-review branch so every reminder can carry
#    the floor — including "absent", which is the state a mid-loop agent is actually in.
#
# Hardened verdict match, reused from the anti-echo pattern already in external-adversary.sh: require the
# FULL structured grammar (break|hold followed by all five numeric fields), not a bare "break" —
# free prose ("cerrado en break parcial", "verdict final registrado=break") and the literal
# grammar placeholder ("break|hold") both defeat a loose match. SAME current-turn-preferred,
# else-transcript precedence as the completion-review match directly above — NOT a last-match
# scan over the concatenated `text`: lam_text (current turn) is prepended before tx_text
# (historical transcript, chronological), so a naive scan over `text` treats ANY older verdict
# still sitting in tx_text as more recent than a live one in lam_text — e.g. a `hold` from an
# earlier round would outrank the current turn `break`, defeating the whole check in exactly the
# multi-round convergence case it exists to catch. Search lam_text first; fall back to tx_text
# (last match there = most recent, since tx_text is chronologically ordered) only if lam_text has
# no structured verdict at all.
verdict_re = (r"\[ADVERSARY-VERDICT:\s*(break|hold)\s+ungrounded=\d+\s+unfalsified=\d+\s+"
              r"incomplete=\d+\s+autonomy-violations=\d+\s+unsafe=\d+\s*\]")
# Moved up from step 5 (was defined right before its first use) so the general parked-turn silence
# below can use it too, without duplicating the grammar. No behavior change — same string, same use
# at step 5 (`lam_crs = re.findall(cr_pat, lam_text, re.I)`).
cr_pat = r"\[COMPLETION-REVIEW:\s*(adversary|none)\b([^\]]*)\]"
lam_verdicts = re.findall(verdict_re, lam_text, re.I)
tx_verdicts = re.findall(verdict_re, tx_text, re.I)
verdicts = lam_verdicts or tx_verdicts
last_verdict = verdicts[-1].lower() if verdicts else None

# Convergence floor — see the header for why this counts text occurrences, not rounds, and why it is
# damped toward under-counting. Note this walks the TURN sequence in chronological order and stops at
# the first non-break turn; it is deliberately NOT the lam-first/tx-fallback precedence above, which
# answers a different question (which verdict is operative *now*).
def turn_verdicts(t):
    return [(m.group(1).lower(), re.sub(r"\s+", " ", m.group(0)).lower())
            for m in re.finditer(verdict_re, t, re.I)]

turns = list(tx_turns)
lam_v = turn_verdicts(lam_text)
if lam_v:
    # The current turn may or may not already be flushed to the transcript file (lam never lags; the
    # file can). If the last recorded turn already carries the verdict of this turn, it IS this turn —
    # appending it again would count one round twice.
    tail = re.sub(r"\s+", " ", tx_turns[-1]).lower() if tx_turns else ""
    if lam_v[-1][1] not in tail:
        turns.append(lam_text)

# 0.43.0 — the window. Until now the walk below could reach the FIRST turn of the session, so a
# session with two goal-spec cycles (a patch, then its release) carried the breaks of the first cycle into
# the second. Measured on five real local transcripts: a peak count of 15 in a session with 22
# breaks, which is not a streak of anything. The window now starts at the LAST turn that wrote a
# `## Goal-spec` — the same marker step 2 above uses as the own precondition of the gate, so no new
# vocabulary. A session with one spec is unaffected (the window is the whole session).
_gs_re = re.compile(r"(^|\n)#{1,6}\s*Goal-spec\b", re.I)
_cycle_start = 0
for _i, _t in enumerate(turns):
    if _gs_re.search(_t):
        _cycle_start = _i
turns = turns[_cycle_start:]

# General "parked-turn" silence (0.44.5) — extends, without touching, the pattern the floor already
# uses below: "if this turn contributes nothing, the same was already true at the previous turn, and
# it was already said then." A signal = a quoted verdict OR a completion-review attempt (even a
# malformed one — trying to close is always news).
def turn_has_signal(t):
    return bool(turn_verdicts(t)) or bool(re.search(cr_pat, t, re.I))

# Build the turn sequence with the current one always represented exactly once at the tail. This is
# a DIFFERENT dedup than the verdict-only append above (turns/lam_v): that one only needs to decide
# whether to append lam when it carries a fresh VERDICT, and a substring-containment check on the
# short verdict text is enough. Here lam may carry no signal at all (the common "parked" case this
# silence exists for), so there is no signal substring to test containment of — the question is
# whether lam_text itself is ALREADY the flushed tail of tx_turns (no lag) or genuinely new (file
# lagging behind). Full-turn equality (not containment) answers that directly and generally, signal
# or not. A false "new" classification on a verbatim-repeated turn just makes both neighbours parked
# either way, which does not change the silence outcome — so this is safe even on the coincidence.
lam_has_signal = turn_has_signal(lam_text)
_lam_norm_full = re.sub(r"\s+", " ", lam_text).strip().lower()
_tail_norm_full = re.sub(r"\s+", " ", tx_turns[-1]).strip().lower() if tx_turns else ""
sig_turns = list(tx_turns)
if not (tx_turns and _lam_norm_full and _lam_norm_full == _tail_norm_full):
    sig_turns.append(lam_text)

# Unlike the OTHER window (_cycle_start above, for `turns`), this one starts AFTER the goal-spec
# turn, not AT it: the spec-announcement turn itself never carries a verdict or a completion-review
# either, so counting it as "the prior parked turn" would silence the very FIRST reminder of every
# session — the opposite of what this exists to fix. When the spec was found in TEXT, skip past it.
_sig_spec_at = None
for _i, _t in enumerate(sig_turns):
    if _gs_re.search(_t):
        _sig_spec_at = _i

# CONFIRMED break (external adversary, GPT-5, 0.44.5 round 1): when the spec was NOT found in text
# (it lives only in a checkpoint-file Write — CHECKPOINT_GOALSPEC_CASES, and the goal_spec_file
# detection in ta.transcript_signals, which this text-only _gs_re scan cannot see), _sig_spec_at
# stays None. The first draft of this branch then fell back to "start at 0, same as before this
# branch existed" -- safe for turns/streak (an over/under-count, advisory only) but NOT safe here: a
# genuinely PRE-cycle parked turn (before the checkpoint was ever written) got treated as the prior
# parked turn, silencing the first real post-checkpoint reminder. Confirmed live: a scratch
# transcript with an older parked turn, then a checkpoint Write, then the first parked turn produced
# no hook output at all. So: no text-based spec turn found -> we cannot safely establish where the
# cycle starts -> general_silence stays OFF entirely (never silence), the same fail-open,
# under-count-over-over-count direction this file already takes everywhere else (see the floor own
# streak comments below). This costs de-dup value only in the disk-only-spec case; the common case
# (the spec posted as chat text, the primary path SKILL.md describes) is unaffected.
sig_turns = sig_turns[(_sig_spec_at + 1):] if _sig_spec_at is not None else []

# Silence fires ONLY when: a text-based goal-spec turn was actually found (see above), this turn
# carries no signal, there was a prior turn in this cycle (sig_turns holds at least the current turn
# plus one before it), and that prior turn ALSO carried no signal. The first parked turn after an
# active one (or the first turn of the cycle -- nothing before it) is always said; only the
# consecutive repeats go quiet. Deliberately scoped to streak < 3 -- streak >= 3 is the floor own
# territory, with its own already-correct silence below, which this must not duplicate or interact
# with.
general_silence = (
    _sig_spec_at is not None
    and (not lam_has_signal)
    and len(sig_turns) >= 2
    and (not turn_has_signal(sig_turns[-2]))
)

streak = 0
counted = set()
for t in reversed(turns):
    vs = turn_verdicts(t)
    if not vs:
        continue          # a turn with no verdict neither counts nor interrupts the run
    if not any(c == "break" for c, _ in vs):
        # 0.43.0 — ANY hold-only turn ends the run, not only the most recent one. This REVERSES a
        # deliberate 0.18.0 decision, so the reversal carries its own measurement: 0.18.0 skipped an
        # earlier hold-only turn because running two backends (one holding in a turn of its own while
        # the other keeps breaking) was measured silencing the counter in the very runs the floor
        # exists for. That hazard is real and is NOT gone. What changed is that the old rule made the
        # count a session-wide tally of every distinct break turn (see the window above), and the
        # claim stated in the header of this file — "no hold-only turn between them" — was then a statement the code did
        # not check. Re-measured on the same five transcripts before shipping this: the peak count
        # drops 15 -> 10, 8 -> 4, 9 -> 9, and the floor still reaches 3 in every session it reached
        # it under the old rule, and stays silent in both sessions where it was silent. So the
        # honest rule costs no firing on this corpus. The under-count direction remains the safe one
        # (it advises less, never more).
        break
    # A turn quoting BOTH backends (e.g. subagent hold + external break) is ONE break round.
    key = tuple(sorted(s for _, s in vs))
    if key in counted:
        continue          # verbatim re-quote of a round already counted — do not double-count
    counted.add(key)
    streak += 1

def remind(detail, skip_general_silence=False):
    # The deferred re-entrant guard (step 0). Below the floor every payload carries
    # `additionalContext` and would re-ask the turn that the last one produced — silence, exactly as
    # 0.18.1 shipped it. At or above the floor the pipeline is allowed to proceed even when
    # re-entrant, because swallowing it here can cost the human the one announcement they get; the
    # floor branch itself then withholds its agent-facing half on a re-entrant Stop (0.43.0), so the
    # one-re-ask-per-prompt bound is enforced there instead of here, not dropped.
    if reentrant and streak < 3:
        fail_open()
    # General parked-turn silence (0.44.5, streak < 3 only — see general_silence above).
    # skip_general_silence=True is for the staleness backstop (step 5b) ONLY: that check has its own
    # condition (a terminal action ran after the operative close) that does not become less true
    # because a later turn also failed to re-declare — treating it as a "repeat with nothing new" is
    # exactly backwards for a safety backstop whose whole job is to catch something an earlier Stop
    # may have been silent about for other reasons (it is evaluated fresh from git log each time,
    # not from what this hook said before). Pinned by test/gate-branches.py case stale-01.
    if streak < 3 and general_silence and not skip_general_silence:
        fail_open()
    # Third field (0.36.0): does the CURRENT turn carry a structured verdict at all? The floor
    # branch below uses it to tell "this turn ran a round of the loop" apart from "this turn did
    # something else entirely while the loop sits parked" — see the parked-loop silence there.
    # Fifth field (0.43.0): the re-entrancy flag, which until now was consumed entirely inside this
    # python (the deferred guard just above). The floor branch needs it on the BASH side too, to
    # decide whether the agent-facing half of its payload is emitted at all — see that branch.
    print("REMIND|%s|%d|%d|%d" % (detail, streak, 1 if lam_verdicts else 0, 1 if reentrant else 0)); sys.exit(0)

# 5. Validate the completion-review declaration.
# Operative completion-review = the current-turn declaration if present (last_assistant_message is
# the reliable current-turn source), else the MOST RECENT one in the transcript. Anchoring on the
# *last* declaration — never the first re.search match — is what prevents an earlier exploratory or
# malformed [COMPLETION-REVIEW] from permanently poisoning the check after a correct one is emitted.
# (cr_pat itself is now defined near verdict_re, above — reused by the general parked-turn silence.)
lam_crs = re.findall(cr_pat, lam_text, re.I)
crs = lam_crs or re.findall(cr_pat, tx_text, re.I)
if not crs:
    remind("completion-review:absent")
mode, body = crs[-1]
mode = mode.lower()

if mode == "adversary":
    if not re.search(r"\[ADVERSARY-VERDICT:", text, re.I):
        remind("completion-review:adversary-claimed-but-no-verdict")
    if last_verdict == "break":
        remind("completion-review:closed-over-break")
    # model=different asserts the adversary verified you on a DIFFERENT model; its only ground-truth is
    # the adversary own [ADVERSARY-MODEL:] self-report. We deliberately DO NOT parse the claimed id and
    # re-match it against the self-report: five adversarial rounds (a fresh-context subagent + an external
    # codex on a different vendor) proved that free-text id-matching from an agent-authored transcript is
    # a bottomless proxy — substring collisions ("o3" in "gpt-4o-3-turbo-preview"), sentinel leaks, prose
    # harvesting ("UNKNOWN / requested gpt-5 unavailable"), version dots, and stale cross-run reports each
    # defeated a successively cleverer matcher. You cannot gate your way out of specification gaming
    # (references/outcome-loop-beats-gates.md), so the check is reduced to the one assertion it can make
    # honestly: a model=different claim requires at least one self-report naming a REAL, non-UNKNOWN model
    # id. The canonical id is taken POSITIONALLY — the single token after the last "/" (grammar is
    # "<name> / <exact id, or UNKNOWN>"), well-formed = one whitespace-free token carrying a letter, not
    # the "unknown" sentinel — so a fallback field ("UNKNOWN", "UNKNOWN / requested gpt-5 unavailable")
    # yields no id. If EVERY [ADVERSARY-MODEL:] is UNKNOWN/absent (the harness silently fell back to
    # same-model — the exact honest mistake this guards), model=different is unsupported and must degrade
    # to model=same. Id-precision and cross-run provenance are NOT gated: that is the outcome loop job.
    if re.search(r"model=different\b", body, re.I):
        def has_real_id(field):
            cid = field.rsplit("/", 1)[-1].strip().lower()
            # A real model id: one whitespace-free token, not the "unknown" sentinel, carrying a letter
            # AND a digit/hyphen/dot (a version marker). That last clause keeps every real id
            # (claude-sonnet-5, o3, gpt-4o, gpt-5.1) while rejecting a bare word ("apology", "different")
            # an executor could type to fake a self-report — without re-entering the id-*matching* proxy.
            return (len(cid) >= 2 and not re.search(r"\s", cid) and cid != "unknown"
                    and bool(re.search(r"[a-z]", cid)) and bool(re.search(r"[0-9.-]", cid)))
        # The marker must END ITS LINE. A real production id can contain brackets --
        # claude-opus-5[1m], the 1M-context variant -- and the old [^\]]* stopped at the FIRST "]",
        # so with brackets in the name field too the capture was cut before the "/" and a genuine
        # different-model close was told to degrade. The obvious repair (greedy to the last "]" on
        # the line) was WRITTEN, MEASURED AND REJECTED: an adversary showed it accepts a garbage
        # token sliced out of trailing prose -- a citation like
        # "…/ claude-sonnet-5] (see plugins/goalspec/hooks/gate-goal-close.sh[283])" yields
        # cid="gate-goal-close.sh[283", which is whitespace-free and carries a letter and a digit,
        # so has_real_id says True for the wrong reason. That fails OPEN in the direction that
        # matters, which is worse than the truncation it replaced.
        # Anchoring to end-of-line is the fix that stays positional instead of getting clever: it
        # encodes the grammar the agent def and this skill already state (the adversary emits the
        # marker as its own line; you quote that line verbatim). Anything appended after the marker
        # means no match at all -> no real id -> degrade to model=same. Fail-safe by construction,
        # and a leading "- " or "> " still matches, so a quoted bullet is unaffected.
        #
        # Proposed a SECOND time and re-rejected (2026-07-26, by the human operator, after a session
        # hit the same degrade on a bold-wrapped marker it had bolded itself when quoting): dropping
        # \s*$ so the greedy .* runs to the last closing bracket on the line is the exact repair the
        # comment above already tried and measured broken -- case 34 in test/gate-branches.py exists
        # specifically to pin it. The two failure directions are NOT symmetric: anchored fails closed
        # (a genuine different-model claim degrades to the honest, sayable model=same -- an
        # under-claim); unanchored fails open (a citation with its own closing bracket on the same
        # line, e.g. claude-sonnet-5 followed by a parenthetical citing file.sh line 283 in brackets,
        # gets sliced into a whitespace-free, letter+digit token that has_real_id accepts as a real id
        # -- a fabricated proof of independence). A false negative here costs an honest degrade; a
        # false positive costs the one guarantee this check exists to make. No formatting convenience
        # justifies inverting that. If you are reading this because you are about to try a third
        # variant: the fix is not in this expression -- see the DETAIL case in the bash MSG mapping
        # below for model-different-needs-nonunknown-self-report, which spells out the grammar (own
        # line, plain text, nothing appended) instead of silently requiring it.
        reports = re.findall(r"\[ADVERSARY-MODEL:\s*(.*)\]\s*$", text, re.I | re.M)
        if not any(has_real_id(r) for r in reports):
            remind("completion-review:model-different-needs-nonunknown-self-report")
else:  # none
    if not re.search(r"reason=.{20,}", body):
        remind("completion-review:none-needs-reason>=20")
    if last_verdict == "break":
        remind("completion-review:none-but-break-recorded")

# 5b. Staleness backstop (added alongside hooks/precheck-terminal-push.sh — see that hook and the
# module docstring in hooks/lib/terminal_actions.py for the incident this responds to). The
# operative completion-review found above can be HONEST at the moment it is declared and still be
# stale by the time this Stop fires, if it came from an EARLIER, already-flushed turn (tx_text) and
# a terminal Bash command (push/merge/deploy/destructive — same shared classifier the PreToolUse
# precheck uses) ran in a turn AFTER it. Real transcript evidence this pins: `[COMPLETION-REVIEW:
# none reason=sin accion terminal, PR abierto sin merge/deploy ...]` declared while a PR was open,
# then merge+deploy to production in the VERY NEXT turn with no completion-review of its own — the
# operative review from the OLD turn was still "valid" by every check above, because none of them
# ask whether something terminal happened SINCE it was written.
#
# Skipped entirely when the operative review came from lam_text (this turn, right now): nothing
# later in the session could have happened yet, so a same-turn close is fresh by construction
# regardless of what tool calls preceded it in this same turn (see the docstring on
# terminal_bash_after() in hooks/lib/terminal_actions.py for why file order, not the lam/tx split,
# is what actually matters there).
#
# Content exemption reuses the SAME allowlist the precheck hook uses (memory/, docs/, .goalspec/,
# root *.md) — a memory-only checkpoint commit pushed after a completion-review is not what this
# backstop exists to catch. Unlike the precheck (which diffs the actual prospective push live,
# before it happens), this runs AFTER the fact and has no clean way to know exactly which files a
# specific historical push carried — so it approximates with `git log --since=<the timestamp of the
# stale review event>`, best-effort and committer-date based (can disagree with the wall-clock
# timestamp recorded on the transcript event by clock-skew-sized amounts). Any uncertainty — no
# timestamp on the review event, no commits found, git itself unavailable — resolves to NOT
# exempt, i.e. flag it: this is a backstop for exactly the cases where something already slipped
# past the live precheck, so silently trusting an unreadable signal here would defeat the point of
# having it at all.
if ta is not None and not lam_crs:
    items = ta.read_transcript_items(tpath)
    idx = ta.last_completion_review_index(items)
    if idx is not None:
        terminal_calls = ta.terminal_bash_after(items, idx)
        if terminal_calls:
            paths = ta.commits_since(data.get("cwd") or os.getcwd(), items[idx].get("timestamp"))
            if not ta.all_exempt(paths):
                remind("completion-review:stale-terminal-action-after-close", skip_general_silence=True)

# 6. Floor as its own branch (0.18.0). Until now the floor could only be APPENDED to a reminder some
#    other check had already raised, so a run that is not converging but has nothing wrong with its
#    declaration got silence — e.g. a turn quoting both backends closes on the hold (operative
#    verdict = hold, every check passes) while the break-round count behind it is 3. The floor is
#    advisory text either way; this only gives it a path to be said at all.
if streak >= 3:
    remind("convergence-floor-only")

print("OK")
' 2>/dev/null)

# Fail-open on empty / OK.
[ -z "$RESULT" ] && exit 0
case "$RESULT" in
  OK) exit 0 ;;
  REMIND*) : ;;
  *) exit 0 ;;
esac

# RESULT is REMIND|<detail>|<streak>|<current-turn-carries-a-verdict>|<stop-is-re-entrant>. No
# detail token contains "|", so the split is unambiguous; a malformed/absent streak field degrades to
# 0 (no convergence note) and a malformed verdict flag degrades to 1 (the SPEAKING side of the floor
# branch below) — both degrade toward the pre-0.36.0 behavior, never toward new silence on a bad
# parse. A malformed re-entrancy flag degrades to 1 (0.43.0), i.e. to the HUMAN-ONLY floor payload
# that 0.36.0 shipped: on a bad parse the floor never gains a channel it would not otherwise have,
# so the degrade direction is "no new re-entry", never "an unbounded one".
REST="${RESULT#REMIND|}"
DETAIL="${REST%%|*}"
REST="${REST#*|}"
STREAK="${REST%%|*}"
REST="${REST#*|}"
LAMV="${REST%%|*}"
REENTRANT="${REST#*|}"
case "$STREAK" in ''|*[!0-9]*) STREAK=0 ;; esac
case "$LAMV" in 0|1) : ;; *) LAMV=1 ;; esac
case "$REENTRANT" in 0|1) : ;; *) REENTRANT=1 ;; esac

# Every branch below sets TWO variables, MSG and AGENT_MSG (0.44.5 — extends the floor's own
# audience split, below, to the rest of remind()). MOST branches still carry two DIFFERENT strings:
# MSG = short, Spanish, human-facing, always carrying the literal "(${DETAIL})" the branch classifier
# greps for; AGENT_MSG = technical, English, unchanged content.
# EXCEPTION (0.44.8, pilot on 2 branches — completion-review:stale-terminal-action-after-close and
# completion-review:model-different-needs-nonunknown-self-report): the split assumed additionalContext
# was invisible to the human on a Stop hook. The official hooks reference says the opposite —
# Stop/SubagentStop additionalContext "is shown in the transcript as hook feedback", literally
# labeled "Stop hook feedback" — so shortening only AGENT_MSG never reduced what the human saw. Those
# two branches now set AGENT_MSG="$MSG": ONE short message in both fields, pointing at the matching
# SKILL.md section instead of re-deriving the instruction inline. See memory/_pendientes.md
# p-a95b61154a for the finding and CHANGELOG [0.44.8]. The other branches below are UNCHANGED and
# still keep the two-string split until/unless a future release extends this collapse to them.
case "$DETAIL" in
  completion-review:closed-over-break|completion-review:none-but-break-recorded)
    MSG="Un revisor independiente marcó un problema sin resolver (${DETAIL}) — el cierre no lo puede pasar por alto todavía."
    AGENT_MSG="Goal-spec present but your operative [ADVERSARY-VERDICT: …] is \`break\` (${DETAIL}) — your [COMPLETION-REVIEW: …] cannot close over it as-is. Do NOT reformulate the completion-review to paper over the break. Pick one, honestly: (1) address the confirmed violation(s) and get a fresh \`hold\` from the adversary — and if the only thing left unverified is the fixes themselves, that is ONE delta-scoped round (payload names the diff since this verdict and the findings each change resolves; it verifies each fix against ground truth AND that it invalidates nothing a prior round held), not a re-run of the whole outcome, which is what makes the loop terminate; (2) if you are stuck (e.g. three consecutive breaks — the design is wrong, not the wording), route to a genuinely different model/vendor and get a hold there; (3) if you've judged the residual break non-actionable, close explicitly with \`[GOAL-CLOSE-WAIVED reason=…]\` (≥20 chars) — this is usable by you, the agent, not only a human operator; it is the honest, greppable way to override, unlike a completion-review that quietly disagrees with its own verdict."
    ;;
  convergence-floor-only)
    # Dead in practice: this detail is only ever emitted by python when streak>=3, and the
    # `STREAK -ge 3` block near the end of this file UNCONDITIONALLY overwrites both MSG and
    # AGENT_MSG below with the floor's own two-string payload before anything is printed. Kept only
    # so every branch of this case sets both variables uniformly; do not treat this MSG as
    # user-visible, and do not touch the floor block itself to "consolidate" this — see that block's
    # own header note for why it stays separate.
    MSG="Nothing objects to how you closed (${DETAIL}) — the declaration checks all pass. This is the convergence counter speaking on its own branch, because the count behind a clean-looking close is what the loop looks like from outside."
    AGENT_MSG="$MSG"
    ;;
  completion-review:model-different-needs-nonunknown-self-report)
    # 0.44.8 — collapsed from two divergent strings (MSG/AGENT_MSG) to one. The split assumed
    # additionalContext was an agent-only channel on a Stop hook; the official hooks reference says
    # the opposite — it's the exact field the transcript labels "Stop hook feedback" and shows the
    # human. So shortening only AGENT_MSG never reduced what the human actually saw. One message now,
    # short enough for both, pointing at SKILL.md's own grammar spec instead of re-deriving it here —
    # the agent already carries that file. See memory/_pendientes.md p-a95b61154a for the finding.
    MSG="model=different no se pudo confirmar por formato (${DETAIL}) — no es defecto grave. Si el adversario reportó UNKNOWN o el mismo modelo, usa model=same. Si no, vuelve a citar su línea [ADVERSARY-MODEL: …] tal cual — sin negritas, nada después del \`]\`. Ver SKILL.md, «Completion-review declaration»."
    AGENT_MSG="$MSG"
    ;;
  completion-review:stale-terminal-action-after-close)
    # 0.44.8 — same collapse as above, same reason.
    MSG="Hubo una acción difícil de deshacer después del último cierre declarado (${DETAIL}) — ese cierre no cubre esta acción. Repite 4b + 6 para ESTA acción y declara un cierre nuevo, o usa [GOAL-CLOSE-WAIVED reason=…] si de verdad es bajo riesgo. Ver SKILL.md, «A completion-review closes the spec, not the session»."
    AGENT_MSG="$MSG"
    ;;
  *)
    MSG="Sigue sin haber un cierre formal de este trabajo (${DETAIL}) — la decisión de cerrarlo o seguir es tuya."
    AGENT_MSG="Goal-spec present but no valid [COMPLETION-REVIEW] declared (${DETAIL}). Run the inherited-decision sweep + red-team, then declare \`[COMPLETION-REVIEW: none reason=…]\` (≥20 chars) or route to the adversary and declare \`[COMPLETION-REVIEW: adversary …]\` with an [ADVERSARY-VERDICT: …] present. Both marker lines must be in YOUR turn's text, not only in the subagent's output. A model=different close needs the adversary's own [ADVERSARY-MODEL: …] line naming a real, non-UNKNOWN id in your turn; if it self-reported UNKNOWN or same, say model=same. Stuck over a residual break? \`[GOAL-CLOSE-WAIVED reason=…]\` is usable by you, the agent, not only a human operator."
    ;;
esac

# Convergence floor (see header). Deliberately a claim about TEXT, not about rounds: it is damped
# toward under-counting, so it tells you to check your own round count instead of asserting one.
# 0.18.0 rewrote what it SAYS. The old text re-offered the three options of SKILL.md's convergence
# guard, two of which re-enter the loop and the third of which (the waiver) has a precondition that
# is false for exactly the residue a runaway produces — executor-authored prose is an actionable
# defect, not a verifier-environment limitation. Measured: both times this floor fired in the worst
# recorded runaway, it RESUMED a loop the executor had already stopped by itself. An instrument that
# detects non-convergence and then re-states the rule that makes stopping illegal is worse than
# silent. What it must do at that moment is make STOPPING legitimate — without widening the waiver,
# which stays exactly as narrow as it was.
#
# 0.18.1: it REPLACES the reminder instead of being appended to it. 0.18.0 gave the floor its own
# branch (step 6) but `remind()` exits before step 6 on every path where a declaration check has
# already fired — so on the path that actually matters, an agent mid-loop with no completion-review
# yet, the floor was still glued under the reminder, and the message opened with "run the sweep +
# red-team" at the exact moment its own next paragraph says to stop. That branch shipped dead; the
# old text apologised for it in prose ("read this INSTEAD of the reminder above, not in addition to
# it") rather than fixing the control flow. The detail code is carried into the floor's first line
# so the reminder it replaces stays greppable and the branch suite keeps its detail column.
#
# 0.36.0 changes WHO this branch talks to, and how often — the third repair of the same defect, and
# the first one that touches the delivery instead of the copy. Two observed sessions (2026-08-09
# paperclip, and the same run's checkpoint turn the next day) showed the remaining cost, which no
# amount of rewriting the text could reach:
#   (1) The default payload carries the message BOTH as `systemMessage` (to the user) and as
#       `hookSpecificOutput.additionalContext` (fed back to the model, which continues the
#       conversation). So the floor SPENDS A TURN: the agent had already written its plain-language
#       close, the floor re-entered, and the agent answered it — leaving a meta-confirmation, not
#       the summary, as the last thing the human reads. The 0.18.0 comment above already recorded
#       that both times the floor fired in the worst runaway it RESUMED a loop the executor had
#       stopped by itself; 0.18.0 rewrote what the floor SAYS and left the re-entry intact. Three
#       firings, zero where the model-facing copy improved the outcome. So the WALL was dropped, and
#       0.36.0 dropped the channel with it: at the floor this branch spoke to the HUMAN and never to
#       the model. 0.43.0 keeps the wall gone and puts a channel back, with a different string — see
#       the amendment in the floor bullet at the top of this file and the branch itself. The
#       distinction it rests on is a JUDGEMENT, not a measurement: the three recorded firings used the
#       old model-facing copy, so what they establish is that THAT copy through that channel resumed
#       loops; that a copy whose only instruction is "stop" behaves differently is reasoned, and is
#       unobserved until a live session shows it. The fuller guidance stays in SKILL.md either way.
#   (2) The break count in a transcript never decays and a parked run never acquires a
#       completion-review, so the floor fired AGAIN on every later turn of that session — including
#       a turn that was a checkpoint the human asked for, burying that report under the same wall.
#       Hence the parked-loop silence below: when this turn attempted no close (detail is plainly
#       `absent`) and carried no verdict of its own, the loop ran no round here, the floor has
#       nothing NEW to say, and saying it again only buries what the human did ask for.
# The wall itself is replaced by one human-readable line, and it stays replaced. Everything the wall
# explained (de-dup semantics, GOAL_GATE_ENFORCE suspension, why not to re-verify, the precondition of
# the waiver) lives in SKILL.md, which the model already carries — so the agent-facing line 0.43.0
# adds is NOT the wall coming back: its whole content is "stop spending rounds and hand the decision
# to the human", and the suite pins that it cannot become the human line.
if [ "$STREAK" -ge 3 ]; then
  # Parked-loop silence. Deliberately narrow, and both halves are required: `absent` means this
  # turn made no close attempt (a turn closing over a break still gets told), and LAMV=0 means it
  # quoted no verdict (a turn that ran a fresh round is news, and is said once). Anything else,
  # including an unparseable flag, falls through to the line below.
  #
  # The first adversary round on this change attacked LAMV as a proxy: it reads only the assistant's
  # own text, so a round whose verdict arrived in a TOOL RESULT and was never quoted looks like a
  # turn that ran nothing, and goes silent. Correct about the mechanism, and it is the same
  # epistemics as every other check in this file (the gate reads authored text; an unquoted verdict
  # does not exist for it — which is why hooks/remind-quote-verdict.sh nudges you to quote one).
  # What keeps it from hiding the floor is an invariant, not the proxy: STREAK counts trailing
  # verdict-carrying turns, so if this turn contributes none, the same count was already >= 3 at the
  # PREVIOUS Stop — and at that Stop the turn did carry the verdict, so the floor was said there,
  # with LAMV=1. The floor therefore lands on the turn the count first reaches it, and the silence
  # only ever suppresses REPEATS. Round 2 of the adversary then broke that invariant where it was
  # weakest: if the ANNOUNCING Stop is itself re-entrant, the step-0 guard used to swallow it, and
  # this silence suppressed every later chance — never announced. Fixed at the root rather than
  # papered over: the guard is now deferred and does not apply to this branch (step 0), so the
  # announcing Stop announces whether or not it is re-entrant. Cases 18 (silent repeat), 41
  # (announcing turn) and 42 (announcing turn that is ALSO re-entrant) are the three sides. Case 30
  # is NOT that third side, though its name suggests it: its shape has no verdict in the turn, so it
  # is silent by the rule right below, not by the guard.
  if [ "$DETAIL" = "completion-review:absent" ] && [ "$LAMV" = "0" ]; then
    exit 0
  fi
  # In Spanish — chosen by the author (2026-08-10) over an English line and over locale detection,
  # because this is a message whose entire audience is the human operator — everything ELSE in this
  # branch (AGENT_MSG, below) is read by the agent. A hook has no model in its path and no locale in
  # its payload, so "in the user's language" would have to be guessed from the transcript; a wrong
  # guess costs more than a fixed choice. English installers get this line in Spanish too.
  # 0.44.5 generalized the two-strings-per-audience SHAPE of this branch (short Spanish systemMessage
  # / technical English additionalContext) to every OTHER remind() branch in the case statement
  # above — so this is no longer the only Spanish string in the plugin, only the only one that also
  # decides, on its own, whether to emit the agent-facing half at all based on re-entrancy (see
  # AGENT_MSG below). `Piso de convergencia` is the literal the branch suite keys its CONV/CONV!
  # column on — if this opening is ever reworded, that constant moves with it.
  MSG="Piso de convergencia (${DETAIL}). Al menos ${STREAK} rondas de revisión independiente objetaron; nadie aprobó este trabajo. La decisión es tuya."
  # 0.43.0 — the floor gets an AGENT-FACING line back, and it is NOT the line above.
  #
  # What 0.36.0 got right and this keeps: the message quoted in $MSG is written FOR THE HUMAN. Its
  # last clause ("La decisión es tuya") addressed to the model is an authorization to continue, at
  # the one moment the model must stop — which is exactly the shape 0.18.0 measured RESUMING a loop
  # the executor had already stopped by itself, twice, in the worst recorded runaway. Feeding that
  # same string back to the model is the defect, and 0.36.0 removed the channel to remove the
  # string.
  #
  # What 0.36.0 got wrong, and why this is not a revert: removing the channel left the floor with NO
  # consumer on the agent side, in EITHER mode — the teeth branch below is guarded `STREAK -lt 3`,
  # so at the floor the hook emits nothing the model can read and nothing that blocks. Measured on a
  # field session (0.41.1, unattended VPS): three streaks of 3, 5 and 3 breaks, the Stop hook
  # running throughout, and a human-only message with no human reading it. That is this project's
  # own hueco #5 — a check whose only consumer may not exist — sitting on the floor itself. The
  # rationale for (1) in the header stands as a rationale about COPY; it was never evidence that the
  # model should be told nothing.
  #
  # So: two different strings, one per audience. `systemMessage` keeps the human line verbatim.
  # `additionalContext` carries a line whose only instruction is to STOP SPENDING ROUNDS and hand
  # the decision to the human. It re-opens nothing and offers no "one more round" — and it
  # deliberately does NOT name the waiver, which is the one pointer 0.18.0 removed from this branch on
  # purpose: the safety of an over-counting floor rests on its message routing to "stop and hand
  # back" INSTEAD of to the waiver, because the cost of a false three-breaks is then an unnecessary
  # suggestion to stop (cheap) rather than a nudge toward a premature close over a break (not cheap).
  # The counter can still over-count on re-quotes, so that property is live, not historical. SKILL.md
  # option (d) also gives the waiver a precondition this line could not state in one sentence
  # (non-actionable residue, e.g. the verifier own environment) — a floor line naming it without the
  # precondition invites exactly the close the precondition forbids. The waiver stays reachable; the
  # agent carries SKILL.md. It is simply not what this line points at. The suite pins its ABSENCE.
  #
  # Bounded by 0.18.1, deliberately: the agent-facing half is emitted ONLY on a non-re-entrant Stop,
  # so it is at most ONE re-ask per user prompt and can never be the runaway that made 0.18.1 an
  # emergency. On a re-entrant Stop the human still gets the announcement — that is the hole the
  # second adversary round of 0.36.0 found and it stays closed.
  AGENT_MSG="goalspec convergence floor (${DETAIL}): at least ${STREAK} independent review rounds objected and nothing has approved this work. STOP running adversary rounds on it — do not spawn another goal-adversary and do not invoke the external backend again. More rounds is the failure mode here, not the fix: at this point the design is wrong, not the wording. Write what you have, say plainly which objection is unresolved, and hand the decision to the human. End the turn with no completion-review: that is a legitimate ending, not a failure to close. Do not treat this line as permission to continue."
  if [ "$REENTRANT" = "1" ]; then
    MSG="$MSG" "$PY" -c 'import json,os; print(json.dumps({"systemMessage": os.environ["MSG"]}))'
  else
    MSG="$MSG" AGENT_MSG="$AGENT_MSG" "$PY" -c 'import json,os; print(json.dumps({"systemMessage": os.environ["MSG"], "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": os.environ["AGENT_MSG"]}}))'
  fi
  exit 0
fi

# Opt-in teeth: block the stop ONCE per user prompt — EXCEPT on the convergence floor, where the
# teeth would bite in the wrong direction. At streak>=3 with an unresolved break, "you may not stop
# until you close" plus "you may not close over a break" is an unterminable block, capped only by
# the harness's 8-consecutive-block override; that combination is the runaway, mechanized. Suspending
# the block IS the mechanical half of the message above — otherwise the gate says stopping is
# legitimate while refusing to let it happen.
#
# 0.18.1 bounds the teeth everywhere else too, via step 0: the Stop that FOLLOWS a block carries
# stop_hook_active and is answered with silence, so the block costs the agent one turn and then
# lets go. This branch stays because the floor case must not spend even that one turn — at
# streak>=3 a single block still pushes toward exactly the loop the floor exists to end.
#
# 0.19.0 measured what the pairing actually left, and it is LESS than the previous wording claimed.
# Compare the two payloads below, not their adjectives: both carry the SAME $MSG, and both re-enter
# the turn exactly once per user prompt (the default via hookSpecificOutput.additionalContext, which
# the harness feeds back to the model — "the conversation continues so Claude can act on the
# feedback"). So "one hard, unignorable interruption that costs the agent a turn" was never a
# description of the ENFORCE branch: it describes the DEFAULT branch just as accurately. What is
# actually different is two things, and only two: the Stop record carries preventedContinuation:true
# instead of false, and — until this release — the block payload OMITTED the systemMessage field the
# advisory payload sets, making the opt-in strictly worse than the default in one user-facing field.
# That omission is fixed below. Do not restate the old predicate anywhere: this is the third time a
# comment in this file asserted teeth semantics that the file's own control flow had falsified.
#
# So say what ENFORCE=1 buys, exactly: the same reminder, delivered as a formal block rather than as
# advisory context, once per user prompt. That is CONTAINMENT of a promise the harness cannot keep —
# it is not "hold until closed", and it is not the answer to what teeth should be. Every mechanism
# this harness offers that CONTINUES the conversation (decision:block, exit 2, additionalContext)
# re-enters the turn, and re-entry is the runaway; the one shape that has teeth without re-entry is
# `continue:false` + `stopReason`, which HALTS instead of holding. That is a real option and it is
# deliberately NOT taken here — see CHANGELOG 0.19.0 for the evidence bar it must clear first
# (live observation, plus its interaction with the second Stop hook in this array). Shipping it on
# suite evidence alone is the pattern that made 0.18.1 an emergency.
#
# Yes, this is gameable: the gate reads executor-authored text, so an executor who wanted to disable
# the teeth could type three fabricated \`break\` verdicts. That is not a new hole and it is not the
# cheap one — today a single fabricated \`hold\` closes cleanly and gets you the same place in one
# step. Every check here is an internal-consistency signal over self-reports, never a lie detector;
# you cannot gate your way out of specification gaming (references/outcome-loop-beats-gates.md), and
# hardening this branch against a self-report you already trust everywhere else would buy nothing
# while re-arming the loop this release exists to end.
if [ "${GOAL_GATE_ENFORCE:-}" = "1" ] && [ "$STREAK" -lt 3 ]; then
  # `reason` is the block explanation the harness/logs carry; `systemMessage` is the user-facing
  # warning. 0.19.0 made both fields present; 0.44.5 makes them the two DIFFERENT per-audience
  # strings every other branch now uses: `reason` = $AGENT_MSG (technical — it's the mechanism's own
  # explanation, not something a human reads on screen), `systemMessage` = $MSG (short, human,
  # Spanish). The suite classifies by the `decision` field (test/gate-branches.py:341), not by which
  # message field is present, and derives its detail from `systemMessage or reason` (:338) — it
  # prefers systemMessage, and $MSG still carries the literal "(${DETAIL})" every branch above sets,
  # so the classifier is unaffected by the split; only the CONTENT split is new, not detection.
  MSG="$MSG" AGENT_MSG="$AGENT_MSG" "$PY" -c 'import json,os; print(json.dumps({"decision":"block","reason":os.environ["AGENT_MSG"],"systemMessage":os.environ["MSG"]}))'
  exit 0
fi

# Default: fail-open advisory. Surface the reminder without blocking the stop. Same split as the
# floor branch above and the ENFORCE block just above: systemMessage = $MSG (short, human,
# Spanish), additionalContext = $AGENT_MSG (technical, English — what the agent reads and acts on).
MSG="$MSG" AGENT_MSG="$AGENT_MSG" "$PY" -c 'import json,os; print(json.dumps({"systemMessage":os.environ["MSG"],"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":os.environ["AGENT_MSG"]}}))'
exit 0

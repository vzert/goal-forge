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
#     between them" — a statement about turns, NOT a round count. (An earlier wording said "no
#     intervening hold", which the external adversary broke: a turn quoting BOTH backends, one holding
#     and one breaking, is a break round that the walk does not reset on, so a hold really can sit
#     inside the counted run. The counter was right; the sentence was claiming more than it checked.) It cannot be a round count: the
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
#           was measured silencing the counter in exactly the runs it exists for;
#       (b) it can now fire on its own branch, so a non-converging run whose declaration happens to
#           pass every check is no longer met with silence;
#       (c) it never blocks, and its message routes to "stop and hand back to the human" instead of
#           to the waiver. The original damping rationale — "a false three-breaks would push toward a
#           premature waiver, worse than not counting" — is retired with (c): over-counting now costs
#           an unnecessary suggestion to stop and ask, which is cheap, so (a) and (b) trade in the
#           direction the old rationale forbade only because the old message pointed somewhere worse.
#   * Opt-in teeth: GOAL_GATE_ENFORCE=1 turns the advisory into a block. Since 0.18.1 that means
#     AT MOST ONE block per user prompt, not "may not stop until the declaration is complete":
#     the re-entrant guard at step 0 runs ahead of this branch, so the Stop that follows a block
#     passes. Say what it is — one hard interruption that costs the agent a turn and cannot be
#     ignored — and not what it is not. Unbounded teeth were never the design; they were the
#     runaway, and re-asking your own output until the harness cuts you off is not enforcement.
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
#     Unbounded, it was the runaway. A
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
RESULT=$(ENFORCE="${GOAL_GATE_ENFORCE:-}" printf '%s' "$INPUT" | "$PY" -c '
import json, sys, os, re

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
if data.get("stop_hook_active"):
    fail_open()

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

# 2. Nothing to enforce unless this session produced a goal-spec.
if not re.search(r"(^|\n)#{1,6}\s*Goal-spec\b", text, re.I):
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

streak = 0
counted = set()
for t in reversed(turns):
    vs = turn_verdicts(t)
    if not vs:
        continue          # a turn with no verdict neither counts nor interrupts the run
    if not any(c == "break" for c, _ in vs):
        # A hold-only turn ends the run ONLY when it is the MOST RECENT verdict-carrying turn
        # (streak still 0): that is convergence, and a floor there would be noise. An EARLIER
        # hold-only turn is skipped, not fatal — running two backends, one holding in its own turn
        # while the other keeps breaking is one unconverged loop, not a reset, and treating it as a
        # reset was measured under-counting the very runs the floor exists for (0.18.0).
        if streak == 0:
            break
        continue
    # A turn quoting BOTH backends (e.g. subagent hold + external break) is ONE break round.
    key = tuple(sorted(s for _, s in vs))
    if key in counted:
        continue          # verbatim re-quote of a round already counted — do not double-count
    counted.add(key)
    streak += 1

def remind(detail):
    print("REMIND|%s|%d" % (detail, streak)); sys.exit(0)

# 5. Validate the completion-review declaration.
# Operative completion-review = the current-turn declaration if present (last_assistant_message is
# the reliable current-turn source), else the MOST RECENT one in the transcript. Anchoring on the
# *last* declaration — never the first re.search match — is what prevents an earlier exploratory or
# malformed [COMPLETION-REVIEW] from permanently poisoning the check after a correct one is emitted.
cr_pat = r"\[COMPLETION-REVIEW:\s*(adversary|none)\b([^\]]*)\]"
crs = re.findall(cr_pat, lam_text, re.I) or re.findall(cr_pat, tx_text, re.I)
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
        reports = re.findall(r"\[ADVERSARY-MODEL:\s*([^\]]*)\]", text, re.I)
        if not any(has_real_id(r) for r in reports):
            remind("completion-review:model-different-needs-nonunknown-self-report")
else:  # none
    if not re.search(r"reason=.{20,}", body):
        remind("completion-review:none-needs-reason>=20")
    if last_verdict == "break":
        remind("completion-review:none-but-break-recorded")

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

# RESULT is REMIND|<detail>|<streak>. No detail token contains "|", so the split is unambiguous;
# a malformed/absent streak field degrades to 0 (no convergence note) rather than erroring.
REST="${RESULT#REMIND|}"
STREAK="${REST##*|}"
DETAIL="${REST%|*}"
case "$STREAK" in ''|*[!0-9]*) STREAK=0 ;; esac

case "$DETAIL" in
  completion-review:closed-over-break|completion-review:none-but-break-recorded)
    MSG="Goal-spec present but your operative [ADVERSARY-VERDICT: …] is \`break\` (${DETAIL}) — your [COMPLETION-REVIEW: …] cannot close over it as-is. Do NOT reformulate the completion-review to paper over the break. Pick one, honestly: (1) address the confirmed violation(s) and get a fresh \`hold\` from the adversary; (2) if you are stuck (e.g. three consecutive breaks — the design is wrong, not the wording), route to a genuinely different model/vendor and get a hold there; (3) if you've judged the residual break non-actionable, close explicitly with \`[GOAL-CLOSE-WAIVED reason=…]\` (≥20 chars) — this is usable by you, the agent, not only a human operator; it is the honest, greppable way to override, unlike a completion-review that quietly disagrees with its own verdict."
    ;;
  convergence-floor-only)
    MSG="Nothing objects to how you closed (${DETAIL}) — the declaration checks all pass. This is the convergence counter speaking on its own branch, because the count behind a clean-looking close is what the loop looks like from outside."
    ;;
  *)
    MSG="Goal-spec present but no valid [COMPLETION-REVIEW] declared (${DETAIL}). Run the inherited-decision sweep + red-team, then declare \`[COMPLETION-REVIEW: none reason=…]\` (≥20 chars) or route to the adversary and declare \`[COMPLETION-REVIEW: adversary …]\` with an [ADVERSARY-VERDICT: …] present. Both marker lines must be in YOUR turn's text, not only in the subagent's output. A model=different close needs the adversary's own [ADVERSARY-MODEL: …] line naming a real, non-UNKNOWN id in your turn; if it self-reported UNKNOWN or same, say model=same. Stuck over a residual break? \`[GOAL-CLOSE-WAIVED reason=…]\` is usable by you, the agent, not only a human operator."
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
if [ "$STREAK" -ge 3 ]; then
  MSG="Convergence floor (${DETAIL}).

At least ${STREAK} verdict-carrying turns in this session each contain a \`break\`, and your most recent verdict-carrying turn is one of them. An earlier turn where one backend held does not reset that count (two backends disagreeing is one unconverged loop, not convergence); a hold in your LATEST verdict-carrying turn does, and would have silenced this. Verbatim re-quotes of one round are de-duplicated, so this can under-count; re-wording an old round can make it over-count. It is a floor, not your round count.

STOPPING HERE IS A LEGITIMATE OUTCOME OF THIS METHOD, AND THIS FLOOR NEVER BLOCKS IT — not even under GOAL_GATE_ENFORCE=1, which is suspended for this branch precisely so that a loop that cannot converge is never mechanically forced to continue. Ending your turn WITHOUT a completion-review is a valid terminal state: say plainly what is unresolved, how many rounds you actually ran, and what you would do next, then hand the decision back to the human. That is not an evasion and not a waiver — you are not closing over the \`break\`, you are declining to keep going alone. The human is the exit the loop does not have.

Why this, rather than \"address it and re-verify\": every corrective round rewrites the outcome, and freshly-written prose is the least verifiable material that exists — it IS the claim, with no ground truth to re-derive it against — so an adversary that resolves what it cannot verify as \`break\` is handed a new break by construction. Past three rounds the next break is likelier to be about your RECORD of the decision than about the decision. Re-verifying an outcome you just rewrote is not converging.

If you do continue, continue on the design, not the wording: a genuinely different approach, or a genuinely different model/vendor, can be worth one more round; a round that only re-words is patching to green. And do not reach for \`[GOAL-CLOSE-WAIVED reason=…]\` as a way out of this — its precondition is unchanged and narrow (a residual break you have verified to be non-actionable, e.g. a limitation of the adversary's own environment rather than a defect in the outcome). If the break is actionable and you still cannot resolve it, the honest exit is the one above: stop, report, hand back."
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
# streak>=3 a single block still pushes toward exactly the loop the floor exists to end. Note what
# the pairing means for a user who sets GOAL_GATE_ENFORCE=1: teeth are one hard, unignorable
# interruption per prompt, not a hold-until-closed. Weaker on purpose. The unbounded version was
# never enforcement — it was the runaway, and it punished the agent that obeyed.
#
# Yes, this is gameable: the gate reads executor-authored text, so an executor who wanted to disable
# the teeth could type three fabricated \`break\` verdicts. That is not a new hole and it is not the
# cheap one — today a single fabricated \`hold\` closes cleanly and gets you the same place in one
# step. Every check here is an internal-consistency signal over self-reports, never a lie detector;
# you cannot gate your way out of specification gaming (references/outcome-loop-beats-gates.md), and
# hardening this branch against a self-report you already trust everywhere else would buy nothing
# while re-arming the loop this release exists to end.
if [ "${GOAL_GATE_ENFORCE:-}" = "1" ] && [ "$STREAK" -lt 3 ]; then
  MSG="$MSG" "$PY" -c 'import json,os; print(json.dumps({"decision":"block","reason":os.environ["MSG"]}))'
  exit 0
fi

# Default: fail-open advisory. Surface the reminder without blocking the stop.
MSG="$MSG" "$PY" -c 'import json,os; m=os.environ["MSG"]; print(json.dumps({"systemMessage":m,"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":m}}))'
exit 0

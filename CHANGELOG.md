# Changelog

All notable changes to the `goalspec` plugin. This project follows
[semantic versioning](https://semver.org/). **Bump `plugins/goalspec/.claude-plugin/plugin.json`
`version` on every release** — the install cache is keyed by version
(`~/.claude/plugins/cache/goal-forge/goalspec/<version>/`), so changes pushed without a
version bump are never delivered to already-installed users.

## [0.18.1] - 2026-07-25

Fix. 0.18.0 rewrote what the Stop gate *says* when a run will not converge. It did not touch the
mechanism that made the gate able to say it nine times in a row.

**The runaway was not the teeth.** In the affected session all 31 Stop records carried
`preventedContinuation:false` and not one emitted `decision:block` — `GOAL_GATE_ENFORCE` was never
set. The re-asking came from the *advisory* path: a Stop hook payload with
`hookSpecificOutput.additionalContext` is fed back into the model, so the turn is re-entered even
though the stop was never prevented. The header claimed the default mode "never blocks" and traded
on that meaning "never re-enters the turn". Those are different properties and only the first was
true.

**The inversion that made it dangerous.** A tool call resets the harness's consecutive-stop counter;
text-only turns accumulate toward it. The agent in that session did exactly what the convergence
floor asked — zero tool calls, no fabricated close, no waiver — and that is *why* it hit the cap
nine times, twice. Running another adversary round would have reset the counter. The mechanism
punished obeying and rewarded staying in the loop, which is the precise opposite of what the floor's
own text declares. Bounded re-asking is not the deliverable; ending that inversion is.

- **Re-entrant Stops are now silent** (`gate-goal-close.sh` step 0, `check-usage-budget.sh` step 0).
  If the harness sets `stop_hook_active`, both Stop hooks emit nothing, in **both** modes — the
  guard runs ahead of the `GOAL_GATE_ENFORCE=1` branch, because "you may not stop until you close"
  re-asked on its own output is the runaway with teeth on. Ceiling is now one re-ask per **user
  prompt**, then silence: measured, not assumed — two separate probe chains each recorded
  `stop_hook_active` false on the first Stop and true on the next, under two different `prompt_id`
  values, so the next thing you say re-arms it. Per-prompt, not per-session. Obeying the floor now
  terminates the turn instead of accumulating toward a cap.
- **⚠️ Behavior change if you set `GOAL_GATE_ENFORCE=1`: the teeth are weaker on purpose.** Because
  the guard precedes the enforce branch, a block is followed by a Stop that carries
  `stop_hook_active` and is answered with silence. So enforce mode is now **at most one block per
  user prompt** — one hard, unignorable interruption that costs the agent a turn — and no longer
  "may not stop until the declaration is complete". Two comments in the gate still claimed the old
  semantics and were corrected with this release. The unbounded version was not enforcement: it was
  the runaway, and it fell hardest on the agent that complied.
- **`additionalContext` is kept, and that is a measured decision, not an omission.** `stop_hook_active`
  was verified to arrive on this harness — `false` on a first Stop, `true` on the next — *including*
  when the continuation came from a purely advisory payload with no block anywhere, which is the
  path the runaway actually took. Since the flag arrives, the guard alone bounds the loop, and the
  nudge keeps the agent-facing consumer that is its entire reason to exist. Had the flag *not*
  arrived, the guard would have been dead code and removing `additionalContext` would have been the
  only real fix.
- **The convergence floor now REPLACES the reminder instead of being appended to it.** 0.18.0 gave
  the floor its own branch, but `remind()` returns before it on every path where a declaration check
  already fired — so for an agent mid-loop with no completion-review yet, the floor was still glued
  underneath, and the message opened with "run the sweep + red-team" at the moment its own next
  paragraph says to stop. That branch shipped dead. The prose that apologised for it ("read this
  INSTEAD of the reminder above") is gone with the bug.
- **`test/gate-branches.py`**: four cases for the re-entrant guard (`true` → silent; absent and
  explicit `false` → unchanged, as controls), per-case assertions so "this fails today" is
  mechanical rather than eyeballed, and a `CONV!` column that separates a floor that replaced the
  reminder from one that rode along on it — without it, `--compare` could not see the floor fix at
  all.

*What is verified and what is not*: the branch suite reads the hook's stdout, so it certifies the
payload and the guard, in both modes, against a pre-edit copy with the intended diffs declared
first (8 changed, 0 unexpected). That the harness stops re-asking is established by direct
measurement of a live Stop payload, not by the suite. The `check-usage-budget.sh` guard is verified
by placement and syntax only — that hook cannot emit anything without real credentials, so no
offline test discriminates.

## [0.18.0] - 2026-07-25

The verification loop ran away and this release attacks the two levers that exist, neither of which
is a terminal.

*Provenance of the figures below, stated because they are load-bearing and you cannot re-derive them
from this repo:* they were counted from one private session transcript (`~/.claude/projects/…jsonl`,
2026-07-25) and recorded in a project-local research note under `memory/`, which is **gitignored —
this is a public repo and session logs are third-party data**. So they are *measured but not
independently reproducible here*, and no test in `test/` re-derives them; read them as the motive
for the change, never as evidence you can check. What you *can* check is every mechanical claim:
the branch suites reproduce their own baselines with `git show <sha>^:<path>`.

Measured from that transcript: **22 adversary invocations → 20 `break`s,
then 2 `hold`s, to decide to change nothing**, ~76M tokens, 2.5× the previous phase. **17 of the 20
breaks attacked text the run itself had fabricated; 15 of 20, text a *previous correction in the
same run* had written. Exactly 1 of 20 attacked the decision — the other 19 attacked the record of
the decision.**

- **The adversary is spawned with paths, not a narrated payload** (`SKILL.md` step 6, both backends).
  It used to be handed "the goal-spec, your outcome, where the work lives, and the ask record" — an
  account the executor typed. Freshly written prose is the least verifiable material there is: it
  *is* the claim, with no ground truth to re-derive it against, so an adversary instructed to resolve
  what it cannot verify as `break` is handed one **by rule, not by chance** — and "on break, address
  every violation and re-verify" then feeds it the correction it just wrote. Pointing at artifacts
  removes the manufacturing step without narrowing the adversary's scope by one inch (delta-scoping
  was rejected: it would blind the check that produced the best findings). Carriers updated together:
  `SKILL.md` :199 and :203, `agents/goal-adversary.md`, `hooks/external-adversary.sh` (header, prompt,
  payload banner), `hooks/route-external-adversary.sh`, `references/external-adversary-setup.md`.
- **The convergence floor stopped pointing back into the loop.** Both times it fired in the measured
  runaway it *resumed* a loop the executor had already stopped — it re-delivered advice the executor
  had read on skill load, phrased around "don't close over a break", which is the rule that made
  stopping impossible. It now says the thing that was true and unsaid: **ending the turn with no
  completion-review, and handing the decision back to the human, is a legitimate terminal state** —
  not an evasion, not a waiver, and explicitly *not* the waiver, whose precondition (non-actionable
  residue, e.g. the verifier's own environment) is false for executor-authored prose and is
  **unchanged**. Same rule mirrored in `SKILL.md`'s convergence guard as option (a).
- **The floor never blocks — `GOAL_GATE_ENFORCE=1` is suspended on that one branch.** "You may not
  stop until you close" plus "you may not close over a break" is an unterminable block capped only by
  the harness's 8-block override: the runaway, mechanized. Yes, an executor could type three fake
  breaks to disable the teeth; that is not a new hole and not the cheap one (a single fabricated
  `hold` closes clean today, in one step), and it is the project's written position that you cannot
  gate your way out of specification gaming.
- **The floor got its own branch.** It could previously only ride a reminder some other check raised,
  so a non-converging run whose declaration happened to pass — e.g. a turn quoting both backends and
  closing on the `hold` — was met with silence at streak 3.
- **Fixed: a hold-only turn extinguished the streak** (`gate-goal-close.sh`). With two backends, one
  holding in a turn of its own switched the counter off mid-runaway; it now resets only when the
  *most recent* verdict-carrying turn is a hold (which is convergence). Measured under-count in the
  runaway: "at least 4" with 6 real, "at least 6" with 12.
- **Fixed: the verdict nudge never saw a verdict** (`remind-quote-verdict.sh`). Since Claude Code
  v2.1.198 subagents run in the background, so the tool result is a handle with no `content` — and
  that handle echoes the executor's own spawn `prompt`, which this method fills with prior verdicts.
  Measured against the pre-edit copy: it therefore reported the **executor's own text** as a verdict
  that "came back" (case 04 of the new suite) — silent on a first round, actively misleading after.
  It now anchors on `tool_input.subagent_type`, excludes echoed input fields, and nudges on the
  launch itself. It stays a **nudge, not a counter**: `PreToolUse` can fail an Nth *spawn*, nothing
  available can fail an Nth adversarial *round*.
- **The verification instrument can now see what changed** (`test/gate-branches.py`). It read
  `systemMessage or reason`, which collapses the advisory and blocking paths — so a change to
  *whether the gate blocks* was invisible to `--compare`, the one check used to certify "no
  regression". It now reports the gate's answer as a third observable and takes `--expected` to
  pre-declare intended diffs. New `test/verdict-nudge-branches.py` covers the nudge's branches.

**How it was verified.** The mechanical half is parity: both branch suites run against pre-edit
copies in default *and* `GOAL_GATE_ENFORCE=1` modes, with the intended diffs **pre-declared** via
`--expected` before the comparison was run (2 in default, 6 under enforce, 0 unexpected). The prose
half got exactly **one** external-adversary round, capped in advance: a `break` there was to be
fixed and the release closed **without a second adversarial round** — the cap is this release's own
lever applied to itself, and it is deliberate, not an oversight.

Read that cap precisely, because it is narrower than "ships unverified", and the distinction is the
whole point: **mechanical verification is not capped.** Any change touching code re-runs both branch
suites against the pre-edit baselines, in both modes — that costs nothing and generates no new
prose. What is capped is *adversarial re-verification of prose*, and only there, because that is the
step measured to manufacture its own next finding: the round that fixes a wording writes the wording
the next round breaks. It ran once; the `break` it returned was addressed; the residue is named in
the release rather than re-litigated. An adversary attacking this cap as "done means verified" is
correct about the general rule and is also, precisely, the loop this release documents.

**What this release does not claim.** (1) The paths payload lowers the **rate** at which break-
eligible surface is generated; it does not give the loop a terminal. (2) The floor makes stopping
legitimate once the instrument has detected non-convergence; it does not make the exit set reachable
in general. **The exit-set defect stays OPEN**: the reachable closes are still `hold` and the waiver,
and `hold` is only reachable by a round that shrinks the corpus while the on-break instruction
prescribes one that grows it. Handing back to the human is an exit from the *turn*, not a close.
And (1) is **not verified by this release** — the project's own bar for it is a **comparison**
(a run with the change against one without), not another passing round; one clean run is not that.

## [0.17.0] - 2026-07-25

Phase 3 of the graph-vs-loops research: **single-source applied to shared state**. Two places in
`SKILL.md` told you to keep a fact alive outside your own context, and both created a *second home*
for that fact — the generator of most defects shipped by this method. They now point at one file.

- **The checkpoint has a name and a shape.** The Execute step said "checkpoint state to disk" with
  no path, no schema, and no reader, while `hooks/check-usage-budget.sh` already nudged toward it —
  a live pointer aimed at something each agent had to invent. It now names
  **`.goalspec/checkpoint.md`**, with its shape in the new `references/durable-artifact.md`.
  **What this is not:** nothing in the plugin reads that file, and **nothing gates its absence** — a
  run that never writes one closes exactly as cleanly. It is a named place plus an instruction to
  fill it, not a guarantee that state survives, and it does **not** close the resume gap (resume is
  a human CLI action no hook can reach; that is unchanged). The narrow, real gain: the nudge now
  points somewhere executable.
- **The instruction to per-entity workers no longer prescribes a re-narrated copy.** The
  coverage-floor decomposition said to *"relay the few facts that must stay consistent across
  entities yourself"* — prescribing that the shared fact live in the coordinator's prose and be
  retold to each worker, where it diverges round by round. It now says to put those facts in the
  checkpoint and have each worker's brief **point at the path**. This changes what the skill tells
  you to do; whether workers ever do it is **unobserved**, for the reason given at the end of this
  entry.
- **Verb restriction over shared state** (`references/durable-artifact.md`): coordinator is the only
  writer, rounds append rather than rewrite, and no worker may `git stash` / `git reset` /
  `git checkout --` shared working state. This is the prior art's best-supported finding — in Bun's
  multi-agent port, clobbering appeared within ~2 minutes and was fixed by removing destructive
  verbs, *not* by changing the number of agents.
- **Two candidate practices not added — with the gap written down instead of papered over.** Each
  has a near-neighbour already in the method, and in both cases the neighbour is **narrower**, so
  "already covered" would have been false. *Review the shared artifact before it becomes shared
  state*: step 6 routes your **outcome** to an adversary at close — it never requires that adversary
  to open the checkpoint, and it fires **after** workers have read it. *A dedicated pass reconciling
  contradictions between artifacts*: the rule-surface enumeration greps every carrier of a **rule
  you changed**, which is not two arbitrary work products that disagree. Both limits are now stated
  in `references/durable-artifact.md`; **neither is filled.** Restating the neighbours would have
  given an existing rule a second home — the defect this release is about — but calling them
  equivalent would have been the overclaim this project ships most often.

**Declared, not validated.** The worker half serves the coverage-floor decomposition (S5c, v0.12.0),
whose trigger has still never been observed firing on its own. This release's own task could not
observe it either, and it fails **both** halves of S5c's condition: the task was never long enough to
risk exhausting one context — the plainer disqualifier, and the one that rules out any short task —
and its entities were carriers of a single claim, so they *share* state, S5c's stated anti-condition.
Only the second half is specific to this class of task.

**Was the checkpoint actually useful? Partly, and less than it sounds.** It was dogfooded
in the session that shipped it, and for its **stated** purpose it was **not needed**: that session hit
no context limit and no cutoff, so nothing was ever resumed from it. What it was actually used for
was the carrier table — the running list of which surfaces had been updated. Whether that beat
keeping the list in context is not something this release measured, so no claim is made either way.
What *is* observed: the file reproduced the defect it exists to prevent **three times** — twice as a
copied fact going stale (a word count, then a superseded scope claim), and once as two carriers
simply disagreeing (its own header contradicted this entry about which items had gone stale). An
adversary caught all three by re-deriving them; the file caught none. It has since been rewritten to
carry pointers and status only, which is what `references/durable-artifact.md` tells you to do. One
session, in which the artifact's own failure mode showed up three times inside the artifact, is not
evidence that it pays for itself.

`SKILL.md` body: 8,706 → 8,757 words (+51); the new material is in
`references/`, which loads only on demand.

## [0.16.0] - 2026-07-25

Phase 2 of the graph-vs-loops research. The phase was a **decision**, and the decision was **not to
adopt** the paper's "third independence lever" (make the verifier commit its own answer before
reading the executor's). What shipped is one small disclosure field.

**Why the lever was not adopted.** The motivating hypothesis was that the subagent backend verifies
*code* while the external backend verifies *claims*, leaving the zero-config user (default backend =
`subagent`) unverified on the claim axis. Classifying the existing recorded corpus by axis —
retroactive and free, since the verdict's five integers were already written down — does not support
that split. Across the 6 findings confirmed **in the corpus as it stood when this was decided**
(5 claim-axis, 1 coverage-axis), all 6 came from the external backend and the subagent had 0 in
either axis. One of its misses had a fully available external error signal (the DoD claimed
"committed locally"; `git log` showed HEAD unmoved with 7 uncommitted files) — a not-checking
failure, not an anchoring failure. So a claim-axis-only intervention would be narrower than the
observed deficit, and the deficit itself is not yet characterized well enough (n=3 comparison rows)
to design against.

**That "subagent has 0" figure is a snapshot, not a property** — and this release's own verification
falsified it within hours. The subagent backend went on to return real findings in both axes over
several rounds, including the sharpest one of the release (a sibling overclaim about `model=` sitting
in the README).

It went further than that, and this is the release's most useful result. In one round **each backend
caught a defect the other missed**: the subagent alone found a threshold contradiction between two
carriers, the external alone found a stale carrier in a third. That is the first *observational*
support this project has for `SKILL.md`'s standing claim that "running both backends is strictly
better than either" — which until now rested on OR-aggregation logic, not evidence. Note how it was
found: an earlier draft of this entry asserted the opposite ("the subagent has not yet caught
anything the external did not"), and both adversaries falsified it from the transcripts. The claim
the verification pass killed was the one that would have thrown away the finding.

Revisit at **n≥5 comparison rows independent of this decision**. The rows added during this release —
five of them, all of them this release's own verification rounds — do not count: letting a decision's
own verification satisfy the threshold that gates revisiting it is circular. Counted that way the
corpus is still at 3, where it was when the call was made.

**Added — `backends=` in the completion-review details.** `backends=both` /
`backends=subagent-only` / `backends=external-only`: a place for a single-backend verification to
say so, in the same pattern as `model=same`. It is true by construction (you know which backends you
ran) and asserts nothing about what a second backend would have found.

Scope of what this does and does not do, stated precisely because an adversarial round caught the
first wording overclaiming it: the field is **ungated, and its absence is ungated too** — omitting it
passes exactly as omitting `model=` does. So it is a slot plus an instruction to fill it, **not** a
guarantee that a single-backend close cannot stay silent.

Its *value* is not honestly gateable — two backends routinely return a byte-identical
`hold 0/0/0/0/0`, so counting *distinct* verdicts would downgrade a genuine dual-backend close while
counting *occurrences* would bless a re-quote of one backend; that is the bottomless-proxy pattern
the 0.11.1 id-matcher removal already paid for. Its *presence* is a different question and would be
mechanizable (the `none` branch already gates `reason=` for presence and length without judging its
truth). Not done here: the ratified scope for this release was explicitly zero change to
`gate-goal-close.sh`, and gating presence changes the outcome for every existing close that omits
the field. Left as a named follow-up.

**Fixed — the same overclaim about `model=`, found by round 2 of this release's own verification.**
`README.md` described a same-model fallback as "announced, **never silent**". It is the identical
claim just retracted for `backends=`, one field over: `gate-goal-close.sh` only checks a body that
*contains* `model=different`, so a close omitting `model=` entirely passes clean. The same wording
had spread to SKILL.md's step 6 ("never a silently-hollow one") and to the backend table in
`references/external-adversary-setup.md` ("degrades announced"). All now say the same thing: you
declare the degradation, and the gate can reject an unsupported `model=different` but not a close
that omits the field. Earlier CHANGELOG entries carry the old wording too; those are left as the
historical record of what was claimed at the time, and this entry is the correction.

**Size** — `SKILL.md` 8,543 → 8,706 words (+163), measured. Most of that is not the feature: the
feature itself was a few sentences, and the rest is the five verification rounds' corrections, which
replaced short absolute claims ("announced, never silent", "never silently skipped") with longer
accurate ones. This file is the single place that figure is recorded, deliberately — a duplicated
copy in the plan file went stale twice during this release.

**Tests** — three cases (21–23) pinning that an extra field inside the completion-review bracket
does not break a valid close and does not mask the `model=different` self-report check, which
`cr_pat`'s `[^\]]*` body capture makes a real risk. Gate script unchanged; suite parity holds in
both default and `GOAL_GATE_ENFORCE=1`.

## [0.15.0] - 2026-07-25

Phase 1 of the graph-vs-loops research: three places where a written rule had no teeth. All three
were verified defects in shipped code, found by an investigation into whether goalspec should be
replaced by a graph-shaped orchestrator (conclusion: no — of ten frameworks reviewed, none has a
forced different-model verifier or a gate on terminal actions; but a graph would have caught these).

### Added
- **The Stop gate now counts the convergence guard (`hooks/gate-goal-close.sh`).** SKILL.md has said
  "at three consecutive breaks, stop editing — the design is wrong, not the wording" since 0.4.0, and
  nothing but the agent's memory observed it. The gate now counts and appends a **convergence floor**
  to whatever reminder it was already emitting (both the `absent` branch — the state a mid-loop agent
  is actually in — and `closed-over-break`).
  The claim it makes is deliberately weak, and phrased to say exactly what the walk checks and no
  more: *"at least N of your most recent verdict-carrying turns each contain a `break`, with no
  `hold`-only turn between them"* — a statement about **turns, not rounds**. (The first wording said
  "no intervening `hold`" and the external vendor adversary broke it in round 2: a turn quoting both
  backends, one holding and one breaking, is a break round the walk does not reset on, so a `hold`
  really can sit inside the counted run. The counter was right; the sentence claimed more than it
  checked — and it claimed it in four carriers at once.) It cannot honestly be a round count, because the skill instructs the agent to quote
  every verdict verbatim in its own turn, so a multi-round loop naturally re-quotes earlier rounds
  when summarizing and a transcript-wide tally inflates *in exactly the scenario the guard exists
  for*. A false "three breaks, stop editing" at round 2 would push toward a premature
  `[GOAL-CLOSE-WAIVED]` — worse than not counting at all. So the count is damped: at most one round
  per assistant turn, identical verdict sets de-duplicated within the trailing run (which under-counts
  identical consecutive breaks — the fail-open direction), a `hold`-only turn ends the run, and a turn
  quoting both backends is one round. The message tells the agent to verify its real round count
  rather than asserting one.
  Only the **counter** is mechanized. The other half of the guard — "each round should break something
  smaller than the last" — is left to the agent explicitly, because it is not mechanizable: the
  verdict's five integers are **cardinalities, not severities** (`incomplete=3` → `unsafe=1` is fewer
  violations and a worse break). Mechanizing it would repeat the id-matching mistake 0.11.1 retired.
  Consumer: the hook's own message branches and the `block` reason under `GOAL_GATE_ENFORCE=1` — no
  new marker, nothing else reads it. Verified across a 20-case branch suite with synthetic multi-turn
  transcripts, including the dedup case (same verdict in `last_assistant_message` **and** as the last
  recorded turn → the floor must not jump) and hold-resets; the eleven pre-existing branches emit
  byte-identical detail codes before and after.

### Fixed
- **The ratify gate (4b) offered four answers and drew one edge.** `Approve / Narrow / Minimal-fix /
  Stop` — and only "Approve" said where it went, leaving the agent to improvise the other three
  mid-run. Now drawn, in step 4b only (the other carrier points at it rather than restating it):
  Narrow → rewrite the spec to the given scope, re-emit it, go to step 5 **without a second modal**;
  Minimal-fix → the minimal reversible fix *becomes* the objective and the systemic branch is demoted
  to a surfaced, unexecuted follow-up; **Stop** → execute nothing but still close, with
  `[COMPLETION-REVIEW: none reason=…]` naming the stop. That last edge closed a real gap: a stopped
  run leaves a `## Goal-spec` behind, so the gate expects a declaration and would otherwise nag an
  agent that had correctly done nothing.
- **Nothing said the `goal-adversary` must be spawned isolated.** 0.12.0 introduced agent-teams
  guidance for *execution* decomposition; neither the adversary spawn nor `agents/goal-adversary.md`
  excluded itself. A teammate is addressable and resumable, so the executor could brief the adversary
  mid-verification or the adversary could ask instead of re-deriving from ground truth — collapsing
  both independence levers at once and **invisibly to the gate**, which only checks the marker's
  shape. Latent, not observed (it needs the experimental flag on, a named-teammate spawn, and someone
  using the channel), and the fix is one clause at the spawn site plus a matching instruction in the
  agent definition itself: no message goes to it after the spawn, and an unreachable fact is an
  unverified claim to report, not a question to ask.

## [0.14.1] - 2026-07-22

### Added
- **"Quick enable" copy-paste agent prompts, in README.md and `references/usage-budget-setup.md`.**
  So a user who hands this repo to their own agent (or gets pointed at it) can trigger the two new
  opt-in features without hand-writing config: one prompt for `usage_budget` (which still routes
  through reading the security doc first, not silent activation) and one for Claude Code's own
  experimental Agent Teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, referenced by 0.12.0's
  coverage-floor decomposition guidance). Also added a "What's new" pointer to CHANGELOG.md in
  README.md. Docs only — no hook/behavior changes.

## [0.14.0] - 2026-07-22

### Added
- **`PostToolUse` nudge for the recurring "gate can't see the verdict" friction
  (`hooks/remind-quote-verdict.sh`) + a matching fix inside `hooks/external-adversary.sh`.**
  Reported as a recurring, previously-unresolved pattern across most goalspec sessions:
  `gate-goal-close.sh` only ever scans assistant-authored text for
  `[ADVERSARY-MODEL: …]`/`[ADVERSARY-VERDICT: …]`, by design — never a tool result. A real verdict
  from the `goal-adversary` subagent or `hooks/external-adversary.sh` arrives as a tool result, so
  it stays invisible to the gate until the executor personally re-types it into their own turn —
  easy to forget across a long session, costing a Stop-hook round-trip every time it's missed (this
  exact session hit it twice in a row). Considered making the gate itself correlate tool_use/
  tool_result pairs to find the verdict automatically, but that repeats the "get clever with the
  parser" pattern that already broke 5 consecutive rounds once before (the model-id matcher,
  0.11.1) — the ruling then was "simplify, don't out-clever it."
  - `remind-quote-verdict.sh` (matcher `Task|Agent` only) fires on a `goal-adversary` spawn
    (subagent_type anchored to end-with "goal-adversary" — a fabricated
    `"not-goal-adversary-example"` substring was caught by adversary review and excluded) whose
    `tool_response` contains a well-formed verdict (or a model line with a malformed/missing one),
    nudging to quote it verbatim in the very next turn.
  - The Bash/`external-adversary.sh` case is deliberately **not** handled by command-string
    detection in that hook. An earlier draft tried exactly that and an external adversary review
    broke it twice in a row: first a bare substring match false-positived on read-only inspection
    (the script's own source contains literal fallback `[ADVERSARY-VERDICT: hold …]` strings, so a
    plain `cat`/`grep` of the file — routine when inspecting hook scripts — would have nudged to
    quote non-evidence into the transcript the real gate reads); then, after tightening to an
    invocation-verb check, real invocation forms (a bare `./external-adversary.sh`, `sh -c "..."`)
    were missed. Rather than patch the heuristic a third time, the reminder was moved to the one
    place that needs no heuristic at all: `external-adversary.sh` itself now emits the identical
    reminder to stderr from the single code path that only runs after it has already validated a
    real, well-formed verdict came back — a structural guarantee, not a guess. `stdout` (the actual
    verdict contract callers parse) is unaffected.
  - Zero changes to `gate-goal-close.sh`'s own parsing logic throughout. Also clarified in
    `SKILL.md`'s completion-review section that "present in the session" means in the executor's
    own authored text, never a tool result — the ambiguity that let this recur silently.
  - A further adversary round found both nudge messages **asserted** "a real verdict" when neither
    hook can actually verify the underlying conclusion is genuine adversarial work rather than
    copied/echoed text (a synthetic "copied example only" response, or a fake `external_cmd` that
    merely echoes a well-formed string, would satisfy the same structural checks). This is the same
    self-report limitation this method already documents everywhere else (`references/`
    `outcome-loop-beats-gates.md`; the bare-verdict-evidence-floor already in `external-adversary.sh`
    is explicitly commented as "a FLOOR, not proof of diligence") — the nudges never granted a
    lazy/copied verdict any new power to satisfy the real gate, but the wording overclaimed a
    certainty neither hook has. Reworded both to explicitly defer the genuineness judgment to the
    executor ("a verdict-shaped block... whether it reflects genuine adversarial work is still
    yours to judge... if you judge it genuine, quote it") rather than asserting authenticity, and
    synced every carrier that still described the old framing (`README.md`, `SKILL.md`, both
    hooks' own header comments).

## [0.13.0] - 2026-07-22

### Added
- **Opt-in usage-budget nudge (`usage_budget.enabled`, off by default).** A new Stop hook,
  `hooks/check-usage-budget.sh`, reads the local Claude Code OAuth credential and calls Anthropic's
  own `api.anthropic.com/api/oauth/usage` endpoint to read the real 5-hour/7-day account usage
  ceiling, nudging (non-blocking, advisory) to checkpoint state once utilization crosses a
  configurable threshold (default 80%) — only within a goalspec-tracked session. This is a
  materially larger trust surface than any other hook in this plugin (every other one reads
  project-local files or spawns a subagent), confirmed the hard way mid-investigation: even
  *checking whether the credentials file exists* was blocked by the executing agent's own
  permission classifier as a sensitive action. So unlike every other config key, it defaults to
  `false` and ships with its own informed-consent doc, `references/usage-budget-setup.md`, that
  must be read before enabling it. The token itself is never logged, cached, or printed — only the
  resulting percentages are cached locally with a short TTL, in the plugin's own cache file,
  independent of any third-party statusline tool's cache (its credential-lookup and endpoint were
  cross-checked against one such tool's source — `ccstatusline` — since `api.anthropic.com/api/oauth/usage`
  is itself undocumented; this is observed compatibility, not a stable guaranteed capability — see
  the caveat in `references/usage-budget-setup.md`. Also confirmed context-window usage specifically
  has no equivalent persisted, hook-readable source — it is delivered live to a statusline script
  only, never to a hook. This is why context risk is addressed instead through execution
  decomposition, not number-reading — see 0.12.0 below.)
- **Fixed before ship, by an external (different-vendor) adversary review, not by the executor:**
  the macOS Keychain path initially treated the raw `security find-generic-password` stdout as a
  bare bearer token. It is not one — the Keychain secret is the same `{claudeAiOauth:{accessToken}}`
  JSON shape as `.credentials.json` (confirmed against `ccstatusline`'s own `parseUsageAccessToken`,
  which JSON-parses it identically) — so the original code would have sent the whole credential
  blob, potentially including other credential fields, into the Authorization header on macOS.
  Fixed to parse it the same way, and reordered to match ccstatusline's own precedence (Keychain
  first on macOS, file as fallback) rather than the reverse. Caught on the first adversary round: a
  fresh-context, different-tier subagent (opus) returned `hold` and missed it; a different-vendor
  external backend (codex/GPT-5) returned `break` and caught it — the exact reason this plugin
  routes security-sensitive decisions to a genuinely different vendor, not just a fresh context.

## [0.12.0] - 2026-07-22

### Added
- **Context-budget-aware execution decomposition (coverage floor).** Users hitting either the agent's
  own context window or the account's rolling 5-hour usage ceiling on long goalspec-driven loops
  prompted a deep investigation of Claude Code's actual mechanisms (verified against primary docs, not
  assumed — the flagship "188% context" incident that motivated this turned out to be a broken
  instrument in an unrelated plugin, not real exhaustion). Findings landed as an extension to the
  existing **coverage-floor** derived pattern: when the enumerated child entities are independent
  (own file/artifact, no round-by-round shared state) and the task is long enough to risk exhausting
  one context, decompose execution across them — prefer agent teams when available
  (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, experimental/off-by-default) for entities that must stay
  mutually consistent, else dispatch one subagent per entity in parallel and resume the *specific*
  subagent by its returned agent ID for revision rounds, rather than collapsing everything onto one
  resumable subagent (which just relocates the same exhaustion into a single worker).
- **Checkpoint-to-disk + countable stop conditions (execute step).** For multi-round tasks, checkpoint
  state to disk after each major round so a context limit or a session cutoff loses at most the
  in-flight round, not the whole run — mirrors this project's own `/checkpoint-3t` pattern. Prefer a
  countable stop condition (a round/entity cap from the coverage-floor enumeration) over open-ended
  "keep refining."
- **Scope note: don't re-invoke `/goalspec:goalspec` mid-session.** A quantified real-session finding
  (two explicit re-invocations duplicated the full SKILL.md body into context, ~10% of that session's
  content bytes, for zero benefit — auto-trigger already applies the method without re-injecting the
  file) is now documented directly in the Scope section.

## [0.11.2] - 2026-07-20

### Fixed
- **The Stop gate now has a mechanical consumer for "do not close over a `break`."** A live session
  showed an executor declare `[COMPLETION-REVIEW: adversary model=same …]` while the operative
  `[ADVERSARY-VERDICT: break …]` still said `break`, rationalizing it via the convergence-guard's
  "stop iterating" language instead of the existing `[GOAL-CLOSE-WAIVED reason=…]` escape — because
  the gate never actually checked the verdict value, only that the markers were well-formed. "Do not
  close over a break" was a written rule with zero mechanical consumer, the exact instrument-consumer
  defect this method exists to catch. The gate now reads the operative `[ADVERSARY-VERDICT: …]`
  (current-turn-preferred, transcript-fallback — the same precedence already used for
  `[COMPLETION-REVIEW: …]` itself) and rejects a close over a structured `break`, for both
  `[COMPLETION-REVIEW: adversary …]` and the `[COMPLETION-REVIEW: none …]` side-channel. Verdict
  matching requires the full structured grammar (all five `field=n` counts), not a bare word, so
  narrative text mentioning "break" never false-positives.
- **`[GOAL-CLOSE-WAIVED reason=…]` reframed from "operator escape" to explicitly agent-usable.** It
  already worked mechanically, but was undocumented in SKILL.md (only in the hook's own comments) and
  labeled in a way that read as human-only — so an executor stuck on a residual break it judged
  non-actionable had no visible honest path and reformulated the completion-review instead. Now
  documented in SKILL.md's completion-review grammar and convergence-guard sections, and in
  README.md, as usable by the agent itself: the honest, greppable way to override a break you've
  judged non-actionable, versus a completion-review that silently disagrees with its own verdict.
- **Verdict-precedence ordering bug**, found by an external-vendor adversary review of the fix above
  before release: the first pass compared verdicts positionally across the concatenated
  `lam_text + tx_text`, which inverts recency — since historical transcript content is appended
  *after* the current turn, any older structured verdict still sitting in the transcript (e.g. an
  earlier round's `hold`) could outrank a live `break` in the current turn. Fixed by matching
  `lam_text` and `tx_text` separately with `lam_text` preferred, mirroring the completion-review
  match's existing precedence exactly.

### Known limitation
- A non-canonical `[ADVERSARY-VERDICT: …]` (reordered or extra fields, deviating from the documented
  grammar) fails open — it isn't recognized as a structured verdict, so a break in that shape can't
  block a close. This is consistent with the project's fail-open philosophy and the documented
  grammar the adversary is instructed to emit; noted here rather than left silent.

## [0.11.1] - 2026-07-19

### Added
- **`adversary.backend: "external"` now has a mechanical consumer — a PreToolUse hook that nudges the
  agent to actually route to it.** Choosing the external backend (codex / a different vendor) was a
  prose instruction in the SKILL that the executing agent had to remember to read every run; nothing
  enforced it, so an agent — and the fleet — would default to the zero-config subagent path and silently
  never run the configured independent adversary. That is a config emission with no consumer, the exact
  instrument-validity defect the method warns about. The new `hooks/route-external-adversary.sh` fires on
  a `goal-adversary` spawn (Task/Agent) and, when the per-key-resolved config (project → user-global, the
  same precedence `external-adversary.sh` uses) says `backend=external`, injects a one-line reminder to
  pipe the goal-spec + outcome + ask record through `hooks/external-adversary.sh` (the configured
  `external_cmd`). Deliberately **non-blocking and fail-open**: it never denies the spawn (the subagent
  is still a valid context-independent adversary, running *both* is stronger, and blocking could leave a
  host with no adversary at all if the external binary is unreachable — e.g. a sanitized daemon PATH); it
  fires only for a goal-adversary spawn with `backend=external`, and any parse error → silent exit 0.
  Registered as PreToolUse (matcher `Task|Agent`) in `hooks/hooks.json`; unit-tested across all branches
  (fires / silent-when-not-external / silent-when-not-adversary / silent-on-other-tools / fail-open on
  malformed input / no python exception).

### Fixed
- **Stop gate no longer rebounds a correct `model=different` completion-review, and the fragile id-match
  that caused it is gone.** The old parser cross-checked the `model=different (<id>)` parenthetical
  against the adversary's `[ADVERSARY-MODEL: …]` self-report with a **one-directional** substring test
  (`claimed in report`). The natural, honest form — naming *both* models to show they differ,
  `model=different (Sonnet 5 / claude-sonnet-5 vs Opus 4.8)` — made `claimed` a **superstring** of the
  self-report, so the match was impossible by construction and a substantively-verified close rebounded
  with `model-different-claimed-but-no-matching-self-report` even though a correct self-report was
  present (observed: a real close spun 3 extra turns before landing on the bare-id form).

  An attempt to *repair* the matcher (bidirectional substring → id-like-token intersection → positional
  canonical extraction with dotted-id support) was broken **five consecutive times** by two independent
  adversaries — a fresh-context subagent and an external `codex` run on a different vendor (GPT-5): a
  substring collision (`o3` inside `gpt-4o-3-turbo-preview`), an `UNKNOWN`-sentinel leak, a generic-word
  echo (`(fabricated-model vs Sonnet 5)` passing on the shared `sonnet`), prose harvesting (`UNKNOWN /
  requested gpt-5 unavailable` leaking `gpt-5`), and a dotted-version-id false-negative (`gpt-5.1`). Each
  round closed one surface and exposed another. That is the method's own convergence guard firing:
  free-text id-matching from an **agent-authored transcript** is a bottomless proxy, and *you cannot gate
  your way out of specification gaming* (`references/outcome-loop-beats-gates.md`).

  So the check is **simplified** to the one assertion it can make honestly: a `model=different` close
  requires **at least one `[ADVERSARY-MODEL:]` self-report naming a real, non-`UNKNOWN` model id** — the
  canonical id taken **positionally** (single whitespace-free token after the last `/`, carrying a
  letter **and** a digit/hyphen/dot version marker — so `claude-sonnet-5`/`o3`/`gpt-5.1` qualify but a
  bare word like `apology` does not, not the `unknown` sentinel, so a fallback field like
  `UNKNOWN / requested gpt-5 unavailable` yields none). If every self-report is `UNKNOWN`/absent — the harness silently fell back to same-model,
  the *exact honest mistake* this guards — `model=different` is unsupported and must degrade to
  `model=same`. **Deliberately not gated:** id-*precision* (the claimed `(<id>)` need not equal the
  self-reported id) and cross-run *provenance* (a stale self-report from another run in the same session)
  — both are agent-authored-transcript proxies the outcome loop owns, not this marker. New detail slug:
  `completion-review:model-different-needs-nonunknown-self-report`. Guarded by a 20-case acid-test
  (including every adversary counterexample above, `model=same`+`UNKNOWN` passing, and a guard that the
  embedded python raises no exception — a prior round shipped an apostrophe inside the single-quoted
  heredoc that silently fail-opened everything).
- **More actionable advisory text.** The Stop reminder now states that both marker lines must appear in
  the assistant's **own** turn (not only in the subagent's output — a task-notification `[ADVERSARY-VERDICT:]`
  is invisible to the transcript-anchored gate), and that a `model=different` close needs the adversary's
  `[ADVERSARY-MODEL: …]` line naming a real, non-`UNKNOWN` id — else declare `model=same`.

## [0.11.0] - 2026-07-19

### Added
- **User-global config: choose the external adversary once, inherit it everywhere.** A user-global
  `~/.claude/goal.config.json` is now read alongside the project `.claude/goal.config.json`. Resolution
  is **per-key, not whole-file**: each of `adversary.backend`, `adversary.external_cmd`, `sweep_files`
  is taken from the project file if set there, else from the global file. So a global `adversary` block
  makes *every* project route to the external CLI with no per-repo file, while a project file can still
  add `sweep_files` or override a single key **without** nulling the rest. The one key enforced in code
  is `external_cmd` — `hooks/external-adversary.sh` resolves it project→global (tested T1–T5, incl.
  empty/malformed project config falling through, and fail-open when nothing resolves). `backend` and
  `sweep_files` are resolved by `/goalspec` step 6 per the SKILL's identical per-key instruction (the
  executor reads them; no separate script consumes them). `GOAL_CONFIG_PATH` still pins the project layer.

### Why
- Observed in the wild (2026-07-19): a host that **pins plugin subagents to a weak tier** — two real
  `/goalspec` runs on an Opus-4.8 main spawned the adversary with `model: sonnet` (and once with no
  override), and the subagent ran `claude-haiku-4-5` **regardless** — the spawn `model` override was
  dropped by the environment, not by goalspec. The self-report caught it honestly (that mechanism
  worked). The subagent backend can't produce a capable adversary in such a host, but the **external
  backend runs as a shell CLI, not a subagent**, so it sidesteps the pin entirely. Global config makes
  "always use the external adversary" a one-time choice instead of a per-project chore — turning the
  only working path on such hosts into the default the user actually wanted. (The weak-tier pin itself
  is a host bug to fix separately; goalspec's side already did the right thing.)

## [0.10.0] - 2026-07-18

### Changed
- **Ratify gate blast-radius: phrase it for a non-technical user, and a counts-anchored size label —
  never a time estimate.** The audited user's wrong expectation came from authorizing a loop without
  gauging its size. The ratify gate (0.8.0) already shows the blast-radius (*"~80 columns across ~20
  tables + a deploy"*) — this makes that legible to a non-technical reader (*"this changes about 80
  things across your database and pushes to production — not something we can easily undo"*: what it
  touches + whether it's reversible, not jargon), optionally with a coarse **small / substantial /
  large** label anchored **strictly to countable structure** (things touched, reversible vs terminal).
- **Explicitly bans a time/effort estimate.** An earlier draft of this release tried a human-effort
  *time* band per option. Three consecutive different-model adversary rounds broke it as ungrounded:
  converting enumerated structure → a time band needs a per-unit human-effort rate an LLM has no
  calibration for, and coarse buckets don't absorb it (even "80 columns" spans ~1.3h–13h across three
  buckets depending on an unknowable per-column rate — false precision just relocated from the agent's
  own ETA). The convergence guard ("three breaks → the design is wrong, not the wording") retired the
  time approach entirely. What *is* groundable — and equally dimensioning for a non-technical user —
  is countable structure (how much a change touches, and reversibility), which the agent knows from
  the coverage floor. So the plugin dimensions by *what it touches*, never by *how long it takes*. A
  fitting close: the minimal-fix lens shipped in 0.9.0 caught this very release starting to build an
  estimation subsystem when a phrasing touch on existing blast-radius was the whole fix.

## [0.9.0] - 2026-07-18

### Added
- **Surface-the-minimal-fix lens (Q2) — the systemic frame must not eat the symptom-fix option.**
  Q1 ("real objective behind the narrative") is a reframing lever: right when the user *under*-scoped
  (shallow symptom, deep cause). Its opposite trap is subtle — and, importantly, it is **not** "the
  agent went deep without asking." In the audited session goalspec's clarify step *did* surface scope
  choices, and the user chose depth: they were explicitly offered *"Dejar histórico como está — cero
  riesgo sobre prod"* and picked *"Migración segura acotada (Recommended)"* + *"Implementar, testear y
  deployar (Recommended)"* themselves. The real gap is narrower and grounded: the agent offered three
  *sizes* of production migration but **never put the genuinely minimal option on the table** — a
  reversible read-layer fix for the one timestamp the user actually complained about, touching no prod
  data. The systemic frame pre-empted the symptom-fix, so the user could pick *how big a migration* but
  never *migration vs. no migration at all*. New Q2 lens: name **both** the smallest reversible fix for
  the reported symptom and the systemic fix, and make the minimal one a real choice via the ratify gate.
  Deliberately **not** "always ship the band-aid" — if the minimal fix is genuinely insufficient for a
  correctness the user needs, say so; the point is an honest fork with blast-radius visible, so the
  *user* chooses depth rather than depth being chosen by omission. **Enforced:** the `goal-adversary`'s
  No-harm check now flags executing a systemic/irreversible fix while the minimal option was never
  surfaced — with two mandatory guards (don't flag when the minimal fix was genuinely insufficient and
  they said so; don't flag when the minimal option *was* surfaced and the user chose depth). Requested
  by the user after this audit; the first draft of this lens ("default to minimal, systemic is opt-in")
  was caught by the different-model adversary as ungrounded (it contradicted 0.8.0's own transcript
  finding that the reframe was the method working) and unsafe (it licensed shipping band-aids over
  genuinely-required fixes) — this is the corrected form.

## [0.8.1] - 2026-07-18

### Fixed
- **Stop gate: anchor the completion-review on the LAST declaration, not the first `re.search` match.**
  Found by dogfooding 0.8.0's own close. `hooks/gate-goal-close.sh` builds its scan text as
  `last_assistant_message + entire transcript`, then used `re.search` (first match) to pick the
  `[COMPLETION-REVIEW: …]` to validate — so an earlier *exploratory or malformed* declaration
  permanently poisoned the check even after a correct one was emitted. Concretely: a first summary
  wrote `model=different (Sonnet 5 / claude-sonnet-5, vs my Opus 4.8)` — the trailing `, vs my Opus
  4.8` made the claimed id longer than the adversary's `[ADVERSARY-MODEL: …]` self-report, so the
  substring match failed; a later, clean re-declaration could not rescue it because first-match keeps
  returning the earliest occurrence. The gate now selects the **current-turn** declaration
  (`last_assistant_message`) if present, else the **most recent** one in the transcript — a stale or
  malformed earlier marker can no longer poison a valid close. Verified: malformed-then-clean now
  passes; malformed-only and genuinely-unmatched-self-report still block. (Instrument-validity on the
  method's own tooling — the same class of defect the 4th derived pattern exists to catch.)

## [0.8.0] - 2026-07-18

### Added
- **"Ratify the spec before you execute" — the plan-mode checkpoint (root-cause fix).** New
  first-class step (4b) between *emit spec* and *execute*. Once the goal-spec is written, the user
  still hasn't seen what the terse request *became* — "resolve the dates" spec'd into an ~80-column
  migration + a prod deploy while the user only asked about a label reading "6h ago." Conditional
  (fires when the spec is non-trivial, contains a terminal/irreversible action, or the work outgrew
  the trigger request; skipped for trivial specs so it never adds ceremony to a one-liner) and
  portable (one `AskUserQuestion` summarizing objective + blast-radius + terminal action, with
  Approve / Narrow / Minimal-fix / Stop; least-irreversible default when a terminal action is
  present; native plan mode optional where the harness has it). This is the checkpoint the audited
  session lacked: the spec was correct and the execution competent, and it *still* felt like it
  "dragged on for an hour" purely because the user never got to approve the scope the (correct)
  reframe produced. Requested directly by the user after they read this audit.
- **"When the work outgrows the request" — signal the reframe early, don't run dark.** Companion
  section, derived from the same session (a "why does it say synced 6h ago?" the user misdiagnosed as
  a server-clock display bug, which goalspec correctly reframed into a real per-row
  timestamp-corruption migration across ~20 tables + a prod deploy). The transcript decomposed to
  **~1.5h of dense agent activity out of 8.26h wall-clock (~18%)**; the other ~82% was long gaps with
  no logged agent action. Crucially — corrected by the user's primary-source account — those gaps
  were **not** the user being away: they were **present and waiting**, interrupting mid-run (*"Listo?"*
  ×2) because the agent looked stuck while it worked silently or blocked on the ~100-min adversary run
  / deploy rebuild (the agent itself later opened with *"perdón — llevo rato en modo silencioso"*).
  So "it took too long" was dominated by **silent long-running stretches watched by a present user**,
  not by inefficient work. Fixes: (1) surface a **cheap coarse fork** before sinking the full
  coverage-floor enumeration; (2) drop a **one-line progress beat** at natural checkpoints so a long
  silence never reads as "abandoned."

### Changed
- **Least-irreversible default for scope/terminal forks.** The `AskUserQuestion` convention "make the
  first option the recommended default so the user can proceed in one click" one-click-shipped a
  **production deploy** in the audited session (the *Alcance* modal defaulted to "Implementar, testear
  y **deployar** (Recommended)"). The rule now carries a hard exception: for a **scope** or
  **terminal-authorization** question, the recommended default is the **least-irreversible option that
  still meets the confirmed objective** — the terminal/maximal option goes in as an explicit
  *non-default* choice. Updated in all three carriers (clarify step, "Decisions you find mid-run",
  and the run-loop step-2 summary) per rule-surface enumeration. (Note: the audited session's
  *Históricos* modal already defaulted correctly to the conservative middle option — the footgun was
  isolated to the terminal-action question, so the fix is scoped there, not a blanket "default to
  smallest".)

## [0.7.1] - 2026-07-16

### Fixed
- **Third transcript-identity trap: never disown the parent by content overlap.** During the 0.7.0
  release verification itself, the different-model adversary excluded the executor's live session
  file from its ask sweep after finding its own spawn-prompt text inside it — reading "contains the
  text I was launched with" as "this is my own transcript". The inference is exactly backwards: the
  parent session *necessarily* records the `Task`/`Agent` `tool_use` that launched the subagent
  (prompt verbatim), and it keeps growing while the subagent runs because the main conversation is
  progressing. Two verification rounds were burned reporting a phantom missing-session while the
  `AskUserQuestion` pair sat in the dismissed file. The agent def now names the trap alongside the
  existing two (never newest-mtime, never text-grep) and upgrades the positive control to a
  mechanical identity check the adversary can run without trusting anyone: **find your own spawn
  record in the candidate file — the file that contains the prompt you actually received is the
  live parent, the one that must hold the ask.** The external backend's prompt carries the same
  rule for its stdin payload (overlap with your payload identifies the live parent; it does not
  make the file yours). The case-study reference (`references/instrument-validity-own-tools.md`)
  records the incident as **instance 6** — a carrier this release's own first pass left stale,
  caught by the verifying adversary running the rule-surface enumeration against the release
  itself (the 0.6.0 mechanism working as designed, on the doc that documents it).

## [0.7.0] - 2026-07-16

### Added
- **Size-aware grounding: an inline branch the spec previously didn't license.** "Ground yourself
  before you spec" modeled acquisition as binary — *skip* (terrain known) or *delegate* (subagent) —
  with inline reading existing only as the degraded no-subagent fallback. A user-reported
  production run on Fable exposed the gap (session-status evidence: grounding that needed ~10
  targeted operations — 1 pattern, 1 file read, 3 dirs, ~3.6k tokens at 7% context — was correctly
  done inline, against the letter of the spec), and the harness's own
  delegation policy ("single-fact / known-file lookups go direct; delegate when sweeping many
  files") actively steers that way. The step now sizes the acquisition first: **targeted** (you can
  name the exact few files/queries; what you read is what you keep) → inline; **broad** (you'd sift
  far more than you'll keep — many files, unknown locations, web research) → delegate. The test is
  **context hygiene, not command count** — spec-compliant behavior no longer costs a spawn that
  saves nothing.
- **Cheap tier for the explorer — the 0.5.0 adversary rule, mirrored.** The adversary spends
  capability *up* a tier because independence is its product; the explorer saves capability *down*
  a tier because its output is re-derived input. Mechanical explorations (locate/enumerate/cite)
  now default to a `model` override targeting a cheaper tier (`haiku`-class or the harness's
  smallest); judgment-heavy explorations (weighing prior-art, characterizing subtle behavior) keep
  the session tier — a cheap model that mis-summarizes terrain poisons the spec it was meant to
  ground. Deliberately **no self-report and no marker**, unlike the adversary: a silently-ignored
  override loses nothing because the explorer's independence is not load-bearing (its synthesis is
  re-derived input either way, and stays subject to the red-team and the adversary).

## [0.6.0] - 2026-07-16

### Added
- **Fourth derived pattern: instrument-consumer trace + rule-surface enumeration.** Five defects
  shipped in this method itself had one shape — an instrument requesting evidence that nothing
  consumes, or whose input can be satisfied by non-evidence (see the new
  `references/instrument-validity-own-tools.md` for the case study). The red-team's "turn this on
  your own instruments too" phrase demonstrably did not prevent instance 5 (it shipped *during*
  the release fixing its neighbor, and was caught by two independent Sonnet passes, not by the
  method). The mechanism is **conditional — it fires only when the change adds or modifies an
  instrument or a written rule**, so a run that touches neither pays nothing (user-ratified
  design). Executor side: for each instrument touched, name the consumer of every emission and
  check the consumer can't be satisfied by non-evidence; for each rule changed, grep its key terms
  and update or exempt every carrier found. Adversary side (subagent def + external prompt): the
  same sweep run from outside, with `ungrounded` for consumer-less emissions and `incomplete` for
  stale rule carriers.
- **Both empirical branches of 0.5.0 observed live.** (a) The installed 0.5.0 agent def emits
  `[ADVERSARY-MODEL: …]` **spontaneously** — a spawn prompt that never mentioned the self-report
  got it anyway, corroborated by 24/24 `"model":"claude-sonnet-5"` entries in the subagent's own
  transcript (the 0.4.0 def omitted it twice even under explicit prompting; contract-in-def works
  where contract-in-prompt didn't). (b) The `UNVERIFIABLE-BY-THIS-BACKEND` abstention branch was
  exercised for the first time with a partner that **genuinely** could not read the session log
  (an OS-level sandbox denying reads under `~/.claude/projects`): the partner diagnosed the exact
  scope of its own blindness, reported UNVERIFIABLE, and did **not** count the unverifiable ask —
  honest abstention, exactly as specified.

### Changed
- Step-6 tier examples generalized to a dynamic rule that doesn't age: "running any tier above
  Sonnet-class → spawn `sonnet`; running Sonnet-class or below → spawn `opus`" — no model-family
  names to fall out of date (user-ratified over naming new families explicitly).

## [0.5.0] - 2026-07-16

### Added
- **Different-model adversary by default for terminal actions — zero install, zero config.** The
  evidence (v0.4.0, recorded in the repo memory): 6 same-model fresh-context adversary rounds
  accepted a false load-bearing premise — round 6 explicitly blessed it — and a different model
  refuted it on first contact, by doing the thing the premise called impossible. Fresh context buys
  independence from the *conversation*, never from the *model's priors*. Yet the only
  different-model path was opt-in, config-gated, and dependent on an external CLI that can be absent
  or broken. Now, when closing a terminal/irreversible decision, the executor reads its **own**
  model from its context and spawns `goal-adversary` with a per-spawn `model` override on a
  different tier (Opus-class executor → `sonnet`; Sonnet-class or below → `opus` — verification is
  the wrong place to save capability). Verified by controlled experiment before building: identical
  probes to the plugin-provided agent, differing only in the override, self-identified as Sonnet 5
  vs the executor's Opus 4.8.
- **`[ADVERSARY-MODEL: <name> / <id>]` self-report opens every adversary output** (subagent and
  external backend both). The routing parameter is *not* evidence that routing happened: the harness
  documentedly **falls back silently** to the inherited model when an override can't be honored, and
  `external_cmd` can be a broken wrapper. Only the partner can attest what it is. The executor
  copies the self-report — never the spawn parameter — into the completion-review as
  `model=different (<id>)` or `model=same`.
- **The self-report has mechanical teeth, not just prompt text** — added after two *independent
  Sonnet reviews of this very change* converged on the same finding: the model line was requested in
  three prompts and enforced by zero code paths (the exact "check without evidence intake" failure
  the method warns about). Now `external-adversary.sh` extracts `[ADVERSARY-MODEL: …]` (rejecting
  the prompt's own `<model name>` template, as `VERDICT_RE` rejects `<n>`) and flags its absence on
  stderr as independence-UNVERIFIED; and the Stop gate cross-checks a `model=different (<id>)`
  completion-review claim against a matching self-report in the turn — advisory, fail-open, like
  every other gate branch.

- **A `hold` must show the work — the bare-hold gap is closed the same way.** Real case: a partner's
  third round returned a naked `hold` with zero bullets after two rounds of showing all its work.
  Now the agent contract states a hold's bullets change subject (what was attacked, what held) rather
  than disappear; `external-adversary.sh` mechanically flags a verdict with no evidence lines above
  it as UNVERIFIED on stderr (a floor, not proof of diligence — filler can game it; the lever remains
  the executor treating UNVERIFIED as UNVERIFIED); and the skill instructs the executor to never cite
  a bare hold as verification. Found in round 2 of this release's own dogfooding: the adversary
  caught the executor closing over the open pendiente that documented this exact gap.

### Changed
- **Degradation is announced, never silent** (fail-open preserved): same-or-UNKNOWN self-report →
  the verdict still counts, but the completion-review must disclose `model=same` — the exact pattern
  of the external backend's UNVERIFIED hold. No harness override, single-model account, non-Claude
  harness: proceed same-model and say so. Nothing blocks.
- **`external` backend repositioned, not demoted**: the subagent override decorrelates across tiers
  of one family; `external` decorrelates across **vendors** — still the strongest form and the only
  lever left on a single-model harness. (The backend that caught the v0.4.0 premise stays exactly
  where it was.)

## [0.4.0] - 2026-07-16

### Added
- **"Decisions you find mid-run — route them, don't narrate them" — the ask door no longer closes
  when the spec is committed.** Observed failure: after emitting the goal-spec, the agent would
  surface real forks in prose ("two decisions are yours"), list them well, and keep going — the
  human got a paragraph, never a question, and the run closed with the decision dangling. The
  mechanism was structural, not a lapse: (1) the only section teaching `AskUserQuestion` was titled
  "Clarify **before** you commit" and sat at step 2, so a fork *discovered during the work* — which
  is where most real forks live — had no affordance left; (2) Q5 asked the agent to *classify* which
  part is a human decision, and Completeness was satisfied by "every factor has an owner", so
  labeling owner=human **felt like discharging it**; (3) all mechanical pressure at close pointed at
  the `[COMPLETION-REVIEW]` marker, so an unasked decision cost the agent nothing. A new section
  makes the ask door stay open for the whole run, with a **decision-vs-doubt test** (route what turns
  on their intent/priorities/authorization *and* changes the work; never route what you can settle by
  reading the repo — that violates Autonomy just as hard), batching, recommended defaults, and
  "asking ≠ blocking".

### Changed
- **Q5 (Autonomy) reframed from labeling to routing** — naming a human decision is a *promise to
  ask*, not a filing category. An unasked decision is not owned.
- **The red-team gained the mirror check** — the Autonomy self-critique asked only "am I handing a
  human something an agent could execute?" (over-delegating). It now also asks the inverse: did I
  name a decision as theirs and never ask it?
- **`goal-adversary` now counts a dead handoff as an `autonomy-violation`** — both directions of the
  Autonomy failure are attackable, and a new mechanical **dead-handoff sweep** takes every Q5 human
  decision plus every fork the outcome hands the user and demands the place it was actually *asked*.
  Per the method's own philosophy (`references/outcome-loop-beats-gates.md`), the teeth go in the
  independent adversary, not in another Stop-hook regex over natural language.
- **The adversary verifies the ask against the session transcript — a source the executor doesn't
  author.** Found by running the adversary on this very change, twice; it returned `break` both times.
  First pass: the dead-handoff sweep had been added to an instrument that couldn't see the thing it
  checked — the adversary was handed only the goal-spec, the outcome, and the location of the work, so
  its only evidence was the executor's prose about the decision, the exact artifact the check exists
  to distrust. Second pass, on the fix for the first: adding an executor-supplied "ask record" to the
  intake **moved the trust without grounding it** — prose-A ("I surfaced it") became prose-B ("I asked
  at X, they said Y"), and both are text the executor types, so a narrating agent and an asking agent
  stayed indistinguishable. The adversary proved the real ground-truth was two commands away, and that
  the file already knew the pattern: the sibling inherited-decision sweep (`goal-adversary.md:24`) says
  "glob for them… grep them **yourself**". So the dead-handoff sweep now has the same **self-discovery verb** — it locates
  the session transcript itself and greps for the `AskUserQuestion` tool_use / tool_result pair. The
  executor's record is demoted to a *pointer to check*. An ask claimed but unverifiable in a source the
  executor doesn't control counts as a violation, per the agent's standing "uncertain → `break`" rule.
  A third pass then broke *that*: the hand-derived transcript path was wrong (`.` also maps to `-`, so
  any dotted cwd missed the glob — and combined with the new fail-closed rule that manufactures
  spurious `break`s), and the sweep never scoped to **this run**, while its sibling action-marker check
  (`goal-adversary.md:23`) does — this repo's transcript dir holds three sessions, all three containing
  an `AskUserQuestion`, so
  a prior session's ask would have blessed an agent that narrated today. The sweep now identifies the
  live transcript **by content** instead of trusting a derived path, and scopes the search to this
  session. A fourth pass then *executed* the instruction and landed on the wrong file — proving the
  newest-mtime tiebreak was a systematic anti-selector (subagent logs are written while the adversary
  runs, so they are always newer than the parent, and a subagent has no `AskUserQuestion` tool, so they
  can never contain an ask), and that a text-grep blesses prose that merely quotes the question. The
  sweep now reads the top-level session file only, matches the `tool_use`/`tool_result` **structure**
  rather than text, and requires a **positive control** — confirm you are reading the live session log
  before concluding an ask is absent, because a broken instrument is a null result with two disjoint
  causes, not proof of a dead handoff. "Confirmed dead handoff" and "unverifiable claim" are now
  reported as distinct outcomes (both count, but the executor can tell which to fix).
- **The `external` adversary backend carries principle 4 too — and is honest about the one check it
  can't run.** `hooks/external-adversary.sh` had kept principle 4 in its pre-fix, one-directional form
  ("nothing an agent could execute should be handed to a human"), so every user on
  `adversary.backend: "external"` would have gotten none of this while the changelog claimed both
  directions were attackable. Caught by the fourth adversary pass as a coverage-floor miss: the two
  documented backends were never enumerated. The fifth pass then broke the first repair — the
  *principle text* had shipped to the external backend but not the *evidence path*: an external CLI runs
  outside the session, so the positive control ("confirm you're reading **this** run's log") has no
  "this run" to anchor to, and the script piped only goal-spec + outcome anyway. Under the script's
  standing "cannot verify → count it" rule that would have manufactured a `break` on a genuinely correct
  ask. So: the ask record is now piped to the external partner, and principle 4 there tells it the ask
  record is a pointer, to **test its reach** and go read the session log if it can, and to report
  `UNVERIFIABLE-BY-THIS-BACKEND` (not counted) only if it genuinely cannot — an unreachable instrument
  is not a finding, but an unchecked one is just laziness.

### The correlated-bias result (why the `external` backend earns its keep)

Six adversary rounds were run against this change, all same-model fresh-context subagents. They found
five real defects. Then a **different model** (`claude -p --model claude-sonnet-5`, via the external
backend) was run on the same outcome — and refuted a premise all six had accepted:

- v0.4.0 had asserted, as fact, that an external partner "runs outside the session, so it cannot read
  the session log," and built the whole `UNVERIFIABLE-BY-THIS-BACKEND` carve-out on it. Adversary #6
  explicitly blessed it as "a real engineering decision, not a rationalization."
- The Sonnet partner falsified it **by doing the thing the design called impossible**: it read the live
  session log and located the `AskUserQuestion` tool_use/tool_result pairs itself. `claude -p` is a
  different *model*, not a different *machine* — same host, same filesystem, same tools.

The carve-out is therefore now **capability-conditional, not backend-conditional**. More importantly,
this is the correlated-bias failure the external backend exists to prevent, demonstrated on the
backend's own documentation: the subagent adversary is context-independent but **model**-correlated, and
six rounds of it could not see a premise the model found plausible. `references/external-adversary-setup.md`
now records this rather than claiming the backends are interchangeable.

### Fixed — instrument-validity in the external backend's own rails

Found by finally smoke-testing `external-adversary.sh` against real CLIs (an item deferred since
2026-07-08; the stub-`cat` test that preceded it proved only that the payload arrives):

- **A present-but-broken CLI produced no verdict at all.** The "missing binary → fail-open" rail checks
  `command -v`, which only proves a *wrapper* is on PATH. A `codex` whose vendored binary is missing
  passes that check, then dies with `ENOENT`, exit 1, and **no `[ADVERSARY-VERDICT:]` line** — handing
  the caller silence that reads as "no objection". The script now captures the run and requires a
  **filled** verdict; a non-zero exit or a malformed reply degrades to an explicit `hold` labelled
  UNVERIFIED, with the partner's output on stderr. (The rail claimed to handle exactly the
  instrument-validity failure it was blind to.) The first cut of this rail was itself broken, and the
  Sonnet partner caught it by *testing* rather than reading: it matched `grep '\[ADVERSARY-VERDICT:'`,
  but **the prompt contains that literal string** as the grammar template — so any CLI that echoes its
  stdin and exits 0 (a debug wrapper, or a plain `cat`) passed the gate and had its unfilled
  **placeholder** printed back as a real verdict. The pattern now demands `(break|hold)` plus numeric
  counts (rejecting both `break|hold` and `<n>`) and takes the last match, so a partner that quotes the
  grammar before answering still resolves to its real verdict. Six branches are covered by test: broken
  binary, missing binary, echo-the-prompt, chatty-no-verdict, quote-then-answer, and well-formed.
- **`gemini -p` was documented as a working `external_cmd` and cannot work.** It takes the prompt as an
  argument, not on stdin, so it can never receive a piped payload. The reference now ships a one-line
  adapter instead of a broken recipe, and flags that `codex`'s install should be verified by running it.
- **Dead-handoff detection is semantic, not a phrase list.** Also found by the adversary: the first
  cut shipped English-only literals (`"your call"`, `"up to you"`) — which would have missed the
  Spanish run that motivated the whole change ("dos decisiones que son tuyas"), while the changelog
  justified skipping hook teeth precisely *because* cross-language regex is fragile. The rationale and
  the artifact didn't reconcile. Both the self-red-team and the adversary now read for the **act**
  (did this sentence put a choice on the human?) in whatever language the executor writes; the phrases
  are illustrations, not the detector.
- The GOOD worked example now models raising the decision as a modal at the decision point, rather
  than as a line in the summary.

### Added — two holes this release's own dogfooding exposed

- **Q2 criteria now get gamed before they are committed.** Nothing in the method red-teamed the *spec*;
  the adversary only ever attacked the *outcome*, by which point the criteria were set. This release
  proved the cost: every one of its own success criteria was "text present in a file" while its
  objective was behavioural — five criteria the executor could satisfy with the very edits it was
  already making. The adversary caught it by quoting the constitution back (`SKILL.md:14`,
  *"marker present" ≠ done*), and it was only closed by running the acid test. Q2 now carries the test:
  *what would a lazy agent do to satisfy this without achieving the objective?* If the answer is "make
  the edit I was already going to make", it is a marker. The tell is an objective describing a
  behaviour against a criterion grepping for text.
- **A convergence guard on the break loop.** Nothing said when to stop patching. This change took five
  consecutive `break`s where **each round broke the previous round's fix** — a loop that could have run
  indefinitely, since every individual patch looked like progress. Step 6 now says: each round should
  break something smaller than the last; at three consecutive breaks the design is wrong, not the
  wording — reconsider the approach or route to a different model.
- **Instrument-validity turned on the method's own tools.** The red-team now asks it explicitly. Every
  expensive defect in this release was the method failing to audit its own instruments: a dead-handoff
  check with no evidence intake, a transcript rule that selected a file that could not hold the
  evidence, a fail-open rail blind to a broken CLI, a verdict gate matching its own prompt template.

### Not changed (deliberate)
- **The Stop gate is untouched.** Detecting "a decision was named" from prose is a regex over natural
  language (and over whatever language the user works in) — fragile, false-positive-prone, and
  exactly the "gate your way out of specification gaming" this method rejects.
- No loop steps were renumbered (the fix folds into existing steps 5, 6 and 7), so the `step N`
  cross-references in `README.md` and `references/external-adversary-setup.md` stay valid.

## [0.3.0] - 2026-07-14

### Added
- **"Ground yourself before you spec" — the agent can now acquire missing context before it commits
  the goal-spec.** A new pre-spec step: if any load-bearing Q2 (success) or Q3 (pre-mortem) claim
  depends on context the agent doesn't have firsthand — how the repo/codebase actually works, what
  the real ground-truth source contains, or the external prior-art / community best-practice — it
  delegates a *bounded* exploration to a fresh-context subagent via the Task tool (whatever agent
  type the environment provides: an `Explore`-style read-only searcher if present, else a
  general-purpose agent) and folds the synthesis into its criteria and pre-mortem. This stops the
  agent from spec-ing off a thin context, which is where shallow goal-specs come from.
- Guardrails baked in so this stays true to the method, not a new rule: **conditional** (skip if you
  already know the terrain — stays a lightweight prefix, not "always investigate"); **fail-open**
  (no subagent / no web / headless → do what you can and record the gap in the Assumptions line);
  **mechanical teeth** (the test is that Q2/Q3 visibly reflect what was found, not a "did I research"
  checkbox); and an explicit firewall — this forward **helper shares the host's frame and is NOT the
  independent adversary**; its output is re-derived and still passes the red-team/adversary before
  close. No new governance marker; it's an application of Grounding + Falsification + Autonomy.

## [0.2.3] - 2026-07-08

### Changed
- **Trigger description now lists common domains instead of a niche one.** 0.2.1 listed
  "even a water-treatment plant" as a domain example — memorable, but too niche for a trigger
  (it signals "for weird edge cases" rather than breadth). Replaced with the domains where users
  actually are: software engineering, data and analytics, marketing, research, writing, and product
  and business decisions. (The water-treatment worked example stays in the adaptation guide, where
  it usefully proves domain-independence.)

## [0.2.2] - 2026-07-08

### Fixed
- **Broken YAML frontmatter in 0.2.1.** The optimized description contained `not just code: software`
  — a colon-space that YAML parses as a mapping, so the skill loaded with **empty metadata** (the
  description was silently dropped, killing auto-trigger). Replaced the colon with a dash. Added a
  frontmatter YAML-parse check to the release routine so this can't recur. Anyone who pulled 0.2.1
  should update to 0.2.2.

## [0.2.1] - 2026-07-08

### Changed
- **Optimized the skill's auto-trigger description** (reviewed via the official skill-creator method).
  The old description listed task *types* but no *domains*, so it read as software/ops jargon and
  risked silently under-triggering on marketing/copywriting/ops/research tasks — undermining the
  zero-config-any-domain design. The new description names explicit domains, adds real-world trigger
  phrasings ("should I kill/ship/publish Y", "figure out why Z dropped", "review this before I
  merge"), and is more directive ("Trigger it whenever…") to counter Claude's known tendency to
  under-trigger skills — while keeping the anti-false-fire clause (no contentless "continue" turns,
  no trivial one-step lookups). Methodology in the body is unchanged.

## [0.2.0] - 2026-07-08

### Changed
- **Renamed the plugin `goal-elaboration` → `goalspec`, and made the skill the single entry point.**
  Claude Code mandates that plugin commands are namespaced (`/plugin:command`), so the old
  `commands/goalspec.md` was only reachable as `/goal-elaboration:goalspec`. Because a skill whose
  name equals its plugin's name renders un-namespaced, naming both `goalspec` makes the skill
  invocable as a clean `/goalspec` (it also auto-triggers). The standalone command was removed and
  its runbook folded into the skill. **Install id is now `goalspec@goal-forge`** — early installers
  of `goal-elaboration@goal-forge` should `uninstall` the old id and install the new one.
- **Zero-config for any domain.** The skill no longer requires `.claude/goal.config.json`. It now
  infers everything domain-specific from the task itself: ground-truth sources (named per-task),
  files to sweep (discovered by globbing decision/TODO/pending docs), which entities to enumerate
  (the task noun), and which actions are terminal (judged per-action). Config survives only as an
  optional power-user override for pinning exact sweep files or selecting an external adversary
  backend.

### Added
- **Clarifying-questions step (anti-drift).** Before committing to a goal-spec, the agent resolves
  load-bearing ambiguity (objective / scope / terminal-action authorization / done-bar) via the
  `AskUserQuestion` modal — so a 30-second question prevents an hour of misdirected work. Balanced
  threshold; when the task is clear it states its assumptions inline instead. Degrades gracefully in
  headless/cron runs.
- **Agent-guided install instructions** in the README: a top-of-file comment for AI agents plus
  terminal-form `claude plugin` commands, team/manual/dev install paths, and uninstall.
- Plugin manifest now carries `repository`, `license`, and `keywords`.

## [0.1.0] - 2026-07-08

### Added
- Initial release: the 5-principle constitution + 6-question goal-spec scaffold + red-team
  (`skills/goalspec`), an independent `goal-adversary` subagent (subagent or external-CLI
  backend), the `/goalspec` command, and a fail-open, transcript-anchored Stop completion gate.
  Genericized from a validated fleet pilot; no control-plane coupling.

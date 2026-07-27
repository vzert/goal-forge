# The durable artifact — one file, one writer, for whoever picks the work up next

`SKILL.md`'s Execute step tells you to checkpoint a long run to disk, and its coverage-floor
decomposition tells you to keep a few facts consistent across per-entity workers. Both are the
same problem: **a fact that has to survive outside one agent's context**. This file gives that
fact a single home.

**What this is not.** Nothing in the plugin reads the checkpoint. `gate-goal-close.sh` never
opens it; no hook parses it; **nothing gates its absence** — a run that never writes one closes
exactly as cleanly as a run that does. The reader is a *resuming agent or a human*, not code —
with one narrow addition: the independent adversary reads it **when and only when** the
executor's step-6 payload points at this file as where the goal-spec or outcome is written
(see "Who reads which section" below for what that reader may and may not treat as a claim).
This is a named place with a shape and an instruction to fill it, not a guarantee that state
survives. Treat a claim that it "closes the resume gap" as unsupported: the resume mechanism
itself is a human CLI action this harness gives no agent any hook into, and that has not changed.
The gain is narrower and real — the nudge in `hooks/check-usage-budget.sh` ("checkpoint state to
disk now") now points at something executable instead of asking each agent to invent a location.

## Where it lives

`.goalspec/checkpoint.md` at the root of the project you are working in. One file per run, not
per entity — a second checkpoint is a second home for the same fact, which is the defect this
exists to prevent.

It is **run state, not a deliverable**: gitignore `.goalspec/` rather than committing it, unless
the project deliberately wants the trail. Never create it speculatively — write it when the run
actually spans many rounds or you dispatched per-entity workers. A one-round task that leaves a
checkpoint behind has added clutter, not durability.

## What goes in it

Four things, and nothing that already lives somewhere better:

1. **The live goal-spec** — objective, ratified scope, terminal action and its authorization
   status, and the success criteria with their baselines.
2. **The coverage-floor table** — one row per entity or carrier, each with a status. This is the
   part a resuming agent cannot re-derive cheaply, and the part that goes stale silently if it
   is also narrated in prose somewhere else.
3. **Rounds** — one line per completed round: what changed, what the verdict was. Append; do not
   rewrite history.
4. **Next** — the single next action.

Anything already recorded in ground truth — commit messages, the CHANGELOG, the test output —
gets **pointed at, not copied**. A derived figure with two homes goes stale; that is not a
hypothetical, it is the failure mode that produced multiple shipped defects in this method.

## Who reads which section — and which sections carry authority

The four sections do not share a reader or a standing, and this section is the **declaration of
both** — every carrier elsewhere (the adversary's definition, the external backend's inline
prompt) cites it rather than asserting its own version:

- **The live goal-spec and the coverage-floor table are the authoritative current state.** They
  are structured claims about the run and its entities. Their readers are whoever must trust the
  run's state without re-deriving it: the resuming agent, a human, and — in the pointed-at case
  above — the adversary. For every such reader these sections are load-bearing: a row claiming
  "done" for an entity that is not done, or two rows that contradict each other, is a real,
  reportable defect, exactly like any other load-bearing figure in an outcome.
- **Rounds is append-only history with no authority over current state.** Its reader is the
  resuming agent reconstructing how the run got here; it is the executor's own process log,
  written for itself and its successor. Where a Rounds line disagrees with the table, the table
  is the current state and the Rounds line is history — the stale line is not, by itself, a
  reportable contradiction. This is the declaration the adversary's exemption cites: narrative
  in this file is exempt from falsification scrutiny *because its declared reader and standing
  are historical*, not because prose is unimportant.
- **Next is a pointer** to the single next action — read by the resuming agent, never a claim
  that the action happened.

The file as a whole remains "run state, not a deliverable" (see "Where it lives" above); nothing
in this section changes who may write it (see "Verbs").

## Verbs — who may do what to it

This is the load-bearing rule, and it is the one with the strongest empirical backing in the
prior art: when Bun ran a large multi-agent port, worker clobbering appeared within ~2 minutes
and was fixed by **restricting the verbs agents could use on shared state** (banning `git stash`
and `git reset`), *not* by changing the number of agents. Tuning parallelism does not fix a
shared-state race; removing the destructive verb does.

So, concretely:

- **The coordinator is the only writer.** Workers **read**. A worker that needs a shared fact
  changed says so in its return value; you fold it in.
- **Append, don't rewrite.** Rounds accumulate. Rewriting an earlier round destroys the only
  record that the run had a different shape before.
- **No worker may `git stash`, `git reset`, `git checkout --`, or otherwise revert shared
  working state.** A worker that thinks the tree is wrong reports it; it does not repair it.
  Two workers "repairing" concurrently is exactly the clobber.
- **One file, one writer** generalizes past this file: if per-entity workers each own their own
  artifact, no two of them may write the same one.

## The worker brief points here

When you dispatch per-entity workers, the facts that must stay consistent across them go **in
this file**, and each worker's brief **points at the path** — it does not carry a re-narrated
copy. Relaying the facts through your own prose gives every fact two homes (yours and each
worker's brief) and they diverge round by round. Alongside the pointer, each brief still needs
its own objective, output format, tool guidance, and boundaries; without those, independent
workers duplicate each other's work.

## Two adjacent practices, and exactly what is *not* covered

The same prior art pairs the shared artifact with two further practices. Each has a near-neighbour
already in this method — and in both cases the neighbour is **narrower**, so "already handled"
would be false. What is stated here is the gap, not a claim to have closed it:

- *Review the shared artifact adversarially before it becomes shared state.* Step 6 routes your
  **outcome** to an independent adversary at close. It never *requires* that adversary to open
  `.goalspec/checkpoint.md` — the adversary reads it only in the pointed-at case, and then under
  the per-section authority above — and it fires **after** workers have already read the file.
  The gap is timing: nothing verifies the shared facts before they are consumed.
- *A dedicated pass reconciling contradictions between artifacts.* The rule-surface enumeration
  greps every carrier of a **rule you changed** and updates or exempts each one. That catches a
  rule left stale in a second carrier — it is not a pass over two arbitrary work products (say a
  design doc and a data file) that disagree with each other.

Neither gap is filled here. Restating the neighbours would give an existing rule a second home,
which is the defect this file exists to prevent; building new machinery for a configuration this
method has never been observed to reach would be worse. They are written down so the limit is
visible to whoever hits it.

# The durable artifact — one file, one writer, for whoever picks the work up next

**Contents**: [Where it lives](#where-it-lives) · [When it goes away](#when-it-goes-away) · [What goes in it](#what-goes-in-it) · [Who reads which section — and which sections carry authority](#who-reads-which-section-and-which-sections-carry-authority) · [Verbs — who may do what to it](#verbs-who-may-do-what-to-it) · [The worker brief points here](#the-worker-brief-points-here) · [Two adjacent practices, and exactly what is *not* covered](#two-adjacent-practices-and-exactly-what-is-not-covered)

`SKILL.md`'s Execute step tells you to checkpoint a long run to disk, and its coverage-floor
decomposition tells you to keep a few facts consistent across per-entity workers. Both are the
same problem: **a fact that has to survive outside one agent's context**. This file gives that
fact a single home.

**What this is not.** `gate-goal-close.sh` never opens it, and **nothing gates its absence** — a
run that never writes one closes exactly as cleanly as a run that does. The reader is a *resuming
agent or a human*, not code — with two narrow, additive exceptions, neither of which changes that:
the independent adversary reads it **when and only when** the executor's step-6 payload points at
this file as where the goal-spec or outcome is written (see "Who reads which section" below for
what that reader may and may not treat as a claim); and `hooks/nudge-decompose.sh` (0.28.0) — a
`Stop` hook, reads only the `## Coverage-floor table` heading and its row count to decide whether to
print an advisory nudge, never the goal-spec or Rounds/Next sections, and stays silent when the file
is absent, the heading isn't there, or **the file was not written by the session it is running in**
(see "Where it lives"). Both readers are consumers of what this file already is; a run that never
writes one is invisible to either.
This is a named place with a shape and an instruction to fill it, not a guarantee that state
survives. Treat a claim that it "closes the resume gap" as unsupported: the resume mechanism
itself is a human CLI action this harness gives no agent any hook into, and that has not changed.
The gain is narrower and real — the nudge in `hooks/check-usage-budget.sh` ("checkpoint state to
disk now") now points at something executable instead of asking each agent to invent a location.

## Where it lives

`.goalspec/checkpoint-<session>.md` at the root of the project you are working in. One file per
run, not per entity — a second checkpoint is a second home for the same fact, which is the defect
this exists to prevent.

**`<session>` is HANDED to you where it can be, DERIVED where it cannot, and never chosen.**

On Claude Code, `hooks/announce-checkpoint-name.sh` (a `SessionStart` hook) names the exact file at
the start of every session: **use that path verbatim.** The token is the session identifier the
harness itself reports — the hook can read it, you cannot — so you neither derive it nor guess it.

Stated no wider than that on purpose. The harness *documents* the `session_id` field; it does not
publish a uniqueness guarantee, so "two sessions cannot collide" is not ours to say, and an
adversary round caught this section saying it. What the announcement removes is the agent inventing
distinctness it has no access to — which was the actual complaint against every earlier draft of
this rule — not the theoretical possibility of a collision.

Only if no name was announced (a different harness, an older install, the hook disabled) do you
derive one, from whatever the environment does vary per session — the transcript path is the best
of these, being the same identifier under another name. A pid or a timestamp is weaker and an
adversary round said so correctly: neither is distinct in the limit (pids repeat across hosts, two
sessions can start inside one second). This branch is a fallback, not a guarantee, and it is the
branch where the residual below is real. What you must not do in either case is *pick* a slug — two
agents asked for "a short random slug" are not two independent draws, they are the same model
reaching for the same obvious word.

And do not reach for the check that suggests itself here: **listing `.goalspec/` and picking a
name that is not taken is not a fix**, it is a check-then-write, and two sessions can pass it in
the same instant and then both write. (An adversary round caught exactly that phrasing in an
earlier draft of this section, correctly: a non-atomic check dressed as a guarantee is worse than
no check, because it reads like one.) Derivation needs no check at all, which is the point — a
name computed from facts that already differ cannot collide with a name computed the same way
somewhere else. If your environment truly offers you no distinguishing fact, then say so in the
run: that is a real limitation to disclose, not a gap to paper over with a lookup.

**Why the name carries a session token, and the two rules that follow from it.** A single fixed
path (`.goalspec/checkpoint.md`, what this said before) is shared state between every session that
happens to run in the same project — and two agents working the same repo at the same time is not
exotic, it is Tuesday. Two concurrent sessions clobbered each other at that path, live (the
incident is recorded under "When it goes away"). The name is the cheapest prevention there is:
sessions whose tokens are derived from facts that already differ do not open the same file, so
the collision is avoided without any check having to fire at the moment of writing.

**What that is not: a lock.** This design removes the *shared* object. It does not provide mutual
exclusion, and the naming rule by itself arbitrates nothing: two sessions that end up with the same
token land on the same path and the name does not stop them.

One thing IS refused, and by code rather than by rule — `hooks/precheck-checkpoint-overwrite.sh`
denies a write over a checkpoint that already exists and that the writing session never
successfully wrote (see "What IS enforced" below). That is arbitration of a contended file, so this
paragraph no longer says it cannot happen; an adversary round on the release caught the older
wording contradicting the gate shipping beside it. What it still is not is a lock: nothing
serializes two sessions creating the same path at the same instant, `Bash` is not matched at all,
and a checkpoint written through a shell heredoc is invisible to the ownership test. That is why the rule above is *use what you
were given, derive only when you were given nothing, never pick*: it moves the guarantee from a
promise about behavior (which nothing here enforces) to a property of the input. Two adversary
rounds on the change that introduced this were spent on this exact sentence — the first draft
claimed sessions could never collide, the second offered a check-then-write as the safety net.
Neither was true, and both were the agent trying to manufacture uniqueness it had no access to.
The announcement removes the need: where it arrives, the token is the session id. Where it does
not, the residual is real and disclosed rather than hidden.

**What IS enforced, and the one thing that is not.** `hooks/precheck-checkpoint-overwrite.sh`
(`PreToolUse` on `Write|Edit`) refuses at most one act: writing over a checkpoint that already
exists and that the writing session never successfully wrote. It fails OPEN on everything before ownership is asked about (a payload it cannot parse, a path
that is not a checkpoint, a file that does not exist yet) and CLOSED on ownership itself: no
readable transcript means it cannot establish the file is yours, and at that point the target is
already known to be an existing checkpoint here, so it denies. An earlier cut allowed there; an
adversary round rated that unsafe and the justification for it — that denying would break harnesses
supplying no transcript — did not survive an audit of the hooks reference, where `transcript_path`
is a common field of every event with no documented absence condition. A wrong deny is always
escapable: write under your own announced name, which is never blocked because it does not exist
yet. That is the incident, and nothing else — a name
that merely differs from the announced one is not refused, because creating a file where none
exists harms nobody and a project keeping a committed trail under its own names is a case this
document blesses. What is NOT enforced, then, is the naming rule itself: an agent that ignores the
announced name and creates its own is not stopped, only one that reaches for somebody else's file
is. Two further limits, so the gate is not read as more than it is: it decides ownership from the
transcript, so a checkpoint written through a shell heredoc is invisible to it, and `Bash` is not
matched at all. So:

- **Never write to a checkpoint file this session did not create.** One you find in `.goalspec/`
  is either another session's *live* state or a leftover from a run that stopped; in both cases it
  is not yours to overwrite. Read it if it helps you resume, then write your own, under your own
  derived name. The legacy `.goalspec/checkpoint.md` name is still read and still adoptable — this
  is a rename for new files, not a break for old ones.
- **Write it with the file tools (`Write`/`Edit`), not a shell heredoc.** Ownership is what lets a
  reader tell your checkpoint from someone else's, and it is derived from the session transcript —
  a `Write`/`Edit` tool call for that path is the evidence. A file conjured by `cat > … <<EOF`
  leaves no such record, so `hooks/nudge-decompose.sh` will treat it as somebody else's and stay
  silent about it. Nothing breaks; you just lose the nudge.

That second rule is the whole content contract, and it is deliberately *not* a new one: no stamp,
no header, no id written **inside** the file. The transcript already records who wrote what, which
is the same evidence `hooks/lib/terminal_actions.py` reads to find a goal-spec written to disk.

It is **run state, not a deliverable**: gitignore `.goalspec/` rather than committing it, unless
the project deliberately wants the trail. Never create it speculatively — write it when the run
actually spans many rounds or you dispatched per-entity workers. A one-round task that leaves a
checkpoint behind has added clutter, not durability.

## When it goes away

**Exception first, since it qualifies everything below**: a project that deliberately committed
`.goalspec/` for a trail instead of gitignoring it (see "Where it lives" above) is keeping that
history on purpose — don't delete on close in that case. Everything that follows targets the
default, gitignored case, where the file is local run state with no other record of it.

Retire it at the event that ends the obligation to keep it: a clean close. When the run that
wrote it — or, on resume, adopted an existing one — reaches its close (the goalspec skill's step
7, or the standalone `/goalspec:adversary` command's own step 5, which has no step 7 of its own),
**delete the file**, not just its contents: a truncated or "CLOSED" placeholder is still a file a
resuming agent or a human reads as live state, and — since this session did write it — still one
`nudge-decompose.sh` will read, shaped like a populated coverage-floor table. Delete it
after any adversary verdict it fed has been quoted and no backend is still in flight (step 6 may
point the adversary at this exact path), and only the coordinator does it — workers never touch
this file either way (see "Verbs" below).

A run that never reaches its close — a crash, a killed session — leaves the file in place, on
purpose: that is the resume case this file exists for, not a defect.

Retire **your own** file and only your own. Another session's checkpoint sitting in the same
directory is not litter for you to sweep up — it may be the live state of a run that is still
going.

**Two live incidents, and the alternative that was declined and then adopted.** The first: a
leftover from a *cleanly-closed* run (v0.28.0, `f148d6c`, already shipped) sat in a working
directory and made `nudge-decompose.sh` nudge on every turn of a later, unrelated session. The fix
chosen then was write-side retirement (above). A read-side alternative — teach the hook to tell
"this session's checkpoint" from somebody else's — was considered, not ruled out as impossible,
and **declined**: it cost a new content contract on the file plus a new read-side check, to close
a gap with exactly one confirmed occurrence, which was a clean close. That paragraph named its own
unlock condition: a second incident to weigh against the cost.

The second incident arrived (0.38.0) and it was a different failure, not a repeat:
two agents working the same project **concurrently** both wrote `.goalspec/checkpoint.md`, and one
destroyed the other's live run state. Write-side retirement cannot touch that — the loser's file
was not stale, it was in use. So the alternative was adopted, in a form that turned out cheaper
than the one costed in 2026: ownership is read from the **session transcript** (a `Write`/`Edit`
tool_use for that path), so the "new content contract" the original estimate priced in never
had to exist. Prevention lives in the per-session filename; detection lives in the read side. What
the read side buys, beyond the collision itself:

- `hooks/nudge-decompose.sh` reads only checkpoints this session wrote. A foreign one, or a
  leftover from a run that crashed and was never resumed, is ignored by construction — **the
  residual this section used to list as open is closed**, and by the mechanism that section
  predicted, not a different one.
- `hooks/lib/terminal_actions.py` recognizes the per-session name as a goal-spec written to disk,
  the same way it recognized the fixed one. It was already session-scoped by construction (it reads
  only this session's transcript), so it needed the new name, not a new notion of ownership.

**What this still does not cover.** A checkpoint written by a route the transcript does not record
(a shell heredoc rather than `Write`/`Edit`) is indistinguishable from a foreign file, and the
nudge stays silent on it — chosen deliberately over nudging about a file that may not be ours, and
named in "Where it lives" as a write-side rule so the loss is avoidable rather than mysterious.
Retirement at close is still write-side and still uncoerced: an agent that skips it leaves a file
behind, and the only cost now is clutter in `.goalspec/` for a human to read past, not a
false-positive nudge in the next session.

**The nudge's window on the final turn.** Deleting at close means the Stop that follows reads no
file, so `nudge-decompose.sh` is silent on that turn by construction — the same shape as the
0.28.0 break where the adversary's own spawn silenced the nudge. It is benign here: the nudge's
useful moment is coverage-floor enumeration time (SKILL.md's Execute step), not close, so losing
the signal on the very last turn costs nothing real. Named here on purpose rather than left for a
fresh reader to flag as the same break twice.

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
both** — the single source every carrier elsewhere is subordinate to. Both carriers restate the
per-section rule inline **by necessity** rather than pointing here and stopping: the external
backend's prompt because the partner cannot read files on this host, and the adversary's
definition because the spawned subagent cannot reliably resolve this reference's path at runtime
(its cwd is the project, the installed cache holds many plugin versions, and other harnesses
relocate the plugin root). Each declares itself a citation of this section, never an owner: where
a carrier's restatement and this section differ, this section wins, and the rule-surface
enumeration must catch both carriers when it changes (grep terms: checkpoint, coverage-floor,
Rounds):

- **The live goal-spec and the coverage-floor table are the authoritative current state.** They
  are structured claims about the run and its entities. Their readers are whoever must trust the
  run's state without re-deriving it: the resuming agent, a human, and — in the pointed-at case
  above — the adversary. For every such reader these sections are load-bearing: a row claiming
  "done" for an entity that is not done, or two rows that contradict each other, is a real,
  reportable defect, exactly like any other load-bearing figure in an outcome. `nudge-decompose.sh`
  is a narrower kind of reader of this same table: it only counts rows under the heading, never
  trusts a row's status text, so a wrong "done" does not affect what it does — only the row count
  and the transcript's own tool_use history do (the latter twice over: to see whether entity
  workers were dispatched, and to see whether this session wrote the file at all).
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
  artifact, no two of them may write the same one. It generalizes past this *run*, too — two
  concurrent **sessions** are two writers, and the prior art's lesson applies unchanged: the fix
  is not coordinating them, it is removing the shared object. That is what the per-session
  filename does ("Where it lives"), and it is why no rule here asks a writer to check whether
  somebody else is using the file first.

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

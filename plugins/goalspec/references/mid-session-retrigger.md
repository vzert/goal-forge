# A closed spec doesn't close the session

## What happened

A real session ran the full loop cleanly: a terse request became a grounded spec, the spec
covered two reversible pull requests, and the agent closed with `[COMPLETION-REVIEW: ...]` —
correctly, since that spec's objective was met and verified. The session kept going. Later in
the *same* conversation, the agent shipped a production release the original spec never
mentioned, and — separately — investigated a question nobody asked, reached a conclusion, and
**wrote that conclusion into a shared memory file the rest of the team reads at session start,
committing and pushing it before showing it to the human**. The conclusion was wrong (a
timezone misread). The human caught it after the fact and the agent had to revert what was
already pushed. (A real incident, re-derived from that session's own raw transcript rather than
a curated summary — the specifics stay in this project's private records; the shape of it is
what's load-bearing here, not who it happened to.)

Nothing in the method was violated on paper. Before this section existed, `SKILL.md` never said
a completion-review is scoped to anything narrower than "the session." So an agent reading it
literally had no reason to believe the discipline it just finished applying — clarify, ratify,
red-team, adversary — still applied to whatever it did next in the same conversation.

## Why documented, not mechanical

The tempting fix is a hook: watch tool calls for a `git push`, a deploy command, a write to a
known shared-state path, and force re-entry when one fires after a completion-review. This
project has built that shape of thing three times before — a match on the *string identity* of
an adversary's self-reported model, a dedup key on the *literal text* of a verdict line, a
loop-boundary counter — and all three lost the arms race: the id-matcher broke across five
correction rounds, the verdict dedup silently under-counted identical strings hiding distinct
findings, and the loop-boundary counter is structurally blind to anything that happens without a
`Stop` between turns. A detector for "is this tool call a new terminal action" has the same
shape: it would need to distinguish a release script from a status check, a write to a shared
learnings file from a write to a scratch file — by pattern, forever chasing new phrasings. This
project's own history says that fight is not winnable by building a smarter matcher.

So the fix is instructional: name the boundary in the text the executor already reads at the
start of every run, and trust the same judgment call the method already asks for everywhere
else ("you judge reversibility per action; you don't need a pre-declared list"). This is not
free — it inherits the standing limitation of every documented-only fix in this method: it
depends on the executor actually re-reading and applying it under time pressure, the same
dependency that let this exact gap through the first time. It is cheaper and more honest than a
detector that would eventually be gamed by a wording it wasn't written for, but it is not a
guarantee.

## What "targeted re-entry" means

When a new terminal-class action appears after a completion-review already closed the session's
spec, don't restart the loop from clarify — but don't fold the new action into the closed spec's
objective/scope either. The production release and the shared-memory push in the incident above
were not what the closed spec (two PRs to `develop`) covered; treating them as already-authorized
by that spec is exactly the gap this document exists to close, just moved one level deeper. What
carries over from the closed spec is the *context* — the repo, the account, whatever's already
grounded — not its authorization. Re-derive only what's genuinely new: this action's own
objective and scope, stated plainly at 4b.

**Skip**: re-asking what nothing here calls into question — session-level facts already
settled, and clarify/Q1–Q3 for whatever this action doesn't put back in doubt. **Don't skip**:
the two checkpoints that exist *because* an action is terminal — showing the human **this
action's** blast radius before spending the effort (4b), and an independent adversary trying to
break **this outcome** before it's treated as done (6), each scoped to the new action, not the
old one. Close the re-entered cycle the way any cycle closes: a fresh `[COMPLETION-REVIEW: ...]`
for this action. The Stop gate's check reads only the most recent declaration in the session —
the prior cycle's completion-review does not, and structurally cannot, stand in for an action it
was never written against; skipping the fresh declaration leaves the gate reading the stale one
as still operative, silently (see "What this does not cover" below).

## What this does not cover

- **Detecting that a new action is terminal in the first place.** This document says what to do
  once you've recognized one — it doesn't (and structurally can't, per the section above) catch
  the recognition failure itself. That's still the executor's judgment call, same as any other
  terminal action.
- **A session that never ran the loop at all.** This is about re-entry after a *prior* close in
  the same session, not a substitute for the initial trigger.
- **Anything outside a single session.** A new session starting fresh already re-triggers
  normally; there is no persistent state to lose track of across session boundaries.
- **The mechanical gate cannot tell an old completion-review from one that actually covers the
  new action.** `gate-goal-close.sh` reads only the *most recent* `[COMPLETION-REVIEW: ...]` in
  the session — it has no way to know whether that declaration was written against the spec that
  produced it or against some unrelated action three turns later. If the executor skips the
  fresh declaration this document asks for, the gate stays silent exactly as if nothing were
  wrong — the same fail-open shape as every other rule in this method that depends on the
  executor actually following it. This is not a defect introduced by targeted re-entry; it is
  the standing limitation from "Why documented, not mechanical" above, landing on the one
  mechanical surface this change touches.

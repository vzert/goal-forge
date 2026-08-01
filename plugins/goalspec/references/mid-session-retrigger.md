# A closed spec doesn't close the session

**Contents**: [What happened](#what-happened) · [Why documented, not mechanical — and where that changed](#why-documented-not-mechanical-and-where-that-changed) · [What "targeted re-entry" means](#what-targeted-re-entry-means) · [What this does not cover](#what-this-does-not-cover)

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

## Why documented, not mechanical — and where that changed

The tempting fix is a hook: watch tool calls for a `git push`, a deploy command, a write to a
known shared-state path, and force re-entry when one fires after a completion-review. This
project has built that shape of thing three times before — a match on the *string identity* of
an adversary's self-reported model, a dedup key on the *literal text* of a verdict line, a
loop-boundary counter — and all three lost the arms race: the id-matcher broke across five
correction rounds, the verdict dedup silently under-counted identical strings hiding distinct
findings, and the loop-boundary counter is structurally blind to anything that happens without a
`Stop` between turns. A detector for "is this tool call a new terminal action, in ANY domain"
has the same shape: it would need to distinguish a release script from a status check, a write
to a shared learnings file from a write to a scratch file — by pattern, forever chasing new
phrasings. That fight is still not winnable by a smarter matcher, and nothing below claims it is.

**A narrower, bounded version of it was built anyway (2026-08 — `hooks/precheck-terminal-push.sh`
+ a staleness check in `gate-goal-close.sh`, both reading `hooks/lib/terminal_actions.py`), in
response to a DIFFERENT pair of incidents than the one this document opens with — both were a
code push/merge/deploy landing before the adversary ran, not a shared-state write.** What makes
that version tractable where the general one is not: it does not try to classify arbitrary
executor prose or infer intent — it pattern-matches a *bounded, literal* set of Bash command
shapes (`git push` to a protected branch, `gh pr merge`, a handful of named deploy/publish CLIs,
a couple of destructive shell idioms) and, for push/merge, diffs the *actual file paths* the
action would touch against a small path allowlist. That is closer in kind to the coverage-floor
enumeration this method already trusts mechanically (glob for files, diff for paths) than to the
three failed matchers above, which all tried to fingerprint free-form, executor-authored text.

**It does NOT cover the incident this document describes.** The path allowlist that makes the
new hook usable in practice (`memory/`, `docs/`, `.goalspec/`, root `*.md` — checkpoint commits
must not trip it on every `/checkpoint-3t` run) is exactly where an unconfirmed conclusion
written to shared state, per this document's own opening incident, would land. The hook cannot
tell a routine session log in `memory/sessions/` from a wrong conclusion asserted in
`memory/learnings/` — that is a content distinction, not a path one, and is the SAME
undecidable-by-pattern problem this section already argues is not winnable; scoping the hook to
Bash-invoked code pushes is what kept it tractable, and the shared-state-write case is exactly
what fell outside that scope by design. So the fix for THIS document's incident remains
instructional, unchanged: name the boundary in the text the executor already reads at the start
of every run, and trust the same judgment call the method already asks for everywhere else ("you
judge reversibility per action; you don't need a pre-declared list"). This is not free — it
inherits the standing limitation of every documented-only fix in this method: it depends on the
executor actually re-reading and applying it under time pressure, the same dependency that let
this exact gap through the first time. Do not read the existence of the code-push hook as
evidence this gap closed too — it did not, and treating "the hook let the push through" as "this
was reviewed" would be a worse mistake than having no hook at all.

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
- **The mechanical gate now catches ONE shape of this, not the general case.** Since 2026-08,
  `gate-goal-close.sh` also flags the operative `[COMPLETION-REVIEW: ...]` as stale when a
  Bash-shaped terminal command (push/merge/deploy/destructive) ran after it and touched anything
  outside the path allowlist — the exact "declaration was written against an earlier spec,
  something terminal happened since, nobody re-declared" gap this document names. But it reads
  only what `hooks/lib/terminal_actions.py` can classify from a Bash command string and a file
  diff; it still cannot tell an old completion-review from one that covers a NEW action that
  isn't Bash-shaped — an MCP tool call, a decision made and acted on entirely in prose, or
  (per the boundary drawn above) an unconfirmed conclusion written to an exempted path. For any
  of those, if the executor skips the fresh declaration this document asks for, the gate stays
  silent exactly as if nothing were wrong — the same fail-open shape as every other rule in this
  method that depends on the executor actually following it. This is not a defect introduced by
  targeted re-entry; it is the standing limitation from "Why documented, not mechanical" above,
  narrowed but not removed by the one mechanical surface this change touches.

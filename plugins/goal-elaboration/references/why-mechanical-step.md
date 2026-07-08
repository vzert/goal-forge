# Why the mechanical step — a self-goal skill isn't "senior" without it

A self-goal constitution and scaffold ("be complete", "resolve what's inherited", "ground your
claims, don't use proxies") measurably improve an agent's reasoning. But **an agent following an
aspirational instruction still self-grades, and still skips whatever it doesn't actively look for.**
The principle-level instruction is necessary but not sufficient. Closing the gap needs a *concrete
mechanical step* (a literal grep, a mandatory enumeration) and, for the independent layer,
*verification that doesn't depend on the agent choosing to invoke it.*

## The evidence (a four-step arc, same terse prompt each time)

1. **Goal-spec scaffold alone.** It *looked* senior — the agent posted a goal-spec + a red-team —
   but it self-graded shallow work: an inherited open decision got skipped, coverage was claimed
   but false, and a phantom action-marker (`[applied resource X]`) was posted over pre-existing state.
2. **+ the rule "resolve inherited decisions".** Better — but the *same* inherited decision got
   skipped *again*, because the agent checked recent items only, not its decision log. The rule was
   aspirational, so it evaporated exactly where it mattered.
3. **+ a mechanical sweep** (a literal grep of the decision files + fetch of recent related items).
   This worked: it surfaced and resolved the inherited decision and produced deep coverage. But the
   agent was still self-grading the close.
4. **+ a `[COMPLETION-REVIEW: adversary|none]` declaration gate.** Now it can't close silently. The
   gate even rejected a malformed declaration and the agent self-corrected; on the same run it
   re-derived a figure that a prior task had gotten wrong by ~30×.

## Why

"Be complete" has no teeth: the agent *believes* it was complete. The literal grep forces the
coverage; the required declaration forces an auditable statement. The independent layer (the
adversary) only adds value if something *requires* it when a real decision or mutation exists — if it
depends on the agent's judgment, it gets skipped in precisely the case that matters.

## Applies to

Any junior→senior uplift by instruction. Teaching an agent to *think* (the skill) is not enough —
tie the thinking to a *verifiable mechanical artifact*. That is why this plugin ships not just a
constitution but a sweep, a coverage floor, and a completion-review declaration.

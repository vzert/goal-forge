# The outcome loop beats a wall of process gates

## What happened

A second audit passed *every* process marker — completeness marker, prior-art marker, query-verified
marker — **on top of a contaminated evidence chain**, and escalated a badly-founded kill. The same
class of failure had already been "fixed" once with three process gates, and it recurred 13 days
later. Gates reward the *proxy* (the marker is present), not the *outcome* → this is textbook
**specification gaming**. Adding more gates is a treadmill.

## The decisive experiment

When a human hand-wrote a *grounded* goal-spec (objective + measurable criteria vs ground-truth +
invariants + verification), the agent self-corrected all three contaminations **with no gate armed
at all**: it discarded the phantom event, reconciled the attribution, resolved the count
contradiction, and overturned the kill. The problem was never a lack of gates — it was that the
agent never framed its own goal.

## The fix is one level up, not another gate

Two universal pieces; the agent derives the rest per task:
1. A **minimal constitution** (≤5 epistemic principles that apply to any agent/domain): Grounding,
   Falsification, Completeness, Autonomy, No-harm.
2. A **reasoning scaffold** (6 generative questions that produce the goal-spec).

Verification is an **independent adversary** (fresh context or a different model, prompted to *break*
the outcome against the constitution) — not a checklist.

## The trap to avoid

Encoding one case's gaps as new "invariants" is *gates by another name* — per-case rules that don't
generalize. **What generalizes is not the content of the rules, it is the method of reasoning that
produces them.** A case's specific failures are *illustrations* of the constitution, not new rules.

## The underlying principle

You cannot gate — nor verify — your way out of specification gaming. Every checkable proxy is
gameable (including a weak self-verifier, and a fail-closed `[GOAL-COMPLETE]` marker, which is just
the old gamed gate reincarnated). The only real levers are:
1. **Measurable criteria against ground-truth, set up front.**
2. **An independent adversary** that tries to break the claim.

This is Constitutional AI applied to operations. It is **why this plugin's Stop gate is deliberately
fail-open/advisory** rather than a blocking wall: a blocking marker just relocates the gaming. The
gate reminds; the constitution and the adversary do the actual work. (`GOAL_GATE_ENFORCE=1` exists
for those who explicitly want teeth, with eyes open to the tradeoff.)

## Supporting work

Evaluator–optimizer loops (Anthropic, *Building Effective Agents*), Reflexion / Self-Refine,
Plan-and-Solve, process-vs-outcome supervision ("Let's Verify Step by Step"), and Constitutional AI.
Caveat from the field: rigid rubrics give high variance — hence a *lightweight* constitution, not a
checklist.

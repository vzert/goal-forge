---
name: interview
description: Structured interview that discovers what the user actually wants BEFORE a goal-spec is written, for tasks the user cannot yet articulate. Invoke as /goalspec:interview when the user explicitly asks to be interviewed ("interview me about this", "help me figure out what I actually want", "grill me on this plan") or plainly states they can't express the task yet ("I don't know how to explain what I need"). When that inability is plainly stated, START HERE even though the main goalspec skill also matches the turn — the goalspec loop runs AFTER the interview settles intent (its clarify step routes to this skill for exactly this case); invoking the loop first on unarticulated intent produces a spec aimed at the wrong objective. Do NOT auto-trigger on merely terse-but-clear requests — the goalspec loop's own clarify step (one batched modal) handles those; this skill is for structurally underspecified intent, where the important forks only become visible as earlier answers land. Walks the decision tree in dependency-ordered rounds of multiple-choice questions, looks up facts itself and asks only decisions, then hands the settled understanding to the full goalspec loop.
---

# Interview — discover the goal before you spec it

The goalspec loop's clarify step resolves the forks you can already **name** by reading the
request — one batched modal, ≤3 questions. This skill exists for the failure mode upstream of
that: the user's description is too thin to even name the forks, and a spec written on thin
intent is grounded, falsifiable, and **aimed at the wrong objective**. The fix is not a bigger
batch — it is an **interview**: the important questions only become visible as earlier answers
land, so you walk the decision tree round by round until nothing load-bearing is left silently
assumed.

This command is purely additive: it writes no `## Goal-spec` (that stays the goalspec skill's
job), adds **no new markers, no new gates, no new matchers**, and ends by handing off into the
full goalspec loop. It is the front door for fuzzy intent, not a replacement for any step of
the loop — the ratify gate still fires later, because settling *intent* here is not the same as
approving *the spec that intent becomes*.

## 1. Frame the tree

From the user's description, sketch the **decision tree**: the decisions the task hinges on,
and which of them depend on which. Root decisions first — objective-level forks (what problem
is this actually solving, for whom, by when it counts as solved) — then the scope, done-bar,
and authorization forks that hang off them. You will not see the whole tree up front; that is
the point. You only need the **frontier**: every decision whose prerequisites are already
settled and which you could ask *now* without guessing at answers you haven't heard.

## 2. Interview in rounds — one modal per round, frontier only

Each round is **one `AskUserQuestion` modal** carrying the current frontier (up to the tool's
limit of 4 questions; if the frontier is larger, take the most load-bearing forks first). Rules
per question, same discipline as the loop's clarify step (that section is the home for the
batching and default rules — grep terms: recommended default first, least-irreversible option
for any scope/terminal fork):

- **Decisions only, never facts.** Anything you can resolve from the environment — the repo,
  the files, the data, prior conversation — is yours to look up, sized exactly as the loop's
  grounding step sizes acquisitions (targeted → inline; broad → delegate a bounded subagent
  exploration). Asking the user for a lookable fact violates Autonomy. A fact lookup still in
  flight makes its downstream questions *unsettled prerequisites* — hold those for a later
  round and ask the rest of the frontier now.
- **Every question is a load-bearing fork** — plausible answers must lead to genuinely
  different work. A question you're asking to be thorough, whose every answer converges on the
  same spec, is interview theater; cut it. Too many questions is a quality failure of this
  rule, not a quantity problem to cap.
- **Recommended option first**, labeled "(Recommended)", reasoning visible in its description —
  the user reacts to a proposal, not a blank prompt. For a scope or terminal-authorization
  fork, the recommended default is the least-irreversible option, never execute-now.
- The built-in "Other" free-text option is the escape valve when your framing of the fork
  itself is wrong — treat an "Other" answer as evidence the tree needs reshaping, not as a
  fifth option.

After each round: fold the answers in, recompute the frontier (settled parents unblock their
children; an answer can also invalidate branches you'd sketched), and run the next round.

## 3. Terminate on an empty frontier — or on the user's steer

The interview is done when the **frontier is empty**: every branch visited, nothing
load-bearing left silently assumed. There is no fixed question cap and no fixed round count —
some asks settle in one round, some need five. Two guards keep that honest:

- **The user can stop it at any time.** Once the objective-level forks are settled and only
  lower-stakes branches remain, include an explicit "Proceed with what we have" option in the
  next round's most natural question — from there on, continuing is the user's choice, not
  your default. Whatever is unsettled when they stop travels into the goal-spec's
  **Assumptions (correct me if wrong)** line, not into silence.
- **A frontier that grows round over round is a signal, not a treadmill.** If each round
  uncovers more open decisions than it settles, the task is bigger than one session's interview
  — say so plainly and put the fork to the user (narrow to one branch now vs. step back and
  scope the effort first) instead of grinding through rounds.

## 4. Hand off to the goalspec loop — synthesize, don't re-interview

When the interview ends, the settled understanding is the **input** to the full goalspec
method — run it now (it auto-triggers on the substantive task you now have; do not re-inject
the skill file via slash command if it already loaded this session). Two rules for the handoff:

- **Do not re-ask anything settled here.** The loop's clarify step (step 2) should find nothing
  left to ask — its purpose was served upstream. Anything the user left unsettled goes in the
  Assumptions line; decisions discovered later mid-run still route through the loop's own
  mid-run ask door as always.
- **The spec must visibly reflect the interview.** The settled decisions land in the
  `## Goal-spec`'s objective, scope, success criteria, and Autonomy split — that is the
  mechanical test that the interview did work. If the spec that comes out is the one you would
  have written without interviewing, either the ask was never underspecified (next time, let
  the ordinary clarify step handle it) or the answers were dropped on the floor.

The interview itself stays **stateless** — it leaves no file behind; the goal-spec that follows
is the durable record of what was settled, exactly as it is for the rest of the method.

## Headless / non-interactive

An interview is interactive by definition — in cron, CI, or `-p` this skill does not apply. Do
not attempt rounds of modals headless: fall back to the goalspec loop's normal headless path
(most defensible defaults, every assumption recorded explicitly, nothing blocked on a modal)
and say that the interview was skipped for that reason.

## Scope

- **Not for already-clear requests.** If you can name the objective, the scope, and the done-bar
  well enough to write the spec — even with 2–3 visible forks — the loop's clarify step is the
  right tool and this command is ceremony. Invoking it there is the interrogation the clarify
  step was explicitly designed to avoid.
- **Not a verification step.** This runs before the spec exists; it neither red-teams an
  outcome (`/goalspec:adversary` does) nor ratifies a spec (the loop's step 4b does).
- **Frame the tree in your own reasoning, not in prose before the modal.** Round 1's "Frame the
  tree" step is how you decide what to ask, not something to narrate to the user first — the
  fork and its reasoning belong in the question and option descriptions themselves. See the main
  `SKILL.md`'s `## Scope` → "keep the method's own reasoning internal" bullet, which applies to
  every round of this skill too.
- One interview per task. If execution later reveals the intent was still wrong, that is a
  mid-run fork for the loop's ask door, not a reason to re-run the interview.

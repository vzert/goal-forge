---
name: goalspec
description: Use this at the START of any non-trivial task with a real outcome — an audit, optimization, diagnosis, decision, plan, review, build, or investigation — in ANY domain, not just code — software, marketing, copywriting, research, operations, even a water-treatment plant. It turns the terse request into your own grounded goal-spec (objective + measurable success + pre-mortem + no-harm + autonomy + definition-of-done) via a 5-principle constitution, so you don't drift or self-grade shallow work. When the request is ambiguous about objective, scope, or authorization, it asks clarifying multiple-choice questions BEFORE committing, to avoid an hour on the wrong task. Before closing it red-teams the outcome and routes terminal/irreversible actions (kill, delete, deploy, publish, merge, send) to an independent adversary. Trigger it whenever a task would benefit from a grounded goal + a verification pass — including phrasings like "audit X", "should I kill/ship/publish Y", "figure out why Z dropped", "plan the...", "review this before I merge". Do NOT trigger on contentless "continue"/"go on" turns with no new directive, or on trivial one-step lookups.
---

# Goal-Elaboration — write your own goal before you execute

A terse request ("audit campaign X", "CPA is 8.7x target", "review this PR") **is not** the goal — it is the trigger. Before executing, **you** build the goal-spec. Afterwards, **you** try to break it. This replaces depending on a human to write your objective, and on a gate to catch your error after the fact.

Why this exists: in the validated pilot, when a human hand-wrote a grounded goal-spec, the agent self-corrected three separate contaminations (a phantom event, fabricated attribution, a count contradiction) **with no gate armed at all**. The problem was never a lack of gates — it was that the agent never framed its own goal.

## The constitution (5 principles — they apply to EVERY task, they are not per-case rules)

1. **Grounding** — every load-bearing claim cites verifiable ground-truth (a query, a real entity state). Question whether your proxy measures the real thing: *a proxy ≠ the thing; "marker present" ≠ done; clicks ≠ conversions.* **Instrument-validity**: evidence is worthless if the instrument that produced it is broken — empty tracking, misconfigured scope, a phantom event, a failing test harness. A null metric has two disjoint causes (broken instrument vs real performance); before concluding "it doesn't work" — and **always** before a kill/pause/delete — falsify "broken instrument" first: is the entity *measurable* AND *serving what I'm judging it on*?
2. **Falsification** — before concluding, try to **break your own conclusion**. Re-derive, don't inherit, any prior claim you depend on (from another task, another agent, your own earlier run). If numbers don't reconcile with each other, your input is wrong — don't close, re-derive it.
3. **Completeness** — "done" = objective **achieved and verified** against ground-truth, not *diagnosed*. Every factor you surface has an **owner** before you close.
4. **Autonomy** — exhaust what **you or another agent** can execute before asking a human. The human **decides**; they do not execute work an agent can do.
5. **No-harm / reversibility** — don't remove, pause, or scale something that works without a validated baseline and, where possible, a reversible path. Fix the cause before you amplify.

These 5 are **not** extended with new per-case rules. A new case is judged by the same 5 — the specific rules are **derived** by applying them to today's task.

## The scaffold — answer these 6 questions FOR THIS task

Post the answers as a `## Goal-spec` block at the start of the run (structured prose; invent no new markers). The questions are universal; your answers are specific to the task:

1. **Real objective** — what does this solve operationally? (Not the ticket's narrative; the business problem behind it.)
2. **Measurable success** [Grounding] — ≥2 criteria, each with a **ground-truth source + baseline + target** (e.g. "test suite green on CI"; "p95 latency ≤ derived ceiling, not a fixed guess"). No subjective or proxy criteria.
3. **Pre-mortem** [Falsification] — what are 2–3 ways I could be wrong? What evidence would falsify my likely conclusion? Which inherited claim am I depending on that I have **not** re-verified today?
4. **No-harm** [No-harm] — what is working that I must not break? Which action here is irreversible or high-blast-radius?
5. **Autonomy** [Autonomy] — which part is executable by me or another **agent** (which one?), and which part is genuinely a **human decision**? Everything agent-executable is NOT assigned to a human.
6. **Definition of done** [Completeness] — when is the objective *achieved and verified*, with every factor owned? (Not "diagnosed".)

## Clarify before you commit — ask, don't drift

A terse request is often ambiguous in a way that would send you down the *wrong* long task. Before you finalize the goal-spec, resolve that ambiguity — a 30-second question beats an hour of work on the wrong objective. This is the constitution's Autonomy principle read correctly: the human **decides** (intent, scope, authorization), the agent **executes** — so ask about *decisions you cannot make for them*, never about *facts you can look up yourself*.

**When to ask** (balanced): if the **objective**, the **scope**, the **authorization for a terminal action**, or the **bar for "done"** is unclear — even if a plausible default exists — ask. First try to resolve it from context (the repo, the files, the conversation); ask only for what's genuinely a user decision. Do NOT ask about anything you can determine yourself (that violates Autonomy), and do NOT ask when every plausible answer leads to the same work.

**How to ask** — use the `AskUserQuestion` tool (a multiple-choice modal), and:
- **Batch it**: one modal, up to ~3 questions, not an iterative interrogation.
- Each question targets a load-bearing fork, most often one of: *objective* ("audit the widgets" → for cost? correctness? to decide kills?), *scope* (all entities vs the one that alarmed), *terminal authorization* (**execute** the irreversible action vs only **recommend** it), *done-bar* (ship-ready vs quick check).
- Make the **first option the recommended default** (label it "(Recommended)") so the user can proceed in one click.
- Fold the answers into the goal-spec's objective, scope, success criteria, and Autonomy split.

**When you DON'T ask** (task is clear enough): still make your assumptions visible. Open the goal-spec with a short **Assumptions (correct me if wrong)** line stating the load-bearing choices you made — objective, scope, and whether you'll *execute* or *recommend* any terminal action — then proceed without blocking. This lets the user course-correct early without a modal.

**Headless / non-interactive (cron, CI, `-p`)**: `AskUserQuestion` may not be answerable. If so, do not block — pick the most defensible default, record every assumption explicitly in the goal-spec's **Assumptions** line and pre-mortem, and proceed. Never hang a scheduled run on a modal.

This front-loads the pre-mortem (Q3): instead of only asking "how could I be wrong?" *after* the work, you make sure you're solving the right problem *before* spending the effort.

Then execute the work **steered by this spec**, not by a fixed checklist.

## Before closing — red-team your own outcome against the constitution

Do not close until you pass your own adversary (Constitutional self-critique). Ask yourself, honestly:
- **Grounding**: does every figure that holds up my verdict come from ground-truth, or from a proxy / a marker / an inherited narrative?
- **Falsification**: did I genuinely try to break my conclusion? Did I reconcile EVERY internal contradiction (two counts that don't match = something is wrong)?
- **Completeness**: is the objective *achieved*, or only diagnosed? Any factor without an owner?
- **Autonomy**: am I handing a human something I or another agent could have executed?
- **No-harm**: am I about to pause / scale / remove something that works without a validated replacement?

For any **terminal or irreversible** decision — one where undoing it would be hard or harmful — this does NOT stay as self-critique: route to the **adversary** (a fresh-context subagent, or an external CLI/model — see `references/external-adversary-setup.md`). You judge reversibility **per action**; you don't need a pre-declared list. The domain tells you what's terminal: `delete`/`kill`/`deploy-to-prod`/`irreversible-migration` for software, `publish`/`send-to-list` for marketing, `merge-to-main`/`force-push` for a repo, dosing a chemical feed for a treatment plant. The sweep touching an inherited open decision, or affirming a mutation, also triggers routing. The adversary is your independent verifier — it is asked to **break** your outcome against the constitution, not to approve it. Fix-first reversible work can proceed while the adversary critiques.

## The three derived patterns — how Grounding + Completeness land in real work

These are **not** new rules — they are how principles 1 and 3 land when the task is an audit / optimization / decision. They are the mechanical teeth that make the work senior instead of aspirational:

- **Mechanical sweep of inherited decisions + dedup** [Completeness] — "resolve what's inherited" is aspirational without a literal search; **do it mechanically**. You don't need a config file to know where to look — **discover it**: (1) glob the project for wherever pending choices are tracked — files matching `TODO`, `open-decisions`, `decisions`, `pending`, `open-questions`, `known-issues`, `backlog`, `notes`, or the doc this project actually uses — and scan recent context/notes for the entity + its key terms; (2) grep those for the entity you're working on and your own recent related items; (3) every **open decision** you find → resolve it or surface it — **do not close without touching it**; (4) every **handoff you already dispatched recently** → do NOT recreate it (dedup). If no decision log exists, say so explicitly ("no decision log found — sweep skipped") rather than silently skipping. The point is a *literal* search that's always attempted, not one that waits on config. (Power users can pin exact files via optional `sweep_files` config for a deterministic grep.)
- **Coverage floor** [Completeness] — before declaring complete, enumerate **all** the child entities the task implies — not a sample, not names+status — with real per-entity data. The task names them: "audit the widgets" → every widget; "review this PR" → every changed file; "check the clarifier stage" → every tank/sensor in it; "write the launch sequence" → every email. You infer the entity type from the task; no config needed. If a data query **fails**, that is a **blocker**, not a silent skip: fix it or mark the gap; never hide it under a "done" marker.
- **Action-marker veracity** [Grounding] — never claim `[action executed]` / "applied (resource X)" unless the mutation **returned an id in this run**. Re-affirming pre-existing state (a config that already existed, an entity already paused) is **not** an action — don't report it as one, and the id you cite must come from the mutation result, not from memory. A completeness marker attests you *did the analysis*, not that you *ran the skill*.

## Completion-review declaration (the marker the gate looks for)

On close, do not silently self-grade. Emit **exactly one** of:

- `[COMPLETION-REVIEW: adversary <details>]` — if you resolved/touched an inherited open decision, or affirmed a mutation, or made a terminal decision. Requires an `[ADVERSARY-VERDICT: ...]` present in the session.
- `[COMPLETION-REVIEW: none reason=<≥20 chars>]` — if the sweep found no open inherited decision and no mutation (a clean, low-stakes close).

The adversary verdict grammar (emitted by the adversary, not by you):

```
[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]
```

`break` = the adversary found a constitution violation you must address before closing. `hold` = the outcome survives.

## Examples — well-formed vs ill-formed spec

**BAD (narrative, proxy, no baseline):**
> Objective: audit the service. Success: improve latency. Done: when I've reviewed performance.

Fails: objective = the ticket's narrative; "improve" is not measurable; no baseline or source; "reviewed" ≠ achieved.

**GOOD (grounded, falsifiable, complete):**
> **Objective**: determine whether the checkout endpoint can meet its SLO at real traffic and, if not, find the config that does — or prove with clean evidence that it can't.
> **Success**: (a) p95 latency ≤ 300ms under the load-test profile (baseline today = 520ms); (b) error rate ≤ 0.1% on the same run; (c) zero contradiction between the APM number and the load-test client's number (delta ≤ 20%).
> **Pre-mortem**: (1) the "DB is the bottleneck" claim inherited from the prior ticket may be a phantom — I re-derive it from a fresh trace; (2) "all latency is server-side" may be a weak proxy — I decompose by span; (3) it may be a client/network artifact, not the service — I check the load generator's own timing.
> **No-harm**: there are healthy replicas serving traffic; I don't drain them without a live replacement. I don't raise the connection pool before I've fixed a diagnosed leak.
> **Autonomy**: I run the load test and the trace analysis myself; only authorizing a production config rollout is a human decision.
> **Done**: actionable config applied and verified by read-back, every non-owned factor assigned to an agent, no live contradiction.

## Adapting to your domain — automatically, no config required

**You do not need a config file.** This skill adapts to any domain — software, marketing, copywriting, operations, a water-treatment plant — by *reasoning*, not by configuration. As you answer the 6 questions you **derive**, for THIS task: what counts as ground-truth (Q2), what the child entities are (definition of done), which actions are irreversible (no-harm), and where inherited decisions might live (you discover the files). That derivation **is** the method — hardcoding it per-domain would be the very "per-case rules" this method is designed to replace, and a fixed list would miss your domain's own terminal actions.

So the domain-specific behavior is emergent, not configured:

| What the fleet version hardcoded | How you get it now |
|---|---|
| ground-truth sources | You name them per-task when answering Q2 (tests/CI, analytics, sensor readings, primary docs — whatever *your* work verifies against). |
| files to sweep | You **discover** them (glob for decision/TODO/pending docs; scan recent context). |
| what "all entities" means | The **task noun** tells you (widgets, changed files, tanks, emails). |
| which actions are terminal | You **judge reversibility per action**; the domain makes it obvious. |

**Optional config (power users only).** Create `.claude/goal.config.json` only if you want to (a) **pin exact `sweep_files`** so the grep is deterministic, or (b) **select an external adversary backend** (`adversary.backend: "external"`, `external_cmd: "codex exec"`) — a preference that can't be inferred. Nothing else needs configuring. See `goal.config.example.json` and `references/adaptation-guide.md`.

## Scope

- Runs at the **start of substantive tasks**, not on contentless "continue" turns. If a human goal-spec already exists, adopt it and still run the final red-team.
- This skill adds **no governance markers beyond the completion-review declaration**. It is a reasoning method, not another rule in a wall — you cannot gate your way out of specification gaming; the only real levers are measurable criteria set up front and an independent adversary. See `references/outcome-loop-beats-gates.md`.

## Running the full loop (invoked as `/goalspec <task>`, or auto-triggered)

When invoked explicitly or auto-triggered on a substantive task, run these in order:

1. **(Optional) config** — best-effort read `.claude/goal.config.json` if present. Absent is the normal case; infer everything domain-specific from the task (above). Never tell the user to go write config.
2. **Clarify before you commit** — resolve load-bearing ambiguity (objective / scope / terminal-action authorization / done-bar) via `AskUserQuestion` (one batched modal, ≤3 questions, recommended default first) — but only for genuine *user decisions*, never for facts you can determine. If clear enough to skip, open the spec with an **Assumptions (correct me if wrong)** line. In headless/cron, never block on the modal — take the most defensible default and record it.
3. **Emit the `## Goal-spec`** — the 6 scaffold answers, grounded and falsifiable, ≥2 measurable success criteria whose ground-truth you named yourself.
4. **Execute**, steered by the spec — run the mechanical sweep + coverage-floor enumeration before considering the objective met; respect action-marker veracity.
5. **Red-team, then route to the adversary if warranted** (terminal/irreversible action, sweep touched an inherited decision, or you affirmed a mutation):
   - **subagent** (default, zero-config): spawn the `goal-adversary` subagent via the Task tool with the goal-spec, your outcome, and where the work lives. It returns `[ADVERSARY-VERDICT: ...]`.
   - **external** (only if `adversary.backend: "external"`): run `${CLAUDE_PLUGIN_ROOT}/hooks/external-adversary.sh` (goal-spec + outcome on stdin) to route to a different model/CLI.
   - On `break`, address every confirmed violation and re-verify. Do not close over a `break`.
6. **Declare the completion-review** — exactly one `[COMPLETION-REVIEW: ...]` (see grammar above). The Stop gate checks for it (fail-open advisory unless `GOAL_GATE_ENFORCE=1`).
7. **Optional — hand off to the built-in `/goal`** — if the success criteria are turn-loopable (something Claude's own output can demonstrate), print a ready-to-paste `/goal "<condition derived verbatim from your measurable criteria>"` so the user gets the built-in multi-turn loop, now driven by a grounded, adversary-checked condition. Only when the condition is genuinely checkable from Claude's own output.

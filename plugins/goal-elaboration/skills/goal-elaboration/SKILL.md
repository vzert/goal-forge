---
name: goal-elaboration
description: Before executing any substantive task (audit, optimization, diagnosis, decision, build), convert the terse request into your own grounded goal-spec — objective + measurable success + pre-mortem + no-harm + autonomy + definition-of-done — applying the 5-principle constitution. Before closing, red-team your own outcome against the constitution; route terminal/irreversible decisions to the adversary. Use at the start of substantive work, not on contentless "continue" turns.
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

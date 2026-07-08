---
description: Convert a terse task into a grounded goal-spec, execute it, verify with an independent adversary, and close through the completion gate. The single entry point for the goal-elaboration methodology.
argument-hint: <terse task, e.g. "audit the checkout service">
---

# /goalspec — self-goal + adversary, in one command

You are running the **goal-elaboration** methodology on this task: `$ARGUMENTS`

Do NOT use the built-in `/goal` for this — that is a different, reserved command. Follow these steps in order.

## 1. (Optional) check for config — but don't require it

This works with **zero config** for any domain. Best-effort read `.claude/goal.config.json` if it exists — you only need it to pin exact sweep files or select an external adversary backend. If it's absent, that is the normal case: infer everything domain-specific from the task itself (see the skill's "Adapting to your domain — automatically"). Do not tell the user to go write config.

## 2. Elaborate the goal-spec

Invoke the **goal-elaboration** skill. Answer the 6 scaffold questions for `$ARGUMENTS` and emit a `## Goal-spec` block — grounded, falsifiable, with ≥2 measurable success criteria. **You name the ground-truth sources yourself** based on what this task verifies against (tests/CI, analytics, sensor/lab readings, primary docs — whatever fits the domain). If the task already carries a human-written goal-spec, adopt it (still run step 4).

## 3. Execute

Do the actual work, steered by the spec — not by a fixed checklist. Run the mechanical sweep (discover decision/TODO/pending docs by globbing, then grep them — or pin `sweep_files` if config exists) and the coverage-floor enumeration (all the entities the task implies) before you consider the objective met. Respect action-marker veracity: only claim a mutation if it returned an id in this run.

## 4. Red-team, then route to the adversary if warranted

Run the self-critique against the 5 principles. Then decide whether an **independent** adversary is required:

- **Required** if: the action is terminal/irreversible (you judge reversibility per-action — no list needed), OR the sweep touched an inherited open decision, OR you affirmed a mutation.
- Invoke the adversary. Default backend is a subagent; use external only if config selects it:
  - **subagent** (default, zero-config): spawn the `goal-adversary` subagent via the Task tool, passing it the goal-spec, your outcome, and where the work lives. It runs in fresh context and returns an `[ADVERSARY-VERDICT: ...]` block.
  - **external** (only if `adversary.backend: "external"` in config): run `${CLAUDE_PLUGIN_ROOT}/hooks/external-adversary.sh` (pipe the goal-spec + outcome on stdin). It routes to a different model/CLI (`adversary.external_cmd`) and returns the same verdict block.
- If the verdict is `break`, address every confirmed violation and re-verify before closing. Do not close over a `break`.

## 5. Declare the completion-review

Emit exactly one:
- `[COMPLETION-REVIEW: adversary <details>]` — if you invoked the adversary (an `[ADVERSARY-VERDICT: ...]` is present in the session).
- `[COMPLETION-REVIEW: none reason=<≥20 chars>]` — if the sweep found no open inherited decision and no mutation.

The Stop hook checks for this. It is fail-open/advisory by default (it reminds, it does not block), unless `GOAL_GATE_ENFORCE=1`.

## 6. Optional — hand off to the built-in /goal

If the success criteria are turn-loopable (something Claude's own output can demonstrate across turns), print a ready-to-paste line so the user gets the built-in multi-turn loop, now driven by a grounded, adversary-checked condition:

```
/goal "<condition derived verbatim from your measurable success criteria>"
```

This is the division of labor: our skill produces the grounded condition and the adversary verifies it against ground-truth; the built-in `/goal` provides the multi-turn auto-loop. Only suggest it when the condition is genuinely checkable from Claude's own output.

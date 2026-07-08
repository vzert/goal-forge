# goal-forge

A Claude Code plugin marketplace for one plugin: **goal-elaboration** — a portable
*self-goal + independent-adversary* methodology that turns a terse request into a grounded,
falsifiable goal-spec, verifies the outcome with an independent adversary, and closes through a
fail-open completion gate.

It is a junior→senior uplift for agents, packaged so anyone can install it in one command and adapt
it to their own domain with a small config file — no control plane, no fleet, no hand-editing agent
files.

## What it does

1. **Writes its own goal.** Before executing a substantive task, the agent converts the terse
   request into a `## Goal-spec` — objective, ≥2 measurable success criteria tied to ground-truth,
   a pre-mortem, a no-harm clause, an autonomy split, and a definition of done — by applying a
   5-principle constitution (Grounding · Falsification · Completeness · Autonomy · No-harm).
2. **Does the work, with mechanical teeth.** A literal sweep of your decision files (so inherited
   decisions can't be silently skipped), a coverage floor (enumerate all children, not a sample),
   and action-marker veracity (only claim a mutation that returned an id this run).
3. **Red-teams itself, then routes to an independent adversary** for terminal/irreversible decisions
   — a fresh-context subagent by default, or a different model/CLI for true independence.
4. **Closes through a completion gate** — a Stop hook that requires a `[COMPLETION-REVIEW: …]`
   declaration. Fail-open/advisory by default; opt-in blocking with `GOAL_GATE_ENFORCE=1`.

## Why not just use the built-in `/goal`?

Claude Code ships a native `/goal` that sets a completion condition and loops across turns until a
fast-model evaluator judges it met. Its documented limitation: the evaluator *"doesn't run commands
or read files independently, so write the condition as something Claude's own output can
demonstrate."* That is exactly the specification-gaming hole this plugin closes.

So this plugin **rides on top of** `/goal` rather than replacing it:

- `goal-elaboration` produces the *grounded, falsifiable* condition and an *independent adversary*
  that verifies it against ground-truth — the check `/goal` won't perform.
- Its measurable criteria become the condition you hand to the built-in `/goal` for the multi-turn
  loop (see `/goalspec` step 6).
- Its command is `/goalspec` — never `/goal` — so it does not shadow the built-in.

## Install

```
/plugin marketplace add vzert/goal-forge      # or a local path: ./goal-forge
/plugin install goal-elaboration@goal-forge
```

This registers the `/goalspec` command, the `goal-adversary` subagent, the `goal-elaboration` skill,
and the fail-open Stop gate.

## Quickstart — zero config, any domain

No setup, no config file. Just run it, whatever your agent does:

```
/goalspec audit the checkout service latency          # software
/goalspec plan the Q3 launch campaign                 # marketing
/goalspec write the onboarding email sequence         # copywriting
/goalspec decide whether to raise the chlorine dose on clarifier 2   # water-treatment ops
```

The command writes the goal-spec, executes the work steered by it, red-teams the outcome, routes
terminal decisions to the adversary, and declares the completion-review — inferring everything
domain-specific from the task itself.

## How it adapts to your domain — automatically

There is **nothing to configure**. The methodology is domain-invariant; the domain-specific behavior
is *emergent*, derived by the agent as it writes the goal-spec:

| The agent needs… | …and infers it from |
|---|---|
| ground-truth sources | what *this* task verifies against — tests/CI, analytics, sensor & lab readings, primary docs |
| which files hold inherited decisions | it **discovers** them (globs for TODO / open-decisions / pending docs) |
| what "cover all the entities" means | the task noun — every widget, every changed file, every tank, every email |
| which actions are terminal/irreversible | it judges reversibility per action — no list to maintain |

Hardcoding those per-domain would be the exact "per-case rules" this method is built to replace — so
it doesn't. A water-treatment expert and a Rust developer run the same command and get the same rigor.

### Optional config (power users only)

Create `.claude/goal.config.json` **only** if you want to pin exact sweep files for a deterministic
grep, or route the adversary to a different model/CLI (`codex`, `gemini`, another Claude). Everything
else stays inferred.

```
cp plugins/goal-elaboration/goal.config.example.json .claude/goal.config.json
```

Full walkthrough with worked mappings for **code review** and **research** in
[`plugins/goal-elaboration/references/adaptation-guide.md`](plugins/goal-elaboration/references/adaptation-guide.md).

## The completion gate

The Stop hook enforces only when a session produced a `## Goal-spec`. If one exists but no valid
`[COMPLETION-REVIEW: …]` was declared, it posts an **advisory reminder** and lets the turn end
(fail-open). Set `GOAL_GATE_ENFORCE=1` to make it blocking instead. Operator escape:
`[GOAL-CLOSE-WAIVED reason=<≥20 chars>]`.

Why fail-open? You cannot gate your way out of specification gaming — a blocking marker just
relocates the gaming. The real levers are measurable criteria up front and an independent adversary.
See [`references/outcome-loop-beats-gates.md`](plugins/goal-elaboration/references/outcome-loop-beats-gates.md).

## How it's built

```
goal-forge/
  .claude-plugin/marketplace.json
  README.md
  plugins/goal-elaboration/
    .claude-plugin/plugin.json
    skills/goal-elaboration/SKILL.md      # constitution + 6-question scaffold + red-team
    agents/goal-adversary.md              # independent adversarial verifier (read-only)
    commands/goalspec.md                  # /goalspec — the single entry point
    hooks/hooks.json                      # registers the Stop gate
    hooks/gate-goal-close.sh              # fail-open, transcript-anchored completion gate
    hooks/external-adversary.sh           # optional: route the adversary to a different model/CLI
    goal.config.example.json              # copy to .claude/goal.config.json
    references/                           # adaptation guide + the design rationale
```

## Design rationale (the interesting part)

- [`why-mechanical-step.md`](plugins/goal-elaboration/references/why-mechanical-step.md) — a
  self-goal skill isn't "senior" without a concrete mechanical step (a literal grep, a mandatory
  enumeration).
- [`outcome-loop-beats-gates.md`](plugins/goal-elaboration/references/outcome-loop-beats-gates.md) —
  why you can't gate or verify your way out of specification gaming, and what to do instead.
- [`external-adversary-setup.md`](plugins/goal-elaboration/references/external-adversary-setup.md) —
  routing critique to a different model for true independence.

## Prior art

Adversarial-review plugins exist, but they do generic "one AI writes, another critiques." This
plugin's novel contribution is the junior→senior uplift loop: a portable constitution that makes the
agent generate its *own* grounded goal-spec, a mechanical inherited-decision sweep, and a fail-open
completion gate. It reuses one idea from the community — "the partner reviews, never the host"
(route critique to a different model) — as the optional external-adversary backend.

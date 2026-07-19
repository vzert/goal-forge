# Adaptation guide — it adapts automatically; here's how, and how to override

**You do not need to configure anything.** The methodology (constitution + scaffold + red-team +
adversary) is domain-invariant, and the domain-specific behavior is *inferred by the agent* as it
writes the goal-spec. A copywriter, a marketer, a Rust developer, and a water-treatment engineer run
the same `/goalspec` and get the same rigor — the agent derives what's domain-specific each time.

## What gets inferred (and why it's better than a config field)

| Domain-specific thing | How the agent gets it, with no config | Why not hardcode it |
|---|---|---|
| **ground-truth sources** | Named per-task when answering scaffold Q2 — whatever *this* task verifies against (tests/CI, an analytics API, sensor & lab readings, a primary document) | A fixed list can't anticipate every task's real ground-truth; the reasoning always can. |
| **files to sweep** | **Discovered** — the agent globs for decision logs (`TODO`, `open-decisions`, `pending`, `open-questions`, `known-issues`, `backlog`, `notes`) and scans recent context | A discovered-and-always-run grep beats a precise grep that's never configured. |
| **which entities to enumerate** | The **task noun** names them: "audit the widgets" → widgets, "review this PR" → changed files, "check clarifier 2" → its tanks/sensors, "write the sequence" → its emails | Nothing to maintain; the task already says it. |
| **terminal / irreversible actions** | The agent **judges reversibility per action** — would undoing it be hard or harmful? | A hardcoded list misses *your* domain's terminal actions (dosing a feed, sending to a list). |

That derivation **is** the method. Encoding it as per-domain config would be the exact "per-case
rules" the method exists to replace (see `outcome-loop-beats-gates.md`).

## The only things worth configuring (optional)

Create a `goal.config.json` (copy `goal.config.example.json`) **only** for these — put it at
`.claude/goal.config.json` in a project, or `~/.claude/goal.config.json` to apply to every project
(resolution is per-key, project value wins if set, else global):

| Field | When to set it |
|---|---|
| `sweep_files` | You want the inherited-decision grep to be *deterministic* — pin the exact files instead of relying on discovery. |
| `adversary.backend` / `external_cmd` | You want the adversary routed to a *different vendor's model/CLI* (`codex`, `gemini`, another Claude) for maximum decorrelation. (A different *tier* of the same family is already automatic for terminal actions — no config.) This is a preference — it can't be inferred. See `external-adversary-setup.md`. |

The remaining fields (`ground_truth_sources`, `enumerate_entities_step`, `no_harm_threshold`,
`terminal_actions`) exist in the example only as **overrides** — set them to *force* a fixed value
instead of the per-task inference. Most users never touch them.

## Worked mappings — what the *inference* produces (shown as config)

You don't write these — the agent arrives at them on its own from the task. They're shown as config
JSON only to make the inferred behavior concrete, and to show what a power-user override would look
like if you wanted to pin it.

### Code review

```json
{
  "ground_truth_sources": ["the test suite + CI status", "the type-checker output", "the running app / a repro"],
  "sweep_files": ["docs/known-issues.md", "TODO.md", ".github/PULL_REQUEST_TEMPLATE.md"],
  "enumerate_entities_step": "list ALL changed files in the diff (not a sample) with, per file, whether its tests exercise the change and whether the type-checker is clean",
  "no_harm_threshold": "don't merge a change that removes a passing behavior without an equivalent test proving the replacement",
  "terminal_actions": ["merge-to-main", "force-push", "delete-branch", "revert"],
  "adversary": { "backend": "subagent", "external_cmd": "codex exec" }
}
```
- The coverage floor stops "I reviewed the important files" — you enumerate *every* changed file with its test result.
- The sweep catches a known-issue the PR closes over.
- `merge-to-main` routes to the adversary: it re-runs the reasoning against the diff in fresh context.

### Research / writing

```json
{
  "ground_truth_sources": ["the primary documents themselves", "reproducible calculations", "cited datasets"],
  "sweep_files": ["notes/open-questions.md", "notes/claims-to-verify.md"],
  "enumerate_entities_step": "list ALL load-bearing claims (not a sample) with, per claim, the primary source that supports it and whether you read it directly",
  "no_harm_threshold": "don't publish a claim you could not re-derive from a primary source",
  "terminal_actions": ["publish", "send", "submit"],
  "adversary": { "backend": "external", "external_cmd": "gemini -p" }
}
```
- Grounding here means every claim maps to a primary source you read — not a secondary summary.
- `publish` is terminal → the adversary tries to break each claim before it ships.

### Water-treatment operations (a non-software example)

```json
{
  "ground_truth_sources": ["SCADA sensor readings (turbidity, chlorine residual, flow)", "the lab result log", "the standard operating procedure"],
  "enumerate_entities_step": "list ALL stages in the treatment train (intake, coagulation, clarifiers, filters, disinfection) with the current reading for each — not just the one that alarmed",
  "no_harm_threshold": "don't change a dose or a setpoint that's holding the effluent within spec without a validated reason and a way to revert",
  "terminal_actions": ["raise/lower a chemical dose", "change a setpoint", "take a train offline"]
}
```
- Ground-truth is a sensor reading and a lab result, not an operator's recollection.
- The coverage floor stops "I looked at the clarifier that alarmed" — you check the whole train.
- Raising the chlorine dose is terminal (hard to walk back downstream) → it routes to the adversary.

## To adapt: nothing. To override (optional):

1. Just run `/goalspec <your task>`. The inference above happens automatically.
2. *Only if you want determinism:* copy `goal.config.example.json` to `.claude/goal.config.json`
   (project) or `~/.claude/goal.config.json` (every project) and set `sweep_files` (pin the exact
   decision docs) and/or `adversary.backend` (route to a different model). Each key resolves
   project→global independently. Delete every other field — they default to inference.

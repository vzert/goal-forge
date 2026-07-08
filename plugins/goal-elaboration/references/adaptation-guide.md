# Adaptation guide — parameterize the methodology for your domain

The methodology (constitution + scaffold + red-team + adversary) is domain-invariant. Five things
are domain-specific; you supply them in `.claude/goal.config.json` (copy `goal.config.example.json`).
With no config the plugin still runs — the reasoning steps work everywhere; only the mechanical
sweep/coverage steps soften to prompts.

## The five fields

| Field | What it is | How to choose it |
|---|---|---|
| `ground_truth_sources` | The verifiable things a success criterion can cite | Anything you can *query and re-derive*: a test suite, CI status, a DB table, an analytics API, an APM dashboard, a primary document. Not a proxy, not a marker, not another agent's summary. |
| `sweep_files` | Files the mechanical inherited-decision sweep greps before closing | Wherever open decisions / TODOs / known-issues accumulate for your work. The point is a *literal grep*, so name real files. |
| `enumerate_entities_step` | What "cover all the children, not a sample" means here | Name the child entity and the per-entity data required (see examples). |
| `no_harm_threshold` | The reversibility bar for a mutating action | State what "working" means and what a "validated replacement + reversible path" looks like in your domain. |
| `terminal_actions` | Actions that force an independent adversary before closing | The irreversible / high-blast-radius verbs in your domain. |
| `adversary.backend` | `"subagent"` (same-model, fresh context) or `"external"` (different model/CLI) | See `external-adversary-setup.md`. Start with `subagent`; move to `external` when you want independence from correlated model bias. |

## Worked mapping 1 — code review

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

## Worked mapping 2 — research / writing

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

## Checklist to adapt

1. Copy `goal.config.example.json` to your project's `.claude/goal.config.json`.
2. Fill `ground_truth_sources` with things you can query and re-derive.
3. Point `sweep_files` at real files where decisions/TODOs live (create one if you have none — an
   `open-decisions.md` is enough).
4. Define `enumerate_entities_step`: name the child entity + the per-entity data.
5. List `terminal_actions` — the verbs that must not close without an independent adversary.
6. Pick the adversary backend. `subagent` is zero-setup; `external` needs a second CLI (see setup doc).

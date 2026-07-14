# External adversary setup — "the partner reviews, never the host"

By default the adversary is a `goal-adversary` **subagent**: fresh context, same model. Fresh context
is a real independence lever — it hasn't seen your reasoning, so it can't inherit your blind spots.
But it *is* the same model, so it shares correlated biases. Community prior art on adversarial-review
plugins is blunt about this: a same-model panel is "structured self-critique, not independent
verification." For true independence, route the critique to a **different model or CLI** — the
"partner reviews, never the host" pattern.

## When to use which

| Backend | Independence | Setup | Use when |
|---|---|---|---|
| `subagent` (default) | Fresh context, same model | None | Most tasks; correlated bias is acceptable |
| `external` | Different model *and* context | A second CLI on PATH | Terminal/irreversible decisions; when you want a genuinely uncorrelated check |

## Enabling the external backend

1. Install a second CLI. Any of these work; pick what you have:
   - **OpenAI Codex CLI** — `external_cmd: "codex exec"`
   - **Google Gemini CLI** — `external_cmd: "gemini -p"`
   - **A different Claude model as the partner** — `external_cmd: "claude -p --model claude-sonnet-5"`
2. In `.claude/goal.config.json`:
   ```json
   "adversary": { "backend": "external", "external_cmd": "codex exec" }
   ```
3. `/goalspec` step 6 will then run `hooks/external-adversary.sh`, which pipes the goal-spec +
   outcome + the adversary prompt to that command on stdin and expects the standard
   `[ADVERSARY-VERDICT: ...]` block back.

## Contract

`external-adversary.sh` reads the goal-spec + outcome on stdin and prints exactly the same verdict
grammar the subagent produces:

```
[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]
```

So the rest of the loop (`/goalspec` step 6, the completion-review declaration, the Stop gate) is
identical regardless of backend.

## Safety rails

- **Missing binary → fail-open.** If the configured CLI isn't on PATH, the script prints a `hold`
  verdict *plus a stderr note that no independent check ran* — treat that `hold` as UNVERIFIED, not
  as a pass. It never blocks the host.
- **Anti-recursion.** If the external command is itself a Claude that has this plugin installed, the
  script exports `GOAL_ADVERSARY_ACTIVE=1`; a nested invocation detects the flag and refuses to
  re-enter the loop. Without this, an external-Claude backend could recurse indefinitely.

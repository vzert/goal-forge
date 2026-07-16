# External adversary setup — "the partner reviews, never the host"

By default the adversary is a `goal-adversary` **subagent**: fresh context — it hasn't seen your
reasoning, so it can't inherit your conversation's blind spots. Since 0.5.0, for **terminal
decisions** the executor also spawns it on a **different model tier** than its own (a per-spawn
`model` override — zero install, zero config) and verifies where it actually ran from the
adversary's own `[ADVERSARY-MODEL: …]` self-report, because harnesses fall back silently when an
override can't be honored. That closes most of the correlated-bias gap within one model family.
Community prior art on adversarial-review plugins is still blunt about the remainder: a same-vendor
panel is weaker than a genuinely foreign one. For the strongest independence, route the critique to
a **different vendor's model/CLI** — the "partner reviews, never the host" pattern.

## When to use which

| Backend | Independence | Setup | Use when |
|---|---|---|---|
| `subagent` (default) | Fresh context; different *tier* of the same family for terminal actions (self-attested, degrades announced) | None | Most tasks, including terminal ones |
| `external` | Different **vendor** *and* context | A second CLI on PATH | The premise under review came from your model family; single-model harnesses; maximum decorrelation |

## Enabling the external backend

1. Install a second CLI. Any of these work; pick what you have:
   - **A different Claude model as the partner** — `external_cmd: "claude -p --model claude-sonnet-5"`
     — the one verified end-to-end against a real CLI (v0.4.0), and it reads stdin natively.
   - **OpenAI Codex CLI** — `external_cmd: "codex exec"` (reads stdin; verify your install actually
     runs — `printf 'say OK' | codex exec`. The npm wrapper can be on PATH while its vendored binary
     is missing, which `command -v` cannot detect.)
   - **Google Gemini CLI** — needs an adapter: `gemini -p` takes the prompt as an **argument**, not on
     stdin, so it cannot be used bare with this script. Wrap it, e.g. a `gemini-stdin` on your PATH:
     `#!/usr/bin/env bash` + `exec gemini -p "$(cat)"`, then `external_cmd: "gemini-stdin"`.
2. In `.claude/goal.config.json`:
   ```json
   "adversary": { "backend": "external", "external_cmd": "codex exec" }
   ```
3. `/goalspec` step 6 will then run `hooks/external-adversary.sh`, which pipes the goal-spec +
   outcome + ask record + the adversary prompt to that command on stdin and expects the standard
   `[ADVERSARY-VERDICT: ...]` block back.

## Contract

`external-adversary.sh` reads the goal-spec + outcome + ask record on stdin and prints exactly the
same verdict grammar the subagent produces — including the model self-report that opens it:

```
[ADVERSARY-MODEL: <name> / <exact id, or UNKNOWN>]
...confirmed-violation bullets...
[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]
```

The model line exists because "I routed to a different model" is itself a load-bearing claim, and
the routing parameter (config, spawn override) is not evidence for it — a wrapper can be broken, a
harness can fall back silently. Only the partner can attest what it is; `UNKNOWN` is honest and
downgrades the independence claim, a fabricated ID would poison it.

So the rest of the loop (`/goalspec` step 6, the completion-review declaration, the Stop gate) is
identical regardless of backend.

**One check depends on your partner's reach.** The dead-handoff check (did a decision named as the
human's actually get *asked*?) is grounded in the session log, because that is the one source the
executor doesn't author. Whether your partner can read it is a property of **the CLI you chose, not of
"being external"** — a file-capable partner on the same host (`claude -p --model …`, or codex/gemini
with filesystem access) can and must go read it; a sandboxed or remote one reports
`UNVERIFIABLE-BY-THIS-BACKEND` and does not count it, since counting would manufacture a `break` on a
correct ask and passing silently would be toothless. The prompt tells the partner to **test its reach
rather than assume**.

> An earlier draft of this paragraph asserted that an external partner "cannot read the session log".
> That was false, and it is worth knowing how it was caught before release: 0.4.0 drafted it as fact,
> six same-model adversary rounds accepted it (one explicitly blessed it as "a real engineering
> decision, not rationalization"), and then a **Sonnet partner refuted it by simply reading the log** —
> the thing the design called impossible. That is the correlated-bias failure this backend exists to prevent, demonstrated on the
> backend's own documentation. Keep the trade in view: the subagent is context-independent but
> **model**-correlated; the external partner is the only one that can catch a premise your own model
> finds plausible. Running both is strictly better than either.

## Safety rails

- **Missing binary → fail-open.** If the configured CLI isn't on PATH, the script prints a `hold`
  verdict *plus a stderr note that no independent check ran* — treat that `hold` as UNVERIFIED, not
  as a pass. It never blocks the host.
- **Missing self-report → independence UNVERIFIED.** A filled verdict with no `[ADVERSARY-MODEL: …]`
  line still counts as a verdict, but the script says so on stderr and the completion-review must
  claim `model=same`, not `model=different`. The Stop gate cross-checks a `model=different (<id>)`
  claim against a matching self-report in the turn (advisory, fail-open).
- **Anti-recursion.** If the external command is itself a Claude that has this plugin installed, the
  script exports `GOAL_ADVERSARY_ACTIVE=1`; a nested invocation detects the flag and refuses to
  re-enter the loop. Without this, an external-Claude backend could recurse indefinitely.

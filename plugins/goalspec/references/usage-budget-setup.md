# Usage-budget setup — OFF by default, read this before enabling

**Contents**: [An honest caveat: this endpoint is undocumented](#an-honest-caveat-this-endpoint-is-undocumented) · [What it does](#what-it-does) · [What it never does](#what-it-never-does) · [Why this needed its own ratify decision, not a default](#why-this-needed-its-own-ratify-decision-not-a-default) · [Enabling it](#enabling-it) · [Relationship to a statusline tool (e.g. ccstatusline)](#relationship-to-a-statusline-tool-eg-ccstatusline)

Every other config key in this plugin (`sweep_files`, `adversary.backend`) reads project-local
files or routes a subagent spawn. `usage_budget` is different in kind: enabling it makes
`hooks/check-usage-budget.sh` read your **local Claude Code OAuth access token** and send it to
Anthropic's own account-usage endpoint. That is why it defaults to `false` and why it gets its own
doc instead of a one-line comment in `goal.config.example.json`.

## An honest caveat: this endpoint is undocumented

`api.anthropic.com/api/oauth/usage` is **not** part of Anthropic's published API reference. What
this hook (and this doc) claims about it — its path, that it accepts the same OAuth token Claude
Code itself uses, its `five_hour`/`seven_day`/`extra_usage` response shape — is inferred entirely
by reading a working third-party client's source (`ccstatusline`, which calls it successfully) and
by testing our own call against it, not from any official Anthropic documentation. Treat it as
**observed compatibility, not a stable, guaranteed capability**: it could change shape or be
restricted without notice, unlike the documented Messages API. The hook is fail-open specifically
*because* of this — every failure mode (wrong shape, 4xx, network error) degrades to silence, never
an error the user has to chase.

## What it does

When `usage_budget.enabled` resolves to `true` (project `.claude/goal.config.json` overrides
user-global `~/.claude/goal.config.json` — the same per-key fallback `adversary.backend` and
`sweep_files` already use), the Stop hook, **only within a goalspec-tracked session** (a
`## Goal-spec` present in the run):

1. Resolves your OAuth token the same way `ccstatusline` does (matched precedence, confirmed
   against its source): on **macOS**, tries the `"Claude Code-credentials"` Keychain entry
   *first*, falling back to `$CLAUDE_CONFIG_DIR/.credentials.json` (default
   `~/.claude/.credentials.json`) only if the Keychain lookup fails. On **every other platform**,
   reads the `.credentials.json` file directly (there is no Keychain to try). Either source is
   parsed the same way: the `claudeAiOauth.accessToken` field of a JSON blob — the Keychain
   secret is **not** a bare token string, it's the identical JSON shape as the file.
2. Calls `GET https://api.anthropic.com/api/oauth/usage` with that token.
3. Reads `five_hour.utilization` (and `seven_day.utilization`) from the response.
4. If utilization is **below** `warn_threshold` (default `80`): stays silent. No output, no noise.
5. If **at or above** threshold: prints a single non-blocking advisory nudging you to checkpoint
   state to `.goalspec/checkpoint-<session>.md` (SKILL.md's "Execute" step; the shape, and why
   the name carries a session token, in `references/durable-artifact.md`) — never blocks the stop.

## What it never does

- Never logs, caches, or prints the token itself — only the resulting utilization percentages are
  cached (to `$CLAUDE_CONFIG_DIR/goalspec-usage-cache.json`, TTL 300s, so a Stop-hook-per-turn
  cadence doesn't hammer the API).
- Never fires outside a goalspec-tracked session.
- Never blocks. A missing token, a network error, a non-200, a malformed response — all fail open,
  silently, exit 0. This is advisory only, same as every other hook in this plugin.

## Why this needed its own ratify decision, not a default

While investigating this mechanism, an attempt to merely *check whether the credentials file
exists* was blocked by the calling agent's own permission classifier as a sensitive action. That is
real signal, not theoretical: reading account credentials — even read-only, even to a first-party
Anthropic endpoint — is a materially larger trust surface than anything else this plugin does. A
public plugin should never default into that; it should require an explicit, informed opt-in. This
doc is that opt-in's informed-consent step.

## Enabling it

```json
// .claude/goal.config.json (project) or ~/.claude/goal.config.json (every project)
{
  "usage_budget": { "enabled": true, "warn_threshold": 80 }
}
```

Put it in `~/.claude/goal.config.json` if you want the nudge on every project; a project file can
override just `warn_threshold`, or set `enabled: false` to opt back out for one repo, without
touching any other resolved key (same per-key precedence as `adversary`).

### Quick enable — hand this prompt to your own agent

You just read the caveat above yourself, so you're the informed party — this prompt has your
agent make the edit without re-litigating consent with itself:

```
Lee plugins/goalspec/references/usage-budget-setup.md (o dime en 2-3 líneas qué implica de
seguridad si no lo encuentras) antes de tocar nada. Si estoy de acuerdo después de eso, crea o
edita .claude/goal.config.json (este proyecto) o ~/.claude/goal.config.json (todos mis proyectos)
para incluir "usage_budget": {"enabled": true, "warn_threshold": 80} sin sobreescribir otras claves
que ya existan ahí.
```

## Relationship to a statusline tool (e.g. ccstatusline)

If you already run a statusline tool that reads this same endpoint (community tools like
`ccstatusline` do — confirmed by reading its source: it calls the identical
`api.anthropic.com/api/oauth/usage` endpoint via the identical credential lookup, caching the
result to its own `~/.cache/ccstatusline/usage.json`), this hook does **not** read that tool's
cache — it is a separate, first-party instrument with its own cache, so it keeps working whether
or not you have any particular statusline installed, and never depends on a third-party tool's
cache format or file location, which can change without notice between versions.

Context-window usage (as opposed to the account's 5-hour/7-day ceiling) is a different, harder
problem: Claude Code only ever delivers `context_window.*` fields live, via stdin, to whatever
script you've configured as your *statusline* — never to a hook, and never persisted to disk by
Claude Code itself. There is no equivalent first-party mechanism this hook can use for context; the
authoritative live source for that remains the interactive `/context` command, or your own
statusline's context bar. This is why "coverage floor" (SKILL.md) address context risk through
**execution decomposition** (subagents/agent teams, one bounded context per independent entity)
rather than through reading a number.

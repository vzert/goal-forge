# goal-forge / goalspec — project guide

Public Claude Code plugin marketplace repo (`github.com/vzert/goal-forge`) containing one plugin,
**goalspec**: a portable self-goal + independent-adversary methodology that turns a terse request
into a grounded, falsifiable goal-spec, verifies it with an independent adversary, and closes through
a fail-open completion gate. Genericized from a validated fleet pilot; zero-config; hardens the
built-in `/goal`.

Layout: `plugins/goalspec/` (skill + agent + hooks + config), `.claude-plugin/marketplace.json`,
`README.md`, `CHANGELOG.md`, `test/` (acid-test fixture).

## Release discipline (hard-won — do not skip)
- **Bump `plugins/goalspec/.claude-plugin/plugin.json` `version` on every release.** The install cache
  is keyed by version (`~/.claude/plugins/cache/goal-forge/goalspec/<version>/`); a push without a
  bump is never delivered to installed users. Keep `marketplace.json` `metadata.version` in sync.
- **Never `| tail` a `claude plugin validate`** — the pipe masks the exit code and a broken manifest
  ships silently. Check the real exit code, and parse the SKILL.md frontmatter as YAML (confirm
  `name`+`description` survive) before committing — a bare `: ` (colon-space) in the description
  breaks YAML and the skill loads with empty metadata (no auto-trigger).
- **Don't rename the plugin.** A rename breaks auto-update (it only bumps same-name versions) and
  forces every existing user through a manual migration. The name `goalspec` is now stable.

## Verifying a change (manual acid-test)
No CI — the plugin is a skill + hooks + docs. To sanity-check a change end-to-end:
1. Validate manifests (real exit code, not `| tail`) and parse SKILL.md frontmatter as YAML.
2. In a throwaway dir with an `open-decisions.md` holding a planted inherited decision, run
   `/goalspec audit <thing> and decide what to kill`. Assert: a `## Goal-spec` with grounded criteria
   appears; the mechanical sweep surfaces the planted decision; the `goal-adversary` runs (terminal
   action) and returns a `break|hold` verdict; a `[COMPLETION-REVIEW: …]` is emitted; the Stop gate
   stays advisory (blocks only with `GOAL_GATE_ENFORCE=1`).
3. Unit-test the Stop gate by piping synthetic `{"last_assistant_message": …}` JSON to
   `hooks/gate-goal-close.sh` across its branches (no-spec → silent; spec-no-review → advisory;
   valid `[COMPLETION-REVIEW: none reason=…]` → pass).

## Memory System
This project uses the 3-tier memory plugin. Operational indexes live in `memory/`:
- `memory/MEMORY.md` — lean Tier 1 index (stable orientation only, no volatile data)
- `memory/_pendientes.md` — open action items by priority
- `memory/_learnings.md` — learnings by topic → `memory/learnings/<topic>.md`
- `memory/_session-index.md` — session history → `memory/sessions/DATE-SLUG.md`
- `memory/_plans-index.md` — plans registry → `memory/plans/`
- `memory/_research-index.md` — research tracker → `memory/research/`

Consult `memory/_learnings.md` before making changes. Use **`/checkpoint-3t`** to save progress at the
end of substantive work — it writes the session log, reconciles + extracts action items, captures
learnings, updates indexes, and git-commits. `/status-3t` for a health overview, `/audit-3t` to verify.

## CRITICAL: Auto-memory MEMORY.md is a BRIDGE ONLY

The file at `~/.claude/projects/<encoded-path>/memory/MEMORY.md` is a bridge that redirects to
`memory/` in this project. NEVER write content, indexes, session data, learnings, or any operational
data into that file. It must ONLY contain the redirect template. All memory operations go to
`memory/` in the project directory. If auto-memory MEMORY.md has more than 30 lines, something is
wrong — rewrite it as a bridge immediately.

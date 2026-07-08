# Changelog

All notable changes to the `goalspec` plugin. This project follows
[semantic versioning](https://semver.org/). **Bump `plugins/goalspec/.claude-plugin/plugin.json`
`version` on every release** — the install cache is keyed by version
(`~/.claude/plugins/cache/goal-forge/goalspec/<version>/`), so changes pushed without a
version bump are never delivered to already-installed users.

## [0.2.3] - 2026-07-08

### Changed
- **Trigger description now lists common domains instead of a niche one.** 0.2.1 listed
  "even a water-treatment plant" as a domain example — memorable, but too niche for a trigger
  (it signals "for weird edge cases" rather than breadth). Replaced with the domains where users
  actually are: software engineering, data and analytics, marketing, research, writing, and product
  and business decisions. (The water-treatment worked example stays in the adaptation guide, where
  it usefully proves domain-independence.)

## [0.2.2] - 2026-07-08

### Fixed
- **Broken YAML frontmatter in 0.2.1.** The optimized description contained `not just code: software`
  — a colon-space that YAML parses as a mapping, so the skill loaded with **empty metadata** (the
  description was silently dropped, killing auto-trigger). Replaced the colon with a dash. Added a
  frontmatter YAML-parse check to the release routine so this can't recur. Anyone who pulled 0.2.1
  should update to 0.2.2.

## [0.2.1] - 2026-07-08

### Changed
- **Optimized the skill's auto-trigger description** (reviewed via the official skill-creator method).
  The old description listed task *types* but no *domains*, so it read as software/ops jargon and
  risked silently under-triggering on marketing/copywriting/ops/research tasks — undermining the
  zero-config-any-domain design. The new description names explicit domains, adds real-world trigger
  phrasings ("should I kill/ship/publish Y", "figure out why Z dropped", "review this before I
  merge"), and is more directive ("Trigger it whenever…") to counter Claude's known tendency to
  under-trigger skills — while keeping the anti-false-fire clause (no contentless "continue" turns,
  no trivial one-step lookups). Methodology in the body is unchanged.

## [0.2.0] - 2026-07-08

### Changed
- **Renamed the plugin `goal-elaboration` → `goalspec`, and made the skill the single entry point.**
  Claude Code mandates that plugin commands are namespaced (`/plugin:command`), so the old
  `commands/goalspec.md` was only reachable as `/goal-elaboration:goalspec`. Because a skill whose
  name equals its plugin's name renders un-namespaced, naming both `goalspec` makes the skill
  invocable as a clean `/goalspec` (it also auto-triggers). The standalone command was removed and
  its runbook folded into the skill. **Install id is now `goalspec@goal-forge`** — early installers
  of `goal-elaboration@goal-forge` should `uninstall` the old id and install the new one.
- **Zero-config for any domain.** The skill no longer requires `.claude/goal.config.json`. It now
  infers everything domain-specific from the task itself: ground-truth sources (named per-task),
  files to sweep (discovered by globbing decision/TODO/pending docs), which entities to enumerate
  (the task noun), and which actions are terminal (judged per-action). Config survives only as an
  optional power-user override for pinning exact sweep files or selecting an external adversary
  backend.

### Added
- **Clarifying-questions step (anti-drift).** Before committing to a goal-spec, the agent resolves
  load-bearing ambiguity (objective / scope / terminal-action authorization / done-bar) via the
  `AskUserQuestion` modal — so a 30-second question prevents an hour of misdirected work. Balanced
  threshold; when the task is clear it states its assumptions inline instead. Degrades gracefully in
  headless/cron runs.
- **Agent-guided install instructions** in the README: a top-of-file comment for AI agents plus
  terminal-form `claude plugin` commands, team/manual/dev install paths, and uninstall.
- Plugin manifest now carries `repository`, `license`, and `keywords`.

## [0.1.0] - 2026-07-08

### Added
- Initial release: the 5-principle constitution + 6-question goal-spec scaffold + red-team
  (`skills/goalspec`), an independent `goal-adversary` subagent (subagent or external-CLI
  backend), the `/goalspec` command, and a fail-open, transcript-anchored Stop completion gate.
  Genericized from a validated fleet pilot; no control-plane coupling.

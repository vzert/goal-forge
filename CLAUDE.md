# goal-forge / goalspec — project guide

Public Claude Code plugin marketplace repo (`github.com/vzert/goal-forge`) containing one plugin,
**goalspec**: a portable self-goal + independent-adversary methodology that turns a terse request
into a grounded, falsifiable goal-spec, verifies it with an independent adversary, and closes through
a fail-open completion gate. Genericized from a validated fleet pilot; zero-config; hardens the
built-in `/goal`.

Layout: `plugins/goalspec/` (skill + agent + hooks + config), `.claude-plugin/marketplace.json`,
`README.md`, `CHANGELOG.md`, `test/` (Stop-gate branch suite + the manual acid test).

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
CI runs the mechanical half on every push and PR (`.github/workflows/tests.yml`): all the suites on
**both** Ubuntu and macOS, plus `bash -n` — and on macOS also `/bin/bash -n`, because /bin/bash there
is 3.2 and the one recorded way this repo shipped a dead hook (an unbalanced apostrophe in an
unquoted heredoc) parses fine under bash 5. A second job runs `test/manifest-checks.py`.
**A green CI run is not the acid test**: it does not observe an agent obeying a written rule, a
hook firing in a real session, or an adversary round running, so every "observe in the wild"
pendiente stays manual. That is a scoping decision, not an impossibility: `claude --help` documents
headless `-p`, credential-bearing auth and `--max-budget-usd`, so such a job is feasible and
boundable. What it would add is a credential in CI, a per-run cost, and non-determinism these
hermetic suites do not have. Whether that trade is worth it is open. To sanity-check a change end-to-end:
1. Validate manifests (real exit code, not `| tail`) and parse SKILL.md frontmatter as YAML.
2. In a throwaway dir with an `open-decisions.md` holding a planted inherited decision, run
   `/goalspec audit <thing> and decide what to kill`. Assert: a `## Goal-spec` with grounded criteria
   appears; because the spec carries a terminal action (kill), the **4b ratify-the-spec gate** fires
   (an `AskUserQuestion` presenting scope/blast-radius before execution, least-irreversible default);
   the mechanical sweep surfaces the planted decision; the `goal-adversary` runs (terminal
   action) and returns a `break|hold` verdict; a `[COMPLETION-REVIEW: …]` is emitted; the Stop gate
   stays advisory (blocks only with `GOAL_GATE_ENFORCE=1`).
3. Run **the ten branch suites plus the carrier suite** (eleven commands; one of them drives no
   hook branches — it asserts text): `python3 test/gate-branches.py` (Stop gate — includes the
   terminal-action staleness backstop cases, `stale-01`..`04`, which need live git repos and
   `CLAUDE_PLUGIN_ROOT` set, unlike every other case in that file),
   `python3 test/verdict-nudge-branches.py` (PostToolUse verdict nudge),
   `python3 test/usage-budget-branches.py` (opt-in usage-budget Stop hook — hermetic, no credential
   and no network; it drives the hook through its cache seam),
   `python3 test/external-adversary-branches.py` (external-partner backend — hermetic via a
   `GOAL_ADVERSARY_CMD` stub; pins the bare-verdict floor scoping and the P25 sandbox rails),
   `python3 test/decompose-nudge-branches.py` (advisory decomposition/checkpoint nudge — hermetic,
   synthetic checkpoint + transcript), `python3 test/terminal-precheck-branches.py` (PreToolUse
   terminal-push precheck — hard-blocks a push/merge/deploy/destructive command with no operative
   adversary hold; needs live git repos per case, built with the bare remote OUTSIDE the working
   tree), `python3 test/announce-checkpoint-branches.py` (SessionStart hook that announces the
   per-session checkpoint filename — hermetic, synthetic payloads; asserts what it emits, never
   that the agent then uses it), `python3 test/claim-surface-carriers.py` (**not a branch suite**: the claim-surface
   rule is present and mutually consistent across its four carriers — hermetic, pure text assertions; it cannot show
   that an agent then applies the rule), `python3 test/checkpoint-overwrite-branches.py` (PreToolUse
   Write|Edit gate that denies overwriting a checkpoint this session did not write — real files in
   a temp dir plus a synthetic transcript, no git), and `python3 test/adversary-writes-branches.py`
   (SubagentStart/Stop read-only rail for the subagent adversary — throwaway git repos, synthetic
   payloads, `TMPDIR` redirected per case), and `python3 test/adversary-report-branches.py` (the Stop
   hook that reports that rail's findings to the executor — fully hermetic, no git).
   Plus `python3 test/manifest-checks.py` (**not a branch suite**: version sync between
   `plugin.json` and `marketplace.json`, frontmatter that a real YAML parser accepts, every
   `hooks.json` path resolving to a file that exists, and the suite counts in this file and
   `test/README.md` matching reality, and that no carrier still claims the project has no CI — the
   silent-failure classes no branch suite can see. Needs PyYAML. `--selftest` breaks each of those
   in a throwaway copy and requires the checker to notice; run it after editing that file).
   **When editing the gate, copy the
   pre-edit script somewhere and `--compare` against it afterwards, in both default and
   `GOAL_GATE_ENFORCE=1` modes** — it exits non-zero if any branch changed, which turns "no
   regression" from an eyeball into a measurement. See `test/README.md`.

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

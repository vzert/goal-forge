# Changelog

All notable changes to the `goalspec` plugin. This project follows
[semantic versioning](https://semver.org/). **Bump `plugins/goalspec/.claude-plugin/plugin.json`
`version` on every release** — the install cache is keyed by version
(`~/.claude/plugins/cache/goal-forge/goalspec/<version>/`), so changes pushed without a
version bump are never delivered to already-installed users.

## [0.4.0] - 2026-07-16

### Added
- **"Decisions you find mid-run — route them, don't narrate them" — the ask door no longer closes
  when the spec is committed.** Observed failure: after emitting the goal-spec, the agent would
  surface real forks in prose ("two decisions are yours"), list them well, and keep going — the
  human got a paragraph, never a question, and the run closed with the decision dangling. The
  mechanism was structural, not a lapse: (1) the only section teaching `AskUserQuestion` was titled
  "Clarify **before** you commit" and sat at step 2, so a fork *discovered during the work* — which
  is where most real forks live — had no affordance left; (2) Q5 asked the agent to *classify* which
  part is a human decision, and Completeness was satisfied by "every factor has an owner", so
  labeling owner=human **felt like discharging it**; (3) all mechanical pressure at close pointed at
  the `[COMPLETION-REVIEW]` marker, so an unasked decision cost the agent nothing. A new section
  makes the ask door stay open for the whole run, with a **decision-vs-doubt test** (route what turns
  on their intent/priorities/authorization *and* changes the work; never route what you can settle by
  reading the repo — that violates Autonomy just as hard), batching, recommended defaults, and
  "asking ≠ blocking".

### Changed
- **Q5 (Autonomy) reframed from labeling to routing** — naming a human decision is a *promise to
  ask*, not a filing category. An unasked decision is not owned.
- **The red-team gained the mirror check** — the Autonomy self-critique asked only "am I handing a
  human something an agent could execute?" (over-delegating). It now also asks the inverse: did I
  name a decision as theirs and never ask it?
- **`goal-adversary` now counts a dead handoff as an `autonomy-violation`** — both directions of the
  Autonomy failure are attackable, and a new mechanical **dead-handoff sweep** takes every Q5 human
  decision plus every fork the outcome hands the user and demands the place it was actually *asked*.
  Per the method's own philosophy (`references/outcome-loop-beats-gates.md`), the teeth go in the
  independent adversary, not in another Stop-hook regex over natural language.
- **The adversary verifies the ask against the session transcript — a source the executor doesn't
  author.** Found by running the adversary on this very change, twice; it returned `break` both times.
  First pass: the dead-handoff sweep had been added to an instrument that couldn't see the thing it
  checked — the adversary was handed only the goal-spec, the outcome, and the location of the work, so
  its only evidence was the executor's prose about the decision, the exact artifact the check exists
  to distrust. Second pass, on the fix for the first: adding an executor-supplied "ask record" to the
  intake **moved the trust without grounding it** — prose-A ("I surfaced it") became prose-B ("I asked
  at X, they said Y"), and both are text the executor types, so a narrating agent and an asking agent
  stayed indistinguishable. The adversary proved the real ground-truth was two commands away, and that
  the file already knew the pattern: the sibling inherited-decision sweep (`goal-adversary.md:24`) says
  "glob for them… grep them **yourself**". So the dead-handoff sweep now has the same **self-discovery verb** — it locates
  the session transcript itself and greps for the `AskUserQuestion` tool_use / tool_result pair. The
  executor's record is demoted to a *pointer to check*. An ask claimed but unverifiable in a source the
  executor doesn't control counts as a violation, per the agent's standing "uncertain → `break`" rule.
  A third pass then broke *that*: the hand-derived transcript path was wrong (`.` also maps to `-`, so
  any dotted cwd missed the glob — and combined with the new fail-closed rule that manufactures
  spurious `break`s), and the sweep never scoped to **this run**, while its sibling action-marker check
  (`goal-adversary.md:23`) does — this repo's transcript dir holds three sessions, all three containing
  an `AskUserQuestion`, so
  a prior session's ask would have blessed an agent that narrated today. The sweep now identifies the
  live transcript **by content** instead of trusting a derived path, and scopes the search to this
  session. A fourth pass then *executed* the instruction and landed on the wrong file — proving the
  newest-mtime tiebreak was a systematic anti-selector (subagent logs are written while the adversary
  runs, so they are always newer than the parent, and a subagent has no `AskUserQuestion` tool, so they
  can never contain an ask), and that a text-grep blesses prose that merely quotes the question. The
  sweep now reads the top-level session file only, matches the `tool_use`/`tool_result` **structure**
  rather than text, and requires a **positive control** — confirm you are reading the live session log
  before concluding an ask is absent, because a broken instrument is a null result with two disjoint
  causes, not proof of a dead handoff. "Confirmed dead handoff" and "unverifiable claim" are now
  reported as distinct outcomes (both count, but the executor can tell which to fix).
- **The `external` adversary backend carries principle 4 too — and is honest about the one check it
  can't run.** `hooks/external-adversary.sh` had kept principle 4 in its pre-fix, one-directional form
  ("nothing an agent could execute should be handed to a human"), so every user on
  `adversary.backend: "external"` would have gotten none of this while the changelog claimed both
  directions were attackable. Caught by the fourth adversary pass as a coverage-floor miss: the two
  documented backends were never enumerated. The fifth pass then broke the first repair — the
  *principle text* had shipped to the external backend but not the *evidence path*: an external CLI runs
  outside the session, so the positive control ("confirm you're reading **this** run's log") has no
  "this run" to anchor to, and the script piped only goal-spec + outcome anyway. Under the script's
  standing "cannot verify → count it" rule that would have manufactured a `break` on a genuinely correct
  ask. So: the ask record is now piped to the external partner, and principle 4 there tells it the ask
  record is a pointer, to **test its reach** and go read the session log if it can, and to report
  `UNVERIFIABLE-BY-THIS-BACKEND` (not counted) only if it genuinely cannot — an unreachable instrument
  is not a finding, but an unchecked one is just laziness.

### The correlated-bias result (why the `external` backend earns its keep)

Six adversary rounds were run against this change, all same-model fresh-context subagents. They found
five real defects. Then a **different model** (`claude -p --model claude-sonnet-5`, via the external
backend) was run on the same outcome — and refuted a premise all six had accepted:

- v0.4.0 had asserted, as fact, that an external partner "runs outside the session, so it cannot read
  the session log," and built the whole `UNVERIFIABLE-BY-THIS-BACKEND` carve-out on it. Adversary #6
  explicitly blessed it as "a real engineering decision, not a rationalization."
- The Sonnet partner falsified it **by doing the thing the design called impossible**: it read the live
  session log and located the `AskUserQuestion` tool_use/tool_result pairs itself. `claude -p` is a
  different *model*, not a different *machine* — same host, same filesystem, same tools.

The carve-out is therefore now **capability-conditional, not backend-conditional**. More importantly,
this is the correlated-bias failure the external backend exists to prevent, demonstrated on the
backend's own documentation: the subagent adversary is context-independent but **model**-correlated, and
six rounds of it could not see a premise the model found plausible. `references/external-adversary-setup.md`
now records this rather than claiming the backends are interchangeable.

### Fixed — instrument-validity in the external backend's own rails

Found by finally smoke-testing `external-adversary.sh` against real CLIs (an item deferred since
2026-07-08; the stub-`cat` test that preceded it proved only that the payload arrives):

- **A present-but-broken CLI produced no verdict at all.** The "missing binary → fail-open" rail checks
  `command -v`, which only proves a *wrapper* is on PATH. A `codex` whose vendored binary is missing
  passes that check, then dies with `ENOENT`, exit 1, and **no `[ADVERSARY-VERDICT:]` line** — handing
  the caller silence that reads as "no objection". The script now captures the run and requires a
  **filled** verdict; a non-zero exit or a malformed reply degrades to an explicit `hold` labelled
  UNVERIFIED, with the partner's output on stderr. (The rail claimed to handle exactly the
  instrument-validity failure it was blind to.) The first cut of this rail was itself broken, and the
  Sonnet partner caught it by *testing* rather than reading: it matched `grep '\[ADVERSARY-VERDICT:'`,
  but **the prompt contains that literal string** as the grammar template — so any CLI that echoes its
  stdin and exits 0 (a debug wrapper, or a plain `cat`) passed the gate and had its unfilled
  **placeholder** printed back as a real verdict. The pattern now demands `(break|hold)` plus numeric
  counts (rejecting both `break|hold` and `<n>`) and takes the last match, so a partner that quotes the
  grammar before answering still resolves to its real verdict. Six branches are covered by test: broken
  binary, missing binary, echo-the-prompt, chatty-no-verdict, quote-then-answer, and well-formed.
- **`gemini -p` was documented as a working `external_cmd` and cannot work.** It takes the prompt as an
  argument, not on stdin, so it can never receive a piped payload. The reference now ships a one-line
  adapter instead of a broken recipe, and flags that `codex`'s install should be verified by running it.
- **Dead-handoff detection is semantic, not a phrase list.** Also found by the adversary: the first
  cut shipped English-only literals (`"your call"`, `"up to you"`) — which would have missed the
  Spanish run that motivated the whole change ("dos decisiones que son tuyas"), while the changelog
  justified skipping hook teeth precisely *because* cross-language regex is fragile. The rationale and
  the artifact didn't reconcile. Both the self-red-team and the adversary now read for the **act**
  (did this sentence put a choice on the human?) in whatever language the executor writes; the phrases
  are illustrations, not the detector.
- The GOOD worked example now models raising the decision as a modal at the decision point, rather
  than as a line in the summary.

### Added — two holes this release's own dogfooding exposed

- **Q2 criteria now get gamed before they are committed.** Nothing in the method red-teamed the *spec*;
  the adversary only ever attacked the *outcome*, by which point the criteria were set. This release
  proved the cost: every one of its own success criteria was "text present in a file" while its
  objective was behavioural — five criteria the executor could satisfy with the very edits it was
  already making. The adversary caught it by quoting the constitution back (`SKILL.md:14`,
  *"marker present" ≠ done*), and it was only closed by running the acid test. Q2 now carries the test:
  *what would a lazy agent do to satisfy this without achieving the objective?* If the answer is "make
  the edit I was already going to make", it is a marker. The tell is an objective describing a
  behaviour against a criterion grepping for text.
- **A convergence guard on the break loop.** Nothing said when to stop patching. This change took five
  consecutive `break`s where **each round broke the previous round's fix** — a loop that could have run
  indefinitely, since every individual patch looked like progress. Step 6 now says: each round should
  break something smaller than the last; at three consecutive breaks the design is wrong, not the
  wording — reconsider the approach or route to a different model.
- **Instrument-validity turned on the method's own tools.** The red-team now asks it explicitly. Every
  expensive defect in this release was the method failing to audit its own instruments: a dead-handoff
  check with no evidence intake, a transcript rule that selected a file that could not hold the
  evidence, a fail-open rail blind to a broken CLI, a verdict gate matching its own prompt template.

### Not changed (deliberate)
- **The Stop gate is untouched.** Detecting "a decision was named" from prose is a regex over natural
  language (and over whatever language the user works in) — fragile, false-positive-prone, and
  exactly the "gate your way out of specification gaming" this method rejects.
- No loop steps were renumbered (the fix folds into existing steps 5, 6 and 7), so the `step N`
  cross-references in `README.md` and `references/external-adversary-setup.md` stay valid.

## [0.3.0] - 2026-07-14

### Added
- **"Ground yourself before you spec" — the agent can now acquire missing context before it commits
  the goal-spec.** A new pre-spec step: if any load-bearing Q2 (success) or Q3 (pre-mortem) claim
  depends on context the agent doesn't have firsthand — how the repo/codebase actually works, what
  the real ground-truth source contains, or the external prior-art / community best-practice — it
  delegates a *bounded* exploration to a fresh-context subagent via the Task tool (whatever agent
  type the environment provides: an `Explore`-style read-only searcher if present, else a
  general-purpose agent) and folds the synthesis into its criteria and pre-mortem. This stops the
  agent from spec-ing off a thin context, which is where shallow goal-specs come from.
- Guardrails baked in so this stays true to the method, not a new rule: **conditional** (skip if you
  already know the terrain — stays a lightweight prefix, not "always investigate"); **fail-open**
  (no subagent / no web / headless → do what you can and record the gap in the Assumptions line);
  **mechanical teeth** (the test is that Q2/Q3 visibly reflect what was found, not a "did I research"
  checkbox); and an explicit firewall — this forward **helper shares the host's frame and is NOT the
  independent adversary**; its output is re-derived and still passes the red-team/adversary before
  close. No new governance marker; it's an application of Grounding + Falsification + Autonomy.

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

# test/

**Thirteen** mechanical suites (one per `*-branches.py` in this directory — keep this count in step when
you add one), plus `claim-surface-carriers.py` (a rule-carrier check, not a branch suite),
`manifest-checks.py` (manifest and wiring checks), and one check by hand.

`.github/workflows/tests.yml` runs everything here on every push and PR, on Ubuntu **and** macOS.
The macOS leg is not redundancy: `/bin/bash` there is 3.2, and an unbalanced apostrophe inside an
unquoted heredoc — the one recorded way this repo shipped a hook that died at parse time — is
accepted by bash 5 on Ubuntu. A green run covers the mechanical branches and nothing else: it does
not watch an agent obey a written rule or a hook fire in a real session. That is what this workflow
was scoped to, not a law: `claude --help` documents headless `-p` and `--max-budget-usd`, so such a
job is feasible and boundable — at the cost of a credential in CI, money per run, and
non-determinism. Whether that trade is worth it is open.

## `manifest-checks.py` — the silent-failure classes no branch suite can see

Not a branch suite: it reads files and parses them, runs nothing, and needs no Claude Code install.
It exists because four things can break a release without breaking a single test, and this project
has been bitten by each:

- **A version that was not bumped.** The install cache is keyed by version, so a push without a bump
  ships to GitHub and reaches nobody. It checks `plugin.json` `version` against `marketplace.json`
  `metadata.version`, and that the plugin is still named `goalspec` (a rename breaks auto-update).
- **Frontmatter that stopped being YAML.** A bare `: ` inside a `description:` makes the block
  unparseable; the skill then loads with empty metadata and never auto-triggers, silently.
  `claude plugin validate` does not catch it. PyYAML is the one dependency and it is the point — the
  check is "does a real parser accept this", which a regex cannot establish.
- **A hook wired to a path that does not exist.** Every `/hooks/*.sh` path in `hooks.json` must
  resolve to a real file. The exec bit is checked **only** for a hook invoked without an interpreter
  prefix — every hook here runs as `bash <path>`, which ignores the mode, and asserting +x is
  required everywhere would be a false claim about what makes a hook run.
- **A suite the docs forgot.** The counts in this file and in `CLAUDE.md`, and every suite being
  named in `CLAUDE.md`'s run list. That count went stale in 0.44.0 and an external adversary found
  it, not a test.

`--selftest` **breaks** each thing the file checks, in a throwaway copy of the tracked working tree,
and requires a non-zero exit — plus a control that must stay clean. A check that has never been seen
to fail is not yet a check, and this file has already shipped two that passed on a healthy repo while
silently missing the defect they named: a typo in the hooks *directory* (`/hookz/…`, which the old
path regex simply did not match, so nothing was checked and everything came back green), and a
document stating two contradictory suite counts (the old regex found the right word somewhere and
stopped looking). An external partner found both by reproducing them in a copy — so the reproduction
now lives in the repo, runnable by anyone, and runs in CI.

```sh
pip install pyyaml
python3 test/manifest-checks.py
python3 test/manifest-checks.py --selftest
```

## `gate-branches.py` — Stop-gate branch suite

Drives `plugins/goalspec/hooks/gate-goal-close.sh` across every branch it can take, with synthetic
`last_assistant_message` payloads and synthetic multi-turn `transcript_path` JSONL where a branch
needs history.

```sh
python3 test/gate-branches.py                                  # run against the repo's gate
python3 test/claim-surface-carriers.py         # claim-surface, role-fixity and visible-text rules present + consistent across their carriers
python3 test/gate-branches.py --compare /tmp/gate-BASELINE.sh  # regression parity vs a pre-edit copy
GOAL_GATE_ENFORCE=1 python3 test/gate-branches.py --compare /tmp/gate-BASELINE.sh
python3 test/gate-branches.py --compare /tmp/gate-BASELINE.sh --expected 16-hold,26-floor
```

**Before editing the gate, copy it somewhere and `--compare` against that copy afterwards** — in both
modes. Exit code is non-zero if any observed cell changed, so the parity claim is mechanical rather
than eyeballed. That is how v0.15.0's convergence floor was shown to leave the eleven pre-existing
branches untouched.

Each row reports **detail code | CONV | how the gate answered** (`block` / `advisory` / `silent`).
That third column arrived in 0.18.0 and is not cosmetic: the suite used to read `systemMessage or
reason`, which collapses the advisory and blocking paths, so a change to *whether the gate blocks*
was invisible to the very instrument used to certify "no regression". Teeth are only teeth if the
instrument can see them — including this one.

`--expected` takes case-name prefixes whose diff is **intended**. Declare them before running the
comparison: the point is to separate a designed change from a regression *in advance*, instead of
reading a non-zero exit afterwards and deciding it was fine. Don't persist the list in the file — a
standing expected-diff list is a muted alarm.

**Checkpoint-file goal-spec cases (`checkpoint-01`..`05`)** pin a separate real break from
the same incident chain: the gate's PRIMARY "did this session produce a goal-spec at all"
precondition — a different, older check than the staleness backstop below — is also a text-only
regex, and was blind to a `## Goal-spec` written via `Write` to `.goalspec/checkpoint.md` (the
pattern `SKILL.md` step 5 itself recommends for long tasks). Against the real session that shipped
this fix, that meant the ENTIRE Stop gate was silently inert, not just the staleness branch.
**01** pins the fix: a spec that exists only in a checkpoint-file `Write` now makes the gate speak.
**02** is a regression control (a normal text-based close still stays silent) — but is NOT, by
itself, evidence that the checkpoint-file signal stays out of the completion-review check (an
earlier version of this file's own comment claimed exactly that and was caught overclaiming by a
later adversary round: 02 passes identically against a gate with no checkpoint mechanism at all,
so it cannot be evidence for a mechanism it does not exercise). **03** is the case that actually
discriminates that claim: a completion-review marker living ONLY inside the checkpoint `Write`,
never in chat text, must still show as `completion-review:absent` — proving a completion-review
cannot be satisfied by a file write, only by the executor's own turn text, per SKILL.md's own
rule. **04** and **05** (0.38.0) carry that fix across the concurrency change: the
checkpoint is now per-session, so **04** is 01 at the new name (`.goalspec/checkpoint-<token>.md`)
— it fails against a gate whose matcher is the pre-fix `endswith(".goalspec/checkpoint.md")`,
which is what makes it worth having — and **05** is its narrowness control (a `## Goal-spec`
written to `docs/checkpoint-notes.md` or `.goalspec/checkpoint.md.bak` is not a checkpoint, so the
gate stays silent). **06** covers a Windows-separator path (`C:\\proj\\.goalspec\\checkpoint-*.md`):
the matcher normalizes backslashes before testing, because a POSIX-separator pattern would leave
the gate blind to a disk-written spec on that platform — the same break as **01**, platform-shaped.
That defect was inherited from the `endswith` this replaced (`memory/_pendientes.md` flagged it
2026-08-01), surfaced by this change's decision-log sweep, and fixed on the user's explicit call.
**No real Windows host has run it**: the assertion is synthetic, and that is the whole of the
evidence. These six need no git repo (the precondition fires before any git command runs), unlike
every other live-git case in this file.

**What `--compare` cannot see here, stated because a green parity run reads like more than it is**:
both the edited gate and the pre-edit copy import `hooks/lib/terminal_actions.py` from
`CLAUDE_PLUGIN_ROOT`, so a change to that shared module is present on BOTH sides of the comparison
and parity is structurally blind to it. Parity covers the gate script's own branches; the
checkpoint and staleness sections, which run against the edited module only, are what cover the
module. When a change touches `terminal_actions.py`, a `parity OK` line is a necessary check, never
a sufficient one.

**Staleness backstop cases (`stale-01`..`09`; 01-04 from 0.32.0)** live in this same file but run separately
from `CASES`/`suite()`/`--compare` above — they need LIVE git state (`hooks/lib/terminal_actions.py`'s
`commits_since()`), unlike every other case here, which is pure-transcript with no filesystem
involved. Each builds its own synthetic repo with a commit stamped at a fixed `GIT_COMMITTER_DATE`
(not real wall-clock time — a `sleep`-based ordering flaked in manual testing) and checks whether
the gate flags the operative `[COMPLETION-REVIEW: ...]` as stale when a terminal Bash command ran
after it. **01** is the positive case, replaying the 2026-08-01 worker-cloudflare incident this
backstop exists for (a `none` review declared honestly before a merge, then the merge in the next
turn with no fresh review). **02** confirms the same content exemption the PreToolUse precheck
uses (memory-only change, not flagged). **03** confirms a FRESH review declared in the current
turn is never stale regardless of what ran earlier. **04** confirms no terminal command at all
after the review means nothing to flag. **05** (0.45.0) is 01 with the field `/push` form,
`SKILL_AUTHORIZED=1 git -C <repo> push -u origin <branch>`: `classify()` returned None for git's
global options before 0.45.0, so this backstop never saw that push. **06**/**07** (0.46.1) pin
*which* repo the backstop reads: the `-C` repo's commits, not the hook cwd's. 06 puts code in the
`-C` repo and only memory in cwd (must flag); 07 is the mirror (must not). Both fail against 0.46.0,
in opposite directions, so neither "also read cwd" nor "always flag" passes both. **08** (0.46.1,
adversary round 1) is a second push the token parse cannot rebuild (`(git -C /y push)`, token
`push)`): its repo is unknown, so cwd must still be read; the first draft of 0.46.1 read only the
parsed `-C` repo and went silent where 0.46.0 flagged. **09** (adversary round 2) is `-C "$OTHER"`:
the repo is one only the shell knew, so nothing is exempt (flag), the same direction the precheck
takes for it. A literal `$OTHER` directory holding only memory, inside a memory-only cwd, is the
trap; 0.46.0 (which read cwd) and the second draft of 0.46.1 (which read the literal path) were
both silent there. Requires `CLAUDE_PLUGIN_ROOT` set in the test's own
subprocess env (the gate imports `hooks/lib/terminal_actions.py` via `LIBDIR`, which resolves from
it) — omitting it makes every staleness case silently degrade to "not stale", indistinguishable
from a passing case, which is exactly the trap the first draft of this suite fell into.

Cases 12–20, 24–26 and 41 cover the convergence floor. Several exist because they are the ones that
can go wrong quietly:

- **14** — the current turn re-quotes a verdict already recorded as the last transcript turn. The
  floor must NOT jump; one round counted twice is a false "three breaks, stop editing", which would
  push an agent toward a premature `[GOAL-CLOSE-WAIVED]`.
- **17** — one turn quoting both backends (subagent `hold` + external `break`) is one break round and
  does not reset the run. This is why the floor's wording says "no `hold`-**only** turn between them";
  an earlier wording said "no intervening hold" and an external adversary broke it on this exact case.
- **20** — the same verdict string in three separate turns collapses to a floor of 1. A deliberate
  under-count: the guard fires late rather than falsely.
- **24 / 25** — the bound on 0.18.0's hold-only fix, from both sides. A `hold` in the *most recent*
  verdict-carrying turn still ends the run (that is convergence; a floor there is noise), while an
  *earlier* hold-only turn no longer extinguishes it — and skipping it must not over-count two break
  rounds into a false three.
- **26** — three break rounds behind a turn that quotes both backends and closes on the `hold`:
  every declaration check passes, so before 0.18.0 the floor had no message to ride and the run got
  silence at streak 3. This is the case the floor's own branch exists for.
- **18 / 41** — the parked-loop silence (0.36.0), from both sides. **18 was inverted** by that
  release: at streak 3 with no close attempted *and no verdict in this turn*, the gate now says
  nothing at all, because the count in a transcript never decays and a parked run never acquires a
  completion-review — so the floor was re-firing on every later turn of a real session, including a
  checkpoint the human had asked for. **41** is the control that keeps the silence from being
  blanket: same streak, same absent declaration, but this turn carries a verdict of its own, so a
  round ran here and the floor is said — once. Both carry an `expect`, asserted on every run.

The section **`payload shape: at the floor, human only`** exists because the columns above cannot
see the 0.36.0 fix at all. `run()` collapses every non-block payload to `advisory`, so removing
`hookSpecificOutput.additionalContext` — the field the harness feeds back to the model, i.e. the one
that costs the agent a turn — leaves every branch cell identical and `--compare` reports parity.
That is precisely the defect a user reported watching the agent answer the hook *after* its own
plain-language close. The four cases pin the floor emitting `systemMessage` only (in both modes) and
below-the-floor keeping both fields and its teeth, plus a **600-char ceiling on the floor message**:
that branch has been rewritten three times and twice grew back into a wall of model-facing prose, so
"one line" is measured, not trusted. What this section still **cannot** prove is that the harness
generates no follow-up turn — that is harness behavior, not hook output, and needs a live run.

- **42** — the announcing turn when the Stop is ALSO re-entrant, from adversary round 2 on 0.36.0.
  The first draft of the parked-loop silence let `stop_hook_active` swallow the announcement at the
  threshold and then suppressed every later chance, so the human was never told. The guard is about
  re-asking the *model*, and the floor branch carries nothing addressed to it, so the guard is now
  deferred and skips that branch. 42 must never go silent; it fails against the first 0.36.0 draft.
  Note **30** did not move: its shape is the parked-loop silence, so it stays silent for a different
  reason than before — which is exactly why the fix needed a new case rather than an edited one.

Cases **27–30** cover the re-entrant-Stop guard (0.18.1). **27** and **30** are the ones that failed
before the fix; **28** (flag absent) and **29** (flag explicitly `false`) are controls — they are the
ordinary first Stop, the overwhelmingly common case, and a guard that silences *them* would be a
worse defect than the one it fixes. Run 27 under `GOAL_GATE_ENFORCE=1` too: before the fix it
answered `block`, which is what proves the guard has to sit ahead of the teeth branch and not merely
ahead of the advisory one.

Cases **31–34** cover bracketed model ids (0.19.1). **32** is the regression test — a real id whose
*name* field also carries brackets was truncated before the `/` and wrongly told to degrade to
`model=same`. **31** and **33** are controls: 31 is the realistic shape that passed *by accident*
before the fix and must keep passing, 33 is the `UNKNOWN` rejection the fix must not loosen.
**34 exists because an adversary broke the first attempt at this fix.** Capturing greedily to the
last `]` on the line accepted a garbage token sliced out of a trailing citation
(`… / claude-sonnet-5] (see plugins/goalspec/hooks/gate-goal-close.sh[283])` → `cid` =
`gate-goal-close.sh[283`, whitespace-free with a letter and a digit), granting `model=different` on
non-evidence — failing **open** on the one assertion the check exists to make. The shipped fix
anchors the marker to end-of-line instead, so anything appended after it matches nothing. Case 34
carries an `expect` so it can never go silent again.

Two smaller instrument changes came with them. Cases may carry an `expect` for the `decision` cell,
asserted on every run and not only under `--compare` — parity-against-a-copy cannot express "this
must emit nothing", because the copy is the thing being changed. And `CONV!` distinguishes a
convergence floor that **replaced** the reminder from a `CONV` that was appended to one; without that
column the 0.18.1 floor fix is invisible to `--compare`, since detail and decision both stay put.

**The `audience split` and `general parked-turn silence` sections (0.44.5)** extend the floor's own
two-audience payload and its parked-loop silence to every OTHER `remind()` branch — before this,
only the floor separated a short human `systemMessage` from a technical agent-facing line, and only
the floor ever went quiet on a turn with nothing new to say. Like the payload-shape section above,
`run()`/`suite()` cannot see either property (both collapse to `advisory`), so these run separately.
**Audience split** pins that `systemMessage` and `additionalContext`/`reason` are genuinely two
different strings (a lazy split that copies the same text into both variables would still pass every
existing branch/decision assertion). **General silence** pins the four-turn invariant: the first
parked turn after the goal-spec (`silence-first-parked-after-spec-SPEAKS`) and the first parked turn
after any active one (`silence-resets-after-active-turn-SPEAKS`) both speak; the second and third
consecutive parked turns (`silence-second-parked-SILENT`, `silence-third-parked-SILENT`) do not. The
first case is the regression control for a real bug found while building this: an earlier draft
counted the goal-spec-announcement turn itself as "the prior parked turn", which silenced the very
first reminder of every session — exactly backwards. The staleness backstop (`stale-01`..`09` above)
is deliberately EXEMPT from this silence (`skip_general_silence=True` at its own call site) — a
terminal action having run after the operative close does not become less true because a later turn
also failed to re-declare, and `stale-01` already pins that it must always fire.

## `verdict-nudge-branches.py` — PostToolUse verdict-nudge suite

Same shape, for `hooks/remind-quote-verdict.sh`. The two payload **shapes** are the point: a
backgrounded spawn (the default since Claude Code v2.1.198) returns a handle with no `content`, and
that handle echoes the executor's own spawn `prompt`. Case **04** pins both halves — the nudge must
fire on the handle (it used to require verdict text that is never there), and it must **not** read
the echoed prompt as a verdict that "came back" (against the pre-edit hook, it did).

## `usage-budget-branches.py` — opt-in usage-budget Stop-hook suite

Same shape, for `hooks/check-usage-budget.sh` (0.19.1). Until then that hook's re-entrant-Stop guard
was verified **by placement and syntax only**, on the belief that it "cannot emit anything without
real credentials" and would therefore exit silently with the flag `true` and `false` alike.

That belief was wrong, and the seam is the hook's own ordering: **step 4 serves from its local cache
before step 5 resolves any credential**, and `GOAL_CONFIG_PATH` / `CLAUDE_CONFIG_DIR` / `HOME` are
all environment-overridable. A seeded cache with a fresh `_fetched_at` therefore drives the hook to
a real emission with **no credential read and no network call**. Cases **01/02/03** are the
discrimination (identical input, only the flag differs); **04–06** are controls proving 01's silence
comes from the guard rather than from a hook that never emits.

```sh
python3 test/usage-budget-branches.py
```

**What it does not cover, stated so a green run does not imply more**: the credential path (Keychain
/ `.credentials.json`) is never exercised — a stale-cache case would fall through to a real Keychain
lookup and possibly a live API call with the user's own token, which a test must not do. And seeding
95% proves the threshold comparison and the payload shape, **not** a real account crossing 80%; that
observation is still open.

## `external-adversary-branches.py` — external-partner backend suite

Same shape, for `hooks/external-adversary.sh` (0.21.1). Hermetic: the partner is a stub selected
through `GOAL_ADVERSARY_CMD` (env outranks config), so no real CLI, no credential, no network.

Case **02** is the regression case: a codex-style run transcript (banner, reasoning traces, echoed
prompt template and fixture text) around a **naked** final `hold`. `EVIDENCE_LINES` used to count
over ALL of `$OUT`, so that noise read as evidence and the bare-verdict floor never fired — an
empty hold sailed through as a verified one, observed live 2026-07-26 (and the echoed text was
mistaken for reasoning by a human reader too, until the bullets between `[ADVERSARY-MODEL:]` and
the verdict were actually counted). The fix scopes the count to the partner's answer block; **03**
is the only shape the old floor caught (control), **01/04** prove real bullets still pass, **05**
pins the no-self-report fallback window.

Cases **08/09/11** pin the P25 sandbox rails: the partner gets a `TMPDIR` the hook's own process
can write to (08) and, since 0.44.9, runs from an isolated review copy of the repo root (not the
repo root itself) when the invocation cwd is inside a subdirectory (09) — both sandbox failures had
come back disguised as ungrounded/UNVERIFIED findings across two consecutive phases. The rails are
host-side only: from outside any git repo there is no root to resolve, so that branch warns on
stderr instead of relocating (11), and a partner whose own sandbox denies writes the hook's process
can make (the v0.19.1 contra-dato) is out of the hook's reach entirely.

**Reviewed-state isolation (0.44.9)**, cases **09/16/17/18/19/24**: the hook materializes the exact
reviewed state into a private linked worktree under the repo's own `git-common-dir` before invoking
the partner, so a concurrent writer sharing the repo (another local session's commit landing
mid-round — the live incident this closes, 2026-09-17/18) can no longer be misattributed to the
partner. **24 is the case that matters most**: a "sibling session" commits to the ORIGINAL repo
while the partner reviews its isolated copy, and the round must come back a clean pass with no
"MODIFIED the repository" warning at all — proof the false-positive class is eliminated, not merely
better-diagnosed. 09's assertion was updated to match the new shape (it lands under the repo's
`git-common-dir`, verified via a second stub line, not literally at the repo root) — and carries a
documented exception: a write-restricted external sandbox that cannot itself create a *second*
nested worktree (observed live reviewing this very change) falls back to the pre-0.44.9 shape
instead, which is the fail-open path working as designed, not a regression; the suite's `expect`
stays strict because that fallback is not what a normal, unsandboxed run (every real CI job) should
ever show.

**32** covers that fallback's attribution (p-55cec2045a). An unborn repo (no commit) cannot be
isolated, so the partner reviews the live shared tree, where a parallel session's write looks the
same as the partner's. The hold must still degrade, and the message must name the other-writer
reading with its evidence bar (name the other writer, or the partner reading stands). Commits
already had that hedge; file paths did not. **16/17/19** assert the other half: isolated, the hedge
must not appear, because nothing else writes to the private copy.

Cases **16/17/19** pin the read-only rail (0.44.0), and **18** is its control. **16 is the
discriminating one**: the stub appends to a file the fixture repo has *already* modified, so the
`git status` porcelain line is byte-identical before and after — a status-based fingerprint passes
it while the repair goes unseen, which is the commonest real shape, since the tree under review is
the uncommitted work being reviewed. Against the pre-0.44.0 hook, 16/17/19 all come back
`pass+mutation-missed` — the repair read as a clean pass. **17** pins the asymmetry that keeps the
rail from ever weakening the gate: a `break` from a mutated tree is printed unchanged and only
warned about, while 16/19's clean `hold` is degraded to `UNVERIFIED`. **19** covers `.goalspec/`,
which `--exclude-standard` hides, so the fingerprint hashes it explicitly. **18** is the control
that keeps this from being a mere dirty-tree detector: same pre-dirtied repo, partner writes
nothing, clean pass. These four run in a throwaway git repo (`cwd` sentinel `MUTREPO`) for the
obvious reason — the stubs write files, and every other case in this file runs with `cwd=REPO`.

Cases **20/21** pin the other half of "never weaken the gate", and 20 exists because an external
partner found the hole in it. Until 0.44.0 the `RC -ne 0` test came **first**, so a partner that
produced a well-formed `break` and then exited nonzero had its confirmed findings replaced by a
synthetic clean hold — the gate weakened by the very branch meant to keep it honest. Against the
pre-fix hook, case 20 comes back `unfilled`; it now comes back `pass+rcwarned` (break intact on
stdout, nonzero exit called out on stderr as a **coverage** limit, since a partner that crashed may
never have reached attacks it had not run). **21** is the control that keeps the fix from widening
into "preserve anything": a `hold` that exits nonzero still degrades.

Cases **25/26/27** pin the declared-sandbox forward (0.46.4). When the partner prints its own writable
roots (codex: `sandbox: workspace-write [workdir, /tmp, $TMPDIR]`), the hook relays the **first**
such line to the executor on stderr and names SKILL.md step 6 as its consumer. 26 adds a later line
of the same shape (a file the partner read) and requires the header to win. 27 relays a
`danger-full-access` line and requires the message to state write failure only as conditional on
the mode (an adversary round caught the first wording asserting it for any mode). **01** is the silent
control: its transcript has no such line, so any forward there fails it. Against the pre-0.46.4
hook, 25/26/27 come back `pass`. What the executor then does with the line is prose no case here can
observe.

Case **28** pins where the notices land (0.46.5). Executors read this hook as `2>&1 | tail -N`, and
on 2026-09-30 a `| tail -60` cut the sandbox relay and the quote reminder, because the hook printed
both before the partner transcript. The case runs the hook the same way, through `tail -20`, over a
transcript longer than 20 lines, and requires the verdict, the sandbox relay and the quote reminder
to survive. Against 0.46.4 it comes back `tail20-lost:sandbox,quote`. It is the one case in this
file whose stdout and stderr are merged, so its classifier reads only stdout.

Case **29** came from running 0.46.5 live before release: a 7431-line partner run printed
`printf: write error: Broken pipe` among the notices, because `grep -m1` closes the pipe at the
first `sandbox:` line while `printf` is still writing `$OUT`. The case feeds a transcript larger
than a pipe buffer and fails on any `write error` on stderr. Case 28 is too small to fill the
buffer, so it never saw this. Against 0.46.4 it comes back `pass+sandboxfwd+brokenpipe`.

Cases **30** and **31** close the residual 0.46.5 left (0.46.6). The note for a `break` with a
nonzero exit (case 20) and the note for a `break` over a repo the partner modified (case 17) still
came before the transcript, so a `| tail` kept the break and cut the note. Both cases pad the
transcript past 20 lines and pipe the hook through `tail -20`, like 28. They require the break
itself, not any filled verdict, plus the note (and for 31 the changed path). Against 0.46.5 they
come back `tail20-lost:rcnote` and `tail20-lost:mutnote,path`. Moving the notes kept one constraint
from 0.46.5: the hold degraded by a mutation exits without printing `$OUT` to stdout (stderr still
shows its first 40 lines, as since 0.44.0). Cases **16** and **19** now pin it: they fail as
`mutation-leaked-out` if a partner line reaches stdout.

When a case comes back `EXPECT FAILED`, the suite prints what the hook emitted under that row: the
exit code, then stderr and stdout (past 80 lines, the first 40 and the last 40, so neither the
hook's leading notices nor the verdict at the end get cut). Case 05 went `unfilled` once on macOS CI
(run 36776930854, attempt 1) and passed on the rerun. At that time the suite discarded the hook's
output, so that red left nothing to diagnose. Green rows print nothing extra, so the `--compare`
table is unchanged.

```sh
python3 test/external-adversary-branches.py
python3 test/external-adversary-branches.py --compare /tmp/external-BASELINE.sh --expected 02,05,08,09,11,16,17,19,20,25,26,27,28,29,30,31
```

Every case carries an `expect` asserted on every run, so the suite is self-verifying without a
baseline copy; `--compare` works like the gate suite's when the hook is edited again.

## `adversary-report-branches.py` — the Stop hook that reaches the executor

For `hooks/report-adversary-writes.sh` (0.44.1). Fully hermetic: no git, no network. Each case
writes a synthetic findings file the way `watch-adversary-writes.sh` would, feeds the hook a `Stop`
payload, and classifies.

**Why the hook exists** is what the suite pins. In 0.44.0 the `SubagentStop` hook both measured and
emitted. Measured on 2026-09-12 in a real session: a `SubagentStop` hook's output is delivered to the
**subagent that just stopped** — it lands in that agent's transcript as `isSidechain: true` and
appears **zero** times in the executor's. The message was written in the second person for the
executor ("YOU edited under an in-flight verifier … decide what to keep or revert"), so the adversary
that received it recorded that it "misread it as a cue that I had become the executor" and wrote to
five files in the repo under review. `Stop` output, by contrast, lands in the executor's own
transcript with `isSidechain: false` — verified in that same file.

Two cases carry that lesson and must not be softened. **08** requires the message to open with an
audience line AND to disarm an adversary reading it in a transcript (the executor's transcript is
exactly what an adversary reads for its principle-4 check, so this text *will* land in front of one);
removing either half flips the case to `reported-no-audience-line`. **09** requires the findings file
to be consumed, or every later turn re-reports a stale finding as new. **04** pins the session
keying, **05** that garbage is skipped rather than fatal, **03/06/07/10** the fail-open paths. **12** (p-55cec2045a) requires the message to name a THIRD writer — a parallel session on the
same project, the human — to stop claiming "exactly two readings", and to keep the evidence bar that
stops the third reading from being a free pass for the executor (name the other writer, or the
verdict stays UNVERIFIED); the human line must name "otra sesión" too.

**Its baseline is NOT 0.44.0**, and that matters: this hook did not exist then, so "fails against the
old hook" says nothing about it. An external partner caught exactly that — case 09 passes against the
0.44.0 watcher for the wrong reason (that hook never reports, so "silent on the second call" is
trivially true). The discriminating baseline is a mutation of *this* hook, and `--selftest` runs ten
of them, each required to be noticed by the case written for it.

```sh
python3 test/adversary-report-branches.py
python3 test/adversary-report-branches.py --selftest
```

## `adversary-writes-branches.py` — the subagent read-only rail

For `hooks/watch-adversary-writes.sh` (0.44.0), the subagent half of the same rail. Hermetic apart
from `git`: each case builds a throwaway repo, feeds the hook a synthetic `SubagentStart` payload,
mutates the repo the way a misbehaving adversary would, then feeds it the matching `SubagentStop`
payload. `TMPDIR` is redirected per case so snapshots never collide and never touch the project.

Why those two events and not the `Task` hooks already registered on `PreToolUse`/`PostToolUse`:
subagents run in the **background**, so the `Task` tool result is a handle and `PostToolUse` fires
at *launch*. A snapshot pair there would bracket the spawn, not the run — an instrument measuring
nothing, which is the exact defect the rail exists to catch. `SubagentStart`/`SubagentStop` bracket
the real run and carry `agent_type` + `agent_id`, so attribution is structural.

**02** is the discriminating case, for the same reason as case 16 of the external suite: an append
to an already-modified file is invisible to `git status`. **05** pins that a `git add` is caught by
the staged-diff hash (it moves the path out of `ls-files -m`) *and* that the index line gets named
rather than stripped — the first run of that case reported a bare 40-char hash as if it were a
filename. **04** covers gitignored `.goalspec/` run state. **06** pins a deliberate non-finding:
changed and changed back is nothing left modified. **01** is the control against a dirty-tree
detector; **07/08** pin the `agent_type` re-check (including `not-goal-adversary-example`, the
fabricated form that slipped a bare substring check once in this project); **09** pins that a
`stop` with no `start` stays silent — claiming "no writes detected" from a measurement that never
ran is the broken instrument this rail is about. **10** (0.44.1) pins the re-arm: the agent stops and
then writes again, and 0.44.0 deleted the snapshot on that first stop, so everything afterwards was
unmeasured — which is exactly how the real 2026-09-12 writes escaped. Against the 0.44.0 hook, 02-05
come back `EMITTED-TO-SUBAGENT` and 10 comes back `silent`.

```sh
python3 test/adversary-writes-branches.py
python3 test/adversary-writes-branches.py --compare /tmp/watch-BASELINE.sh --expected 02
```

## `decompose-nudge-branches.py` — decomposition-nudge Stop-hook suite

Same shape, for `hooks/nudge-decompose.sh` (0.28.0) — Fase 2 of
`memory/plans/plan-trigger-decomposicion.md`. Gives the coverage-floor/decomposition trigger a real
mechanical consumer, non-blocking: no `decision:block`, no `GOAL_GATE_ENFORCE` branch at all in this
hook, by design.

The signal: a `.goalspec/checkpoint*.md` in the cwd **that this session wrote** (a `Write`/`Edit`
tool_use for that exact path in this session's own transcript) carries a `## Coverage-floor table`
heading with >= 2 markdown-table data rows, and the transcript records zero entity-worker
`Task`/`Agent` tool_use anywhere — a `Task`/`Agent` whose `subagent_type` is an EXACT match for a known adversary
agent-type name (`goal-adversary` / `goalspec:goal-adversary`) does not count, since the plugin's
own step-6 verification spawn is itself a `Task`/`Agent` call and would otherwise close the nudge's
window on almost every checkpointed run. Checkpoint.md is optional-by-design
(`references/durable-artifact.md`), so its presence with a populated table is already the agent's
own claim of >=2 tracked entities — this hook does not try to parse that enumeration out of
freeform turn prose.

Case **01** is the re-entrant guard (same discipline as `usage-budget-branches.py`'s 01-03).
**04/05** are controls that decomposition via either `Agent` or `Task` silences the nudge; **06**
proves an unrelated tool call (`Bash`, `Read`) does NOT count as decomposition.

**07-10 pin two real breaks caught live against this exact release, one from each adversary
backend**: the subagent backend (Opus) caught that the adversary's own step-6 spawn is ALSO a
`Task`/`Agent` tool_use, and step-6 explicitly directs the executor to write the checkpoint and
THEN spawn the adversary pointing at it — so an earlier version of this hook that counted any
`Task`/`Agent` as "decomposed" had its nudge window close on the plugin's own mandated verification
step, on almost every checkpointed run. **07** proves a bare adversary spawn does NOT silence the
nudge on its own; **08** proves a real worker alongside the adversary spawn still does; **09**
proves the exclusion matches on `Task` as well as `Agent`. The external backend (codex/GPT-5), used
to re-verify the fix, then caught that the first fix used a **substring** test on `"adversary"` —
gameable by any real worker whose `subagent_type` merely contains that word (e.g.
`not-goal-adversary-example`) without being one of the two known exact adversary agent-type names.
**10** pins this collision control: an exact-match check must still classify it as real
decomposition (silent), not nudge.

**11/12** prove the row-count check is real (1 row, 0 rows); **13/14** prove the
checkpoint/heading gate is real (no file, heading absent).

```sh
python3 test/decompose-nudge-branches.py
```

**Case 16** pins the advisory message's CONTENT, which every other case collapses away to
nudge/silent. It was introduced in 0.29.0 to pin a sentence telling the human to delete a leftover
checkpoint by hand; ownership (below) now performs that check mechanically, so the sentence became
false and the assertion moved with it — it now pins that the message names the specific file it
read and still points at the lifecycle declaration.

**Cases 17-22 (0.38.0) are the read-side half of the concurrency fix**, and the
only cases in this file that test a control-flow branch rather than pinning an unchanged one. Two
sessions running goalspec in the same project used to clobber each other at the single fixed path
`.goalspec/checkpoint.md`; the file is now per-session and this hook decides ownership from the
transcript. **17** is the incident (a concurrent session's checkpoint -> silent); **19** is the
residual `references/durable-artifact.md` had listed as open since 0.29.0 (a leftover from a run
that crashed and was never resumed, at the legacy name -> silent); **18/21/22** are the twin
controls that ownership does not simply silence everything (same file, same table, ownership
present -> nudge, via `Write`, via `Edit`, and via a relative path that must resolve against the
cwd). **20** is the narrowness control, and it is built to fail against a loose matcher on
purpose: its decoy files (`docs/checkpoint-notes.md`, `.goalspec/checkpoint.md.bak`,
`.goalspec/nested/checkpoint.md`) really exist and really carry >= 2-row tables, because with
absent decoys a loose matcher would resolve them to nothing and fall silent anyway — green against
the very implementation the case exists to reject. Verified by mutation: replacing the matcher
with a bare `checkpoint` substring flips 20 to `nudge`.

**Case 23** was found by an external adversary round on this very change, by live-probing the hook
instead of reading it: the path pattern alone accepts any `.goalspec/` *below* the cwd, while this
hook's header and `references/durable-artifact.md` both say the cwd's own. The code was broader
than its own claim; the fix anchors the match to `<cwd>/.goalspec/` rather than widening the claim.
Mutation-verified (dropping the anchor flips 23 to `nudge`). Landing that anchor immediately broke
eight cases on macOS — `/var` vs `/private/var` — which is why both sides of the comparison use
`realpath`, not `normpath`.

Because ownership is a precondition, **every pre-existing case's fixture changed**: each now emits
a `Write` tool_use for the checkpoint it creates, **and its paired `tool_result`**. That second
half arrived later, from an adversary round on the sibling gate: a tool_use alone is a REQUEST, and
a denied write is still recorded as one, so ownership that ignores the result counts a refusal as
proof of writing. Cases **24-25** pin it here (a denied write, and a write with no result, neither
confers ownership). Their expected cells did not change — that is the no-regression check.

**What it does not cover**: a real live session where the table was populated and decomposition was
genuinely skipped is not exercised — every case drives the hook with a synthetic checkpoint and
transcript, the same hermetic pattern `usage-budget-branches.py` uses for its own hook. That live
observation stays open, not something this suite closes. Nor does anything here exercise whether an
executor actually performs the new close-step deletion in a real multi-round run — that instruction
lives in `SKILL.md` prose, not in this hook, so no hermetic test can assert it; it stays a second
open live observation alongside the decomposition-skip case.


## `interview-handoff-branches.py` — interview-to-spec reminder (0.46.0)

For `hooks/nudge-interview-handoff.sh`. After `/goalspec:interview`, the agent is supposed to
invoke the goalspec loop and write the `## Goal-spec`. Field data: on one team VPS 11 of 23
interview sessions never did, and none of those 11 invoked the loop; on the maintainer machine 10
of 70, 8 of which never invoked the loop and went on working. The hook adds one agent-facing line
of context after an answered `AskUserQuestion`, and on UserPromptSubmit once work (Bash, Write or
Edit) has followed the interview, while that handoff is still pending
(`terminal_actions.interview_handoff_pending`). It blocks nothing. 18 cases, hermetic: the pending
cases (typed or Skill-tool entry, a spec from an earlier cycle, the loop routing into the
interview, a code edit), the discharging ones (loop invoked, spec in text, spec in the checkpoint
file), and the silent ones (no interview, other tool, other event, tag inside a `tool_result`,
malformed input, an interview that concluded "nothing to do" followed by plain conversation).

```sh
python3 test/interview-handoff-branches.py
python3 test/interview-handoff-branches.py --selftest
```

The hook is new, so "fails against the previous version" would prove nothing. `--selftest` copies
the plugin, applies nine mutations to the component (pending always true, loop entry ignored,
checkpoint spec ignored, a spec before the interview counted, the tool filter dropped, the wrong
`hookEventName`, the work requirement dropped, work never recorded, the interview kind lost) and
requires at least one case to fail under each. Run
over this machine's 70 real interview transcripts, the detector marks exactly the 8 that went on
with no spec and no loop call. What no suite can show: that the agent then obeys the reminder.

## `spec-on-entry-branches.py` — post the spec when the loop loads (0.48.0)

For `hooks/nudge-spec-on-entry.sh`. Measured 2026-10-06 over 275 real sessions (maintainer Mac +
team VPS): 25 loaded the goalspec loop and never posted a visible `## Goal-spec`, and in 13 the Stop
gate never saw one anywhere. One agent wrote it only in its thinking and believed it visible;
another planned in its thinking and went straight to tools. The hook adds one agent-facing line
(`terminal_actions.SPEC_ON_ENTRY_NUDGE`) right after a Skill call that loads `goalspec:goalspec`
while no spec exists yet. It blocks nothing. 12 cases, hermetic: the nudging ones (loop loaded,
bare skill name, a spec that lives only in a `thinking` block, no transcript), and the silent ones
(interview, standalone adversary, another skill, another tool, a spec already in text or in the
checkpoint file, another event, malformed input). New with no predecessor, so `--selftest` mutates
the component (7 mutations) and requires a case to catch each.

The Stop-gate half of the same release lives in `gate-branches.py`, section "entered the loop,
never wrote a spec": 10 cases run in both modes, asserting an advisory that never blocks, silence
for interview-only, adversary-only, waiver, re-entrant Stop and a missing lib, and the ordinary
branches once a spec exists.

```sh
python3 test/spec-on-entry-branches.py
python3 test/spec-on-entry-branches.py --selftest
```

## `handback-verdict-branches.py` — reminder to quote a hand-back verdict (0.46.8)

For `hooks/remind-handback-verdict.sh`. A goal-adversary launched in the background reports later,
as a subagent hand-back; `remind-quote-verdict.sh` fires at the launch, before any verdict exists,
so nothing reminded the executor to quote it (agente-coordinador b30f155f: two holds quoted only in
thinking, four pushes denied). The hook has two halves: `record` on SubagentStop (exact
goal-adversary type) stores the report's `[ADVERSARY-MODEL]`/`[ADVERSARY-VERDICT]` lines per session
and prints nothing — SubagentStop output goes to the subagent, not the executor; `remind` on
UserPromptSubmit consumes them and names the exact lines, unless a text block written after the
record already quotes them. It never reads `prompt`, which the human can type. 32 cases, hermetic
(synthetic transcripts, a per-case `TMPDIR`): the reminding ones (hand-back call, last-text fallback,
bare type, break with its note, a resumed adversary's latest report, two adversaries, a missing
model line, an identical line quoted only BEFORE the record), the silent ones (other or look-alike
type, no verdict, no record, already quoted, other session, a forged prompt, malformed payload,
other events), and `hooks.json` registering both halves.

```sh
python3 test/handback-verdict-branches.py
python3 test/handback-verdict-branches.py --selftest
```

New in 0.46.8, so `--selftest` copies the plugin and applies 15 mutations (type check dropped or
made a substring, `record` printing, the record not consumed, the quoted check or its time bound
dropped, text preferred over the hand-back call, the session left out of the key, no per-agent
dedupe, the model line, break note or visible-text clause dropped, either half firing on any
event, a verdict read from the prompt) and requires a case to fail under each. Measured end to end
on real data: a SubagentStop payload captured in a live session plus the real goal-adversary
transcript of b30f155f give the exact model and hold lines once, then silence. The event order it
rests on (SubagentStop finishes before the hand-back's UserPromptSubmit) was measured with probe
hooks, idle and busy. What no suite can show: that the agent then quotes the lines.

0.46.9 (p-3cbde60989): that order does not hold. With harness 2.1.291, session idle, the
UserPromptSubmit ran 43 and 94 ms BEFORE the record (five live runs), so `remind` now also reads the
report from `<transcript stem>/subagents/agent-<id>.jsonl` when its `.meta.json` names an exact
goal-adversary and the report line itself is stamped within the last minute. Cases 21-33 reproduce
that order (no record, report already on disk): it reminds once, a late record is not a second
reminder, a resumed adversary's newer report beats an older record of the same agent, and an old
transcript, an old report in a freshly appended file, a report with no timestamp of its own (left to
the record), another or look-alike type, a missing `.meta.json` or an existing quote stay silent;
case 29 checks the record file is still consumed. Seven more mutations (scan dropped, type ignored,
window on mtime only, prefilter ignored, record winning over a newer report, mtime fallback, the
reminded set not kept) bring `--selftest` to 22. Replayed on the real idle-form run
(session 3bc4592b, cut before the hand-back): 0.46.8 silent, 0.46.9 names both lines.

## `terminal-precheck-branches.py` — PreToolUse terminal-push precheck suite

For `hooks/precheck-terminal-push.sh` (0.32.0), the hard-blocking companion to the staleness
backstop above — it denies the push/merge/deploy/destructive command BEFORE it runs, rather than
flagging it after. Structurally different from every other suite here: this hook reads LIVE git
state (it diffs the actual prospective push), so every case gets its own synthetic repo built with
a working tree plus a bare `origin` created **outside** that working tree — nesting the bare repo
inside the working tree was tried first and broke every case, since `git add -A` sucks in the bare
repo's own object files as untracked content (a fixture bug, not a hook bug, but an easy one to
reintroduce).

70 cases cover: the `## Goal-spec` precondition (no spec → allow regardless of content, cases
01-02); the core policy (spec + no verdict → deny, + break → deny, + hold → allow, + waiver →
allow, cases 03-06); content exemption (memory/docs/root-`*.md`-only → allow, mixed diff → deny,
cases 07-10); branch scoping (a feature-branch push is out of scope unless `--force`, cases
11-12); merge classification (`gh pr merge` against a synthetic repo with no real GitHub remote —
`gh pr diff` fails deterministically, so the diff is undeterminable and NOT exempt by design,
regardless of content, case 13); deploy/destructive commands (never content-exempt, branch-
agnostic, cases 14-16); the two universal escape hatches (not our tool, not a terminal command,
malformed JSON — all allow, cases 17-19); a goal-spec written to disk instead of posted as
chat text (cases 20-22, see below); and the deny text itself (cases 42, 43 and the deny-text case numbered 44: an interview-only
session is told to write the spec, the waiver is scoped to one command, and — new in 0.46.2 — a
verdict quote only counts as a visible text block, never one written in thinking); and text inside a heredoc body or a `-c` string (cases 65-69, new in 0.46.3: those
bodies are classified, a string that only mentions a merge included, and the deny text names
the file route out together with the fact that the hook never reads the contents of a file the
command runs); and a hold that reached the session as a goal-adversary's report but was never quoted
(cases 70-85, new in 0.46.7: the decision stays deny, the deny text gives the exact line to quote; a
later text verdict wins; a hold in a Bash result, an Explore result, a hand-back from an agent no
goal-adversary spawn launched, a user message carrying the hand-back tag, a queued_command the human
typed, a background launch's receipt, or an agent type that only contains `goal-adversary` is not
read as relayed; the `queue-operation` copies are not
read); and the same relay delivered while the session is idle, as a `user` event carrying the
harness `origin` with the report in `origin.body` (cases 86-95, new in 0.46.8: 72 of the 75
goal-adversary hand-backs on record have this shape and 0.46.7 read none of them — 86 and 89 come
back `wrong-text` against it, every case below 86 is unchanged; the same origin checks as the
queued form, plus: an origin of kind `human`, one without the `handback` flag, and a hold present
only in the message text and not in `origin.body` are not read as relayed).

```sh
python3 test/terminal-precheck-branches.py
```

**Cases 20-22 are a regression pin for a real break, not a hypothetical.** A `goal-adversary`
round run against this SKILL's own diff, before it shipped, found the text-only scan blind to a
`## Goal-spec` written via `Write` to `.goalspec/checkpoint.md` — exactly the pattern `SKILL.md`
step 5 recommends for long tasks — confirmed live: run against the REAL session transcript with
the REAL prospective `git push`, the shipped hook's `has_goal_spec()` returned `False` and the
push was silently allowed. **20/21** pin the fix (a spec living only in a checkpoint-file `Write`
is now detected, and still requires a `hold` same as any other). **22** pins that the fix stayed
narrow: the first attempt captured ANY `Write`/`Edit` content as a text-equivalent signal, and
broke immediately — this SKILL's own docs are full of literal example marker text
(`[GOAL-CLOSE-WAIVED reason=...]` samples, sample verdicts), so editing `SKILL.md` or
`CHANGELOG.md` was read as a genuine waiver declaration. **22** replays exactly that shape (a
`Write` to an unrelated doc file containing example waiver text) and pins that it must still
`DENY` — only a `Write`/`Edit` whose `file_path` is a `.goalspec/checkpoint*.md` contributes to
the goal-spec signal, and it contributes to THAT signal only, never to waiver/verdict/completion-
review (`hooks/lib/terminal_actions.py`'s `transcript_signals()`).

**Cases 23-24 (0.38.0)** carry 20/21/22 forward across the concurrency fix: the
checkpoint is now per-session (`.goalspec/checkpoint-<token>.md`), so **23** is 20 at the new name
— had the matcher stayed pinned to the old exact filename, a session writing its spec to the new
one would reproduce the very break 20/21 exist for, this hook blind to the spec and silently
allowing the push. **24** is 22's control for the widening: a near-miss path (`docs/checkpoint-
notes.md`, `.goalspec/checkpoint.md.bak`) carrying a real `## Goal-spec` is not the checkpoint, so
no spec is on record and the hook has nothing to gate (`ALLOW`). Both verified by mutation:
reverting the matcher to the pre-fix `endswith(".goalspec/checkpoint.md")` flips 23 to `allow`
while 24 holds. **25** is the Windows-separator twin of gate-branches' `checkpoint-06`, with the
same synthetic-only caveat: a backslash path must still be recognized as the checkpoint, or the
hook is blind to the spec on that platform and silently allows the push.

**What it does not cover, stated so a green run does not imply more**: a real live push actually
denied and then retried after a genuine `hold` — every case here is single-shot.


**Cases 26-64 (0.45.0)** pin three gaps from a field report (VPS, 4 devs, 2026-09-08..29: of 12
sessions with goalspec use that never ran the adversary, 10 pushed, merged or released).
**26-32** — entering goalspec counts as tracked: a typed `/goalspec:interview` (the harness's
`<command-name>` tag in a user event, string or list content, copied from a real transcript) or a
`Skill` tool call to `goalspec:interview` / `goalspec:goalspec` now denies without a spec; the
standalone `goalspec:adversary` does not (29); the same tag inside a `tool_result` is data, not an
entry (31). **33-38** — git's global options: `git -C <repo> push` and `git -c k=v push` classify
as push, the branch and diff checks run against the `-C` repo rather than the hook's cwd (33, 35,
36 run the hook from a non-repo dir), a feature-branch push via `-C` stays out of scope (37), and a
trailing `&& echo done` is no longer read as the push target (38). **39-41** — a waiver passes one
terminal command: a second merge after a waived one is denied (39), while the retry the waiver was
written for passes whether or not the harness already logged that call (40, 41); a user prompt
between the waiver and the command voids it (44, the field session's shape), a `tool_result`
does not (45). **42-43** assert
the deny wording itself (write the spec; the waiver covers one command). **46-55** come from an
external adversary round that broke the first version: one malformed event no longer wipes the
spec (46); the entry tag counts only when it opens the user message (47); a `<task-notification>`
does not end the waiver's turn (48); with the payload's `tool_use_id` the same command re-run after
a waived run is denied (49); chained pushes, `HEAD:refs/heads/main`, `--all`, a `+` refspec and an
attached `;` are all seen (50-54); a quoted `-C` path with a space resolves (55). **56-60** come
from the second external round: a bare `--exec-path` is not a push (56); `bash -c "git push …"`,
`--force-with-lease=<ref>`, a `gh pr merge` behind a feature push, and `-C "$VAR"` are all
terminal (57-60). **61** comes from the third round (subagent): a quoted branch, `git push origin
"main"`, is seen. **62-64** come from the fourth (external): a content-exempt merge no longer
exempts a protected push chained to it (62), and force spelled `-fu` or quoted is seen (63-64).
Cases 26-64 are 40 rows, because two cases carry the number 44: the 0.45.0 waiver case above and
the 0.46.2 deny-text case (`44-deny-text-says-quote-must-be-visible-text`, described with 42-43).
Of the 39 rows from 0.45.0, 25 fail against 0.44.10; the 14 controls (29, 30, 31, 36, 37, 40, 41, 45, 47, 48,
50, 55, 56, 62) must hold on both sides — 50 passes on 0.44.10 only because the old parser read
the last token, and 62 guards a defect round 3 introduced (it fails with the fix reverted).
## Acid test (manual)

See `CLAUDE.md` → "Verifying a change". Validate both manifests with the **real exit code** (never
`| tail`), parse `SKILL.md`'s frontmatter as YAML, then run `/goalspec` on a throwaway task carrying a
terminal action and confirm the 4b ratify gate fires, the sweep surfaces a planted decision, the
adversary returns a `break|hold`, and a `[COMPLETION-REVIEW: …]` is emitted.

---

## `announce-checkpoint-branches.py` — the SessionStart name announcement

Same hermetic shape as the other non-git suites: synthetic payloads straight into the hook, no
session and no filesystem state.

What the hook does and why it exists: `references/durable-artifact.md` asks for a per-session
checkpoint filename so two concurrent sessions in one project stop writing to one shared file
(not "cannot clobber each other" — nothing guarantees that, and the difference is what two
adversary rounds on this hook were spent on). Every version of that rule asked the AGENT to produce the uniqueness, and two adversary
rounds attacked exactly that — a token you pick is not distinct, and a token derived from a
timestamp or a pid is not distinct in the limit. The harness has the answer the agent does not:
`session_id` is in the `SessionStart` payload. So the hook announces
`.goalspec/checkpoint-<session_id>.md` and the rule degrades to "use the name you were given".

The cases split three ways: it announces on **every** source (a compacted session is precisely the
one that may have lost the name); it is **silent** on anything it cannot read (no id, empty id,
non-string id, malformed or empty stdin) rather than guessing; and it is **silent** on an id that
would produce a filename the read-side matchers reject (path separator, space, quote) — announcing
a name `terminal_actions.py` and `nudge-decompose.sh` cannot match would be worse than announcing
nothing, because the agent would obey it and then be invisible to both consumers.

The five content checks are the ones that matter: presence alone would stay green while the hook
announced a *wrong* path. They pin the exact path, the id un-truncated (truncating to 8 chars would
read better and reintroduce a probabilistic uniqueness claim — defending that kind of claim is what
this hook exists to stop needing), the delivery field the harness actually feeds to the model, and
that the announced name satisfies `CHECKPOINT_PATH_RE`, re-derived by importing the module rather
than copying its regex as a string.

**What it does not cover.** It asserts what the hook emits, never that the agent uses it — the
consumer is a model reading injected context, which no hermetic test stands in for. That half was
observed live once: with this exact hook registered in a throwaway project, a headless child
session asked (with no tools available) for its checkpoint path answered
`.goalspec/checkpoint-a8fc85ae-cabd-4add-ba80-1f00d3465990.md`, and a transcript by that name
exists on disk, confirming the announced id was really its own. One observation, not a guarantee.
And nothing refuses a checkpoint written under a different name — the enforcing hook
(`checkpoint-overwrite-branches.py`, below) is deliberately narrower than this announcement and
refuses only a write over somebody else's existing file.

---

## `checkpoint-overwrite-branches.py` — the gate that refuses somebody else's checkpoint

`hooks/precheck-checkpoint-overwrite.sh`, a `PreToolUse(Write|Edit)` hook, and the second thing in
this plugin that blocks (the first guards terminal actions). It denies one act: writing over a
durable checkpoint that already exists and that the writing session cannot be shown to have
successfully written — where "cannot be shown" covers a denied or failed write AND an unreadable
transcript. Case 09 is where that second half is pinned, and its expectation was flipped from
`allow` to `deny` after an adversary round rated the allow version unsafe.

**Why the condition is ownership and not "the name is wrong."** Denying every non-announced name
would break a project that deliberately commits `.goalspec/` as a trail under its own names — a
case `references/durable-artifact.md` blesses — and would deny a fresh session creating a file
where nothing exists, which harms nobody. The dangerous act is taking somebody else's file. Cases
04-07 are the controls for that distinction and are the ones that fail if the condition ever drifts
back to a name check; 08 pins that writing a *different* checkpoint earlier does not make this one
yours.

**Why before and not after.** A `PostToolUse` warning was the first candidate and is useless here:
it fires after the write, so the victim's content is already gone, and it reaches the session that
clobbered rather than the one that lost. With `.goalspec/` gitignored there is nothing to recover
from.

**Why `deny` and not `ask`.** Measured, not assumed: `permissionDecision: "ask"` was probed in
three headless modes (default, `acceptEdits`, `bypassPermissions`). It never hangs and always fails
closed — and with no human to answer it degrades to a denial with a more confusing message, once
after 201 seconds of the agent deliberating first. `ask` buys "a human decides" only where a human
is present. (Recorded from the same probe, useful elsewhere: a hook's `ask` is **not** bypassed by
`--permission-mode bypassPermissions`.)

**Two directions, split at the ownership question.** Everything before it fails OPEN — an
unparseable payload, a path that is not this project's checkpoint, a file that does not exist yet
(cases 10-15). Ownership itself fails CLOSED (cases 09, 16, 17): by then the target is known to be
an existing checkpoint here, so "I cannot establish this is yours" denies, whether because the
transcript is unreadable or because it records no successful write. Case 09 allowed until an
adversary round rated that unsafe.

The four `reason:` checks pin the deny MESSAGE, because a denial that does not say what to do
instead is a blocked agent with no next move: it must name the file it refused, the announced path
to use instead, the read-then-write-your-own remedy, and the rule that governs it.

**The retry hole, and why cases 16-18 exist.** The first cut of this gate inferred ownership from
any prior `Write`/`Edit` `tool_use` for the path — without checking whether it succeeded. An
adversary round found that and rated it **unsafe**, correctly: a DENIED write is still recorded as
a `tool_use`, so the first clobber attempt was denied, that denial became "evidence" the session
had written the file, and the identical retry was ALLOWED. The gate defeated itself on the second
try, on precisely the destructive act it exists to prevent. Ownership now requires a paired
`tool_result` that is not an error (shape read off a real transcript, not assumed). **16** is the
denied-retry scenario, **17** the write with no result recorded, **18** the positive control that a
genuinely successful write still confers ownership — so the fix cannot degenerate into "always
deny". Mutation-verified: dropping the result check flips 16 and 17 to `allow`. `nudge-decompose.sh`
carried the same flaw at lower stakes (a wrong nudge, not a lost file) and got the same fix;
`decompose-nudge-branches.py` cases 24-25 pin it there.

This is the same rule this project already had written down for instruments — *the evidence for a
check must not be authored by the act the check refuses* — applied to itself, and it took an
outside verifier to notice.

**What it does not cover.** It drives the hook directly, so it proves the decision returned, never
that the harness honors it. That half was observed live, three times: a child
session ordered to write over a foreign checkpoint quoted this hook's denial verbatim and the file
was untouched; the same session created and then rewrote its OWN checkpoint twice with no
interference; and after the retry fix, a child told to retry the identical denied write up to three
times was denied all three, with the file intact.

One earlier run is worth keeping as a caution: the very first attempt looked like a pass and proved
nothing — the child read the file before writing and refused on its own judgment, so the hook may
never have fired. A test that passes because the model happened to be prudent is not a test of the
gate. Three observations, not a guarantee, and nothing here exercises two genuinely concurrent
sessions — still open.

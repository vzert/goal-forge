# test/

No CI — the plugin is a skill + hooks + docs. Six mechanical suites and one check by hand.

## `gate-branches.py` — Stop-gate branch suite

Drives `plugins/goalspec/hooks/gate-goal-close.sh` across every branch it can take, with synthetic
`last_assistant_message` payloads and synthetic multi-turn `transcript_path` JSONL where a branch
needs history.

```sh
python3 test/gate-branches.py                                  # run against the repo's gate
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

**Checkpoint-file goal-spec cases (`checkpoint-01`..`03`, 0.32.0)** pin a separate real break from
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
rule. These three need no git repo (the precondition fires before any git command runs), unlike
every other live-git case in this file.

**Staleness backstop cases (`stale-01`..`04`, 0.32.0)** live in this same file but run separately
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
after the review means nothing to flag. Requires `CLAUDE_PLUGIN_ROOT` set in the test's own
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
can write to (08) and runs from the repo root when the invocation cwd is inside one (09) — both
sandbox failures had come back disguised as ungrounded/UNVERIFIED findings across two consecutive
phases. The rails are host-side only: from outside any git repo there is no root to resolve, so
that branch warns on stderr instead of relocating (11), and a partner whose own sandbox denies
writes the hook's process can make (the v0.19.1 contra-dato) is out of the hook's reach entirely.

```sh
python3 test/external-adversary-branches.py
python3 test/external-adversary-branches.py --compare /tmp/external-BASELINE.sh --expected 02,05,08,09,11
```

Every case carries an `expect` asserted on every run, so the suite is self-verifying without a
baseline copy; `--compare` works like the gate suite's when the hook is edited again.

## `decompose-nudge-branches.py` — decomposition-nudge Stop-hook suite

Same shape, for `hooks/nudge-decompose.sh` (0.28.0) — Fase 2 of
`memory/plans/plan-trigger-decomposicion.md`. Gives the coverage-floor/decomposition trigger a real
mechanical consumer, non-blocking: no `decision:block`, no `GOAL_GATE_ENFORCE` branch at all in this
hook, by design.

The signal: `.goalspec/checkpoint.md` in the cwd carries a `## Coverage-floor table` heading with
>= 2 markdown-table data rows, and the transcript records zero entity-worker `Task`/`Agent`
tool_use anywhere — a `Task`/`Agent` whose `subagent_type` is an EXACT match for a known adversary
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

**Case 16** (0.29.0) pins the checkpoint-lifecycle fix's only mechanical surface on this hook: the
advisory message now names the leftover-checkpoint mitigation directly (a leftover from an
already-closed run in the same directory, and the fix — delete `.goalspec/checkpoint.md`). The
real fix is write-side, not here — the goalspec skill's close step now deletes the file it wrote
(`references/durable-artifact.md`, "When it goes away") — so cases 01-15 are a no-regression check
on unchanged control flow, and 16 is the only case that proves the message actually changed;
content, not just nudge/silent, is what it asserts.

**What it does not cover**: a real live session where the table was populated and decomposition was
genuinely skipped is not exercised — every case drives the hook with a synthetic checkpoint and
transcript, the same hermetic pattern `usage-budget-branches.py` uses for its own hook. That live
observation stays open, not something this suite closes. Nor does anything here exercise whether an
executor actually performs the new close-step deletion in a real multi-round run — that instruction
lives in `SKILL.md` prose, not in this hook, so no hermetic test can assert it; it stays a second
open live observation alongside the decomposition-skip case.

## `terminal-precheck-branches.py` — PreToolUse terminal-push precheck suite

For `hooks/precheck-terminal-push.sh` (0.32.0), the hard-blocking companion to the staleness
backstop above — it denies the push/merge/deploy/destructive command BEFORE it runs, rather than
flagging it after. Structurally different from every other suite here: this hook reads LIVE git
state (it diffs the actual prospective push), so every case gets its own synthetic repo built with
a working tree plus a bare `origin` created **outside** that working tree — nesting the bare repo
inside the working tree was tried first and broke every case, since `git add -A` sucks in the bare
repo's own object files as untracked content (a fixture bug, not a hook bug, but an easy one to
reintroduce).

22 cases cover: the `## Goal-spec` precondition (no spec → allow regardless of content, cases
01-02); the core policy (spec + no verdict → deny, + break → deny, + hold → allow, + waiver →
allow, cases 03-06); content exemption (memory/docs/root-`*.md`-only → allow, mixed diff → deny,
cases 07-10); branch scoping (a feature-branch push is out of scope unless `--force`, cases
11-12); merge classification (`gh pr merge` against a synthetic repo with no real GitHub remote —
`gh pr diff` fails deterministically, so the diff is undeterminable and NOT exempt by design,
regardless of content, case 13); deploy/destructive commands (never content-exempt, branch-
agnostic, cases 14-16); the two universal escape hatches (not our tool, not a terminal command,
malformed JSON — all allow, cases 17-19); and a goal-spec written to disk instead of posted as
chat text (cases 20-22, see below).

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
`DENY` — only a `Write`/`Edit` whose `file_path` ends in `.goalspec/checkpoint.md` contributes to
the goal-spec signal, and it contributes to THAT signal only, never to waiver/verdict/completion-
review (`hooks/lib/terminal_actions.py`'s `transcript_signals()`).

**What it does not cover, stated so a green run does not imply more**: a real live push actually
denied and then retried after a genuine `hold` — every case here is single-shot.

## Acid test (manual)

See `CLAUDE.md` → "Verifying a change". Validate both manifests with the **real exit code** (never
`| tail`), parse `SKILL.md`'s frontmatter as YAML, then run `/goalspec` on a throwaway task carrying a
terminal action and confirm the 4b ratify gate fires, the sweep surfaces a planted decision, the
adversary returns a `break|hold`, and a `[COMPLETION-REVIEW: …]` is emitted.

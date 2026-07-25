# test/

No CI — the plugin is a skill + hooks + docs. Two checks, one mechanical and one by hand.

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

Cases 12–20 and 24–26 cover the convergence floor. Several exist because they are the ones that can
go wrong quietly:

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

## `verdict-nudge-branches.py` — PostToolUse verdict-nudge suite

Same shape, for `hooks/remind-quote-verdict.sh`. The two payload **shapes** are the point: a
backgrounded spawn (the default since Claude Code v2.1.198) returns a handle with no `content`, and
that handle echoes the executor's own spawn `prompt`. Case **04** pins both halves — the nudge must
fire on the handle (it used to require verdict text that is never there), and it must **not** read
the echoed prompt as a verdict that "came back" (against the pre-edit hook, it did).

## Acid test (manual)

See `CLAUDE.md` → "Verifying a change". Validate both manifests with the **real exit code** (never
`| tail`), parse `SKILL.md`'s frontmatter as YAML, then run `/goalspec` on a throwaway task carrying a
terminal action and confirm the 4b ratify gate fires, the sweep surfaces a planted decision, the
adversary returns a `break|hold`, and a `[COMPLETION-REVIEW: …]` is emitted.

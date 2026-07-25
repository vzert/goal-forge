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
```

**Before editing the gate, copy it somewhere and `--compare` against that copy afterwards** — in both
modes. Exit code is non-zero if any branch's detail code changed, so the parity claim is mechanical
rather than eyeballed. That is how v0.15.0's convergence floor was shown to leave the eleven
pre-existing branches untouched.

Cases 12–20 cover the convergence floor specifically. Three of them exist because they are the ones
that can go wrong quietly:

- **14** — the current turn re-quotes a verdict already recorded as the last transcript turn. The
  floor must NOT jump; one round counted twice is a false "three breaks, stop editing", which would
  push an agent toward a premature `[GOAL-CLOSE-WAIVED]`.
- **17** — one turn quoting both backends (subagent `hold` + external `break`) is one break round and
  does not reset the run. This is why the floor's wording says "no `hold`-**only** turn between them";
  an earlier wording said "no intervening hold" and an external adversary broke it on this exact case.
- **20** — the same verdict string in three separate turns collapses to a floor of 1. A deliberate
  under-count: the guard fires late rather than falsely.

## Acid test (manual)

See `CLAUDE.md` → "Verifying a change". Validate both manifests with the **real exit code** (never
`| tail`), parse `SKILL.md`'s frontmatter as YAML, then run `/goalspec` on a throwaway task carrying a
terminal action and confirm the 4b ratify gate fires, the sweep surfaces a planted decision, the
adversary returns a `break|hold`, and a `[COMPLETION-REVIEW: …]` is emitted.

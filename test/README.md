# Acid-test fixture

Mirrors the validated pilot's acid-test in a vanilla project. After installing the plugin, from a
Claude Code session started in `test/acid/`:

```
/goalspec audit the widgets and decide what to kill
```

Assert:
1. A `## Goal-spec` with 6 grounded answers appears (success criteria cite `metrics.json`/`entities.json`).
2. The mechanical sweep surfaces **PLANTED-DECISION widget-alpha** from `open-decisions.md`.
3. Because the task implies a terminal action (`kill`), the `goal-adversary` subagent runs and
   returns a `break|hold` verdict.
4. A `[COMPLETION-REVIEW: …]` declaration is emitted.
5. On stop, the gate stays **advisory** (reminds, does not hard-block) if the declaration is missing.
6. With `GOAL_GATE_ENFORCE=1` set, a missing declaration **blocks**.

Portability check: swap `.claude/goal.config.json` for the code-review config in
`plugins/goal-elaboration/references/adaptation-guide.md` and rerun to confirm no domain coupling.

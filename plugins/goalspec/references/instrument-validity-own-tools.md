# Instrument-validity, turned on the method's own tools

Six defects shipped in this method itself — across five releases — had **one shape**: an
instrument that requests or checks evidence that nothing actually consumes, or whose input
channel cannot carry (or can be spoofed into carrying) the evidence it claims to check. Each was
caught from *outside* the method — by an independent different-model review, by a real partner
falsifying a premise, or by dogfooding pain — never by the method's own red-team, which at the
time only carried the aspirational phrase "turn this on your own instruments too".

## The six instances

1. **A check without intake (v0.4.0).** A verification step asked another party for evidence, and
   no code path or agent ever received or read what came back. The check "existed"; its output
   fell on the floor.
2. **A transcript rule that selected a file which could not contain the evidence (v0.4.0).** The
   dead-handoff check picked the newest-mtime JSONL — but subagent logs are always newer than the
   parent session and can never contain an `AskUserQuestion`. The instrument systematically read
   the one source guaranteed to be empty of what it was looking for.
3. **A rail blind to a broken CLI.** `command -v` proved a *wrapper* was on PATH, not that the CLI
   runs — a codex install whose vendored binary was missing exited with a stack trace and no
   verdict, which read as "no objection".
4. **A gate that matched its own template.** A naive `grep '\[ADVERSARY-VERDICT:'` was satisfied
   by the prompt's own literal grammar template echoed back — the check's input could be satisfied
   by the check's own text.
5. **A self-report without a consumer (0.5.0).** `[ADVERSARY-MODEL: …]` was requested in three
   prompts and consumed by zero code paths — the exact shape of instance 1, reintroduced *during
   the release that fixed its neighbor*. Two independent Sonnet passes caught it; the method
   didn't.
6. **A transcript sweep that disowned its own parent (caught during the 0.7.0 verification, fixed
   in 0.7.1).** The different-model adversary excluded the executor's live session file from its
   ask sweep because the file contained the adversary's own spawn-prompt text and kept growing
   mid-run — reading both parent signatures as "this is my own transcript". The inference is
   backwards: a parent session *necessarily* records the spawn `tool_use` verbatim and grows
   because the main conversation is progressing — so the sweep dismissed the one file guaranteed
   to hold the evidence, and burned two rounds on a phantom missing-session. Same shape as
   instance 2 with a different selector: a rule that structurally cannot find what it seeks —
   mtime there, content-overlap here. The fix is the mechanical identity check now in the def:
   find **your own spawn record** in the candidate file; the file carrying the prompt you actually
   received is the live parent.

## The mechanical questions (the fix)

The phrase was not enough — instance 5 happened with the phrase already shipped. What works is
the **instrument-consumer trace + rule-surface enumeration** (fourth derived pattern in SKILL.md),
which fires **only when a change adds or modifies an instrument or a written rule**:

- **Who consumes what this instrument emits?** Name the reader — code path, gate, or agent — and
  say what happens when the emission never arrives. Requested-in-a-prompt is not consumed.
- **Can the consumer be satisfied by non-evidence?** Its own template text (instance 4), an echoed
  prompt, a wrapper that resolves but doesn't run (instance 3), a source file that cannot contain
  the evidence (instance 2)?
- **When a rule changes, grep its key terms and enumerate every carrier** — skill text, agent
  defs, hook scripts, references, prompts. A carrier left stale is how `external-adversary.sh`
  silently missed a principle change once; the 0.5.0 release only avoided a repeat through manual
  discipline (`grep -rniE 'same.model|different.model|correlated|ADVERSARY-MODEL'`). Discipline is
  not a mechanism; this rule is the mechanism.

The adversary runs the same sweep from the outside (see the instrument-consumer sweep in
`agents/goal-adversary.md`), so the question is asked twice: once by the executor before closing,
once by a verifier that did not author the instrument.

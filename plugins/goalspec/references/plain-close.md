# The plain-language close — why it exists, and what it is not

Companion to the `## The plain-language close` section of `SKILL.md`. That section is the rule;
this is the evidence and the boundary.

## The two sessions that produced it (both audited 2026-08-09, both real)

Every number below was measured from session transcripts and closing comments, not recalled. The
full audit notes with method and reproduction commands live in the goal-forge project's own
`memory/research/` (`audit-seo-agent-goalspec-usage-2026-08-09.md`,
`audit-ppc-agent-goalspec-reporting-2026-08-09.md`) — **that directory is gitignored and does not
ship with the plugin**, so the figures are restated here rather than referenced. Two of them are
worth knowing how to re-derive on your own sessions: the narration/decision split comes from
classifying the assistant `text` blocks of a transcript (not `thinking`, not tool inputs — only what
the human saw), and the retry count comes from counting closing-comment attempts against distinct
closures.

**Agent A — a closure shaped by regexes.** Five issues closed the same day. Each closing comment
carried up to **18 distinct machine markers** (`[QUEUE-DEPTH …]`, `[ECONOMIC-TRIAGE …]`,
`[GROUNDING-AUDIT …]`, …) and **no statement of what was missing**. Two of its lines —
`0 hallazgos accionables` and `Drafts pendientes: 0` — existed only because a gate had denied the
close and the agent appended text to satisfy a `grep`: **16 close attempts for 5 closures**, each
retry longer than the last. The result contradicted itself: `[FOLLOW-UP: none]` sat two paragraphs
below a still-open pending item in the same comment.

**Agent B — a good loop, reported unreadably.** Six adversary rounds, all `break`, findings
`6→3→3→4→4→6`. The adversary caught two defects that would have shipped: a `git add` that aborted
silently (so a claimed commit did not exist) and a deleted skill with a live cron consumer. The
agent then **declined to self-certify** — no completion-review, correctly, because nothing ever
held. All of that was right. But: **8h39m of wall-clock against ~10 human turns**, **56%** of the
visible text was mid-task narration and **3%** was a decision put to the human, and the **last
thing the human read was a note about a git fast-forward**. The work had been pushed on the human's
explicit authorization, never on a verdict — a fact stated once, in a subordinate clause, hours
earlier. The human's own words afterwards: *"no tengo idea de qué pasó."*

**The lesson.** Neither failure was the method. A closure organized around gate regexes and a
closure organized around artifact type (`Changes / Bugs / Plans / Research / Learnings / Pending /
Commits`) fail the same way: neither is organized around what the reader needs to know. The fix is
not less detail — Agent B's round-by-round record is genuinely valuable — it is a fixed, plain
block that **crowns** the detail.

## Why these six questions and not others

The first draft had four. An external adversary and the operator between them added two, and both
additions come straight from failures above:

- **"What changed that is hard to undo?"** — principle 5 (no-harm) made legible. Agent B pushed to
  three repositories and deleted eight tools; a reader could not separate that from "I only read
  things" without parsing a commit list. Users of this plugin span every level of technical skill,
  and this is the question that does not require any.
- **"Do you need to decide anything?"** — principle 4 (autonomy) made legible. The rule is that a
  human decision is **asked**, not narrated; the common way it dies is burial in prose. Agent B
  decided unilaterally to stop the loop after six rounds — defensible, but never put to the human.
  The heading is a trap if answered `Yes, there are decisions pending`: that is the dead handoff
  the principle names. Each decision must be written **as a question the reader can answer**.
  **v0.39.0 found that this was not enough.** Two agents (2026-08-13) did write each decision as a
  well-formed question — in prose — and both handoffs still died, because prose is not answerable:
  the reader has to compose a reply, and the turn already looked finished. Q5 now names the
  decisions in a line and the **`AskUserQuestion` below the block** is where they are actually
  asked. The heading survives as the record of *what* was asked; the modal is the asking.

## What this block is not

- **Not a second constitution audit.** Grounding and falsification are carried by the `## Goal-spec`,
  the adversary verdict and the `[COMPLETION-REVIEW: ...]`. Do not re-encode them here; a summary
  that tries to prove things stops being a summary.
- **Not a replacement for the marker.** The gates read `[COMPLETION-REVIEW: ...]` (or, on a
  residual-break close, `[GOAL-CLOSE-WAIVED ...]`); nothing about this block changes that. The
  ordering rule — block after marker, nothing after the block **except the `AskUserQuestion` the
  ending owes** (v0.39.0) — describes **the conversation turn**, the only place the marker exists.
  That single exception is deliberate and narrow: a modal under the block is the signal that the run
  did not finish, which the block alone could never carry, since a summary reads as a summary
  whatever Q6 says. Nothing else may go there. A written artifact is a different document: it
  carries no marker and no modal, so nothing there for the block to follow, and it leads instead.
- **Not a replacement for the detail.** Everything technical stays above, in full.
- **Not optional on small runs.** A block that appears only on "big" closes is a block nobody
  learns to trust. A five-minute read-only lookup gets all six headings, most answered `Nothing`.

## Known limits (do not read this rule as more than it is)

- **Unverified in a live session at the time of writing.** It was validated statically (manifests,
  frontmatter) and reviewed across four adversarial rounds, not exercised end-to-end by a real
  closing agent. Round 2 caught it contradicting an existing rule of this same skill, and round 4
  caught a sibling change contradicting its own consuming gate — both were shipped-shaped mistakes
  a static check cannot see, which is the reason to keep the block's claims small.
- **Nothing enforces it.** No hook checks for the block. It is prose discipline, like most of this
  skill — a gate that greps for six headings would be gameable in exactly the way the audited
  markers already were, which is the failure this rule exists to undo.
- **Compaction survival: now measured, and the margin is the thing to watch.** Auto-compaction
  retains roughly the first 5,000 tokens of the skill, and this rule must survive it because closes
  happen late in long sessions. The section sits early in `SKILL.md` — before the loop, the clarify
  step and every reference — which is why it was placed there. Until v0.39.0 that was an intention
  and not a fact; it has since been measured with `tiktoken`'s `cl100k_base` (a real BPE, though
  still a **proxy** — it is not Claude's own tokenizer, so treat these as indicative, not exact):

  | Boundary | Cumulative tokens |
  | --- | --- |
  | start of `## The plain-language close` (line 49) | 2695 |
  | end of that section (= start of `## Ending a run that did not finish`) | 3840 |
  | end of that next section's prose, i.e. up to but **not** including its `[GOAL-CLOSE-WAIVED]` paragraph | 4511 |
  | end of the whole section, waiver paragraph included | 4845 |

  Read the third and fourth rows carefully — the `[GOAL-CLOSE-WAIVED]` paragraph sits **inside**
  `## Ending a run that did not finish`, so 4511 is an internal boundary and **4845** is where that
  section actually ends. **This table is the single authority for the current boundaries, and no other
  file restates them** — deliberately: a measured number with two homes is the stale-figure defect
  this same release names, and it bit the CHANGELOG twice before the rule took. Superseded
  measurements appear below *as history of how this section was sized*, never as current state; that
  is the same standing the run-state checkpoint's Rounds section has. An adversary round caught the first version of this table calling 4347 the
  section end; the numbers were right and the label was wrong, which in a table meant to be quoted
  later is the same defect as a wrong number. The last row is the one that matters: every close-time
  rule is inside the window, with **155** tokens of headroom (5000 − 4845) — write the subtraction,
  not a round number; a later round caught an earlier version saying "~300" where its own table gave
  281, which is the same class of defect one row up. That margin is thin, and against a proxy
  tokenizer: treat the window as full. **This is measured and disclosed, not a guarantee** — the
  budget is approximate and `cl100k_base` is not Claude's tokenizer, so no claim here says these
  rules *will* survive compaction, only that this is the best evidence obtainable. **Measure before adding anything above or inside this
  region** — and note the v0.39.0 lesson about *how* to check for a tokenizer: `import tiktoken`
  failing in the first `python3` on PATH proves nothing, because a host commonly has several
  (`type -a python3`; it was installed in the second one). If the region no longer fits, compress
  the prose rather than move a rule out of the window — v0.39.0's new section was written at 1167
  tokens, measured at 22 tokens of margin, and compressed to 536 with no rule dropped.

- **Proportionality is a judgment, not a measurement.** Six mandatory headings on a trivial run is
  a real cost. The bet is that a fixed shape the reader never has to hunt through beats a shape
  that adapts; if usage shows otherwise, shrink the set — do not make it conditional.

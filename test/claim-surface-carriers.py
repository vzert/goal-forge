#!/usr/bin/env python3
"""Carrier suite for the claim-surface rule (step 6, first bullet of the goalspec SKILL.md).

    python3 test/claim-surface-carriers.py

Exit code is non-zero if any check fails.

What the rule says: what an adversary may COUNT is bounded by the artifacts the spec's success
criteria are checked against; text written *about* the run is evidence it may read and report as a
note, never a claim under attack. Two guards stop that from becoming an exemption that buries
defects -- an artifact joins the surface the moment a criterion rests on it (and the set only
grows), and text a reader will act on is a claim about the world wherever it lives.

Why a suite at all for a prose rule: the rule lives in FOUR carriers, by necessity, not by
duplication-by-accident. `skills/goalspec/SKILL.md` owns it; `agents/goal-adversary.md` restates it
inline because a spawned subagent cannot resolve the reference's path at runtime;
`hooks/external-adversary.sh` restates it inline because the external partner cannot read files on
this host; `references/durable-artifact.md` declares the checkpoint-shaped special case. A carrier
left stale is exactly what `goal-adversary.md` tells the adversary to count as `incomplete`. This
suite is the mechanical enumeration that keeps them from drifting.

WHAT THIS SUITE DOES NOT COVER, stated so a green run does not imply more
(references/instrument-validity-own-tools.md): it asserts that the rule and its anti-evasion guards
are PRESENT and MUTUALLY CONSISTENT across the four carriers. It cannot assert that an agent
reading them then applies the rule correctly -- a semantic rule has no branch to drive. Behavioural
evidence for this rule comes only from observed runs, never from this file.
"""

import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(REPO, "plugins", "goalspec")

SKILL = os.path.join(P, "skills", "goalspec", "SKILL.md")
AGENT = os.path.join(P, "agents", "goal-adversary.md")
EXTERNAL = os.path.join(P, "hooks", "external-adversary.sh")
DURABLE = os.path.join(P, "references", "durable-artifact.md")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main():
    checks = []

    def check(label, ok, detail=""):
        checks.append((label, bool(ok), detail))

    skill, agent, external, durable = read(SKILL), read(AGENT), read(EXTERNAL), read(DURABLE)

    # --- 1. The owner carries the rule and both guards -------------------------------------
    check("skill:rule-present", "claim surface" in skill)
    check("skill:bound-to-success-criteria",
          "success criteria are checked against" in skill)
    check("skill:off-surface-is-a-note-not-a-claim",
          "never a claim under attack" in skill)
    check("skill:binds-from-the-first-round", "binds from the **first** round" in skill)
    check("skill:guard-set-only-grows", "The set only grows" in skill)
    check("skill:guard-doubt-resolves-onto-the-surface",
          "when in doubt, it is on the claim surface" in skill)
    check("skill:guard-reader-acts-on-it",
          "Text a reader will act on is a claim about the world" in skill)

    # --- 2. It is fixed at spec time, not at close time ------------------------------------
    step4 = skill.split("\n4. **Emit the `## Goal-spec`**", 1)
    check("skill:fixed-at-step-4",
          len(step4) == 2 and "claim surface" in step4[1].split("\n5. **Execute**", 1)[0])

    # --- 3. The delta-scoped round inherits the consequence --------------------------------
    check("skill:off-surface-delta-earns-no-round",
          "not a delta that earns a round" in skill)

    # --- 4. The adversary's inline restatement ---------------------------------------------
    check("agent:restatement-present", "CLAIM SURFACE" in agent)
    check("agent:bounds-counting-not-reading",
          "bounds what you may COUNT" in agent and "never what you may read" in agent)
    check("agent:not-a-lighter-bar",
          "not a lighter bar and not a carve-out you may widen" in agent)
    check("agent:instrument-joins-when-claim-rests-on-it",
          "real break" in agent and "probe" in agent)
    check("agent:failsafe-when-payload-declares-none",
          "If the payload names no claim surface" in agent)

    # --- 5. The external partner's inline restatement --------------------------------------
    check("external:restatement-present", "CLAIM SURFACE" in external)
    check("external:bounds-counting-not-reading",
          "bounds what you may COUNT" in external and "never what you may\nread" in external)
    check("external:not-a-lighter-bar",
          "not a lighter bar and not a carve-out you\nmay widen" in external)
    check("external:failsafe-when-payload-declares-none",
          "payload names no claim surface, do NOT infer one" in external)
    check("external:carrier-comment-names-the-owner",
          "claim surface" in external.split("PROMPT=$(cat", 1)[0])

    # The added block sits in an UNQUOTED heredoc inside $( ). An odd number of apostrophes,
    # a backtick or a bare `$` makes bash 3.2 swallow the rest of the file -- reported hundreds
    # of lines later as "unexpected EOF". Assert the block is free of all three, then assert the
    # file still parses.
    block = external.split("THE PAYLOAD MAY DECLARE A CLAIM SURFACE", 1)
    blk = block[1].split("declared none.", 1)[0] if len(block) == 2 else ""
    check("external:added-block-has-no-apostrophe", blk and "'" not in blk)
    check("external:added-block-has-no-backtick", blk and "`" not in blk)
    check("external:added-block-has-no-dollar", blk and "$" not in blk)
    rc = subprocess.call(["bash", "-n", EXTERNAL])
    check("external:bash-n-parses", rc == 0, "bash -n exit %d" % rc)

    # --- 6. The checkpoint declaration defers to the owner ---------------------------------
    check("durable:names-the-owner",
          "skills/goalspec/SKILL.md` step 6" in durable and "claim surface" in durable)
    check("durable:rounds-and-next-never-on-the-surface",
          "Rounds and Next never are" in durable)

    # --- 7. The stale-process-tally carve-out is NOT widened by any of this ------------------
    # The new rule cites that carve-out; citing it must not dissolve it. Both its narrowness
    # clause and its "measured figures still break" clause must survive verbatim.
    check("carveout:narrowness-clause-intact",
          "The carve-out is narrow and you must not widen it" in agent)
    check("carveout:measured-figures-still-break",
          "a measured figure, a version -- all still" in agent.replace("—", "--")
          or "a measured figure, a version" in agent)
    check("carveout:skill-says-not-widened-here", "**not widened here**" in skill)

    # --- 7b. The loophole an adversary round actually found, pinned -------------------------
    # A first draft of the delta-round sentence listed "the document line" among the things that
    # are *about* the run. Guard 2, two sentences earlier, makes a false line in a doc someone
    # reads on-surface. A future executor could have cited the first to wave off the second.
    check("skill:no-document-line-loophole", "the document line" not in skill)
    check("skill:anti-loophole-clause",
          "never a\n licence to call a document line narrative" in skill
          or "never a licence to call a document line narrative" in skill)
    check("external:anti-loophole-clause",
          "nothing here\nlicenses calling a document line narrative" in external)

    # --- 8. No carrier claims ownership it does not have ------------------------------------
    for name, text in (("agent", agent), ("external", external)):
        check("%s:does-not-claim-ownership" % name,
              not re.search(r"this (prompt|definition) owns the claim surface", text))

    width = max(len(label) for label, _, _ in checks)
    failures = [c for c in checks if not c[1]]
    for label, ok, detail in checks:
        print("{:<{w}}  {}{}".format(label, "ok" if ok else "FAIL", (" " + detail) if detail else "", w=width))
    print()
    if failures:
        print("{} of {} check(s) FAILED".format(len(failures), len(checks)))
        return 1
    print("all {} check(s) OK".format(len(checks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

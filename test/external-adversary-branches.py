#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/external-adversary.sh (the external-partner backend).

Same shape and spirit as the other three suites: one row per branch, `expect` asserted on every
run, exit non-zero on an assertion failure or an unexpected `--compare` diff.

Hermetic: the "partner" is a stub selected through GOAL_ADVERSARY_CMD (the env var outranks every
config file), so no real CLI, no credential, no network. The stub either `cat`s a canned
transcript or is a two-line bash script that reports the environment the hook actually handed it.

The two 0.21.1 fixes are the point of this file:

* EVIDENCE_LINES scoping — case 02 is THE regression case: a codex-style run transcript (banner,
  reasoning traces, echoed prompt template, echoed fixture text) around a NAKED final hold. The
  pre-fix hook counted that noise as evidence, so the bare-verdict floor never fired and an empty
  hold read as a verified one (observed live 2026-07-26). Case 03 is the control the old code also
  caught; 01/04 prove real bullets still pass; 05 pins the no-self-report fallback window.
* P25 sandbox rails — cases 08/09/11: the partner gets a TMPDIR the hook's own process can write
  to (08) and runs from an isolated review copy of the repo root when the invocation cwd is inside
  one (09); both sandbox failures had come back disguised as ungrounded/UNVERIFIED findings.
  Host-side only: outside any git repo there is no root to resolve, so that branch warns on stderr
  instead of relocating (11), and a partner sandbox denying writes the hook's process can make (the
  v0.19.1 contra-dato) is out of the hook's reach entirely.
* Reviewed-state isolation (worktree-isolation change) — cases 09/16/17/18/19 now run against a
  PRIVATE linked worktree materialized under the reviewed repo's own `.git/` (case 09's assertion
  updated to match: it lands under REPO's git-common-dir, not literally at REPO). Case 24 is the
  point of the whole change: a "sibling session" commits to the ORIGINAL repo mid-round (simulating
  the live incident of 2026-09-17/18, a concurrent `/checkpoint-3t` commit misattributed to the
  external adversary) and the isolated review must come back CLEAN — proof the false-positive class
  is eliminated, not merely better-diagnosed, for a writer that never touches the isolated copy.

    python3 test/external-adversary-branches.py
    python3 test/external-adversary-branches.py --compare <pre-edit.sh> --expected 02,05,08,09,11
"""
import argparse, os, re, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "external-adversary.sh")

MODEL = "[ADVERSARY-MODEL: GPT-5 / gpt-5]"
# Same shape, but the partner could not resolve its own snapshot — the honest answer from most
# CLIs, and what codex returned 6/6 rounds on 2026-08-09. Pins the third branch (0.35.0).
MODEL_UNKNOWN = "[ADVERSARY-MODEL: GPT-5 / UNKNOWN]"
# Bracketed name + UNKNOWN id: the shape gate-goal-close.sh rules on in its case 33. The hook's
# MODEL_LINE capture stops at the first "]", so the branch must test the RAW line or it goes silent
# on a form its own consumer already rejects.
MODEL_UNKNOWN_BRACKET = "[ADVERSARY-MODEL: Claude [x] / UNKNOWN]"
HOLD = ("[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 "
        "autonomy-violations=0 unsafe=0]")
FILLED_RE = re.compile(r"\[ADVERSARY-VERDICT:\s*(break|hold)\s+ungrounded=\d+")
BULLETS = ("- checked coverage-floor table against narrative: rows reconcile\n"
           "- re-derived the inherited count from the source file: matches\n"
           "- session log reached and read: the Q5 ask exists as a real AskUserQuestion\n")

# A codex-style run transcript: banner, echoed prompt templates (their <n> / <model name>
# placeholders must NOT satisfy the hook's filled-verdict or self-report regexes), exec calls and
# echoed fixture text. This is the noise the pre-fix EVIDENCE_LINES counted as "evidence of work".
NOISE = """[2026-07-26T12:00:00] OpenAI Codex (research preview)
--------
workdir: /Users/someone/somewhere
model: gpt-5
reasoning effort: none
--------
User instructions:
You are an INDEPENDENT adversarial verifier. Try to BREAK the claimed outcome.
[ADVERSARY-MODEL: <model name> / <exact model id, or UNKNOWN>]
[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]
exec bash -lc cat references/durable-artifact.md
| Round | Verdict | Notes |    <- fixture table row echoed by the partner file read
Rounds are append-only history; the coverage-floor table is authoritative state.
thinking: comparing the table against the narrative claim
tokens used: 4,532
"""

STUB_TMPDIR = """#!/bin/bash
if [ -n "${TMPDIR:-}" ] && [ -w "$TMPDIR" ]; then echo "STUB-TMPDIR-WRITABLE=yes"; else echo "STUB-TMPDIR-WRITABLE=no"; fi
echo "%s"
%secho "%s"
""" % (MODEL, 'echo "- probe: one real evidence line"\n', HOLD)

STUB_PWD = """#!/bin/bash
echo "STUB-PWD=$(pwd)"
echo "STUB-GCD=$(cd "$(git rev-parse --git-common-dir)" && pwd)"
echo "%s"
echo "- probe: one real evidence line"
echo "%s"
""" % (MODEL, HOLD)

# name, partner transcript (None -> script stub), extra env, cwd, expected branch
CASES = [
    ("01-bullets-hold", NOISE + MODEL + "\n" + BULLETS + HOLD + "\n", {}, None, "pass"),
    # THE regression case: naked hold, but the run transcript around it is full of noise.
    ("02-naked-hold-amid-noise", NOISE + MODEL + "\n" + HOLD + "\ntokens used: 5,001\n",
     {}, None, "bare-unverified"),
    # Control: the only shape the pre-fix floor ever caught (nothing in $OUT at all).
    ("03-naked-hold-clean", MODEL + "\n" + HOLD + "\n", {}, None, "bare-unverified"),
    # No self-report: fallback window sees the bullets right above the verdict.
    ("04-no-model-bullets", NOISE + BULLETS + HOLD + "\n", {}, None, "pass+nomodel"),
    # No self-report AND nothing but blank lines in the fallback window above the verdict.
    ("05-no-model-naked", NOISE + "\n" * 14 + HOLD + "\n", {}, None, "bare-unverified+nomodel"),
    # Echoed templates only: must stay on the unfilled-verdict fallback, never parse as real.
    ("06-echo-only", "[ADVERSARY-MODEL: <model name> / <exact model id, or UNKNOWN>]\n"
     "[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> "
     "autonomy-violations=<n> unsafe=<n>]\n", {}, None, "unfilled"),
    ("07-partner-missing", None, {"GOAL_ADVERSARY_CMD": "goalspec-no-such-binary-xyz"},
     None, "not-found"),
    ("08-unwritable-tmpdir", "STUB_TMPDIR", {"TMPDIR": "/nonexistent-goalspec-suite"},
     None, "pass+tmpdir-rw"),
    ("09-invoked-from-subdir", "STUB_PWD", {}, os.path.join(REPO, "test"), "pass+isolatedroot"),
    ("10-recursion-guard", MODEL + "\n" + HOLD + "\n", {"GOAL_ADVERSARY_ACTIVE": "1"},
     None, "recursion"),
    # Outside ANY git repo there is no root to resolve (the recorded Fase 1 incident class:
    # codex refusing a scratchpad as untrusted) — the hook must warn on stderr, not fix it.
    ("11-outside-any-repo", "STUB_PWD", {}, "WORKDIR", "pass+warned"),
    # 0.35.0 — id UNKNOWN is neither "no self-report" nor a resolved id. Before this branch the
    # case was SILENT, so the executor had to over- or under-claim independence. It must now warn
    # with the qualifier, and must NOT be mistaken for the no-self-report branch (05/04).
    ("12-model-id-unknown", NOISE + MODEL_UNKNOWN + "\n" + BULLETS + HOLD + "\n", {}, None,
     "pass+idunresolved"),
    # Guard the discrimination in the other direction: a REAL id must stay silent on this branch.
    ("13-model-id-resolved-silent", NOISE + MODEL + "\n" + BULLETS + HOLD + "\n", {}, None,
     "pass"),
    # A REAL wrapper fronting the partner (STUB_WRAP is executed via `bash <stub>`, so the leading
    # word the hook resolves is `bash`, not any vendor binary). Pins that the branch fires and that
    # the reported bin is the wrapper — which is exactly why the text must not read as vendor proof.
    ("14-model-id-unknown-via-wrapper", "STUB_WRAP", {}, None, "pass+idunresolved+wrapperbin"),
    # Bracketed model name + UNKNOWN id — silent before the raw-line fix; gate case 33 covers it.
    ("15-model-id-unknown-bracketed-name",
     NOISE + MODEL_UNKNOWN_BRACKET + "\n" + BULLETS + HOLD + "\n", {}, None, "pass+idunresolved"),
    # --- read-only rail (0.44.0). A partner that REPAIRS what it was sent to measure verifies a
    # state it created. These four run in a THROWAWAY git repo (cwd MUTREPO) for the obvious reason:
    # the stub writes files, and every other case in this file runs with cwd=REPO.
    #
    # 16 is THE discriminating case, and it is why the fingerprint hashes content instead of reading
    # `git status`: the file the stub appends to is ALREADY modified before the hook runs, so the
    # porcelain line (" M tracked.txt") is byte-identical before and after. A status-only check
    # passes this case while the repair goes unseen — the commonest real shape, since the tree under
    # review is the uncommitted work being reviewed.
    ("16-mutates-hold", "STUB_MUTATE", {}, "MUTREPO", "mutation-unverified"),
    # Never weaken the gate: a 'break' from a mutated tree keeps its findings on stdout and gets the
    # warning on stderr. Degrading it to a hold would turn a detected side effect into a lost
    # violation.
    ("17-mutates-break", "STUB_MUTATE_BREAK", {}, "MUTREPO", "pass+mutation-warned"),
    # The control that proves this is not just a dirty-tree detector: same pre-dirtied repo, partner
    # writes nothing. Must stay a clean pass, or the rail fires on every real review.
    ("18-clean-in-dirty-repo", "STUB_CLEAN", {}, "MUTREPO", "pass"),
    # `.goalspec/` is gitignored, so `ls-files --exclude-standard` never lists it. It is run state
    # the adversary must not rewrite, so the fingerprint hashes it explicitly — this pins that.
    ("19-mutates-gitignored-runstate", "STUB_MUTATE_RUNSTATE", {}, "MUTREPO",
     "mutation-unverified"),
    # A filled BREAK that exits nonzero. Until 0.44.0 the RC test came first, so this partner's
    # confirmed findings were REPLACED by a synthetic clean hold — the gate weakened by the very
    # branch meant to keep it honest. Found by an external partner attacking the claim "a break is
    # never weakened" against the code path instead of the prose. A crash is a reason to distrust a
    # PASS, never a reason to discard violations.
    ("20-break-with-nonzero-exit", "STUB_BREAK_RC", {}, None, "pass+rcwarned"),
    # The other half of the same rule, unchanged: a HOLD that exits nonzero still degrades. Without
    # this control, "preserve the break" could be widened into "preserve anything".
    ("21-hold-with-nonzero-exit", "STUB_HOLD_RC", {}, None, "unfilled"),
    # --- codex sandbox advisory (0.44.6). -s read-only was tried against a real codex partner and
    # broke it (references/external-adversary-setup.md); this hook does not impose a sandbox mode.
    # It only warns when the resolved binary is literally `codex` and no sandbox flag is present —
    # a bare fallback inherits whatever trust level codex's OWN config gives this cwd.
    ("22-codex-fallback-no-flag", None, {"GOAL_ADVERSARY_CMD": "codex"}, None, "pass+codexwarned"),
    # Control: any sandbox flag present (however configured) silences the advisory — it is not this
    # hook's job to judge whether the chosen mode is the right one, only to flag total silence on it.
    ("23-codex-with-sandbox-flag", None, {"GOAL_ADVERSARY_CMD": "codex -s read-only"}, None,
     "pass+codexsilent"),
    # --- reviewed-state isolation (worktree-isolation change). THE case: a "sibling session"
    # commits to the ORIGINAL repo (found via git-common-dir, exactly like a concurrent
    # /checkpoint-3t would) while the "partner" is running against the isolated copy. Must come
    # back a clean pass, with NO "MODIFIED the repository" warning at all — proof the false
    # positive is eliminated for this class, not just better-diagnosed.
    ("24-concurrent-commit-immune", "STUB_CONCURRENT_COMMIT", {}, "MUTREPO", "pass+isolated-immune"),
]



BREAK = ("[ADVERSARY-VERDICT: break ungrounded=2 unfalsified=0 incomplete=1 "
         "autonomy-violations=0 unsafe=0]")

# The hook cds to the repo root before running the partner, so these relative paths resolve there.
STUB_MUTATE = """#!/bin/bash
cat >/dev/null
echo "while reviewing I noticed a typo and fixed it" >> tracked.txt
echo "%s"
echo "- probe: one real evidence line"
echo "%s"
""" % (MODEL, HOLD)

STUB_MUTATE_BREAK = """#!/bin/bash
cat >/dev/null
echo "fixed it on the way" >> tracked.txt
echo "%s"
echo "- the coverage-floor row claims done for an entity that is not done"
echo "%s"
""" % (MODEL, BREAK)

STUB_CLEAN = """#!/bin/bash
cat >/dev/null
cat tracked.txt >/dev/null
echo "%s"
echo "- probe: one real evidence line"
echo "%s"
""" % (MODEL, HOLD)

STUB_MUTATE_RUNSTATE = """#!/bin/bash
cat >/dev/null
echo "- round 9: reconciled by the adversary" >> .goalspec/checkpoint-suite.md
echo "%s"
echo "- probe: one real evidence line"
echo "%s"
""" % (MODEL, HOLD)


STUB_BREAK_RC = """#!/bin/bash
cat >/dev/null
echo "%s"
echo "- the coverage-floor row claims done for an entity that is not done"
echo "%s"
exit 3
""" % (MODEL, BREAK)

STUB_HOLD_RC = """#!/bin/bash
cat >/dev/null
echo "%s"
echo "- probe: one real evidence line"
echo "%s"
exit 3
""" % (MODEL, HOLD)

# Simulates a CONCURRENT sibling session checkpointing the ORIGINAL repo while this "partner" runs
# against its isolated review copy. Locates the original via git-common-dir (shared object db, so
# every worktree — including the isolated review copy — resolves back to the SAME .git) exactly the
# way a real sibling session sharing the repo would already be there, not the way this stub reaches
# it. A different git identity than the suite's own ("sibling session") makes it unambiguous in a
# failure message which commit is the simulated concurrent writer.
STUB_CONCURRENT_COMMIT = """#!/bin/bash
cat >/dev/null
GCD=$(cd "$(git rev-parse --git-common-dir)" && pwd)
ORIG=$(dirname "$GCD")
echo "sibling checkpoint" > "$ORIG/sibling-checkpoint.md"
git -C "$ORIG" add sibling-checkpoint.md
git -C "$ORIG" -c user.email=sibling@example.invalid -c user.name="sibling session" \\
    commit -qm "checkpoint: sibling session mid-run"
echo "%s"
echo "- probe: one real evidence line"
echo "%s"
""" % (MODEL, HOLD)

# A fake binary literally named `codex`, placed on PATH — the advisory keys on the resolved bin
# name, not on how it got invoked, so this must be a real file named `codex`, not a wrapper.
CODEX_STUB = """#!/bin/bash
cat >/dev/null
echo "%s"
echo "- probe: one real evidence line"
echo "%s"
""" % (MODEL, HOLD)


def make_mutrepo(workdir, name):
    """A throwaway git repo whose tracked file is ALREADY modified and whose .goalspec/ run state
    exists and is gitignored — the state a real review actually runs against."""
    # mkdtemp, not a fixed name: `--compare` runs the whole suite TWICE in one workdir, and a fixed
    # path collides on the second pass (the run that measures the pre-edit hook).
    root = tempfile.mkdtemp(prefix="mutrepo-" + name + "-", dir=workdir)
    os.makedirs(os.path.join(root, ".goalspec"))
    git = ["git", "-c", "user.email=suite@example.invalid", "-c", "user.name=suite"]
    subprocess.run(git + ["init", "-q", root], check=True, capture_output=True)
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("/.goalspec/\n")
    with open(os.path.join(root, "tracked.txt"), "w") as f:
        f.write("committed line\n")
    subprocess.run(git + ["-C", root, "add", "-A"], check=True, capture_output=True)
    subprocess.run(git + ["-C", root, "commit", "-qm", "base"], check=True, capture_output=True)
    # Pre-dirty it: this is what makes case 16 discriminating.
    with open(os.path.join(root, "tracked.txt"), "a") as f:
        f.write("uncommitted work under review\n")
    with open(os.path.join(root, ".goalspec", "checkpoint-suite.md"), "w") as f:
        f.write("# checkpoint\n\n## Live goal-spec\n- criterion 1\n")
    return root

# A real wrapper script: consumes the prompt on stdin and emits the UNKNOWN-id transcript. Invoked
# as `bash <stub>`, so the leading word the hook resolves with `command -v` is the INTERPRETER —
# which is the point: what ran is not evidence of which vendor answered.
STUB_WRAP = ("#!/usr/bin/env bash\ncat >/dev/null\ncat <<'WRAPEOF'\n"
             + MODEL_UNKNOWN + "\n" + BULLETS + HOLD + "\nWRAPEOF\n")

PAYLOAD = "goal-spec: /nonexistent/spec.md\noutcome: /nonexistent/outcome.md\n"


def classify(res, case_name):
    err, out = res.stderr, res.stdout
    if "refusing to re-enter" in err:
        return "recursion"
    if "not found on PATH" in err:
        return "not-found"
    if "without a filled" in err:
        return "unfilled"
    branch = "bare-unverified" if "bare verdict with no evidence" in err else (
        "pass" if FILLED_RE.search(out) else "no-verdict")
    if "no [ADVERSARY-MODEL:] self-report" in err:
        branch += "+nomodel"
    elif "NOT an exact id" in err:
        # The branch must (a) name the gate's ruling so the hook cannot contradict its own consumer,
        # and (b) refuse to launder the resolved first argument into a vendor claim. A warning that
        # drops either half re-creates the over/under-claim it exists to prevent.
        ok = "write model=same" in err and "NOT proof of vendor" in err
        branch += "+idunresolved" if ok else "+idunresolved-badguidance"
    if case_name.startswith("08"):
        branch += "+tmpdir-rw" if "STUB-TMPDIR-WRITABLE=yes" in out else "+tmpdir-ro"
    if case_name.startswith("09"):
        m = re.search(r"STUB-PWD=(.+)", out)
        seen = os.path.realpath(m.group(1).strip()) if m else "?"
        gcd_m = re.search(r"STUB-GCD=(.+)", out)
        gcd = os.path.realpath(gcd_m.group(1).strip()) if gcd_m else "?"
        # NOT os.path.join(REPO, ".git"): when REPO is itself a linked worktree (e.g. this suite
        # run from inside one), REPO/.git is a FILE (a gitdir pointer), not the shared common dir,
        # so that join silently produced the wrong path and this branch fell through to the
        # generic +cwd: catch-all. Ask git for REPO's real common dir instead — correct whether
        # REPO is the main worktree or a linked one. Confirmed real, 2026-09-17: reproduced by hand
        # (an UNSANDBOXED nested worktree, pre-fix hook) and independently reproduced again by a
        # subagent adversary (Opus) running outside any sandbox.
        # CORRECTION, same day: this join bug is NOT what caused the external adversary's own
        # `pass+root` reports in rounds 1 and 2 — that symptom can only come from the branch below
        # (`seen == REPO`, meaning the hook's OWN worktree-add attempt failed), which this join fix
        # cannot touch. The executor's original comment here claimed otherwise; a follow-up
        # adversary round (Opus, fresh context, outside codex's sandbox) proved it false by
        # reproducing the PRE-fix hook from inside an unsandboxed nested worktree and getting
        # `pass+cwd:...`, never `pass+root`. Two separate, real defects, not one — see the comment
        # on the `+root` branch below for what actually explains rounds 1 and 2.
        repo_git = os.path.realpath(subprocess.run(
            ["git", "-C", REPO, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True).stdout.strip())
        if not os.path.isabs(repo_git):
            repo_git = os.path.realpath(os.path.join(REPO, repo_git))
        if seen == os.path.realpath(REPO):
            # isolation unavailable, un-isolated fallback landed at REPO itself — CORRECT here, not
            # only a degraded case: this branch is EXPECTED (not a regression) when the HOOK'S OWN
            # `git worktree add` call fails, e.g. from inside a write-restricted sandbox that cannot
            # create a second linked worktree. THIS is what actually explains the external
            # adversary's `pass+root` in rounds 1 and 2 (2026-09-17) — not the git-common-dir join
            # fix above, which cannot produce this branch (see the CORRECTION comment there).
            # Observed live: the external adversary reviewing this fix, itself already running from
            # an isolated review copy, hit `Operation not permitted` attempting the nested worktree
            # its own reproduction needed and correctly fell back here. (Likely cause, NOT
            # independently confirmed: its sandbox grants write access only under its own workdir,
            # and git needs to write into the repo's shared .git/worktrees/, outside that — a
            # plausible read of the error, not a verified mechanism.) A THIRD, independent adversary
            # round (subagent, Opus, running outside any sandbox) confirmed the isolation mechanism
            # itself is sound: both a normal run and a hand-built nested-worktree reproduction, run
            # unsandboxed, reliably reach `pass+isolatedroot` — this `+root` fallback is specific to
            # a write-restricted reviewer, not a property of the shipped hook. This suite's own
            # `expect` for case 09 stays `pass+isolatedroot` on purpose — that is what MUST hold in a
            # normal, unsandboxed
            # environment (every real CI run, every ordinary dev checkout), and weakening it would
            # hide a genuine future regression there. A sandboxed reviewer seeing `pass+root`
            # instead is this fallback working as designed, not a new defect to re-report.
            branch += "+root"
        elif gcd == repo_git and seen.startswith(repo_git + os.sep):
            branch += "+isolatedroot"  # isolated review copy, provably under REPO's own git-common-dir
        else:
            branch += "+cwd:" + seen
    if case_name.startswith("14"):
        # The resolved bin must be the WRAPPER interpreter, never a vendor binary — that is the
        # whole point of refusing to read `command -v` as vendor evidence.
        branch += "+wrapperbin" if re.search(r"bin='[^']*/bash'", err) else "+notwrapper"
    if case_name.startswith("11"):
        branch += "+warned" if "not inside any git repo" in err else "+silent"
    if case_name.startswith("20"):
        # Both halves: the break must reach stdout intact, AND the nonzero exit must be called out
        # as a COVERAGE limit rather than swallowed.
        kept = "break ungrounded=2" in out
        warned = "returned a filled 'break'" in err
        branch = ("pass+rcwarned" if kept and warned
                  else ("break-suppressed" if not kept else "pass+rcsilent"))
    if case_name[:2] in ("16", "17", "19"):
        # Two halves, both required: the hook must SAY the partner modified the tree, and it must
        # NAME the path. A warning that cannot name what changed sends the operator to a blank
        # `git status` on an already-dirty tree — the same blindness the content fingerprint exists
        # to remove.
        said = "MODIFIED the repository" in err
        named = ("tracked.txt" in err if case_name[:2] in ("16", "17")
                 else "checkpoint-suite.md" in err)
        if said and named:
            # 16/19: the clean hold is degraded, so stdout must carry a hold and stderr must say so.
            # 17: the break must survive verbatim on stdout.
            if case_name.startswith("17"):
                branch = ("pass+mutation-warned" if "break ungrounded=2" in out
                          else "break-suppressed")
            else:
                branch = ("mutation-unverified"
                          if "Degraded to UNVERIFIED" in err and FILLED_RE.search(out)
                          else "mutation-not-degraded")
        else:
            branch += "+mutation-missed" if not said else "+mutation-unnamed"
    if case_name.startswith("22") or case_name.startswith("23"):
        branch += "+codexwarned" if "sets no sandbox mode" in err else "+codexsilent"
    if case_name.startswith("24"):
        contaminated = "MODIFIED the repository" in err
        branch = "pass+isolated-immune" if (branch == "pass" and not contaminated) \
            else "FALSE-POSITIVE-" + branch
    return branch


def suite(hook, workdir):
    rows = []
    fakebin = os.path.join(workdir, "fakebin")
    os.makedirs(fakebin, exist_ok=True)
    codex_path = os.path.join(fakebin, "codex")
    with open(codex_path, "w") as f:
        f.write(CODEX_STUB)
    os.chmod(codex_path, 0o755)
    for name, transcript, env_extra, cwd, expect in CASES:
        env = dict(os.environ)
        env.pop("GOAL_ADVERSARY_ACTIVE", None)
        env.pop("GOAL_ADVERSARY_CMD", None)
        env.pop("GOAL_CONFIG_PATH", None)
        env["PATH"] = fakebin + os.pathsep + env.get("PATH", "")
        stubs = {"STUB_TMPDIR": STUB_TMPDIR, "STUB_PWD": STUB_PWD, "STUB_WRAP": STUB_WRAP,
                 "STUB_MUTATE": STUB_MUTATE, "STUB_MUTATE_BREAK": STUB_MUTATE_BREAK,
                 "STUB_CLEAN": STUB_CLEAN, "STUB_MUTATE_RUNSTATE": STUB_MUTATE_RUNSTATE,
                 "STUB_BREAK_RC": STUB_BREAK_RC, "STUB_HOLD_RC": STUB_HOLD_RC,
                 "STUB_CONCURRENT_COMMIT": STUB_CONCURRENT_COMMIT}
        if transcript in stubs:
            stub = os.path.join(workdir, "stub-" + name + ".sh")
            with open(stub, "w") as f:
                f.write(stubs[transcript])
            env["GOAL_ADVERSARY_CMD"] = "bash " + stub
        elif transcript is not None:
            fixture = os.path.join(workdir, "out-" + name + ".txt")
            with open(fixture, "w") as f:
                f.write(transcript)
            env["GOAL_ADVERSARY_CMD"] = "cat " + fixture
        env.update(env_extra)
        if cwd == "WORKDIR":
            run_cwd = workdir
        elif cwd == "MUTREPO":
            run_cwd = make_mutrepo(workdir, name)
        else:
            run_cwd = cwd or REPO
        res = subprocess.run(["bash", hook], input=PAYLOAD, capture_output=True,
                             text=True, env=env, cwd=run_cwd, timeout=30)
        rows.append((name, classify(res, name), expect))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hook", nargs="?", default=DEFAULT_HOOK)
    ap.add_argument("--compare", metavar="OTHER_HOOK")
    ap.add_argument("--expected", default="", help="case-name prefixes whose diff is INTENDED")
    a = ap.parse_args()

    expected = [s.strip() for s in a.expected.split(",") if s.strip()]
    with tempfile.TemporaryDirectory() as workdir:
        rows = suite(a.hook, workdir)
        other = suite(a.compare, workdir) if a.compare else None

    failures = 0
    for i, (name, branch, expect) in enumerate(rows):
        flag = ""
        if branch != expect:
            flag = "   <-- EXPECT FAILED: wanted %s" % expect
            failures += 1
        if other and other[i][1] != branch:
            tag = "EXPECTED-DIFF" if any(name.startswith(p) for p in expected) else "DIFFERS"
            flag += "   <-- %s: %s" % (tag, other[i][1])
        print("%-28s %-28s%s" % (name, branch, flag))

    rc = 0
    if failures:
        print("\n%d expect assertion(s) failed" % failures)
        rc = 1
    if other:
        diffs = [r[0] for r, o in zip(rows, other) if r[1] != o[1]]
        unexpected = [d for d in diffs if not any(d.startswith(p) for p in expected)]
        if diffs:
            print("\n%d branch(es) changed vs compare: %s" % (len(diffs), ", ".join(diffs)))
        if unexpected:
            print("REGRESSION: %d unexpected: %s" % (len(unexpected), ", ".join(unexpected)))
            rc = 1
        elif not failures:
            print("\nparity OK — %d branches, %d intended change(s)" % (len(rows), len(diffs)))
    return rc


if __name__ == "__main__":
    sys.exit(main())

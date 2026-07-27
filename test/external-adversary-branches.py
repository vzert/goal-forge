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
  to (08) and runs from the repo root when the invocation cwd is inside one (09); both sandbox
  failures had come back disguised as ungrounded/UNVERIFIED findings. Host-side only: outside any
  git repo there is no root to resolve, so that branch warns on stderr instead of relocating (11),
  and a partner sandbox denying writes the hook's process can make (the v0.19.1 contra-dato) is
  out of the hook's reach entirely.

    python3 test/external-adversary-branches.py
    python3 test/external-adversary-branches.py --compare <pre-edit.sh> --expected 02,05,08,09,11
"""
import argparse, os, re, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "external-adversary.sh")

MODEL = "[ADVERSARY-MODEL: GPT-5 / gpt-5]"
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
    ("09-invoked-from-subdir", "STUB_PWD", {}, os.path.join(REPO, "test"), "pass+root"),
    ("10-recursion-guard", MODEL + "\n" + HOLD + "\n", {"GOAL_ADVERSARY_ACTIVE": "1"},
     None, "recursion"),
    # Outside ANY git repo there is no root to resolve (the recorded Fase 1 incident class:
    # codex refusing a scratchpad as untrusted) — the hook must warn on stderr, not fix it.
    ("11-outside-any-repo", "STUB_PWD", {}, "WORKDIR", "pass+warned"),
]

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
    if case_name.startswith("08"):
        branch += "+tmpdir-rw" if "STUB-TMPDIR-WRITABLE=yes" in out else "+tmpdir-ro"
    if case_name.startswith("09"):
        m = re.search(r"STUB-PWD=(.+)", out)
        seen = os.path.realpath(m.group(1).strip()) if m else "?"
        branch += "+root" if seen == os.path.realpath(REPO) else "+cwd:" + seen
    if case_name.startswith("11"):
        branch += "+warned" if "not inside any git repo" in err else "+silent"
    return branch


def suite(hook, workdir):
    rows = []
    for name, transcript, env_extra, cwd, expect in CASES:
        env = dict(os.environ)
        env.pop("GOAL_ADVERSARY_ACTIVE", None)
        env.pop("GOAL_ADVERSARY_CMD", None)
        env.pop("GOAL_CONFIG_PATH", None)
        if transcript == "STUB_TMPDIR" or transcript == "STUB_PWD":
            stub = os.path.join(workdir, "stub-" + name + ".sh")
            with open(stub, "w") as f:
                f.write(STUB_TMPDIR if transcript == "STUB_TMPDIR" else STUB_PWD)
            env["GOAL_ADVERSARY_CMD"] = "bash " + stub
        elif transcript is not None:
            fixture = os.path.join(workdir, "out-" + name + ".txt")
            with open(fixture, "w") as f:
                f.write(transcript)
            env["GOAL_ADVERSARY_CMD"] = "cat " + fixture
        env.update(env_extra)
        run_cwd = workdir if cwd == "WORKDIR" else (cwd or REPO)
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

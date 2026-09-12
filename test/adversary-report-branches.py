#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/report-adversary-writes.sh (the Stop-side reporter).

Same shape as the other suites: one row per branch, `expect` asserted on every run, exit non-zero on
an assertion failure or an unexpected `--compare` diff.

Fully hermetic: no git, no network, no Claude Code. Each case writes a synthetic findings file the
way `watch-adversary-writes.sh` would, feeds the hook a synthetic `Stop` payload, and classifies.

WHY THIS HOOK EXISTS, because it is the thing the suite is really pinning. In 0.44.0 the
SubagentStop hook both measured and emitted. Measured on 2026-09-12 in a real session
(3-tier-memory, 035edc21): a SubagentStop hook's output is delivered to the SUBAGENT that just
stopped — it lands in that agent's transcript as `isSidechain: true`, and appears ZERO times in the
executor's. The message was written in the second person for the executor ("YOU edited under an
in-flight verifier ... decide what to keep or revert"), so the adversary that received it recorded
that it "misread it as a cue that I had become the executor" and wrote to five files in the
repository under review. Stop output, by contrast, lands in the executor's own transcript with
`isSidechain: false` — verified in that same file. Hence the split: measure there, report here.

Two assertions carry that lesson and must not be softened:
  * the message opens with an explicit AUDIENCE line that disarms an adversary reading it in a
    transcript (case 08) — the executor's transcript is exactly what an adversary reads for its
    principle-4 check, so this text will end up in front of one;
  * a finding is reported ONCE and the file is deleted (case 09), or every later turn re-reports a
    stale finding as if it were new.

    python3 test/adversary-report-branches.py
    python3 test/adversary-report-branches.py --compare <pre-edit.sh> --expected 08
"""
import argparse, json, os, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "report-adversary-writes.sh")

SESSION = "sess-abc"

ONE_ROUND = """ts=2026-09-12T16:58:22Z agent=subagent_xyz repo=/tmp/repo
path CHANGELOG.md
path plugins/x/bin/tool.sh
end
"""

TWO_ROUNDS = ONE_ROUND + """ts=2026-09-12T17:10:03Z agent=subagent_xyz repo=/tmp/repo
path CHANGELOG.md
path new-file.md
end
"""

MALFORMED = """this line is not a record at all
ts=broken
path CHANGELOG.md
   garbage with no prefix
path
end
"""

NO_PATHS = """ts=2026-09-12T16:58:22Z agent=subagent_xyz repo=/tmp/repo
end
"""


def payload(session_id=SESSION, drop_session=False, raw=None):
    if raw is not None:
        return raw
    d = {"transcript_path": "/nonexistent/t.jsonl", "cwd": "/tmp",
         "permission_mode": "default", "hook_event_name": "Stop"}
    if not drop_session:
        d["session_id"] = session_id
    return json.dumps(d)


# name, findings file content (None -> no file), findings filename stem, payload kwargs, expected
CASES = [
    # The normal case: one round, two paths, reported and named.
    ("01-one-round", ONE_ROUND, SESSION, {}, "reported:CHANGELOG.md,plugins/x/bin/tool.sh|rounds=1"),
    # Two rounds accumulate; paths are deduplicated across them and the round count is stated.
    ("02-two-rounds", TWO_ROUNDS, SESSION, {},
     "reported:CHANGELOG.md,new-file.md,plugins/x/bin/tool.sh|rounds=2"),
    # No findings file at all: the overwhelmingly common case. Silence, every turn, forever.
    ("03-no-findings", None, SESSION, {}, "silent"),
    # A findings file belonging to ANOTHER session must not be picked up — that is the whole point
    # of keying by session_id rather than dropping one file in a shared tmp dir.
    ("04-other-session", ONE_ROUND, "sess-OTHER", {}, "silent"),
    # Garbage in the file must be skipped, not fatal: a reporter that dies on bad input is a
    # reporter that stays silent about a real finding sitting in the same file.
    ("05-malformed-lines", MALFORMED, SESSION, {}, "reported:CHANGELOG.md|rounds=1"),
    # A record with no `path` lines names nothing, so there is nothing to report.
    ("06-record-without-paths", NO_PATHS, SESSION, {}, "silent"),
    # Fail-open on a payload that is not JSON at all.
    ("07-unparseable-payload", ONE_ROUND, SESSION, {"raw": "not json at all"}, "silent"),
    # THE audience assertion. The executor's transcript is what an adversary reads for its
    # principle-4 ask check, so this text lands in front of one. It must say who it is for AND say
    # that reading it changes nothing about an adversary's role.
    ("08-audience-line", ONE_ROUND, SESSION, {}, "reported:CHANGELOG.md,plugins/x/bin/tool.sh|rounds=1"),
    # Reported once: the file is consumed, so a second Stop in the same session is silent.
    ("09-reported-once", ONE_ROUND, SESSION, {}, "silent-on-second"),
    # No session id in the payload: nothing to key on, so nothing to read. Fail-open.
    ("10-no-session-id", ONE_ROUND, SESSION, {"drop_session": True}, "silent"),
]


def classify(res, name, findings_path):
    out = res.stdout.strip()
    if not out:
        return "silent"
    try:
        msg = json.loads(out).get("systemMessage") or ""
    except Exception:
        return "malformed-json"
    paths = sorted(ln.strip()[2:] for ln in msg.splitlines() if ln.strip().startswith("- "))
    if not paths:
        return "reported-unnamed"
    rounds = "?"
    for token in msg.split():
        if token.startswith("(") and token[1:].isdigit():
            rounds = token[1:]
            break
    tag = "reported:" + ",".join(paths) + "|rounds=" + rounds

    if name.startswith("08"):
        # Both halves. Naming the audience is not enough on its own: 0.44.0's message also had an
        # implicit audience and an adversary still took it as its own instruction. The disarming
        # sentence is what makes it inert.
        named = msg.lstrip().upper().startswith("ADDRESSED TO THE EXECUTOR")
        disarms = ("you verify, you do not repair" in msg.lower()
                   and "not addressed to you" in msg.lower())
        if not named:
            return "reported-no-audience-line"
        if not disarms:
            return "reported-audience-not-disarming"
    if os.path.isfile(findings_path):
        # Not deleted: every later turn would re-report the same finding as if it were new.
        return tag + "|NOT-CONSUMED"
    return tag


def suite(hook, workdir):
    rows = []
    for name, body, stem, kw, expect in CASES:
        tmp = tempfile.mkdtemp(prefix="tmp-" + name + "-", dir=workdir)
        snap = os.path.join(tmp, "goalspec-adversary-snap")
        os.makedirs(snap)
        findings = os.path.join(snap, stem + ".findings")
        if body is not None:
            with open(findings, "w") as f:
                f.write(body)
        env = dict(os.environ)
        env["TMPDIR"] = tmp
        # classify() looks for THIS session's file; case 04 writes another session's.
        own = os.path.join(snap, SESSION + ".findings")
        res = subprocess.run(["bash", hook], input=payload(**kw), capture_output=True,
                             text=True, env=env, cwd=tmp, timeout=30)
        if name.startswith("09"):
            res = subprocess.run(["bash", hook], input=payload(**kw), capture_output=True,
                                 text=True, env=env, cwd=tmp, timeout=30)
            rows.append((name, "silent-on-second" if not res.stdout.strip() else "RE-REPORTED",
                         expect))
            continue
        rows.append((name, classify(res, name, own), expect))
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
        print("%-34s %-56s%s" % (name, branch, flag))

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

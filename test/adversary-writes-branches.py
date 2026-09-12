#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/watch-adversary-writes.sh (the subagent read-only rail).

Same shape as the other suites: one row per branch, `expect` asserted on every run, exit non-zero on
an assertion failure or an unexpected `--compare` diff.

Hermetic apart from git: no network, no credential, no Claude Code. Each case builds a throwaway git
repo, feeds the hook a synthetic SubagentStart payload, optionally mutates the repo the way a
misbehaving adversary would, then feeds it the matching SubagentStop payload and classifies what it
said. TMPDIR is redirected per case so the snapshot files never collide and never touch the project.

The discriminating case is 02-appends-to-dirty-file. The tree under review is almost always ALREADY
dirty — it IS the uncommitted work being reviewed — so an adversary that appends one line to an
already-modified file leaves the byte-identical " M tracked.txt" porcelain line before and after. A
`git status` fingerprint passes that case while the repair goes unseen; only hashing content catches
it. 01 is the control that keeps this from being a mere dirty-tree detector.

    python3 test/adversary-writes-branches.py
    python3 test/adversary-writes-branches.py --compare <pre-edit.sh> --expected 02
"""
import argparse, json, os, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "watch-adversary-writes.sh")

GIT = ["git", "-c", "user.email=suite@example.invalid", "-c", "user.name=suite"]


def payload(event, cwd, agent_type="goalspec:goal-adversary", agent_id="subagent_xyz789"):
    d = {"session_id": "sess-abc", "transcript_path": "/nonexistent/t.jsonl", "cwd": cwd,
         "permission_mode": "default", "hook_event_name": event, "agent_id": agent_id,
         "agent_type": agent_type}
    if event == "SubagentStop":
        d["last_assistant_message"] = "[ADVERSARY-VERDICT: hold ungrounded=0 ...]"
    return json.dumps(d)


def make_repo(workdir, name):
    """A repo in the state a real review runs against: one tracked file ALREADY modified, plus
    gitignored .goalspec/ run state."""
    root = tempfile.mkdtemp(prefix="repo-" + name + "-", dir=workdir)
    os.makedirs(os.path.join(root, ".goalspec"))
    subprocess.run(GIT + ["init", "-q", root], check=True, capture_output=True)
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("/.goalspec/\n")
    with open(os.path.join(root, "tracked.txt"), "w") as f:
        f.write("committed line\n")
    subprocess.run(GIT + ["-C", root, "add", "-A"], check=True, capture_output=True)
    subprocess.run(GIT + ["-C", root, "commit", "-qm", "base"], check=True, capture_output=True)
    with open(os.path.join(root, "tracked.txt"), "a") as f:
        f.write("uncommitted work under review\n")
    with open(os.path.join(root, ".goalspec", "checkpoint-suite.md"), "w") as f:
        f.write("# checkpoint\n\n## Live goal-spec\n- criterion 1\n")
    return root


# --- what each case does to the repo BETWEEN start and stop ---
def noop(root):
    pass


def append_dirty(root):
    """THE discriminating mutation: appends to a file that was already modified, so `git status` is
    identical before and after."""
    with open(os.path.join(root, "tracked.txt"), "a") as f:
        f.write("while reviewing I noticed a typo and fixed it\n")


def new_file(root):
    with open(os.path.join(root, "adversary-notes.md"), "w") as f:
        f.write("my fixes\n")


def touch_runstate(root):
    with open(os.path.join(root, ".goalspec", "checkpoint-suite.md"), "a") as f:
        f.write("- round 9: reconciled by the adversary\n")


def stage_it(root):
    """Staging alone moves the path out of `ls-files -m`; the staged-diff hash is what catches it."""
    subprocess.run(GIT + ["-C", root, "add", "tracked.txt"], check=True, capture_output=True)


def revert_it(root):
    """Changed and changed back: correctly NOT a finding — nothing was left modified."""
    p = os.path.join(root, "tracked.txt")
    orig = open(p).read()
    with open(p, "a") as f:
        f.write("temporary\n")
    with open(p, "w") as f:
        f.write(orig)


# name, mutation, agent_type, expected branch
CASES = [
    # Control: the tree is dirty the whole time and the adversary writes nothing. Must stay silent,
    # or the rail fires on every honest review and gets ignored.
    ("01-clean-run-dirty-repo", noop, None, "silent"),
    # THE discriminating case — invisible to a `git status` fingerprint.
    ("02-appends-to-dirty-file", append_dirty, None, "reported:tracked.txt"),
    ("03-creates-new-file", new_file, None, "reported:adversary-notes.md"),
    # .goalspec/ is gitignored, so `ls-files --exclude-standard` never lists it; hashed explicitly.
    ("04-touches-gitignored-runstate", touch_runstate, None, "reported:.goalspec/checkpoint-suite.md"),
    # `git add` moves the path out of the unstaged scan — the staged-diff hash is the only thing
    # that still sees it. The index line carries no path of its own, so it must be NAMED, not
    # stripped: the first run of this case reported a bare 40-char hash as a modified file.
    ("05-stages-the-change", stage_it, None,
     "reported:(the git index: content was staged or unstaged),tracked.txt"),
    # Changed and changed back is not a finding, and saying so is the point: the rail reports what
    # was LEFT modified, not every transient write.
    ("06-changed-and-reverted", revert_it, None, "silent"),
    # Not our subagent: the agent_type re-check must hold even if a harness matches loosely.
    ("07-other-subagent", append_dirty, "Explore", "silent"),
    # The fabricated form that slipped a bare substring check once, in this project, on this exact
    # anchor. It must not match.
    ("08-lookalike-agent-type", append_dirty, "not-goal-adversary-example", "silent"),
    # No SubagentStart was seen (installed mid-run, event skipped). Claiming "no writes detected"
    # from a measurement that never ran is the broken instrument this rail is about, so: silent.
    ("09-stop-without-start", append_dirty, None, "silent"),
]


def run_case(hook, workdir, name, mutate, agent_type, skip_start):
    root = make_repo(workdir, name)
    tmp = tempfile.mkdtemp(prefix="tmp-" + name + "-", dir=workdir)
    env = dict(os.environ)
    env["TMPDIR"] = tmp
    kw = {"agent_type": agent_type} if agent_type else {}

    if not skip_start:
        subprocess.run(["bash", hook, "start"], input=payload("SubagentStart", root, **kw),
                       capture_output=True, text=True, env=env, cwd=root, timeout=30)
    mutate(root)
    return subprocess.run(["bash", hook, "stop"], input=payload("SubagentStop", root, **kw),
                          capture_output=True, text=True, env=env, cwd=root, timeout=30)


def classify(res):
    out = res.stdout.strip()
    if not out:
        return "silent"
    try:
        msg = json.loads(out).get("systemMessage") or ""
    except Exception:
        return "malformed-json"
    if "repository content changed" not in msg:
        return "reported-without-the-claim"
    # Both halves are required: saying a change happened AND naming the path. A warning that cannot
    # name what changed sends the operator to a blank `git status` on an already-dirty tree, which is
    # the blindness the content fingerprint exists to remove.
    paths = [ln.strip()[2:] for ln in msg.splitlines() if ln.strip().startswith("- ")]
    if not paths:
        return "reported-unnamed"
    # Both readings must be offered — an accusation the executor cannot have caused is a rail that
    # gets argued with instead of acted on.
    if "YOU edited under an in-flight verifier" not in msg:
        return "reported-one-reading-only:" + ",".join(sorted(paths))
    return "reported:" + ",".join(sorted(paths))


def suite(hook, workdir):
    rows = []
    for name, mutate, agent_type, expect in CASES:
        res = run_case(hook, workdir, name, mutate, agent_type,
                       skip_start=name.startswith("09"))
        rows.append((name, classify(res), expect))
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
        print("%-34s %-42s%s" % (name, branch, flag))

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

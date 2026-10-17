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
import argparse, json, os, stat, subprocess, sys, tempfile
import tmp_cleanup  # this run's own TMPDIR, removed at exit (p-1a5a4e9828)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import expected_check  # noqa: E402 — the --expected check every --compare suite shares

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "watch-adversary-writes.sh")
# The SessionEnd half of the run directory (0.62.0). Always the current one: --compare swaps the
# watcher, and the cleanup cases build their own directories, so they never depend on it.
CLEANUP_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "cleanup-run-dir.sh")
PLUGIN = os.path.join(REPO, "plugins", "goalspec")

GIT = ["git", "-c", "user.email=suite@example.invalid", "-c", "user.name=suite"]


def payload(event, cwd, agent_type="goalspec:goal-adversary", agent_id="subagent_xyz789",
            session="sess-abc"):
    d = {"session_id": session, "transcript_path": "/nonexistent/t.jsonl", "cwd": cwd,
         "permission_mode": "default", "hook_event_name": event, "agent_id": agent_id,
         "agent_type": agent_type}
    if session is None:
        del d["session_id"]
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
    ("02-appends-to-dirty-file", append_dirty, None, "recorded:tracked.txt"),
    ("03-creates-new-file", new_file, None, "recorded:adversary-notes.md"),
    # .goalspec/ is gitignored, so `ls-files --exclude-standard` never lists it; hashed explicitly.
    ("04-touches-gitignored-runstate", touch_runstate, None, "recorded:.goalspec/checkpoint-suite.md"),
    # `git add` moves the path out of the unstaged scan — the staged-diff hash is the only thing
    # that still sees it. The index line carries no path of its own, so it must be NAMED, not
    # stripped: the first run of this case reported a bare 40-char hash as a modified file.
    ("05-stages-the-change", stage_it, None,
     "recorded:(the git index: content was staged or unstaged),tracked.txt"),
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
    # RE-ARM (0.44.1). The agent stops, then keeps going and writes again. 0.44.0 DELETED the
    # snapshot on the first stop, so everything after it was unmeasured — which is precisely how the
    # real 2026-09-12 writes escaped: they landed after the first stop and no firing could see them.
    # Two rounds must be recorded, naming both paths.
    ("10-second-stop-after-more-writes", append_dirty, None,
     "recorded:adversary-notes.md,tracked.txt|rounds=2"),
    # --- 0.62.0 (p-42d7c57137): one run directory per session, owner and mode checked. Measured on
    # a 4-developer VPS: the old fixed ${TMPDIR:-/tmp}/goalspec-adversary-snap belonged to the
    # first user, and the other three hit `Permission denied` on 361 of 361 adversary runs.
    # No session id: nothing written anywhere. The old hook keyed the findings by the agent id.
    ("11-no-session-id-writes-nothing", append_dirty, None, "silent|no-files"),
    # A directory under the session's name that is not ours to use (mode 0755 stands in for another
    # user's: a suite cannot chown without root). Nothing written in it, and a failure note left
    # for the Stop reporter. The old hook ignored it and wrote to the shared directory.
    ("12-run-dir-wrong-mode-refused", append_dirty, None, "refused|noted"),
    # A symlink planted under the session's name, pointing at a 0700 directory: never followed.
    ("13-run-dir-symlink-refused", append_dirty, None, "refused|noted"),
    # Two sessions sharing one TMPDIR: each records in its own 0700 directory, nothing shared.
    ("14-two-sessions-own-dirs", append_dirty, None, "own-dirs-0700"),
]

# SessionEnd cleanup (cleanup-run-dir.sh): name, setup, expected.
CLEANUP_CASES = [
    ("15-cleanup-removes-own-dir", "own", "removed"),
    ("16-cleanup-keeps-wrong-mode-dir", "mode755", "kept"),
    ("17-cleanup-keeps-symlink-and-target", "symlink", "kept"),
    ("18-cleanup-keeps-other-session-dir", "other", "kept"),
]

# run_dir.py driven directly (a suite cannot be another uid, and must not write to the real /tmp or
# HOME): name, expected. Each runs the library of the plugin under test in a child Python.
UNIT_CASES = [
    # A relative TMPDIR / XDG_STATE_HOME / HOME is ignored: nothing relative to the cwd, ever.
    ("19-relative-env-never-used", "absolute-only"),
    # The owner check, with getuid() patched to another uid: refused and noted.
    ("20-other-owner-refused", "refused|noted"),
    # A temp root that is neither sticky nor private (another user could swap the directory after
    # the check): refused and noted.
    ("21-shared-non-sticky-parent-refused", "refused|noted"),
    # A TMPDIR that is a symlink sitting in a shared non-sticky directory, pointing at a private
    # one: another user could re-point the link, so the whole real path is checked, and refused.
    ("23-symlinked-tmpdir-in-shared-dir-refused", "refused|noted"),
    # XDG_STATE_HOME is a regular file: the note falls back to ~/.local/state (HOME redirected).
    ("22-failure-note-fallback", "noted-in-fallback"),
]

UNIT_SRC = r"""
import os, stat, sys, json
sys.path.insert(0, sys.argv[1])
import run_dir
case, tmp = sys.argv[2], sys.argv[3]
if case == "19":
    os.chdir(tmp)
    os.environ.update(TMPDIR="rel-tmp", XDG_STATE_HOME="rel-state", HOME="rel-home")
    p = run_dir.path_for("sess-abc")
    notes = run_dir._failures_paths("sess-abc")
    ok = p.startswith("/") and all(n.startswith("/") for n in notes)
    print("absolute-only" if ok and not os.listdir(tmp) else "relative:%s|%s" % (p, notes))
elif case == "20":
    # A sticky parent, so only the owner check of the directory itself can refuse it.
    root = os.path.join(tmp, "sticky")
    os.mkdir(root)
    os.chmod(root, 0o1700)
    os.environ.update(TMPDIR=root, XDG_STATE_HOME=os.path.join(tmp, "state"))
    real = os.getuid()
    d = os.path.join(root, "goalspec-run-sess-abc")
    os.mkdir(d, 0o700)
    os.getuid = lambda: real + 1
    # Isolate the owner check: with getuid patched, every ancestor the path check walks would look
    # foreign too (cases 21 and 23 cover that check).
    run_dir.check_parent = lambda parent: ""
    got = run_dir.ensure("sess-abc", "suite")
    note = os.path.isfile(os.path.join(tmp, "state", "goalspec", "run-dir-failed-sess-abc"))
    print(("USED" if got else "refused") + "|" + ("noted" if note else "no-note"))
elif case == "21":
    root = os.path.join(tmp, "shared")
    os.mkdir(root)
    os.chmod(root, 0o777)
    os.environ.update(TMPDIR=root, XDG_STATE_HOME=os.path.join(tmp, "state"))
    got = run_dir.ensure("sess-abc", "suite")
    note = os.path.isfile(os.path.join(tmp, "state", "goalspec", "run-dir-failed-sess-abc"))
    print(("USED" if got else "refused") + "|" + ("noted" if note else "no-note"))
elif case == "23":
    shared = os.path.join(tmp, "shared")
    os.mkdir(shared)
    os.chmod(shared, 0o777)
    private = os.path.join(shared, "private")
    os.mkdir(private, 0o700)
    link = os.path.join(tmp, "link")  # tmp itself is private: the link is ours, its target is not safe
    os.symlink(private, link)
    os.environ.update(TMPDIR=link, XDG_STATE_HOME=os.path.join(tmp, "state"))
    got = run_dir.ensure("sess-abc", "suite")
    note = os.path.isfile(os.path.join(tmp, "state", "goalspec", "run-dir-failed-sess-abc"))
    print(("USED" if got else "refused") + "|" + ("noted" if note else "no-note"))
elif case == "22":
    bad = os.path.join(tmp, "xdg-is-a-file")
    open(bad, "w").close()
    home = os.path.join(tmp, "home")
    os.mkdir(home)
    os.environ.update(TMPDIR=tmp, XDG_STATE_HOME=bad, HOME=home)
    run_dir.note_failure("sess-abc", "suite", "why")
    fb = os.path.join(home, ".local", "state", "goalspec", "run-dir-failed-sess-abc")
    print("noted-in-fallback" if os.path.isfile(fb) and run_dir.take_failures("sess-abc")
          and not os.path.exists(fb) else "lost")
"""


def unit_case(lib, workdir, name):
    tmp = tempfile.mkdtemp(prefix="tmp-" + name + "-", dir=workdir)
    r = subprocess.run([sys.executable, "-I", "-c", UNIT_SRC, lib, name[:2], tmp],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip() or "ERROR:" + r.stderr.strip()[-120:]


def run_case(hook, workdir, name, mutate, agent_type, skip_start, tmp=None, session="sess-abc"):
    root = make_repo(workdir, name)
    tmp = tmp or tempfile.mkdtemp(prefix="tmp-" + name + "-", dir=workdir)
    env = dict(os.environ)
    env["TMPDIR"] = tmp
    # Failure notes go to this user's state directory: keep them inside the case.
    env["XDG_STATE_HOME"] = os.path.join(tmp, "state")
    env["CLAUDE_PLUGIN_ROOT"] = os.path.join(REPO, "plugins", "goalspec")  # where a copied hook finds hooks/lib
    kw = {"agent_type": agent_type} if agent_type else {}
    kw["session"] = session

    if not skip_start:
        subprocess.run(["bash", hook, "start"], input=payload("SubagentStart", root, **kw),
                       capture_output=True, text=True, env=env, cwd=root, timeout=30)
    mutate(root)
    res = subprocess.run(["bash", hook, "stop"], input=payload("SubagentStop", root, **kw),
                         capture_output=True, text=True, env=env, cwd=root, timeout=30)
    return res, tmp, root, env, kw


def classify(res, findings_dir, session="sess-abc"):
    """0.44.1: a `stop` that EMITS is the bug. It must be silent on stdout and leave the finding in
    the per-session findings file instead.

    Why this is the discriminating assertion: a SubagentStop hook's output is delivered to the
    SUBAGENT that just stopped, not to the executor (measured 2026-09-12, real session — it lands in
    the agent's own transcript as `isSidechain: true` and appears ZERO times in the executor's). The
    0.44.0 message was written in the second person for the executor, so the adversary read it as a
    role change and wrote to five files. Emitting here is not a cosmetic defect; it is the defect."""
    out = res.stdout.strip()
    if out:
        return "EMITTED-TO-SUBAGENT"
    # Both layouts, so --compare against a pre-0.62.0 watcher measures behaviour, not a path rename.
    fpath = os.path.join(findings_dir, "goalspec-run-" + session, "findings")
    if not os.path.isfile(fpath):
        fpath = os.path.join(findings_dir, "goalspec-adversary-snap", session + ".findings")
    if not os.path.isfile(fpath):
        return "silent"
    body = open(fpath).read()
    paths = sorted({ln[5:].strip() for ln in body.splitlines() if ln.startswith("path ")})
    if not paths:
        return "recorded-unnamed"
    rounds = body.count("ts=")
    tag = "recorded:" + ",".join(paths)
    return tag + ("" if rounds == 1 else "|rounds=%d" % rounds)


def files_under(tmp):
    """Every file the hook left under TMPDIR, the state directory included."""
    out = []
    for dp, _, fns in os.walk(tmp):
        out += [os.path.relpath(os.path.join(dp, f), tmp) for f in fns]
    return sorted(out)


def run_dir_case(hook, workdir, name, mutate, agent_type):
    tmp = tempfile.mkdtemp(prefix="tmp-" + name + "-", dir=workdir)
    if name.startswith("11"):
        res, *_ = run_case(hook, workdir, name, mutate, agent_type, False, tmp=tmp, session=None)
        if res.stdout.strip():
            return "EMITTED-TO-SUBAGENT"
        # goalspec's own names and the state directory only: git on macOS can leave its xcrun
        # cache in a fresh TMPDIR.
        left = [f for f in files_under(tmp) if f.startswith(("goalspec", "state" + os.sep))]
        return "silent|no-files" if not left else "files-left:" + ",".join(left)
    if name.startswith("14"):
        for sess in ("sess-A", "sess-B"):
            run_case(hook, workdir, name + sess, mutate, agent_type, False, tmp=tmp, session=sess)
        tags = []
        for sess in ("sess-A", "sess-B"):
            d = os.path.join(tmp, "goalspec-run-" + sess)
            ok = (os.path.isdir(d) and not os.path.islink(d)
                  and stat.S_IMODE(os.lstat(d).st_mode) == 0o700
                  and os.path.isfile(os.path.join(d, "findings")))
            tags.append(ok)
        if all(tags) and not os.path.exists(os.path.join(tmp, "goalspec-adversary-snap")):
            return "own-dirs-0700"
        return "shared-or-missing:" + ",".join(files_under(tmp))
    # 12 / 13: a directory under the session's name that must not be used.
    d = os.path.join(tmp, "goalspec-run-sess-abc")
    target = d
    if name.startswith("12"):
        os.mkdir(d)
        os.chmod(d, 0o755)
    else:
        target = tempfile.mkdtemp(prefix="planted-", dir=workdir)  # 0700, ours, elsewhere
        os.symlink(target, d)
    res, *_ = run_case(hook, workdir, name, mutate, agent_type, False, tmp=tmp)
    if res.stdout.strip():
        return "EMITTED-TO-SUBAGENT"
    used = os.listdir(target)
    if used:
        return "USED:" + ",".join(sorted(used))
    # Only goalspec's own names count: git on macOS can leave its xcrun cache in a fresh TMPDIR.
    others = [f for f in files_under(tmp) if f.startswith("goalspec")]
    if others:
        return "wrote-elsewhere:" + ",".join(others)
    note = os.path.join(tmp, "state", "goalspec", "run-dir-failed-sess-abc")
    return "refused|noted" if os.path.isfile(note) else "refused|no-note"


def cleanup_case(workdir, name, setup, cleanup_hook=CLEANUP_HOOK):
    tmp = tempfile.mkdtemp(prefix="tmp-" + name + "-", dir=workdir)
    env = dict(os.environ, TMPDIR=tmp, XDG_STATE_HOME=os.path.join(tmp, "state"),
               CLAUDE_PLUGIN_ROOT=os.path.join(REPO, "plugins", "goalspec"))
    d = os.path.join(tmp, "goalspec-run-sess-abc")
    target = d
    if setup == "symlink":
        target = tempfile.mkdtemp(prefix="planted-", dir=workdir)
        os.symlink(target, d)
    elif setup == "other":
        d = target = os.path.join(tmp, "goalspec-run-sess-OTHER")
        os.mkdir(d, 0o700)
    else:
        os.mkdir(d, 0o700)
        if setup == "mode755":
            os.chmod(d, 0o755)
    with open(os.path.join(target, "findings"), "w") as f:
        f.write("ts=1\npath x\nend\n")
    subprocess.run(["bash", cleanup_hook], input=json.dumps({"session_id": "sess-abc",
                   "hook_event_name": "SessionEnd", "reason": "other"}),
                   capture_output=True, text=True, env=env, timeout=30)
    gone = not os.path.lexists(d)
    target_kept = os.path.isfile(os.path.join(target, "findings"))
    if setup == "own":
        return "removed" if gone else "kept"
    if setup == "symlink":
        return "kept" if (os.path.islink(d) and target_kept) else "followed-or-removed"
    return "kept" if (not gone and target_kept) else "removed"


def suite(hook, workdir, plugin=PLUGIN):
    """`plugin` supplies the cleanup hook and the run_dir library; --selftest points it at a mutant
    copy, --compare swaps only the watcher."""
    rows = []
    for name, mutate, agent_type, expect in CASES:
        if name[:2] in ("11", "12", "13", "14"):
            rows.append((name, run_dir_case(hook, workdir, name, mutate, agent_type), expect))
            continue
        res, tmp, root, env, kw = run_case(hook, workdir, name, mutate, agent_type,
                                           skip_start=name.startswith("09"))
        if name.startswith("10"):
            new_file(root)
            res = subprocess.run(["bash", hook, "stop"], input=payload("SubagentStop", root, **kw),
                                 capture_output=True, text=True, env=env, cwd=root, timeout=30)
        rows.append((name, classify(res, tmp), expect))
    for name, setup, expect in CLEANUP_CASES:
        rows.append((name, cleanup_case(workdir, name, setup,
                                        os.path.join(plugin, "hooks", "cleanup-run-dir.sh")), expect))
    for name, expect in UNIT_CASES:
        rows.append((name, unit_case(os.path.join(plugin, "hooks", "lib"), workdir, name), expect))
    return rows


# --selftest: break run_dir.py in a copy of the plugin and require the case written for it to turn.
# The cleanup and unit cases have no pre-0.62.0 baseline to --compare against, so this is their proof.
LIB_MUTATIONS = [
    ("cleanup removes without the check", "    p = existing(session_id)\n    if p:",
     "    p = path_for(session_id)\n    if p:", "16"),
    ("mode check dropped", "    if mode != 0o700:", "    if False:", "12"),
    ("owner check dropped", "    if st.st_uid != os.getuid():", "    if False:", "20"),
    ("parent check dropped", "    why = check_parent(os.path.dirname(p))\n    if why:",
     "    why = \"\"\n    if why:", "21"),
    ("only the last directory of the path checked", "        up = os.path.dirname(d)\n        if up == d:",
     "        up = d\n        if up == d:", "23"),
    ("relative TMPDIR accepted", '    return v if os.path.isabs(v) else ""', "    return v", "19"),
    ("no fallback for the failure note", "            continue  # e.g. XDG_STATE_HOME is a file",
     "            return  # e.g. XDG_STATE_HOME is a file", "22"),
    ("failure not noted", "        note_failure(session_id, hook, why)\n", "", "12"),
]


def selftest():
    import shutil
    lib_rel = os.path.join("hooks", "lib", "run_dir.py")
    src = open(os.path.join(PLUGIN, lib_rel), encoding="utf-8").read()
    bad = 0
    with tempfile.TemporaryDirectory() as work:
        base = {n: b for n, b, _ in suite(DEFAULT_HOOK, tempfile.mkdtemp(dir=work))}
        for label, old, new, case in LIB_MUTATIONS:
            if src.count(old) != 1:
                print("%-42s SETUP FAILED: pattern absent or repeated" % label)
                bad += 1
                continue
            mp = os.path.join(tempfile.mkdtemp(dir=work), "goalspec")
            shutil.copytree(PLUGIN, mp)
            with open(os.path.join(mp, lib_rel), "w", encoding="utf-8") as f:
                f.write(src.replace(old, new, 1))
            rows = {n: b for n, b, _ in suite(os.path.join(mp, "hooks", "watch-adversary-writes.sh"),
                                              tempfile.mkdtemp(dir=work), plugin=mp)}
            changed = [n for n in rows if rows[n] != base.get(n)]
            hit = any(n.startswith(case) for n in changed)
            print("%-42s case %s %s%s" % (label, case, "ok" if hit else "MISSED",
                                          "" if hit else "  <- changed: %s" % (", ".join(changed) or "none")))
            bad += 0 if hit else 1
    print()
    if bad:
        print("selftest: %d mutation(s) not caught" % bad)
        return 1
    print("selftest: every mutation caught by the case written for it")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hook", nargs="?", default=DEFAULT_HOOK)
    ap.add_argument("--compare", metavar="OTHER_HOOK")
    ap.add_argument("--expected", default="", help="case-name prefixes whose diff is INTENDED")
    ap.add_argument("--selftest", action="store_true",
                    help="break run_dir.py in a copy and require its own case to notice")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

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
        if expected_check.report(expected, [r[0] for r in rows], diffs):
            rc = 1
        elif not unexpected and not failures:
            print("\nparity OK — %d branches, %d intended change(s)" % (len(rows), len(diffs)))
    return rc


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Every suite in test/ leaves its temp dir as it found it.

Not a suite (the name does not end in `-branches.py`, so the suite counts in manifest-checks do not
see it). It runs the other suites, each with TMPDIR pointed at a fresh dir of its own, and fails if
anything is left in that dir afterwards, or if a new entry of this user's appeared in /tmp (one
suite builds a fixture there on purpose, outside every TMPDIR).

Why it exists (p-1a5a4e9828, 2026-10-14): the suites created dirs with mkdtemp and never removed
them. Measured that day: ~15 GB a day in $TMPDIR, 546 terminal-precheck dirs on that date alone,
~150 per run of claim-surface --selftest. A full disk then made the module-swap recipe of
test/README.md fail to restore hooks/lib/terminal_actions.py (p-71266974e6).

The fresh TMPDIR is mode 1777 (sticky), because hooks/lib/terminal_actions.py treats only a sticky
dir, or macOS's per-user T, as a temp root, and terminal-precheck's cases depend on running under one.

    python3 test/temp-leak-check.py               # every suite, default mode and --selftest
    python3 test/temp-leak-check.py <suite.py>... # only those (a path, or a name under test/)
    python3 test/temp-leak-check.py --selftest    # plant a suite that leaks, require a red

What it cannot see: a suite that writes outside both TMPDIR and /tmp (the repo, HOME), and a /tmp
entry another process of this user created while the suite ran (it would show as a false red,
named, never hidden). `--compare` runs are not driven here: each needs a pre-edit copy of a hook,
so they go through the same cleanup code (tmp_cleanup, imported at the top of every suite) and are
measured by hand per test/README.md.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SKIP = {"temp-leak-check.py", "expected_check.py", "tmp_cleanup.py"}


def suites():
    return sorted(f for f in os.listdir(HERE) if f.endswith(".py") and f not in SKIP)


def has_selftest(path):
    return "--selftest" in open(path, encoding="utf-8").read()


def tmp_entries():
    try:
        return {e for e in os.listdir("/tmp")
                if os.lstat(os.path.join("/tmp", e)).st_uid == os.getuid()}
    except OSError:
        return set()


def run_one(path, args):
    """(rc, leftover entries under the suite's TMPDIR, new /tmp entries)."""
    box = tempfile.mkdtemp(prefix="temp-leak-check.")
    os.chmod(box, 0o1777)
    env = dict(os.environ, TMPDIR=box)
    env.setdefault("CLAUDE_PLUGIN_ROOT", os.path.join(REPO, "plugins", "goalspec"))
    before = tmp_entries()
    try:
        p = subprocess.run([sys.executable, path] + args, env=env, cwd=REPO,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
        rc = p.returncode
    finally:
        left = sorted(os.listdir(box))
        new_tmp = sorted(tmp_entries() - before)
        shutil.rmtree(box, ignore_errors=True)
    return rc, left, new_tmp


def check(paths):
    bad = 0
    for path in paths:
        modes = [[]] + ([["--selftest"]] if has_selftest(path) else [])
        for args in modes:
            label = " ".join([os.path.basename(path)] + args)
            rc, left, new_tmp = run_one(path, args)
            if left or new_tmp:
                bad += 1
                shown = ["$TMPDIR/" + e for e in left[:5]] + ["/tmp/" + e for e in new_tmp[:5]]
                print("LEAK  %-48s rc=%d  %d left: %s" % (label, rc, len(left) + len(new_tmp),
                                                          ", ".join(shown)))
            elif rc != 0:
                # A run that crashed may have cleaned up nothing because it built nothing, so a
                # clean dir after rc!=0 proves nothing. It also catches a suite (or its --selftest
                # copy) that cannot import tmp_cleanup: CI runs --selftest only through here.
                bad += 1
                print("FAIL  %-48s rc=%d  (clean dir, but the run failed)" % (label, rc))
            else:
                print("ok    %-48s rc=%d" % (label, rc))
    return bad


def selftest():
    """A planted suite that leaves one mkdtemp dir must turn this red; one that cleans, green."""
    work = tempfile.mkdtemp(prefix="temp-leak-selftest.")
    try:
        leaky = os.path.join(work, "leaky.py")
        clean = os.path.join(work, "clean.py")
        with open(leaky, "w") as f:
            f.write("import tempfile\ntempfile.mkdtemp(prefix='leaky-')\n")
        with open(clean, "w") as f:
            f.write("import sys\nsys.path.insert(0, %r)\nimport tmp_cleanup\n"
                    "import tempfile\ntempfile.mkdtemp(prefix='clean-')\n"
                    "tempfile.mkstemp(prefix='clean-')\n" % HERE)
        ok = True
        if check([leaky]) != 1:
            print("SELFTEST FAIL: a suite that leaves a dir did not turn the check red")
            ok = False
        if check([clean]) != 0:
            print("SELFTEST FAIL: a suite that imports tmp_cleanup still left something")
            ok = False
        print("selftest %s" % ("OK" if ok else "FAILED"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    paths = [a if os.sep in a else os.path.join(HERE, a) for a in argv] or \
        [os.path.join(HERE, s) for s in suites()]
    bad = check(paths)
    print("\n%s: %d run(s) left something behind" % ("FAIL" if bad else "OK", bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

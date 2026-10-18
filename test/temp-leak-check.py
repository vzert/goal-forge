#!/usr/bin/env python3
"""Every suite in test/ leaves its temp dir as it found it.

Not a suite (the name does not end in `-branches.py`, so the suite counts in manifest-checks do not
see it). It runs the other suites, each with TMPDIR pointed at a fresh dir of its own, and fails if
anything is left in that dir afterwards, if a new path appeared in /tmp under a name that starts
with this run's prefix, suite_tmp.BASE + its pid (or inside such a dir, at any depth: terminal-precheck builds two fixtures
there on purpose, outside every TMPDIR), or if the run exited non-zero. The rest of /tmp is not
looked at: other programs of this user write there all the time (p-9991d7ddc9).

Why it exists (p-1a5a4e9828, 2026-10-14): the suites created dirs with mkdtemp and never removed
them. Measured that day: ~15 GB a day in $TMPDIR, 546 terminal-precheck dirs on that date alone,
~150 per run of claim-surface --selftest. A full disk then made the module-swap recipe of
test/README.md fail to restore hooks/lib/terminal_actions.py (p-71266974e6).

The fresh TMPDIR is mode 1777 (sticky), because hooks/lib/terminal_actions.py treats only a sticky
dir, or macOS's per-user T, as a temp root, and terminal-precheck's cases depend on running under one.

    python3 test/temp-leak-check.py               # every suite, default mode and --selftest
    python3 test/temp-leak-check.py <suite.py>... # only those (a path, or a name under test/)
    python3 test/temp-leak-check.py --selftest    # plant a suite that leaks, require a red

What it cannot see: a suite that writes outside its TMPDIR anywhere but under the prefix -- in /tmp
with another name, in the repo, in HOME. The rule that a suite does not is written in
test/README.md; this checker does not enforce it. `--compare` runs are not driven here: each needs a pre-edit copy of a hook,
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
SKIP = {"temp-leak-check.py", "expected_check.py", "tmp_cleanup.py", "suite_tmp.py", "suite_bash.py"}
sys.path.insert(0, HERE)
import suite_tmp  # noqa: E402 — not tmp_cleanup: importing that would redirect TMPDIR
# This run's own prefix, handed to every suite it starts (suite_tmp.ENV): a second run at the same
# time uses another pid, so neither sees the other's fixtures as its leak.
PREFIX = suite_tmp.BASE + "%d-" % os.getpid()
try:
    import yaml  # noqa: F401  (only to know whether manifest-checks.py can run here)
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


def suites():
    return sorted(f for f in os.listdir(HERE) if f.endswith(".py") and f not in SKIP)


def has_selftest(path):
    return "--selftest" in open(path, encoding="utf-8").read()


def tmp_entries():
    """Every path in /tmp whose top-level name starts with PREFIX, and everything inside such a dir,
    at any depth: a file left inside a dir that already existed is a leak too (codex round 1 on the
    first version, which listed the top level only)."""
    out = set()
    try:
        names = os.listdir("/tmp")
    except OSError:
        return out
    for name in names:
        if not name.startswith(PREFIX):
            continue
        top = os.path.join("/tmp", name)
        out.add(top)
        if os.path.isdir(top) and not os.path.islink(top):
            for root, dirs, files in os.walk(top, onerror=lambda e: None):
                out.update(os.path.join(root, n) for n in dirs + files)
    return out


TAIL = 40  # lines of a failed run's own output shown under its FAIL/LEAK line


def run_one(path, args):
    """(rc, leftover entries under the suite's TMPDIR, new /tmp entries, the run's output)."""
    # No "." in the prefix: a dir named like mktemp's (name.XXXXXX) nested inside another temp root
    # (on Linux every TMPDIR is under /tmp) makes terminal_actions._in_own_mktemp judge the outer
    # root first, in set order, and deny case 117 or a gate case at random (CI 38700885747, ubuntu).
    box = tempfile.mkdtemp(prefix="temp-leak-check-")
    os.chmod(box, 0o1777)
    env = dict(os.environ, TMPDIR=box, **{suite_tmp.ENV: PREFIX})
    env.setdefault("CLAUDE_PLUGIN_ROOT", os.path.join(REPO, "plugins", "goalspec"))
    before = tmp_entries()
    out = ""
    try:
        p = subprocess.run([sys.executable, path] + args, env=env, cwd=REPO,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
        rc = p.returncode
        out = p.stdout.decode("utf-8", "replace")
    finally:
        left = sorted(os.listdir(box))
        new_tmp = sorted(tmp_entries() - before)
        shutil.rmtree(box, ignore_errors=True)
    return rc, left, new_tmp, out


def show_tail(out):
    # Without it a red in CI names the suite and nothing else: claim-surface --selftest failed once
    # on macos-latest (run 39082027219, attempt 1), passed on the re-run, and its output was gone.
    lines = out.rstrip("\n").split("\n")
    for line in lines[-TAIL:]:
        print("      | " + line)


def check(paths):
    bad = 0
    for path in paths:
        if os.path.basename(path) == "manifest-checks.py" and not HAVE_YAML:
            # It exits 2 without PyYAML, which the CI `suites` job does not install (goal-adversary
            # round 1). The `manifests` job, which has it, runs this check on that file alone.
            print("skip  %-48s (needs PyYAML)" % os.path.basename(path))
            continue
        modes = [[]] + ([["--selftest"]] if has_selftest(path) else [])
        for args in modes:
            label = " ".join([os.path.basename(path)] + args)
            rc, left, new_tmp, out = run_one(path, args)
            if left or new_tmp:
                bad += 1
                shown = ["$TMPDIR/" + e for e in left[:5]] + new_tmp[:5]
                print("LEAK  %-48s rc=%d  %d left: %s" % (label, rc, len(left) + len(new_tmp),
                                                          ", ".join(shown)))
                if rc != 0:
                    show_tail(out)
            elif rc != 0:
                # A run that crashed may have cleaned up nothing because it built nothing, so a
                # clean dir after rc!=0 proves nothing. It also catches a suite (or its --selftest
                # copy) that cannot import tmp_cleanup: CI runs --selftest only through here.
                bad += 1
                print("FAIL  %-48s rc=%d  (clean dir, but the run failed)" % (label, rc))
                show_tail(out)
            else:
                print("ok    %-48s rc=%d" % (label, rc))
    return bad


def selftest():
    """A planted suite that leaves one mkdtemp dir must turn this red; one that cleans, green."""
    work = tempfile.mkdtemp(prefix="temp-leak-selftest-")
    try:
        leaky = os.path.join(work, "leaky.py")
        clean = os.path.join(work, "clean.py")
        with open(leaky, "w") as f:
            f.write("import tempfile\ntempfile.mkdtemp(prefix='leaky-')\n")
        with open(clean, "w") as f:
            f.write("import sys\nsys.path.insert(0, %r)\nimport tmp_cleanup\n"
                    "import tempfile\ntempfile.mkdtemp(prefix='clean-')\n"
                    "tempfile.mkstemp(prefix='clean-')\n" % HERE)
        nested = os.path.join(work, "nested.py")
        pre = tempfile.mkdtemp(prefix=PREFIX + "pre-", dir="/tmp")  # exists BEFORE the run
        with open(nested, "w") as f:
            f.write("open(%r, 'w').close()\n" % os.path.join(pre, "left-inside"))
        prefixed = os.path.join(work, "prefixed.py")
        with open(prefixed, "w") as f:
            f.write("import tempfile\ntempfile.mkdtemp(prefix=%r, dir='/tmp')\n" % (PREFIX + "left-"))
        # A fixture of another temp-leak-check run going on at the same time: BASE with another pid.
        other_path = os.path.join("/tmp", suite_tmp.BASE + "%d-other" % (os.getpid() + 1))
        other = os.path.join(work, "other.py")
        with open(other, "w") as f:
            f.write("open(%r, 'w').close()\n" % other_path)
        # The prefix a suite gets must be this run's: a suite that writes with suite_tmp.PREFIX.
        via_module = os.path.join(work, "via_module.py")
        with open(via_module, "w") as f:
            f.write("import sys, tempfile\nsys.path.insert(0, %r)\nimport suite_tmp\n"
                    "tempfile.mkdtemp(prefix=suite_tmp.PREFIX + 'mod-', dir='/tmp')\n" % HERE)
        # Another program's file in /tmp, made during the run and left there: not a suite's, so
        # not a leak (the old checker called it one). Removed below by its fixed name.
        foreign_path = os.path.join("/tmp", "temp-leak-foreign-%d" % os.getpid())
        foreign = os.path.join(work, "foreign.py")
        with open(foreign, "w") as f:
            f.write("open(%r, 'w').close()\n" % foreign_path)
        failing = os.path.join(work, "failing.py")
        with open(failing, "w") as f:
            f.write("print('the-last-words-of-the-run')\nraise SystemExit(3)\n")
        ok = True
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            n = check([failing])
        sys.stdout.write(buf.getvalue())
        if n != 1 or "| the-last-words-of-the-run" not in buf.getvalue():
            print("SELFTEST FAIL: a run that exited non-zero did not show its own output")
            ok = False
        if check([nested]) != 1:
            print("SELFTEST FAIL: a file left inside a pre-existing prefixed /tmp dir did not turn it red")
            ok = False
        shutil.rmtree(pre, ignore_errors=True)
        before = tmp_entries()
        if check([prefixed]) != 1:
            print("SELFTEST FAIL: a prefixed dir left in /tmp did not turn the check red")
            ok = False
        for p in sorted(tmp_entries() - before, reverse=True):
            shutil.rmtree(p, ignore_errors=True)
        before = tmp_entries()
        if check([via_module]) != 1:
            print("SELFTEST FAIL: a dir left with suite_tmp.PREFIX did not turn it red (prefix not handed down)")
            ok = False
        for p in sorted(tmp_entries() - before, reverse=True):
            shutil.rmtree(p, ignore_errors=True)
        if check([other]) != 0:
            print("SELFTEST FAIL: another run's fixture (same base, other pid) turned it red")
            ok = False
        if not os.path.exists(other_path):
            print("SELFTEST FAIL: the planted other-run file was never written, so its case proved nothing")
            ok = False
        try:
            os.unlink(other_path)
        except OSError:
            pass
        if check([foreign]) != 0:
            print("SELFTEST FAIL: a file another program left in /tmp, without the prefix, turned it red")
            ok = False
        if not os.path.exists(foreign_path):
            print("SELFTEST FAIL: the planted foreign file was never written, so its case proved nothing")
            ok = False
        try:
            os.unlink(foreign_path)
        except OSError:
            pass
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

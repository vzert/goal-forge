"""Give this suite run a temp dir of its own, and remove it, with everything in it, at exit.

Imported at the top of every suite (`import tmp_cleanup`, before any fixture is built). On import it
makes one dir with mkdtemp, points TMPDIR (and Python's tempfile) at it, and registers an atexit
handler that removes it. So every temp path of the run lands inside it: the suite's own mkdtemp
calls, a nested `--selftest` or `--compare` child (which imports this module again, one level down),
and what the hooks write from their subprocesses (`mktemp` in bash, state files keyed by session).
The handler runs after a pass, a failure, an uncaught exception or sys.exit; not on os._exit or
SIGKILL. Paths a suite builds outside TMPDIR on purpose (terminal-precheck's /tmp fixture) are
registered with `track()`, and so is every mkdtemp/mkstemp given an explicit `dir=`.

The dir is mode 1777 (sticky): hooks/lib/terminal_actions.py counts only a sticky dir, or macOS's
per-user T, as a temp root, and terminal-precheck's cases depend on running under one.

Why (p-1a5a4e9828, 2026-10-14): the suites never removed their temp dirs. Measured that day: ~15 GB a
day in $TMPDIR, 546 terminal-precheck dirs on that date alone, ~250 entries per run of
claim-surface --selftest, some of them made by the hooks, not by Python. test/temp-leak-check.py
measures that this works.

Not a suite: the name does not end in `-branches.py`, so the suite counts in manifest-checks do not
see it.
"""
import atexit
import os
import shutil
import stat
import tempfile

_mkdtemp = tempfile.mkdtemp
_mkstemp = tempfile.mkstemp
_made = []


def track(path):
    """Remove `path` (a file, a link or a dir tree) at exit too."""
    _made.append(path)
    return path


def _mkdtemp_tracked(*a, **k):
    return track(_mkdtemp(*a, **k))


def _mkstemp_tracked(*a, **k):
    fd, path = _mkstemp(*a, **k)
    return fd, track(path)


def _writable(func, path, _exc):
    # A fixture may chmod a dir to 0555 or 0000 to test a hook; make it removable and retry once.
    try:
        os.chmod(os.path.dirname(path), stat.S_IRWXU)
        if not os.path.islink(path):
            os.chmod(path, stat.S_IRWXU)
        func(path)
    except OSError:
        pass


def cleanup():
    while _made:
        path = _made.pop()
        if os.path.islink(path) or os.path.isfile(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        elif os.path.isdir(path):
            shutil.rmtree(path, onerror=_writable)


# A suite that must run under the REAL temp root sets TMP_CLEANUP_KEEP_TMPDIR=1 before importing
# this module: terminal-precheck, because a sticky box always matches the sticky clause of
# terminal_actions._temp_roots, and its cases 116-117 then never reach the macOS per-user-T clause
# (goal-adversary round 1 on this change: with that clause disabled, the suite still passed). That
# suite gets tracking only: its own mkdtemp dirs and track()ed paths are removed, nothing redirected.
if os.environ.get("TMP_CLEANUP_KEEP_TMPDIR") == "1":
    # The hooks it runs call git, and on macOS the git shim runs xcrun, which writes its cache
    # `xcrun_db` into TMPDIR (codex round 2 found it left in a fresh one). Remove it only if this
    # run created it: in a TMPDIR that already had it, it is someone else's cache.
    _xcrun = os.path.join(tempfile.gettempdir(), "xcrun_db")
    if not os.path.lexists(_xcrun):
        _made.append(_xcrun)
else:
    BOX = _mkdtemp(prefix="goalspec-suite-")  # no ".": see the box prefix in temp-leak-check.py
    os.chmod(BOX, 0o1777)
    _made.append(BOX)  # first in, so popped last: tracked paths inside it go first
    os.environ["TMPDIR"] = BOX
    tempfile.tempdir = BOX
tempfile.mkdtemp = _mkdtemp_tracked
tempfile.mkstemp = _mkstemp_tracked
atexit.register(cleanup)

#!/usr/bin/env python3
"""Run the external adversary's CLI with a wall-clock cap (0.65.7).

Usage: run_capped.py <seconds> <cmd> [args...]   (stdin goes to the command; its stdout and stderr
come back merged on stdout, the way the hook's `OUT=$(... 2>&1)` captured them before)

external-adversary.sh had no cap at all: measured over the 490 rounds of 2026-10-05..19 in four
projects, 12 ran 30 minutes or more (max 53). Past the cap this kills the partner and every process
below it at that moment (see _descendants), prints whatever it had written, and exits 124 -- the status `timeout(1)` uses, which macOS
does not ship. The hook reads 124 like any nonzero exit: a filled break it already printed stands,
anything else is an UNVERIFIED hold.

<seconds> of 0 means no cap. Exit status otherwise is the command's own; 127 when it cannot start.
"""
import os
import signal
import subprocess
import sys
import threading
import time

TIMED_OUT = 124


def _descendants(root):
    """Every pid below root, from one `ps` snapshot of pid/ppid pairs. A process group is not
    enough: codex runs each shell command in a session of its own (measured with codex-cli 0.155.1:
    the command's pid, pgid and sid all differed from codex's), so killpg left a `sleep` codex had
    started running after the cap. A process that already left the tree (double fork, reparented)
    is not in the snapshot and survives."""
    try:
        ps = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True,
                            timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    children = {}
    for line in ps.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [root]
    while todo:
        for c in children.get(todo.pop(), []):
            if c not in found:
                found.append(c)
                todo.append(c)
    return found


def _signal_all(pids, sig):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _kill_tree(proc):
    if os.name == "nt":
        # No process groups: taskkill /T takes the children (codex spawns its own) with it.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    # Snapshot the tree BEFORE the first signal: once the partner dies its children are reparented
    # and no longer name it as their parent.
    tree = _descendants(proc.pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        _signal_all(tree, sig)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            continue
        if sig == signal.SIGTERM:
            # The partner is gone; give its children the same grace, then SIGKILL what is left.
            alive = [p for p in tree if _alive(p)]
            if not alive:
                return
            time.sleep(2)
            _signal_all([p for p in alive if _alive(p)], signal.SIGKILL)
        return


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("run_capped.py: usage: run_capped.py <seconds> <cmd> [args...]\n")
        return 2
    try:
        cap = float(sys.argv[1])
    except ValueError:
        cap = 0
    data = sys.stdin.buffer.read()
    try:
        proc = subprocess.Popen(sys.argv[2:], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=(os.name != "nt"))
    except OSError as e:
        sys.stdout.write("run_capped.py: cannot start %s: %s\n" % (sys.argv[2], e))
        return 127

    def feed():
        try:
            proc.stdin.write(data)
        except OSError:
            pass  # a partner that exits without reading its prompt
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    chunks = []

    def drain():
        for chunk in iter(lambda: proc.stdout.read1(65536), b""):
            chunks.append(chunk)

    # The partner runs in its own session so the cap can kill its whole tree; that also takes it
    # out of the hook's process group, so a SIGTERM or Ctrl-C sent to the hook's group (a timeout
    # around the hook, the user) would no longer reach it. Pass it on, then exit as killed.
    def forward(signum, _frame):
        _kill_tree(proc)
        sys.exit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT) + ((signal.SIGHUP,) if hasattr(signal, "SIGHUP") else ()):
        signal.signal(sig, forward)

    # Daemon threads: a grandchild that left the process group can hold the pipe open forever, and
    # it must not hold this process open with it.
    threading.Thread(target=feed, daemon=True).start()
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        rc = proc.wait(timeout=cap if cap > 0 else None)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        rc = TIMED_OUT
    reader.join(timeout=5)
    sys.stdout.buffer.write(b"".join(chunks))
    sys.stdout.flush()
    return rc


if __name__ == "__main__":
    sys.exit(main())

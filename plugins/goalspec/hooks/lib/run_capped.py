#!/usr/bin/env python3
"""Run the external adversary's CLI with a wall-clock cap (0.65.6).

Usage: run_capped.py <seconds> <cmd> [args...]   (stdin goes to the command; its stdout and stderr
come back merged on stdout, the way the hook's `OUT=$(... 2>&1)` captured them before)

external-adversary.sh had no cap at all: measured over the 490 rounds of 2026-10-05..19 in four
projects, 12 ran 30 minutes or more (max 53). Past the cap this kills the partner's whole process
tree, prints whatever it had written, and exits 124 -- the status `timeout(1)` uses, which macOS
does not ship. The hook reads 124 like any nonzero exit: a filled break it already printed stands,
anything else is an UNVERIFIED hold.

<seconds> of 0 means no cap. Exit status otherwise is the command's own; 127 when it cannot start.
"""
import os
import signal
import subprocess
import sys
import threading

TIMED_OUT = 124


def _kill_tree(proc):
    if os.name == "nt":
        # No process groups: taskkill /T takes the children (codex spawns its own) with it.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


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

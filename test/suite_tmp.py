"""The one name prefix a suite may use for a path it builds directly in /tmp, outside its TMPDIR.

Imported by test/terminal-precheck-branches.py (the one suite whose cases need a path in /tmp itself)
and by test/temp-leak-check.py (which watches, in /tmp, only names that start with it). No side
effects on import, unlike tmp_cleanup: temp-leak-check must not get a TMPDIR of its own from it.

Why (p-9991d7ddc9): temp-leak-check used to walk all of /tmp, where other programs of the same user
write too (Claude Code's sockets, context-mode, the Paperclip agents' read-loop hook), and each of
them turned it red until it was named in a list. A suite that builds a /tmp path without this prefix
is not seen; the rule is written in test/README.md.

Chosen because nothing else used it in /tmp on 2026-10-17. "goalspec-suite-" was the first pick and
was already taken: 13 `goalspec-suite-<suite>.py.out` logs and two mktemp dirs, written 2026-10-12..15
by some other run on this machine.

Not a suite: the name does not end in `-branches.py`.
"""
PREFIX = "goalspec-test-fixture-"

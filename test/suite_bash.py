"""The bash every suite runs the hooks with: BASH, used as `subprocess.run([BASH, hook], ...)`.

On Linux and macOS it is the plain name "bash", resolved on PATH exactly as before.

On Windows it cannot be the plain name. Python hands "bash" to CreateProcess, which looks in the
Windows system directory before PATH, and finds C:\\Windows\\System32\\bash.exe there: the WSL
launcher, not Git Bash. Measured on a windows-latest runner (2026-10-18, run 39149542165): with no
Linux distribution installed it only printed "Windows Subsystem for Linux has no installed
distributions", and 18 of the 19 suites failed before one hook ran. Claude Code runs the hooks with
Git Bash on Windows, so that is the bash the suites must use: the first bash.exe on PATH that is not
under the Windows directory, or GOALSPEC_TEST_BASH when it is set.

Not a suite: the name does not end in `-branches.py`. No side effects on import.
"""
import os


def _windows_bash():
    forced = os.environ.get("GOALSPEC_TEST_BASH", "")
    if forced:
        return forced
    windir = os.path.normcase(os.path.realpath(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"))
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        cand = os.path.join(d, "bash.exe")
        real = os.path.normcase(os.path.realpath(cand))
        if os.path.isfile(cand) and not (real == windir or real.startswith(windir + os.sep)):
            return cand
    return "bash"


BASH = _windows_bash() if os.name == "nt" else "bash"

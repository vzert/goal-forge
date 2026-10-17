"""run_dir.py — the per-session state directory of the subagent read-only rail and the hand-back
reminder (watch-adversary-writes.sh, report-adversary-writes.sh, remind-handback-verdict.sh), and
the SessionEnd hook that removes it (cleanup-run-dir.sh).

WHY (p-42d7c57137, 0.62.0). Until 0.61 those hooks kept their state in ONE fixed directory,
${TMPDIR:-/tmp}/goalspec-adversary-snap, made with `mkdir -p` and never checked. On Linux TMPDIR is
usually unset, so every user of the machine shared it, and the first one to run an adversary owned
it. MEASURED on a 4-developer VPS (2026-10-17): the directory belonged to one developer with mode
775 and a group nobody else was in; the other three ran 361 goal-adversary subagents between
2026-09-21 and 2026-10-16 and every one of them hit `Permission denied` on its snapshot. The write
detection never measured anything for them and the hand-back record never landed, and nobody saw it:
the hooks exit 0 and the error stayed in each subagent's own transcript.

So each SESSION now gets its own directory, the same idea as .goalspec/checkpoint-<session>.md:
${TMPDIR:-/tmp}/goalspec-run-<session_id>/, made by mkdir mode 0700 (no -p), and used only if it is
a real directory (not a symlink) owned by this uid with mode 0700. Anything else is someone else's
or a plant: the hook writes nothing there and a FAILURE NOTE is left in this user's own state
directory, which report-adversary-writes.sh turns into one line on `Stop` (the one event whose
output reaches the executor and the human). A payload with no session_id gets no directory at all.

Threat model: catches sessions or users colliding by accident, and a directory planted under the
predictable name. Not root, and not a user who can write inside a 0700 directory it does not own
(it cannot).

Usable as a module (remind-handback-verdict.sh imports it) and as a command (the bash hooks):
  run_dir.py ensure <session_id> <hook>   print the directory, creating it; on failure print nothing
                                          and leave a failure note
  run_dir.py path <session_id>            print the directory only if it exists and passes the check
  run_dir.py failures <session_id>        print this session's failure notes and delete them
  run_dir.py remove <session_id>          delete the directory (if it passes the check) and the notes
Every command exits 0: a state directory that cannot be used is never a reason to block anything.
"""
import os, re, shutil, stat, sys

PREFIX = "goalspec-run-"


def key(session_id):
    """Filesystem-safe form of the id; "" when there is none. Ids are harness-generated, so this is
    hygiene, not distrust."""
    if not isinstance(session_id, str) or not session_id:
        return ""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]


def path_for(session_id):
    k = key(session_id)
    if not k:
        return ""
    return os.path.join(os.environ.get("TMPDIR") or "/tmp", PREFIX + k)


def check(p):
    """-> "" when `p` is a usable run directory, else the reason it is not."""
    try:
        st = os.lstat(p)
    except OSError as e:
        return "cannot stat %s: %s" % (p, e.strerror)
    if stat.S_ISLNK(st.st_mode):
        return "%s is a symlink" % p
    if not stat.S_ISDIR(st.st_mode):
        return "%s is not a directory" % p
    if st.st_uid != os.getuid():
        return "%s belongs to uid %d, not to this user (uid %d)" % (p, st.st_uid, os.getuid())
    mode = stat.S_IMODE(st.st_mode)
    if mode != 0o700:
        return "%s has mode %o, not 700" % (p, mode)
    return ""


def _failures_path(session_id):
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "goalspec", "run-dir-failed-" + key(session_id))


def note_failure(session_id, hook, reason):
    try:
        fp = _failures_path(session_id)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "a", encoding="utf-8") as fh:
            fh.write("%s: %s\n" % (hook, reason))
    except Exception:
        pass  # nowhere writable to say it: silent, as before


def ensure(session_id, hook):
    """-> the run directory, created if absent; "" when there is no id or it cannot be used."""
    p = path_for(session_id)
    if not p:
        return ""
    try:
        os.mkdir(p, 0o700)
    except FileExistsError:
        pass
    except OSError as e:
        note_failure(session_id, hook, "cannot create %s: %s" % (p, e.strerror))
        return ""
    why = check(p)
    if why:
        note_failure(session_id, hook, why)
        return ""
    return p


def existing(session_id):
    """-> the run directory if it exists and passes the check, else "" (never creates)."""
    p = path_for(session_id)
    if not p or not os.path.lexists(p) or check(p):
        return ""
    return p


def take_failures(session_id):
    if not key(session_id):
        return []
    fp = _failures_path(session_id)
    try:
        body = open(fp, encoding="utf-8").read()
    except Exception:
        return []
    try:
        os.remove(fp)
    except Exception:
        pass
    seen, out = set(), []
    for ln in body.splitlines():
        if ln.strip() and ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out


def remove(session_id):
    p = existing(session_id)
    if p:
        shutil.rmtree(p, ignore_errors=True)  # rmtree never follows a symlink inside it
    if key(session_id):
        try:
            os.remove(_failures_path(session_id))
        except Exception:
            pass


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    sid = argv[2] if len(argv) > 2 else ""
    if cmd == "ensure":
        out = ensure(sid, argv[3] if len(argv) > 3 else "hook")
        if out:
            print(out)
    elif cmd == "path":
        out = existing(sid)
        if out:
            print(out)
    elif cmd == "failures":
        for ln in take_failures(sid):
            print(ln)
    elif cmd == "remove":
        remove(sid)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:
        sys.exit(0)

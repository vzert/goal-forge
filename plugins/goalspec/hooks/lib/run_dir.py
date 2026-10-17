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

WHERE, AND WHY NOT THE TEMP ROOT. Each SESSION gets its own directory, the same idea as
.goalspec/checkpoint-<session>.md, under this user's own state directory:
  POSIX:   ${XDG_STATE_HOME:-~/.local/state}/goalspec/run-<session_id>/
  Windows: %LOCALAPPDATA%\\goalspec\\run-<session_id>\\
A first version put it in the shared temp root with owner and mode checks, and three review rounds
in a row each found another way to swap it from another account (a relative TMPDIR, a symlink on the
way, a sticky directory owned by someone else). A per-user directory removes that whole class: no
other account writes on the way to it.

Checks (POSIX): the run directory is made with mode 0700 and used only if it is a real directory
(not a symlink), owned by this uid, mode 0700; and every directory on the real path to it belongs to
this user or root and is not writable by others, nor by its group unless that group is private (no
members, primary group of this user only: the Debian/Ubuntu default, where ~/.local is 0775,
measured on the VPS for all five users). A sticky directory owned by root or this user (like /tmp)
is accepted too. On Windows uid and mode bits do not exist (os.getuid is Unix-only, access is by
ACL, and %LOCALAPPDATA% is private to the user by default), so only "a real directory, not a
symlink or junction" is checked there.

Anything else is someone else's or a plant: the hook writes nothing there and a FAILURE NOTE is left
in the same state directory, which report-adversary-writes.sh turns into one line on `Stop` (the one
event whose output reaches the executor and the human). A payload with no session_id gets no
directory at all. Only absolute paths are used: a relative XDG_STATE_HOME, LOCALAPPDATA or HOME is
ignored, so nothing is ever written relative to the hook's working directory.

Threat model: catches sessions or users colliding by accident, a directory planted under the
predictable name, and a swap from another account after the check. Not root, and not this same user
racing its own hooks.

Usable as a module (remind-handback-verdict.sh imports it) and as a command (the bash hooks):
  run_dir.py ensure <session_id> <hook>          print the directory, creating it; on failure print
                                                 nothing and leave a failure note
  run_dir.py path <session_id>                   print the directory only if it exists and passes
  run_dir.py note <session_id> <hook> <reason>   leave a failure note
  run_dir.py failures <session_id>               print this session's failure notes, delete them
  run_dir.py remove <session_id>                 delete the directory (if it passes), its notes, and
                                                 this user's run directories older than 7 days
Every command exits 0: a state directory that cannot be used is never a reason to block anything.
"""
import os, re, shutil, stat, sys, time

IS_WINDOWS = os.name == "nt"
PREFIX = "run-"
STALE_SECONDS = 7 * 24 * 3600


def key(session_id):
    """Filesystem-safe form of the id; "" when there is none. Ids are harness-generated, so this is
    hygiene, not distrust."""
    if not isinstance(session_id, str) or not session_id:
        return ""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]


def _abs_env(name):
    v = os.environ.get(name) or ""
    return v if os.path.isabs(v) else ""


def bases():
    """This user's goalspec state directories, in order of preference; absolute paths only."""
    home = os.path.expanduser("~")
    home = home if os.path.isabs(home) else ""
    if IS_WINDOWS:
        cands = (_abs_env("LOCALAPPDATA"), os.path.join(home, "AppData", "Local") if home else "")
    else:
        cands = (_abs_env("XDG_STATE_HOME"), os.path.join(home, ".local", "state") if home else "")
    out = []
    for c in cands:
        if c and os.path.join(c, "goalspec") not in out:
            out.append(os.path.join(c, "goalspec"))
    return out


def _group_private(gid):
    """True when the group has no listed members and is the primary group of this user only."""
    try:
        import grp, pwd
        if grp.getgrgid(gid).gr_mem:
            return False
        me = pwd.getpwuid(os.getuid()).pw_name
        return [p.pw_name for p in pwd.getpwall() if p.pw_gid == gid] == [me]
    except Exception:
        return False


def check_parent(parent):
    """-> "" when no other account can replace anything on the real path to `parent`, else why."""
    if IS_WINDOWS:
        return ""
    d = os.path.realpath(parent)
    while True:
        try:
            st = os.lstat(d)
        except OSError as e:
            return "cannot stat %s: %s" % (d, e.strerror)
        owner_ok = st.st_uid in (os.getuid(), 0)
        if st.st_mode & stat.S_ISVTX:
            safe = owner_ok
        else:
            safe = owner_ok and not st.st_mode & stat.S_IWOTH and (
                not st.st_mode & stat.S_IWGRP or _group_private(st.st_gid))
        if not safe:
            return "%s (on the way to %s) lets another account replace entries in it" % (d, parent)
        up = os.path.dirname(d)
        if up == d:
            return ""
        d = up


def check(p):
    """-> "" when `p` is a usable run directory, else the reason it is not."""
    why = check_parent(os.path.dirname(p))
    if why:
        return why
    try:
        st = os.lstat(p)
    except OSError as e:
        return "cannot stat %s: %s" % (p, e.strerror)
    if stat.S_ISLNK(st.st_mode) or getattr(os.path, "isjunction", lambda _p: False)(p):
        return "%s is a symlink" % p
    if not stat.S_ISDIR(st.st_mode):
        return "%s is not a directory" % p
    if IS_WINDOWS:
        return ""
    if st.st_uid != os.getuid():
        return "%s belongs to uid %d, not to this user (uid %d)" % (p, st.st_uid, os.getuid())
    mode = stat.S_IMODE(st.st_mode)
    if mode != 0o700:
        return "%s has mode %o, not 700" % (p, mode)
    return ""


def note_failure(session_id, hook, reason):
    for b in bases():
        try:
            os.makedirs(b, 0o700, exist_ok=True)
            with open(os.path.join(b, "run-dir-failed-" + key(session_id)), "a", encoding="utf-8") as fh:
                fh.write("%s: %s\n" % (hook, reason))
            return
        except Exception:
            continue  # e.g. XDG_STATE_HOME is a file: try the next place
    # nowhere writable to say it: silent, as before


def ensure(session_id, hook):
    """-> the run directory, created if absent; "" when there is no id or it cannot be used."""
    k = key(session_id)
    if not k:
        return ""
    why = "no state directory (HOME and %s unset or relative)" % (
        "LOCALAPPDATA" if IS_WINDOWS else "XDG_STATE_HOME")
    for b in bases():
        p = os.path.join(b, PREFIX + k)
        try:
            os.makedirs(b, 0o700, exist_ok=True)
            os.mkdir(p, 0o700)
        except FileExistsError:
            pass
        except OSError as e:
            why = "cannot create %s: %s" % (p, e.strerror)
            continue  # this state directory is unusable (e.g. XDG_STATE_HOME is a file): next one
        # It exists but fails the check: someone else's or a plant. Never fall through to the next
        # state directory: a refused directory is reported, not routed around.
        why = check(p)
        break
    if not why:
        # Real path: the checked chain, never re-followed; and what watch-adversary-writes.sh
        # compares with the repository root git reports, which is resolved too.
        return os.path.realpath(p)
    note_failure(session_id, hook, why)
    return ""


def existing(session_id):
    """-> the run directory if it exists and passes the check, else "" (never creates)."""
    k = key(session_id)
    if not k:
        return ""
    for b in bases():
        p = os.path.join(b, PREFIX + k)
        if os.path.lexists(p) and not check(p):
            return os.path.realpath(p)
    return ""


def take_failures(session_id):
    k = key(session_id)
    if not k:
        return []
    body = ""
    for b in bases():
        fp = os.path.join(b, "run-dir-failed-" + k)
        try:
            body += open(fp, encoding="utf-8").read()
        except Exception:
            continue
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


def remove(session_id, now=None):
    p = existing(session_id)
    if p:
        shutil.rmtree(p, ignore_errors=True)  # rmtree never follows a symlink inside it
    k = key(session_id)
    now = time.time() if now is None else now
    for b in bases():
        if k:
            try:
                os.remove(os.path.join(b, "run-dir-failed-" + k))
            except Exception:
                pass
        # A session that crashed never reaches SessionEnd: its directory is pruned here after a week,
        # under the same check, so the per-user state directory does not grow without end.
        try:
            names = os.listdir(b)
        except Exception:
            continue
        for n in names:
            q = os.path.join(b, n)
            try:
                if n.startswith(PREFIX) and now - os.lstat(q).st_mtime > STALE_SECONDS and not check(q):
                    shutil.rmtree(q, ignore_errors=True)
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
    elif cmd == "note":
        if key(sid):
            note_failure(sid, argv[3] if len(argv) > 3 else "hook", " ".join(argv[4:]) or "unknown")
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

"""other_writer.py — which changed paths ANOTHER session wrote, with proof (p-2bf372e6e3, 0.65.0).

Used by watch-adversary-writes.sh on SubagentStop. Until 0.64.x a path that changed during an
adversary round was always reported as "the adversary, you, or another session", and the notice
asked the executor for evidence that names the other writer. The hook had that evidence on disk and
never looked: a session's Write and Edit calls are in its transcript, with what they wrote.

THE PROOF IS A CONTENT CHAIN, NOT A NAME MATCH. A first design attributed a path to another session
when that session's transcript wrote it and the adversary's own transcript did not name it. That
guard never fires where it matters: the adversary reads the files it reviews, so it names every one
of them. Instead, for each changed path, take every successful Write/Edit of it by another session
(toolUseResult with filePath, sessionId not this session's) made since the round's snapshot, in
time order, and require:
  - an Edit starts from the state before it: the path's content in the snapshot (or its blob at HEAD
    when the snapshot does not list it, or no file at all when HEAD has none) for the first link,
    the previous link's output after that;
  - a Write replaces the whole file, so it starts a link from any state;
  - the last link's output is the content the stop measured.
Then the change from before to after is entirely that session's recorded writes, and the adversary
left nothing on that path. Anything else — a link that does not start where the last one ended, an
output that is not the final content, no recorded write at all — leaves the path as before: the
hook does not know who wrote it. MEASURED on 7 real transcripts of this project (2026-10-17): 54
Edit-after-Edit links chained; the 5 that did not each had a real change by another writer between
the two edits (a script adding a session_id line, another editor).

Declared limits: a change with no recorded Write/Edit (a Bash `sed -i`, a git command) is never
attributed; an Edit whose result carries no originalFile breaks the chain, and the harness often
leaves it out (281 of 464 Edit results in this project's transcripts, measured by the 0.65.0
adversary round — mostly `contentNotInModelContext`, i.e. larger files), so the attribution mostly
fires for Writes and Edits of smaller files; a forged transcript is out of scope; hashes are git blob hashes of the recorded text
(no clean filters), so a file under autocrlf or a filter attribute does not match and stays
unattributed — the safe side. This session's own writes are not attributed here (the "you" reading
stays in the notice).

Usage: other_writer.py attribute <session_key> <start_epoch> <repo_root>
  stdin: BEFORE \\0 AFTER \\0 CHANGED   (two fingerprints and the changed-path list of the hook)
  stdout: one line per changed path, "path <p>" or "other <sid8>[,<sid8>...] <p>"
Fail-open: any error prints every path as "path <p>", unchanged from 0.64.x.
"""
import datetime
import glob
import hashlib
import json
import os
import subprocess
import sys


def blob(text):
    """The git blob id of a recorded text, as `git hash-object` gives for a file holding it."""
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def parse_fp(text):
    """A fingerprint -> ({printed path: blob or 'absent'}, [roots], pseudo) where pseudo is True
    when it carries no path lines we can use."""
    files, roots = {}, []
    for line in text.splitlines():
        if line.startswith("root "):
            roots.append(line[5:])
        elif line.startswith(("HEAD ", "staged ")) or not line:
            continue
        else:
            h, _, p = line.partition(" ")
            if p:
                files[p] = h
    return files, roots


def where(printed, roots, repo_root):
    """The tree and the path inside it for a path as the notice prints it."""
    if os.path.isabs(printed):
        for r in sorted(roots, key=len, reverse=True):
            if printed.startswith(r.rstrip("/") + "/"):
                return r, printed[len(r.rstrip("/")) + 1:]
        return None, None
    return repo_root, printed


def head_blob(root, rel):
    try:
        out = subprocess.run(["git", "-C", root, "rev-parse", "--verify", "-q", "HEAD:" + rel],
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 else "absent"


def epoch(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def transcripts(start):
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.environ.get("HOME", ""), ".claude")
    if not os.path.isabs(base):
        return []
    found = glob.glob(os.path.join(base, "projects", "*", "*.jsonl"))
    found += glob.glob(os.path.join(base, "projects", "*", "*", "subagents", "*.jsonl"))
    out = []
    for f in found:
        try:
            if os.path.getmtime(f) >= start:
                out.append(f)
        except OSError:
            pass
    return out


def writes(targets, session_key, start):
    """{real path: [(epoch, sid, kind, original, output)]} for other sessions' successful writes."""
    by_path = {t: [] for t in targets}
    names = {os.path.basename(t) for t in targets}
    for f in transcripts(start):
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"toolUseResult"' not in line or not any(n in line for n in names):
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                sid = str(d.get("sessionId") or "")
                if not sid or sid.startswith(session_key):
                    continue
                r = d.get("toolUseResult")
                if not isinstance(r, dict) or not isinstance(r.get("filePath"), str):
                    continue
                content = (d.get("message") or {}).get("content")
                if isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error")
                        for b in content):
                    continue
                t = epoch(d.get("timestamp"))
                if t is None or t < start:
                    continue
                p = os.path.realpath(r["filePath"])
                if p not in by_path:
                    continue
                orig = r.get("originalFile")
                if r.get("type") in ("create", "update") and isinstance(r.get("content"), str):
                    by_path[p].append((t, sid, "write", None, r["content"]))
                elif isinstance(orig, str) and isinstance(r.get("oldString"), str) \
                        and isinstance(r.get("newString"), str):
                    new = (orig.replace(r["oldString"], r["newString"]) if r.get("replaceAll")
                           else orig.replace(r["oldString"], r["newString"], 1))
                    by_path[p].append((t, sid, "edit", orig, new))
                else:
                    # A write of a kind this cannot replay (MultiEdit, a notebook): it breaks the
                    # chain rather than being skipped, or a path could be attributed over it.
                    by_path[p].append((t, sid, "unknown", None, None))
    return by_path


def chain(before, after, events):
    """The sessions that made the whole change, or None."""
    if not events:
        return None
    state = before
    sids = []
    for _, sid, kind, orig, out in sorted(events, key=lambda e: e[0]):
        if kind == "unknown":
            return None
        if kind == "edit" and blob(orig) != state:
            return None
        state = blob(out)
        if sid[:8] not in sids:
            sids.append(sid[:8])
    return sids if state == after else None


def attribute(session_key, start, repo_root, before_fp, after_fp, changed):
    bfiles, roots = parse_fp(before_fp)
    afiles, _ = parse_fp(after_fp)
    lines = [c for c in changed.splitlines() if c.strip()]
    # A moved HEAD or a changed index is a pseudo-line with no path: then nothing is attributed,
    # since the before-state of every path is in doubt.
    if any(c.startswith("(") for c in lines):
        return ["path " + c for c in lines]
    plan = {}
    for c in lines:
        root, rel = where(c, roots or [repo_root], repo_root)
        a = afiles.get(c)
        if not root or not a or a in ("absent", "unreadable"):
            continue
        b = bfiles.get(c) or head_blob(root, rel)
        if b in ("unknown", "unreadable"):
            continue
        plan[c] = (os.path.realpath(os.path.join(root, rel)), b, a)
    found = writes({v[0] for v in plan.values()}, session_key, start) if plan else {}
    out = []
    for c in lines:
        sids = None
        if c in plan:
            real, b, a = plan[c]
            sids = chain(b, a, found.get(real, []))
        out.append("other %s %s" % (",".join(sids), c) if sids else "path " + c)
    return out


def main(argv):
    if len(argv) != 5 or argv[1] != "attribute":
        return 2
    data = sys.stdin.read()
    parts = data.split("\0")
    changed = parts[2] if len(parts) > 2 else ""
    try:
        res = attribute(argv[2], float(argv[3]), argv[4], parts[0], parts[1], changed)
    except Exception:
        res = ["path " + c for c in changed.splitlines() if c.strip()]
    for line in res:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

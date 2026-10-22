"""subagent_gate.py — the external partner runs only on a tree the goal-adversary subagent held.

WHY (p-d047a850d6, measured 2026-10-20). Over 15 days in one user's four projects, 457 codex rounds
carried a verdict, and 414 of them ran on a tree the subagent had not held: 97 with no subagent
verdict in the session yet, 156 right after a subagent break, 161 after a hold with work changed
since. 368 codex rounds broke, and 268 of those found at least one real defect: codex kept finding,
slowly, defects the cheaper subagent round finds too. Only 43 rounds ran on a tree the subagent had
held, and there codex found real defects the subagent missed in 17. That is the round it is for. So
the external partner now runs on a held tree, or after the subagent broke twice in a row (the switch
SKILL.md step 6 already mandates), and otherwise refuses with the reason.

Three steps, all fail-open:
  start (from watch-adversary-writes.sh `start`, on SubagentStart of a goal-adversary): hash the
    content of every tree the round measures, and the time, to `<agent>.gate-start` in this
    session's run directory (hooks/lib/run_dir.py).
  record (from remind-handback-verdict.sh `record`, on SubagentStop): hash it again and append the
    subagent's verdict to `subagent-rounds`. A hold over content that changed DURING the round (an
    executor edit under an in-flight background subagent: 21 of 927 rounds over 60 s in one user's
    transcripts, adversary round of 0.66.0) is recorded as `hold-moved`, which is not a hold. Since
    0.67.1 the attribution gate() uses applies there too: a change during the round that no tool call
    of this session made keeps the hold, with its paths in `moved_by_other` (moved_by_other below).
  gate (from external-adversary.sh, before the partner starts): read that file and decide.

THE CONTENT HASH is `git write-tree` of a private copy of the index after `git add -A`, with the
session's .goalspec/ left out. It does not depend on HEAD or on the real index, so committing the
held tree does not undo the hold; refreshing the checkpoint does not either. Any other change does:
a source file, a test, a doc, memory/ (where a tracked memory directory is, an unconfirmed
conclusion lands, and SKILL.md calls that write terminal). Ignored files are invisible to it.
Since 0.67.0 a change counts only when this session (or one of its subagents) may have made it after
the hold, read from its own transcript (own_changes below); a change no tool call of the session
made is another writer's, and the partner runs. With no transcript found, every change counts.

Declared limits: a round with no `start` record (the plugin installed mid-round) is judged on its
stop hash alone; content git cannot add (a file this user cannot read) gives no hash, and then the
gate lets the partner run rather than block for good; a nested repository or submodule is one entry
to git, so edits inside it are invisible here; a session that runs the partner in a
repository the subagent never measured is refused; with no session id (CLAUDE_CODE_SESSION_ID) the
gate cannot tell sessions apart and lets the partner run.
"""
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_dir  # noqa: E402

ROUNDS = "subagent-rounds"
HOOK = "subagent-gate"


def _git(root, *args, env=None):
    r = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, env=env)
    return r.stdout.strip() if r.returncode == 0 else None


def repo_root(path):
    return _git(path, "rev-parse", "--show-toplevel") if path and os.path.isdir(path) else None


def content_hash(root):
    """-> the tree hash of the working content of `root` (tracked + untracked, not ignored, without
    .goalspec/), or None when it cannot be computed."""
    index = _git(root, "rev-parse", "--git-path", "index")
    if index is None:
        return None
    if not os.path.isabs(index):
        index = os.path.join(root, index)
    tmpd = tempfile.mkdtemp(prefix="goalspec-gate-")
    try:
        tmp_index = os.path.join(tmpd, "index")
        if os.path.isfile(index):
            # Keeps the stat cache (add -A rehashes only changed files) AND the index's own mtime:
            # git rehashes an entry as "racily clean" only by comparing it with that mtime, so a
            # plain copy (new mtime) missed a same-size edit made in the second of the last index
            # write (measured: case 03 flipped to run once in a selftest pass).
            shutil.copy2(index, tmp_index)
        env = dict(os.environ, GIT_INDEX_FILE=tmp_index)
        # No exclude pathspec: git exits 1 on it when .goalspec/ is ignored. Add everything, then
        # drop .goalspec from the private index (a no-op when it is ignored).
        if _git(root, "add", "-A", env=env) is None:
            return None
        if _git(root, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", ".goalspec", env=env) is None:
            return None
        return _git(root, "write-tree", env=env)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def _roots_of(snap, agent_id, cwd):
    """The trees the adversary-writes rail measured for this agent (root lines of its snapshot,
    hooks/watch-adversary-writes.sh), else the repository of the session's cwd."""
    roots = []
    akey = _akey(agent_id)
    fp = os.path.join(snap, akey + ".fp") if akey else ""
    if fp and os.path.isfile(fp):
        with open(fp, encoding="utf-8", errors="replace") as fh:
            roots = [l[5:].rstrip("\n") for l in fh if l.startswith("root ")]
    if not roots:
        r = repo_root(cwd)
        roots = [r] if r else []
    return roots


def _akey(agent_id):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(agent_id or ""))[:120]


def start(snap, agent_key, roots):
    """Hash the content a round starts from (called with the run directory and agent key the
    adversary-writes rail already resolved)."""
    if not snap or not agent_key or not os.path.isdir(snap):
        return
    # The time first: own_changes() reads the session's writes at or after it, and a write made
    # while the hashes are computed must not fall before it.
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(os.path.join(snap, agent_key + ".gate-start"), "w", encoding="utf-8") as fh:
        json.dump({"ts": ts, "trees": {r: content_hash(r) for r in roots if r}}, fh)


def record(session_id, agent_id, verdict, cwd):
    """Append one round. Only `hold` and `break` are recorded: a report with no well-formed verdict
    is neither, and must not reset a streak or stand in for a hold."""
    if verdict not in ("hold", "break"):
        return
    snap = run_dir.ensure(session_id, HOOK)
    if not snap:
        return
    roots = _roots_of(snap, agent_id, cwd)
    trees = {r: content_hash(r) for r in roots}
    began = {}
    sp = os.path.join(snap, _akey(agent_id) + ".gate-start")
    if os.path.isfile(sp):
        try:
            with open(sp, encoding="utf-8") as fh:
                began = json.load(fh)
        except (OSError, ValueError):
            began = {}
        try:
            os.remove(sp)
        except OSError:
            pass
    # A start record from 0.67.0 or older is the bare {root: hash} map, with no time: a change
    # during that round cannot be attributed, and it stays hold-moved.
    began = began if isinstance(began, dict) else {}
    began_ts = began.get("ts") if isinstance(began.get("trees"), dict) else None
    began = began["trees"] if isinstance(began.get("trees"), dict) else began
    moved = [r for r, h in sorted(trees.items()) if r in began and began[r] != h]
    by_other = []
    if verdict == "hold" and moved:
        by_other = moved_by_other(session_id, began_ts, {r: (began[r], trees[r]) for r in moved})
        if not by_other:
            verdict = "hold-moved"
    rec = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "agent": str(agent_id or ""), "verdict": verdict, "trees": trees}
    if by_other:
        rec["moved_by_other"] = by_other
    with open(os.path.join(snap, ROUNDS), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def moved_by_other(session_id, since, hashes):
    """-> the paths ("<root>/<path>") that changed during a round when no tool call of this session
    wrote any of them after `since` (the round's start), else []. Since 0.67.1: until then any
    change during the round made it hold-moved, and on 2026-10-21 that refused the partner in 7 of
    19 calls on one Mac, every one of them while another session wrote memory/ or handoffs/ in the
    same checkout. [] (stay hold-moved) when the start has no time, a hash is missing, git cannot
    list the paths, or the transcript is not found: the same direction gate() fails in."""
    if not since or any(b is None or a is None for b, a in hashes.values()):
        return []
    paths = {r: changed_paths(r, b, a) for r, (b, a) in hashes.items()}
    if not all(paths.values()):
        return []
    own = own_changes(session_id, since, paths)
    if own is None or own:
        return []
    return sorted(os.path.join(r, p) for r, ps in paths.items() for p in ps)


def gate(session_id, cwd):
    """-> (run: bool, reason: str)."""
    if os.environ.get("GOAL_ADVERSARY_AFTER_SUBAGENT", "1") == "0":
        return True, "off (GOAL_ADVERSARY_AFTER_SUBAGENT=0)"
    if not session_id:
        return True, "no session id"
    here = repo_root(cwd)
    if not here:
        return True, "not in a git repository"
    snap = run_dir.ensure(session_id, HOOK, here)
    if not snap:
        return True, "this session's state directory cannot be used"
    rounds = []
    path = os.path.join(snap, ROUNDS)
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("verdict") in ("hold", "break", "hold-moved"):
                    rounds.append(r)
    if not rounds:
        return False, ("no goal-adversary subagent round has finished in this session yet. Run the "
                       "subagent first; the external partner reviews the tree it held.")
    streak = 0
    for r in reversed(rounds):
        if r["verdict"] != "break":
            break
        streak += 1
    if streak >= 2:
        return True, "the subagent broke %d rounds in a row (SKILL.md step 6: switch backend)" % streak
    last = rounds[-1]
    if last["verdict"] == "hold-moved":
        return False, ("the content changed while the last goal-adversary subagent round (%s) was "
                       "running, so its hold covers content that is gone. Run the subagent again on the "
                       "current tree." % last["ts"])
    if last["verdict"] == "break":
        return False, ("the last goal-adversary subagent round (%s) broke. Fix what it found and run "
                       "the subagent again; the external partner reviews the tree it held." % last["ts"])
    trees = last.get("trees") or {}
    if here not in trees:
        return False, ("the subagent's last hold (%s) measured %s, not this repository (%s). Run the "
                       "subagent on this tree." % (last["ts"], ", ".join(sorted(trees)) or "no tree", here))
    if any(h is None for h in trees.values()):
        return True, "the content of the held tree could not be hashed (git add failed)"
    now = {r: content_hash(r) for r in sorted(trees)}
    if any(h is None for h in now.values()):
        return True, "the current content could not be hashed (git add failed)"
    changed = [r for r, h in sorted(trees.items()) if now[r] != h]
    if changed:
        paths = {r: changed_paths(r, trees[r], now[r]) for r in changed}
        own = own_changes(session_id, last["ts"], paths)
        if own is not None and not own and all(paths[r] for r in changed):
            shown = sorted(p for r in changed for p in paths[r])
            return True, ("the subagent held this content at %s; what changed since (%s) is in no Write or Edit of "
                          "this session's transcript, so another writer made it (a shared ledger, another "
                          "account) or a Bash write of this session, which is not attributed" % (last["ts"], ", ".join(shown[:5]) + (" and %d more" % (len(shown) - 5)
                                                                           if len(shown) > 5 else "")))
        return False, ("the content changed after the subagent's last hold (%s) in %s (.goalspec/ "
                       "and a commit of the same content do not count). Run the subagent on the "
                       "current tree first." % (last["ts"], _few(sorted(own) if own else changed)))
    if last.get("moved_by_other"):
        return True, ("the subagent held this content at %s; what changed during that round (%s) is in no "
                      "Write or Edit of this session's transcript, so another writer made it (a shared ledger, "
                      "another session in this checkout) or a Bash write of this session, which is not attributed"
                      % (last["ts"], _few(last["moved_by_other"])))
    return True, "the subagent held this content at %s" % last["ts"]


def _few(items, n=5):
    return ", ".join(items[:n]) + (" and %d more" % (len(items) - n) if len(items) > n else "")


def changed_paths(root, before, after):
    """-> the paths that differ between two content hashes of `root`, or [] when git cannot say."""
    out = _git(root, "diff-tree", "-r", "--name-only", "--no-renames", before, after)
    return [p for p in (out or "").splitlines() if p]


# A git command that rewrites the working tree without naming the files it changes: after one of
# these, every changed path counts as this session's.
_GIT_REWRITE = re.compile(r"\bgit\b(?:\s+-[Cc]\s+\S+)*\s+(merge|pull|rebase|checkout|switch|reset|stash|am|"
                          r"apply|cherry-pick|revert|restore|mv|rm|clean|read-tree|checkout-index)\b")


# Text a command carries as data, not as a command: a heredoc body (an adversary payload, a file
# written with cat <<EOF) and a quoted string (a commit message). A git verb inside either is not a
# git command that ran.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
_QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


def _command_text(cmd):
    return _QUOTED.sub(" ", _HEREDOC.sub(" ", cmd))


def session_transcripts(session_id):
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    if not os.path.isabs(base) or not session_id:
        return []
    found = glob.glob(os.path.join(base, "projects", "*", glob.escape(session_id) + ".jsonl"))
    found += glob.glob(os.path.join(base, "projects", "*", glob.escape(session_id), "subagents", "*.jsonl"))
    return found


def _epoch(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def own_changes(session_id, since, paths):
    """-> the changed paths ("<root>/<path>") this session may have written after `since`, or None
    when its transcript is not found (then nothing can be attributed and the gate blocks as before).

    A path is this session's when, at or after the hold, one of its own or its subagents' Write,
    Edit, MultiEdit or NotebookEdit calls wrote it and did not fail, or when a git command that
    rewrites the tree without naming files ran (merge, pull, rebase, checkout, reset, stash and the
    like; then every path is). A git verb inside a heredoc body or a quoted string is data, not a
    command. Anything else is another writer's: the shared memory ledger other accounts append to on
    a shared server, which kept the partner from running there on 2026-10-20 in 6 of 32 attempts the
    server's log states, and probably in 9 more it cannot prove.

    Bash writes are deliberately not attributed. Guessing them from command text was tried three ways
    in the 0.67.0 review rounds (any mention of the path, then only commands that can write, then the
    path and not the bare file name), and each time the external partner found an ordinary command the
    guess got wrong in the expensive direction: a read of the ledger, a write to another file with the
    same name, a payload heredoc that mentions the ledger path, each blocked a review this rule exists
    to let run. A Bash write this session makes (sed -i, a redirect, a script) therefore lets the
    partner run on content the subagent did not hold: that costs a round and never blocks a review."""
    files = session_transcripts(session_id)
    start = _epoch(since)
    if not files or start is None:
        return None
    want = {}
    for root, ps in paths.items():
        for p in ps:
            want[os.path.join(root, p)] = (root, p)
    want_real = {abs_p: os.path.normcase(os.path.realpath(abs_p)) for abs_p in want}
    own = set()
    for f in files:
        writes = []  # (tool_use id, real path)
        failed = set()
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            return None
        with fh:
            for line in fh:
                if '"tool_use"' not in line and '"is_error"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                content = (e.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result" and b.get("is_error"):
                        failed.add(b.get("tool_use_id"))
                        continue
                    if b.get("type") != "tool_use":
                        continue
                    t = _epoch(e.get("timestamp"))
                    if t is None or t < int(start):
                        continue
                    inp = b.get("input")
                    inp = inp if isinstance(inp, dict) else {}
                    name = b.get("name")
                    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                        fp = inp.get("file_path") or inp.get("notebook_path") or ""
                        # realpath on both sides: git prints /private/var/... where the agent
                        # wrote /var/... (a symlink on macOS), and a match by spelling misses it.
                        if isinstance(fp, str) and os.path.isabs(fp):
                            writes.append((b.get("id"), os.path.normcase(os.path.realpath(fp))))
                    elif name == "Bash" and _GIT_REWRITE.search(_command_text(str(inp.get("command") or ""))):
                        return set(want)
        for tid, fp in writes:
            if tid in failed:
                continue
            for abs_p, real in want_real.items():
                if real == fp:
                    own.add(abs_p)
    return own


if __name__ == "__main__":
    # start <run dir> <agent key>   (roots on stdin, one per line)
    if len(sys.argv) >= 4 and sys.argv[1] == "start":
        try:
            start(sys.argv[2], sys.argv[3], [l.strip() for l in sys.stdin if l.strip()])
        except Exception:
            pass
        sys.exit(0)
    # gate <cwd>   (session id from CLAUDE_CODE_SESSION_ID). Prints RUN|BLOCK<TAB>reason; exit 0.
    if len(sys.argv) >= 3 and sys.argv[1] == "gate":
        try:
            ok, why = gate(os.environ.get("CLAUDE_CODE_SESSION_ID", ""), sys.argv[2])
        except Exception as e:  # fail-open: a broken gate never stops a review
            ok, why = True, "the gate failed (%s)" % e.__class__.__name__
        print(("RUN" if ok else "BLOCK") + "\t" + why)

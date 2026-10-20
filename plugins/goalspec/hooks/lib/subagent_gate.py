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
    content of every tree the round measures, to `<agent>.gate-start` in this session's run
    directory (hooks/lib/run_dir.py).
  record (from remind-handback-verdict.sh `record`, on SubagentStop): hash it again and append the
    subagent's verdict to `subagent-rounds`. A hold over content that changed DURING the round (an
    executor edit under an in-flight background subagent: 21 of 927 rounds over 60 s in one user's
    transcripts, adversary round of 0.66.0) is recorded as `hold-moved`, which is not a hold.
  gate (from external-adversary.sh, before the partner starts): read that file and decide.

THE CONTENT HASH is `git write-tree` of a private copy of the index after `git add -A`, with the
session's .goalspec/ left out. It does not depend on HEAD or on the real index, so committing the
held tree does not undo the hold; refreshing the checkpoint does not either. Any other change does:
a source file, a test, a doc, memory/ (where a tracked memory directory is, an unconfirmed
conclusion lands, and SKILL.md calls that write terminal). Ignored files are invisible to it.

Declared limits: a round with no `start` record (the plugin installed mid-round) is judged on its
stop hash alone; content git cannot add (a file this user cannot read) gives no hash, and then the
gate lets the partner run rather than block for good; a nested repository or submodule is one entry
to git, so edits inside it are invisible here; a session that runs the partner in a
repository the subagent never measured is refused; with no session id (CLAUDE_CODE_SESSION_ID) the
gate cannot tell sessions apart and lets the partner run.
"""
import datetime
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
    with open(os.path.join(snap, agent_key + ".gate-start"), "w", encoding="utf-8") as fh:
        json.dump({r: content_hash(r) for r in roots if r}, fh)


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
    if verdict == "hold" and any(r in began and began[r] != h for r, h in trees.items()):
        verdict = "hold-moved"
    rec = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "agent": str(agent_id or ""), "verdict": verdict, "trees": trees}
    with open(os.path.join(snap, ROUNDS), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


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
    changed = [r for r, h in sorted(trees.items()) if content_hash(r) != h]
    if changed:
        return False, ("the content changed after the subagent's last hold (%s) in %s (.goalspec/ "
                       "and a commit of the same content do not count). Run the subagent on the "
                       "current tree first." % (last["ts"], ", ".join(changed)))
    return True, "the subagent held this content at %s" % last["ts"]


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

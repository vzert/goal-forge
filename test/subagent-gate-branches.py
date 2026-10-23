#!/usr/bin/env python3
"""Branch suite for the subagent-first gate of the external partner (0.66.0, p-d047a850d6):
plugins/goalspec/hooks/lib/subagent_gate.py, its `record` call in remind-handback-verdict.sh and its
`gate` call in external-adversary.sh.

    python3 test/subagent-gate-branches.py              # the cases
    python3 test/subagent-gate-branches.py --selftest   # break the component, require a case to notice

Every case builds a throwaway git repository with one committed file, records zero or more
goal-adversary subagent rounds the way the harness does (remind-handback-verdict.sh `record` on a
synthetic SubagentStop payload, with a synthetic subagent transcript), optionally changes the tree,
then runs external-adversary.sh with a stub partner (`cat` of a hold). The outcome is `run` when the
partner ran (its verdict is in the output) and `block` when the hook refused (exit 3 and the
unprefixed NOT RUN line, no verdict line). Hermetic: per-case TMPDIR, XDG_STATE_HOME/LOCALAPPDATA
and HOME, no network, no real ~/.claude.

No predecessor exists (new in 0.66.0), so `--selftest` copies the plugin, applies one mutation at a
time, and requires at least one case to notice.
"""
import concurrent.futures, datetime, glob, json, os, shutil, subprocess, sys, tempfile
import tmp_cleanup  # this run's own TMPDIR, removed at exit (p-1a5a4e9828)
from suite_bash import BASH  # noqa: E402 — Git Bash on Windows, plain "bash" elsewhere

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
GATE_REL = os.path.join("hooks", "lib", "subagent_gate.py")
EXT_REL = os.path.join("hooks", "external-adversary.sh")
HBV_REL = os.path.join("hooks", "remind-handback-verdict.sh")
WATCH_REL = os.path.join("hooks", "watch-adversary-writes.sh")

MODEL = "[ADVERSARY-MODEL: Sonnet 5.5 / claude-sonnet-5-5]"
HOLD = "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
BREAK = "[ADVERSARY-VERDICT: break ungrounded=1 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
PARTNER_OUT = ("[ADVERSARY-MODEL: GPT-5 / UNKNOWN]\n- re-ran the suite: green\n- pursued and refuted: x\n"
               "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]\n")
SID, OTHER = "sess-gate-1", "sess-gate-2"


def git(repo, *a):
    subprocess.run(["git", "-C", repo] + list(a), check=True, capture_output=True)


class Case:
    def __init__(self, plugin, tmp):
        self.plugin, self.tmp = plugin, tmp
        self.repo = os.path.join(tmp, "repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        with open(os.path.join(self.repo, "work.py"), "w") as fh:
            fh.write("x = 1\n")
        with open(os.path.join(self.repo, ".gitignore"), "w") as fh:
            fh.write(".goalspec/\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        self.env = dict(os.environ, TMPDIR=tmp, CLAUDE_PLUGIN_ROOT=plugin,
                        XDG_STATE_HOME=os.path.join(tmp, "state"), LOCALAPPDATA=os.path.join(tmp, "state"),
                        HOME=os.path.join(tmp, "home"), CLAUDE_CONFIG_DIR=os.path.join(tmp, "cfg"))
        for k in ("CLAUDE_CODE_SESSION_ID", "GOAL_ADVERSARY_ACTIVE", "GOAL_ADVERSARY_AFTER_SUBAGENT",
                  "GOAL_ADVERSARY_TIMEOUT", "GOAL_CONFIG_PATH"):
            self.env.pop(k, None)
        os.makedirs(self.env["HOME"], exist_ok=True)
        self.n = 0

    def begin(self, sid=SID):
        """SubagentStart of the next round, through the real adversary-writes rail (which hashes
        the content the round starts from)."""
        payload = {"hook_event_name": "SubagentStart", "session_id": sid, "agent_type": "goalspec:goal-adversary",
                   "agent_id": "a%d" % (self.n + 1), "cwd": self.repo}
        subprocess.run([BASH, os.path.join(self.plugin, WATCH_REL), "start"], input=json.dumps(payload),
                       capture_output=True, text=True, env=self.env, cwd=self.repo)

    def subagent(self, report, sid=SID, cwd=None, stop=False, cut=False):
        """One finished goal-adversary round, recorded as the harness would on SubagentStop (with
        stop=True the rail's own `stop` runs first, as it does beside `record`)."""
        if stop:
            payload = {"hook_event_name": "SubagentStop", "session_id": sid, "agent_type": "goalspec:goal-adversary",
                       "agent_id": "a%d" % (self.n + 1), "cwd": self.repo}
            subprocess.run([BASH, os.path.join(self.plugin, WATCH_REL), "stop"], input=json.dumps(payload),
                           capture_output=True, text=True, env=self.env, cwd=self.repo)
        self.n += 1
        tp = os.path.join(self.tmp, "agent-%d.jsonl" % self.n)
        with open(tp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "SubagentHandback", "id": "h%d" % self.n,
                 "input": {"message": report}}]}}) + "\n")
        payload = {"hook_event_name": "SubagentStop", "session_id": sid, "agent_type": "goalspec:goal-adversary",
                   "agent_id": "a%d" % self.n, "agent_transcript_path": tp, "cwd": cwd or self.repo}
        env = self.env
        if cut:
            # The harness killing `record` mid-hash (a hook timeout): a `git` that kills the
            # process that ran it, the moment the content hash starts listing the tree (0.68.3) or
            # adding it (0.68.2 and older, so the case reproduces the bug there).
            bindir = os.path.join(self.tmp, "cutbin")
            os.makedirs(bindir, exist_ok=True)
            with open(os.path.join(bindir, "git"), "w") as fh:
                fh.write('#!/bin/bash\ncase " $* " in *" ls-files -z -m "*|*" add -A "*) kill -9 $PPID; exit 1 ;; esac\n'
                         'exec %s "$@"\n' % shutil.which("git"))
            os.chmod(os.path.join(bindir, "git"), 0o755)
            env = dict(self.env, PATH=bindir + os.pathsep + self.env.get("PATH", ""))
        subprocess.run([BASH, os.path.join(self.plugin, HBV_REL), "record"], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, cwd=self.repo)

    def write(self, rel, text):
        p = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)

    def transcript(self, *calls, sid=SID, sub=False, ago=0, cwd=None):
        """Append tool calls to this session's own transcript (sub=True: a subagent's), stamped now
        minus `ago` seconds, with the cwd the harness records on every entry (default: the repo).
        Each call is (name, input)."""
        base = os.path.join(self.env["CLAUDE_CONFIG_DIR"], "projects", "-tmp-repo")
        d = os.path.join(base, sid, "subagents") if sub else base
        os.makedirs(d, exist_ok=True)
        ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=ago)).isoformat()
        with open(os.path.join(d, "w.jsonl" if sub else sid + ".jsonl"), "a", encoding="utf-8") as fh:
            for name, inp in calls:
                self.n += 1
                fh.write(json.dumps({"type": "assistant", "timestamp": ts.replace("+00:00", "Z"), "cwd": cwd or self.repo,
                                     "message": {"content": [{"type": "tool_use", "id": "t%d" % self.n, "name": name,
                                                              "input": inp}]}}) + "\n")

    def partner(self, sid=SID, cwd=None, show=False, **extra):
        """show=True: the stub partner prints the work.py of the tree it reviews first, and the
        outcome says which tree that was (run-in:<its first line>) when the gate moved it."""
        fx = os.path.join(self.tmp, "partner.txt")
        with open(fx, "w") as fh:
            fh.write(PARTNER_OUT)
        cmd = "cat " + fx
        if show:
            stub = os.path.join(self.tmp, "partner.sh")
            with open(stub, "w") as fh:
                fh.write('printf "reviewed: %%s\\n" "$(head -n 1 work.py)"\ncat "%s"\n' % fx.replace("\\", "/"))
            cmd = "bash " + stub.replace("\\", "/")
        env = dict(self.env, GOAL_ADVERSARY_CMD=cmd, GOAL_ADVERSARY_TIMEOUT="0")
        if sid:
            env["CLAUDE_CODE_SESSION_ID"] = sid
        env.update(extra)
        r = subprocess.run([BASH, os.path.join(self.plugin, EXT_REL)], input="pointers: work.py\n",
                           capture_output=True, text=True, env=env, cwd=cwd or self.repo)
        out = r.stdout + r.stderr
        self.last_out = out
        if r.returncode == 3 and "NOT RUN (goalspec external adversary):" in out and "[ADVERSARY-VERDICT:" not in out:
            return "block"
        if "re-ran the suite: green" in out and "so the partner reviews" in r.stderr:
            seen = [l.split("reviewed: ", 1)[1].strip() for l in out.splitlines() if "reviewed: " in l]
            return "run-in:" + (seen[0] if seen else "?")
        if "re-ran the suite: green" in out:
            if "was cut before it finished" in r.stderr:
                return "run+cut"
            return "run+notice" if "so another writer made it" in r.stderr else "run"
        return "other(rc=%d)" % r.returncode


H = MODEL + "\n- re-ran the suite: green\n" + HOLD
B = MODEL + "\n- figure does not re-derive\n" + BREAK


def c01(c):  # the 97 rounds: no subagent round yet
    return c.partner()


def c02(c):
    c.subagent(H)
    return c.partner()


def c03(c):  # the 161: work changed after the hold
    c.subagent(H)
    c.write("work.py", "x = 2\n")
    return c.partner()


def c04(c):  # refreshing the checkpoint does not undo the hold
    c.subagent(H)
    c.write(".goalspec/checkpoint-%s.md" % SID, "## Goal-spec\nHEAD now\n")
    return c.partner()


def c16(c):  # same, in a project that does not ignore .goalspec/
    os.remove(os.path.join(c.repo, ".gitignore"))
    git(c.repo, "commit", "-qam", "track run state")
    c.write(".goalspec/checkpoint-%s.md" % SID, "v1\n")
    c.subagent(H)
    c.write(".goalspec/checkpoint-%s.md" % SID, "v2\n")
    return c.partner()


def c05(c):  # committing the held content does not undo the hold
    c.write("work.py", "x = 3\n")
    c.subagent(H)
    git(c.repo, "commit", "-qam", "held")
    return c.partner()


def c06(c):  # the 156: right after a subagent break
    c.subagent(B)
    return c.partner()


def c07(c):  # two breaks in a row: the switch SKILL.md step 6 mandates
    c.subagent(B)
    c.subagent(B)
    return c.partner()


def c08(c):  # a hold between the breaks resets the streak
    c.subagent(B)
    c.subagent(H)
    c.subagent(B)
    return c.partner()


def c09(c):  # a new untracked file is a change
    c.subagent(H)
    c.write("new_test.py", "assert True\n")
    return c.partner()


def c10(c):  # no session id: cannot tell sessions apart, fail-open
    return c.partner(sid="")


def c11(c):  # the human's off switch
    return c.partner(GOAL_ADVERSARY_AFTER_SUBAGENT="0")


def c12(c):  # another session's hold does not count here
    c.subagent(H, sid=OTHER)
    return c.partner()


def c13(c):  # a report with no usable verdict neither holds nor breaks
    c.subagent(H)
    c.subagent(MODEL + "\n- ran out of time\n")
    return c.partner()


def c14(c):  # a hold measured on another repository
    other = os.path.join(c.tmp, "elsewhere")
    os.makedirs(other)
    git(other, "init", "-q")
    c.subagent(H, cwd=other)
    return c.partner()


def c15(c):  # a deleted file is a change
    c.subagent(H)
    os.remove(os.path.join(c.repo, "work.py"))
    return c.partner()


def c17(c):  # an executor edit DURING the round: the hold covers content that is gone
    c.begin()
    c.write("work.py", "x = 9\n")
    c.subagent(H, stop=True)
    return c.partner()


def c18(c):  # the real start/stop rail with no change during the round
    c.begin()
    c.subagent(H, stop=True)
    return c.partner()


def c29(c):  # unhashable content appears AFTER the hold: run with that reason, not a crash
    c.subagent(H)
    p = os.path.join(c.repo, "secret2.bin")
    with open(p, "w") as fh:
        fh.write("s\n")
    os.chmod(p, 0)
    try:
        fx = os.path.join(c.tmp, "partner.txt")
        with open(fx, "w") as fh:
            fh.write(PARTNER_OUT)
        env = dict(c.env, GOAL_ADVERSARY_CMD="cat " + fx, GOAL_ADVERSARY_TIMEOUT="0", CLAUDE_CODE_SESSION_ID=SID)
        r = subprocess.run([sys.executable, os.path.join(c.plugin, GATE_REL), "gate", c.repo],
                           capture_output=True, text=True, env=env, cwd=c.repo)
        return "run-unhashable" if r.stdout.startswith("RUN\tthe current content could not be hashed") else r.stdout.strip()[:60]
    finally:
        os.chmod(p, 0o600)


def c19(c):  # content git cannot hash (an unreadable untracked file): run, never block for good
    c.subagent(H)
    p = os.path.join(c.repo, "secret.bin")
    with open(p, "w") as fh:
        fh.write("s\n")
    os.chmod(p, 0)
    try:
        c.subagent(H)
        return c.partner()
    finally:
        os.chmod(p, 0o600)


def c30(c):  # this session only READ the ledger another writer changed (codex round, 0.67.0)
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    c.transcript(("Bash", {"command": "sed -n 1,5p memory/review-stats/ledger.jsonl 2>/dev/null; ls memory/review-stats"}))
    return c.partner()


def c31(c):  # a redirect into the path is not attributed either
    c.subagent(H)
    c.write("work.py", "x = 2\n")
    c.transcript(("Bash", {"command": "echo 'x = 2' > work.py"}))
    return c.partner()


def c32(c):  # this session wrote b/work.py (Write); another writer changed a/work.py (same file name)
    c.subagent(H)
    c.write("a/work.py", "x = 1\n")
    c.write("b/work.py", "x = 2\n")
    git(c.repo, "add", "-A")  # both tracked; the hold measured neither, so both changed
    c.transcript(("Write", {"file_path": os.path.join(c.repo, "b", "work.py"), "content": "x = 2\n"}))
    return "own-only-b" if c.partner() == "block" and _reason_names(c, "b/work.py", "a/work.py") else "other"


def _reason_names(c, want, not_want):
    env = dict(c.env, CLAUDE_CODE_SESSION_ID=SID)
    r = subprocess.run([sys.executable, os.path.join(c.plugin, GATE_REL), "gate", c.repo],
                       capture_output=True, text=True, env=env, cwd=c.repo)
    return want in r.stdout and not_want not in r.stdout


def c33(c):  # an Edit that failed changed nothing: the change is another writer's
    c.subagent(H)
    c.write("work.py", "x = 2\n")
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "work.py"), "old_string": "zz", "new_string": "2"}))
    base = os.path.join(c.env["CLAUDE_CONFIG_DIR"], "projects", "-tmp-repo", SID + ".jsonl")
    with open(base, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t%d" % c.n, "is_error": True,
             "content": "String to replace not found"}]}}) + "\n")
    return c.partner()


def c34(c):  # a payload heredoc that names the ledger and a git verb is data, not a write or a command
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    c.transcript(("Bash", {"command": "cat > /tmp/payload.txt <<'EOF'\nread memory/review-stats/ledger.jsonl\n"
                                      "after git merge origin/main\nEOF\ngit commit -m \"before git reset\""}))
    return c.partner()


def c28(c):  # an ordinary held run prints no other-writer notice
    c.subagent(H)
    return c.partner()


def c20(c):  # another writer (a shared ledger) changed a file; this session wrote nothing since
    c.transcript(("Read", {"file_path": os.path.join(c.repo, "work.py")}))
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    return c.partner()


def c21(c):  # this session edited the file after the hold
    c.subagent(H)
    c.write("work.py", "x = 2\n")
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "work.py"), "old_string": "1", "new_string": "2"}))
    return c.partner()


def c22(c):  # a Bash write is not attributed (0.67.0 design): the partner runs, which costs a round
    c.subagent(H)
    c.write("work.py", "x = 2\n")
    c.transcript(("Bash", {"command": "sed -i.bak 's/1/2/' work.py"}))
    return c.partner()


def c23(c):  # a git command that rewrites the tree without naming files: every path is this session's
    c.subagent(H)
    c.write("other.py", "y = 1\n")
    c.transcript(("Bash", {"command": "git " + "merge origin/main"}))
    return c.partner()


def c24(c):  # an edit BEFORE the hold does not make a later change by someone else this session's
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "work.py"), "old_string": "1", "new_string": "1"}), ago=3600)
    c.subagent(H)
    c.write("work.py", "x = 5\n")
    return c.partner()


def c25(c):  # a subagent of this session wrote it after the hold (its main transcript wrote nothing)
    c.transcript(("Read", {"file_path": os.path.join(c.repo, "work.py")}))
    c.subagent(H)
    c.write("work.py", "x = 2\n")
    c.transcript(("Write", {"file_path": os.path.join(c.repo, "work.py"), "content": "x = 2\n"}), sub=True)
    return c.partner()


def c26(c):  # the ledger changed AND this session edited the work: blocks
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    c.write("work.py", "x = 2\n")
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "work.py"), "old_string": "1", "new_string": "2"}))
    return c.partner()


def c27(c):  # another session's transcript writing the path does not make it this session's
    c.transcript(("Read", {"file_path": "x"}))
    c.subagent(H)
    c.write("work.py", "x = 2\n")
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "work.py"), "old_string": "1", "new_string": "2"}), sid=OTHER)
    return c.partner()


def c35(c):  # another writer changed a file DURING the round (0.67.1: 7 of 19 calls on 2026-10-21)
    c.transcript(("Read", {"file_path": os.path.join(c.repo, "work.py")}))
    c.begin()
    c.write("memory/sessions/other.md", "another session\n")
    c.subagent(H, stop=True)
    return c.partner()


def c36(c):  # this session edited the work DURING the round: the hold covers content that is gone
    c.begin()
    c.write("work.py", "x = 2\n")
    n = c.n  # transcript() counts calls; the stop must name the agent begin() started
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "work.py"), "old_string": "1", "new_string": "2"}))
    c.n = n
    c.subagent(H, stop=True)
    return c.partner()


def c37(c):  # another writer AND this session's edit during the round: blocks
    c.begin()
    c.write("memory/sessions/other.md", "another session\n")
    c.write("work.py", "x = 2\n")
    n = c.n  # transcript() counts calls; the stop must name the agent begin() started
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "work.py"), "old_string": "1", "new_string": "2"}))
    c.n = n
    c.subagent(H, stop=True)
    return c.partner()


def c38(c):  # a start record from 0.67.0 (no time): a change during that round cannot be attributed
    c.transcript(("Read", {"file_path": os.path.join(c.repo, "work.py")}))
    c.begin()
    for p in glob.glob(os.path.join(c.env["XDG_STATE_HOME"], "**", "*.gate-start"), recursive=True):
        with open(p, encoding="utf-8") as fh:
            rec = json.load(fh)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rec["trees"], fh)
    c.write("memory/sessions/other.md", "another session\n")
    c.subagent(H, stop=True)
    return c.partner()


def c39(c):  # a change during the round with no transcript found: nothing can be attributed
    c.begin()
    c.write("memory/sessions/other.md", "another session\n")
    c.subagent(H, stop=True)
    return c.partner()


def loose_objects(repo):
    d = os.path.join(repo, ".git", "objects")
    return sum(len(fs) for r, _, fs in os.walk(d) if os.path.basename(r) not in ("pack", "info"))


def c41(c):  # 0.68.3: hashing the content stores nothing in the repository's .git
    c.write("big/new.bin", "x" * 100000)
    before = loose_objects(c.repo)
    c.begin()
    c.subagent(H, stop=True)
    got = c.partner()
    return "%s,objects+%d" % (got, loose_objects(c.repo) - before)


def c42(c):  # 0.68.3: `record` cut after the hold (a hook timeout): run, and say why
    c.subagent(H, cut=True)
    return c.partner()


def c43(c):  # the same cut after a break still blocks as a break
    c.subagent(B, cut=True)
    return c.partner()


def c44(c):  # a cut hold, then a full round of a later agent: judged on the full one
    c.subagent(H, cut=True)
    c.subagent(H)
    return c.partner()


def c45(c):  # a commit inside an untracked nested repository after the hold is a change
    sub = os.path.join(c.repo, "sub")
    os.makedirs(sub)
    git(sub, "init", "-q")
    git(sub, "config", "user.email", "t@t")
    git(sub, "config", "user.name", "t")
    with open(os.path.join(sub, "f"), "w") as fh:
        fh.write("1\n")
    git(sub, "add", "-A")
    git(sub, "commit", "-qm", "1")
    c.subagent(H)
    with open(os.path.join(sub, "f"), "w") as fh:
        fh.write("2\n")
    git(sub, "commit", "-qam", "2")
    return c.partner()


def make_repo(path, text):
    os.makedirs(path)
    git(path, "init", "-q")
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")
    with open(os.path.join(path, "work.py"), "w") as fh:
        fh.write(text)
    git(path, "add", "-A")
    git(path, "commit", "-qm", "init")
    return path


def worktree(c, name, text):
    wt = os.path.join(c.tmp, name)
    git(c.repo, "worktree", "add", "-q", "-b", name, wt)
    with open(os.path.join(wt, "work.py"), "w") as fh:
        fh.write(text)
    return wt


def c46(c):  # 0.68.4: the subagent held a worktree of this repository; run from the main checkout
    wt = worktree(c, "wt", "x = 'wt'\n")
    c.subagent(H, cwd=wt)
    return c.partner(show=True)


def c47(c):  # 0.68.4: the subagent held a repository nested in this one (the executor had cd'd in)
    with open(os.path.join(c.repo, ".gitignore"), "a") as fh:
        fh.write("app/\n")
    app = make_repo(os.path.join(c.repo, "app"), "x = 'app'\n")
    c.subagent(H, cwd=app)
    return c.partner(show=True)


def c48(c):  # run from a repository nested INSIDE the held tree: its hold does not cover it
    with open(os.path.join(c.repo, ".gitignore"), "a") as fh:
        fh.write("app/\n")
    app = make_repo(os.path.join(c.repo, "app"), "x = 'app'\n")
    c.subagent(H)
    got = c.partner(cwd=app)
    return got + ("+inside" if "separate repository inside it" in c.last_out else "")


def c49(c):  # two held worktrees: which one the review is of is not known, so it blocks
    wt1 = worktree(c, "wt1", "x = 'wt1'\n")
    wt2 = worktree(c, "wt2", "x = 'wt2'\n")
    payload = {"hook_event_name": "PreToolUse", "session_id": SID, "cwd": c.repo, "tool_name": "Agent",
               "tool_input": {"subagent_type": "goalspec:goal-adversary",
                              "prompt": "review %s and %s" % (os.path.join(wt1, "work.py"), os.path.join(wt2, "work.py"))}}
    subprocess.run([BASH, os.path.join(c.plugin, WATCH_REL), "spawn"], input=json.dumps(payload),
                   capture_output=True, text=True, env=c.env, cwd=c.repo)
    c.begin()
    c.subagent(H, stop=True)
    got = c.partner()
    return got + ("+two" if "wt1" in c.last_out and "wt2" in c.last_out else "")


def c50(c):  # 0.68.4 (VPS hold-moved): a checkout in a clone under /tmp during the round is not this tree's
    other = make_repo(os.path.join(c.tmp, "clone"), "y = 1\n")
    c.begin()
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    n = c.n
    c.transcript(("Bash", {"command": "git -C %s checkout -q -b review" % other}))
    c.n = n  # the transcript's tool ids advance the counter the agent id is read from
    c.subagent(H, stop=True)
    return c.partner()


def c51(c):  # a `cd <other repo> &&` before the git command: it ran there
    other = make_repo(os.path.join(c.tmp, "clone"), "y = 1\n")
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    c.transcript(("Bash", {"command": "cd %s && git stash" % other}), sub=True)
    return c.partner()


def c52(c):  # a variable assigned in the same command names another repository
    other = make_repo(os.path.join(c.tmp, "clone"), "y = 1\n")
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    c.transcript(("Bash", {"command": 'W="%s"; git -C "$W" reset --hard' % other}))
    return c.partner()


def c53(c):  # the same variable naming THIS repository: every path is this session's
    c.subagent(H)
    c.write("other.py", "y = 1\n")
    c.transcript(("Bash", {"command": 'W="%s"; git -C "$W" reset --hard' % c.repo}), cwd=c.tmp)
    return c.partner()


def c54(c):  # a directory that cannot be resolved is not attributed (a Bash write is not either)
    c.subagent(H)
    c.write("other.py", "y = 1\n")
    c.transcript(("Bash", {"command": "git -C $W reset --hard"}))
    return c.partner()


def c55(c):  # a checkout in a repository nested in the tree counts only for paths inside it
    sub = make_repo(os.path.join(c.repo, "sub"), "z = 1\n")
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    c.transcript(("Bash", {"command": "git -C sub checkout -q -b x"}))
    return c.partner()


def c56(c):  # 0.68.4: a refusal names the loaded version and a newer one installed beside it
    with open(os.path.join(c.plugin, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        ver = json.load(fh)["version"]
    cache = os.path.join(c.tmp, "cache", "goalspec")
    loaded = os.path.join(cache, ver)
    shutil.copytree(c.plugin, loaded, ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(cache, "99.0.0", ".claude-plugin"))
    with open(os.path.join(cache, "99.0.0", ".claude-plugin", "plugin.json"), "w") as fh:
        json.dump({"version": "99.0.0"}, fh)
    c.plugin = loaded
    c.env["CLAUDE_PLUGIN_ROOT"] = loaded
    got = c.partner()
    return got + ("+newer" if ("goalspec %s is what this session loaded; 99.0.0 is installed" % ver) in c.last_out else "")


def c57(c):  # adversary round, 0.68.4: the usual quoted form, cd "$(git rev-parse --show-toplevel)"
    c.subagent(H)
    c.write("other.py", "y = 1\n")
    c.transcript(("Bash", {"command": 'cd "$(git rev-parse --show-toplevel)" && git checkout -- .'}))
    return c.partner()


def c58(c):  # a quoted directory with a blank in it is the directory, not `cd` alone (~)
    os.makedirs(os.path.join(c.repo, "my dir"))
    c.subagent(H)
    c.write("other.py", "y = 1\n")
    c.transcript(("Bash", {"command": 'cd "my dir" && git stash'}))
    return c.partner()


def c59(c):  # codex round, 0.68.4: a brace group, { cd OTHER && git checkout; }, ran in OTHER
    other = make_repo(os.path.join(c.tmp, "clone"), "y = 1\n")
    c.subagent(H)
    c.write("memory/review-stats/ledger.jsonl", '{"r": 1}\n')
    c.transcript(("Bash", {"command": "{ cd %s && git checkout -- .; }" % other}))
    return c.partner()


def c60(c):  # codex round, 0.68.4: after RUN-IN the round cap is the project's, where the hook was run
    os.makedirs(os.path.join(c.repo, ".claude"))
    with open(os.path.join(c.repo, ".claude", "goal.config.json"), "w") as fh:
        json.dump({"adversary": {"max_external_rounds": 1}}, fh)
    wt = worktree(c, "wt", "x = 'wt'\n")
    c.subagent(H, cwd=wt)
    first = c.partner(show=True)
    second = c.partner(show=True)
    return first + "," + second + ("+version" if "[goalspec " in c.last_out else "")


def c40(c):  # an edit BEFORE the round does not make a change during it this session's
    c.transcript(("Edit", {"file_path": os.path.join(c.repo, "memory", "sessions", "other.md"),
                           "old_string": "a", "new_string": "b"}), ago=3600)
    c.begin()
    c.write("memory/sessions/other.md", "another session\n")
    c.subagent(H, stop=True)
    return c.partner()


CASES = [
    ("01-no-subagent-round-blocks", c01, "block"),
    ("02-hold-same-tree-runs", c02, "run"),
    ("03-work-changed-after-hold-blocks", c03, "block"),
    ("04-checkpoint-only-change-runs", c04, "run"),
    ("05-commit-of-held-content-runs", c05, "run"),
    ("06-after-one-break-blocks", c06, "block"),
    ("07-two-breaks-in-a-row-run", c07, "run"),
    ("08-hold-resets-break-streak", c08, "block"),
    ("09-new-untracked-file-blocks", c09, "block"),
    ("10-no-session-id-runs", c10, "run"),
    ("11-off-switch-runs", c11, "run"),
    ("12-other-session-hold-blocks", c12, "block"),
    ("13-malformed-report-keeps-hold", c13, "run"),
    ("14-hold-on-another-repo-blocks", c14, "block"),
    ("15-deleted-file-blocks", c15, "block"),
    ("16-tracked-checkpoint-change-runs", c16, "run"),
    ("17-edit-during-round-blocks", c17, "block"),
    ("18-real-rail-no-change-runs", c18, "run"),
    ("19-unhashable-content-runs", c19, "run"),
    ("20-other-writer-change-runs", c20, "run+notice"),
    ("21-own-edit-after-hold-blocks", c21, "block"),
    ("22-own-bash-write-not-attributed-runs", c22, "run+notice"),
    ("23-own-git-rewrite-blocks", c23, "block"),
    ("24-own-edit-before-hold-runs", c24, "run+notice"),
    ("25-own-subagent-write-blocks", c25, "block"),
    ("26-ledger-plus-own-edit-blocks", c26, "block"),
    ("27-other-session-edit-runs", c27, "run+notice"),
    ("28-held-run-prints-no-notice", c28, "run"),
    ("29-unhashable-after-hold-runs", c29, "run-unhashable"),
    ("30-own-bash-read-of-ledger-runs", c30, "run+notice"),
    ("31-own-redirect-not-attributed-runs", c31, "run+notice"),
    ("32-same-file-name-elsewhere-not-own", c32, "own-only-b"),
    ("33-failed-edit-not-own-runs", c33, "run+notice"),
    ("34-heredoc-and-quoted-are-data-runs", c34, "run+notice"),
    ("35-other-writer-during-round-runs", c35, "run+notice"),
    ("36-own-edit-during-round-blocks", c36, "block"),
    ("37-other-plus-own-during-round-blocks", c37, "block"),
    ("38-old-start-record-stays-moved", c38, "block"),
    ("39-during-round-no-transcript-blocks", c39, "block"),
    ("40-own-edit-before-round-runs", c40, "run+notice"),
    ("41-hash-writes-no-objects", c41, "run,objects+0"),
    ("42-cut-record-after-hold-runs", c42, "run+cut"),
    ("43-cut-record-after-break-blocks", c43, "block"),
    ("44-full-round-after-cut-one-runs", c44, "run"),
    ("45-commit-in-nested-repo-blocks", c45, "block"),
    ("46-held-worktree-runs-there", c46, "run-in:x = 'wt'"),
    ("47-held-nested-repo-runs-there", c47, "run-in:x = 'app'"),
    ("48-cwd-nested-in-held-blocks", c48, "block+inside"),
    ("49-two-held-worktrees-block", c49, "block+two"),
    ("50-git-in-other-clone-during-round-runs", c50, "run+notice"),
    ("51-cd-other-repo-git-not-own-runs", c51, "run+notice"),
    ("52-var-other-repo-git-not-own-runs", c52, "run+notice"),
    ("53-var-this-repo-git-blocks", c53, "block"),
    ("54-unresolved-git-dir-not-own-runs", c54, "run+notice"),
    ("55-nested-repo-checkout-not-root-runs", c55, "run+notice"),
    ("56-refusal-names-newer-version", c56, "block+newer"),
    ("57-quoted-toplevel-cd-git-blocks", c57, "block"),
    ("58-quoted-dir-with-blank-blocks", c58, "block"),
    ("59-brace-group-cd-other-repo-runs", c59, "run+notice"),
    ("60-run-in-keeps-project-round-cap", c60, "run-in:x = 'wt',block+version"),
]

MUTATIONS = [
    ("gate always runs", GATE_REL, '        return False, ("no goal-adversary subagent round',
     '        return True, ("no goal-adversary subagent round'),
    ("streak of one switches", GATE_REL, "    if streak >= 2:", "    if streak >= 1:"),
    ("checkpoint counts as a change", GATE_REL, '"--ignore-unmatch", "--", ".goalspec"',
     '"--ignore-unmatch", "--", ".goalspec-none"'),
    ("hash is HEAD's tree", GATE_REL, '        return _git(root, "write-tree", "--missing-ok", env=env)',
     '        return _git(root, "rev-parse", "HEAD^{tree}")'),
    ("hash stores objects in the repo", GATE_REL, "GIT_OBJECT_DIRECTORY=store, ", ""),
    ("verdict not written before hashing", GATE_REL, '"verdict": verdict, "pending": True}) + "\\n")',
     '"verdict": verdict, "pending": True}) + "\\n") if False else None'),
    ("cut hold blocks", GATE_REL, "    if last.get(\"pending\"):\n        # Fail-open", "    if False:\n        # Fail-open"),
    ("full line does not supersede pending", GATE_REL, "                if not r.get(\"pending\"):\n                    # The full",
     "                if False:\n                    # The full"),
    ("nested repository not added", GATE_REL, '        nested = any(p.endswith(b"/")', '        nested = False and any(p.endswith(b"/")'),
    ("off switch ignored", GATE_REL, 'os.environ.get("GOAL_ADVERSARY_AFTER_SUBAGENT", "1") == "0"', "False"),
    ("malformed recorded as break", GATE_REL, '    if verdict not in ("hold", "break"):\n        return',
     '    if verdict not in ("hold", "break"):\n        verdict = "break"'),
    ("repo membership not checked", GATE_REL, "    if here not in trees:", "    if False:"),
    ("hook ignores the gate", EXT_REL, "      exit 3\n", "      :\n"),
    ("start hash ignored", GATE_REL, '        verdict = "hold-moved"', '        pass'),
    ("start never recorded", WATCH_REL, '"$PY" "$GATE_PY" start "$SNAP_DIR"', '"$PY" "$GATE_PY" nostart "$SNAP_DIR"'),
    ("unhashable blocks for good", GATE_REL, '        return True, "the content of the held tree could not be hashed',
     '        return False, "the content of the held tree could not be hashed'),
    ("own writes ignored", GATE_REL, "                if real == fp:\n                    own.add(abs_p)",
     "                if real == fp:\n                    pass"),
    ("git rewrite not counted", GATE_REL, '                    elif name == "Bash":\n', '                    elif False:\n'),
    ("hold time ignored", GATE_REL, "                    if t is None or t < int(start):", "                    if t is None:"),
    ("subagent transcripts skipped", GATE_REL, '"subagents", "*.jsonl"))\n    return found',
     '"nosubagents", "*.jsonl"))\n    return found'),
    ("other writer never attributed", GATE_REL, "        if own is not None and not own and all(", "        if False and all("),
    ("other-writer notice dropped", EXT_REL, '      echo "external-adversary: ${GATE_OUT#RUN', '      : "external-adversary: ${GATE_OUT#RUN'),
    ("current content unhashable crashes", GATE_REL, '        return True, "the current content could not be hashed (git add failed)"',
     '        pass'),
    ("failed edits counted", GATE_REL, "            if tid in failed:\n                continue", "            pass"),
    ("heredoc not stripped", GATE_REL, "    return _QUOTED.sub(keep, _HEREDOC.sub(\" \", cmd))", "    return _QUOTED.sub(keep, cmd)"),
    ("quoted not stripped", GATE_REL, "    return _QUOTED.sub(keep, _HEREDOC.sub(\" \", cmd))", "    return _HEREDOC.sub(\" \", cmd)"),
    ("record never called", HBV_REL, "        subagent_gate.record(", "        (lambda *a: None)("),
    ("during-round never attributed", GATE_REL, "    if own is None or own:\n        return []", "    if True:\n        return []"),
    ("during-round own writes ignored", GATE_REL, "    if own is None or own:\n        return []",
     "    if own is None:\n        return []"),
    ("round start time ignored", GATE_REL, "by_other = moved_by_other(session_id, began_ts,",
     'by_other = moved_by_other(session_id, "1970-01-01T00:00:00Z",'),
    ("old start record attributed", GATE_REL, 'began_ts = began.get("ts") if isinstance(began.get("trees"), dict) else None',
     'began_ts = began.get("ts") if isinstance(began.get("trees"), dict) else "1970-01-01T00:00:00Z"'),
    ("during-round notice dropped", GATE_REL, '    if last.get("moved_by_other"):', "    if False:"),
    ("held tree never moved to", GATE_REL, "    return found[0] if len(found) == 1 else None", "    return None"),
    ("ambiguous held trees pick one", GATE_REL, "    return found[0] if len(found) == 1 else None",
     "    return found[0] if found else None"),
    ("nested-inside message dropped", GATE_REL, "    if inside:\n        return (", "    if False:\n        return ("),
    ("hook ignores the held tree", EXT_REL, '      if ! cd "$GATE_ROOT" 2>/dev/null; then', "      if ! cd . 2>/dev/null; then"),
    ("git target ignored", GATE_REL, "own.update(a for a, real in want_real.items() if (real + os.sep).startswith(top))",
     "own.update(want_real)"),
    ("unresolved git dir counted", GATE_REL, "                            if not top:\n                                continue",
     "                            if not top:\n                                own.update(want_real)\n                                continue"),
    ("cd ignored", GATE_REL, '        if words[i] in ("cd", "pushd"):', '        if False:'),
    ("assignment ignored", GATE_REL, "            names[n] = v if n not in names", "            names[n] = None if n not in names"),
    ("entry cwd ignored", GATE_REL, 'str(inp.get("command") or ""), e.get("cwd"))', 'str(inp.get("command") or ""), None)'),
    ("toplevel substitution unread", GATE_REL, "    if _TOPLEVEL.fullmatch(word.strip()):", "    if False:"),
    ("quoted directory text dropped", GATE_REL, "        word = _PLACEHOLDER.sub(lambda m: quoted[int(m.group(1))], word)",
     "        word = _PLACEHOLDER.sub(\"\", word)"),
    ("brace group hides cd", GATE_REL, '        while i < len(words) and words[i] in ("{", "}", "!",',
     '        while i < len(words) and words[i] in ("}", "!",'),
    ("cap read where RUN-IN moved", EXT_REL, 'cap "$RUN_FROM" "$REVIEW_REPO"', 'cap "$(pwd)" "$REVIEW_REPO"'),
    ("cap refusal names no version", EXT_REL, '      [ -f "$GATE_PY" ] && CAP_WHY="$CAP_WHY [$(', '      false && CAP_WHY="$CAP_WHY [$('),
    ("version note dropped", GATE_REL, '            why += " [%s]" % version_note()', "            pass"),
]


def suite(plugin, first_miss=False):
    """-> (name, want, got) per case. first_miss=True (the selftest): stop at the first case whose
    outcome differs, since one is enough to catch a mutation. With 47 mutations by 60 full runs
    the selftest passed the 30-minute cap of temp-leak-check.py on macOS CI (0.68.4)."""
    rows = []
    # Windows has no mode bits: a chmod 000 file is still readable there. Shown, never dropped.
    nt_skip = {"19": "mode bits", "29": "mode bits", "42": "a bash git on PATH",
               "43": "a bash git on PATH", "44": "a bash git on PATH"} if os.name == "nt" else {}
    for name, fn, want in CASES:
        if name[:2] in nt_skip:
            rows.append((name, "skipped (windows): " + nt_skip[name[:2]], "skipped (windows): " + nt_skip[name[:2]]))
            continue
        tmp = tempfile.mkdtemp(prefix="gate-")
        try:
            got = fn(Case(plugin, tmp))
        except Exception as e:
            got = "error:" + e.__class__.__name__
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        rows.append((name, want, got))
        if first_miss and want != got:
            break
    return rows


def main():
    if "--selftest" in sys.argv:
        failed = []

        def one(mutation):
            # -> (description, the first case that caught it, or None; or "TARGET NOT FOUND")
            desc, rel, old, new = mutation
            d = tempfile.mkdtemp(prefix="gate-mut-")
            try:
                mp = os.path.join(d, "goalspec")
                shutil.copytree(PLUGIN, mp)
                f = os.path.join(mp, rel)
                s = open(f, encoding="utf-8").read()
                if old not in s:
                    return desc, "TARGET NOT FOUND"
                open(f, "w", encoding="utf-8").write(s.replace(old, new, 1))
                caught = [n for n, want, got in suite(mp, first_miss=True) if want != got]
                return desc, caught[0] if caught else None
            finally:
                shutil.rmtree(d, ignore_errors=True)
        # Each mutation has its own plugin copy and each case its own temp dir, so they run side by
        # side: one after another they passed the 30-minute cap of temp-leak-check.py on macOS CI.
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
            results = list(pool.map(one, MUTATIONS))
        for desc, caught in results:
            if caught == "TARGET NOT FOUND":
                failed.append("%s: mutation target not found (suite drifted from the code)" % desc)
                print("%-34s TARGET NOT FOUND" % desc)
                continue
            print("%-34s %s" % (desc, ("caught by " + caught) if caught else "NOT CAUGHT"))
            if not caught:
                failed.append(desc)
        if failed:
            print("\nSELFTEST FAILURES: %d\n  %s" % (len(failed), "\n  ".join(failed)))
            return 1
        print("\nOK — %d mutations, each caught by at least one case" % len(MUTATIONS))
        return 0
    rows = suite(PLUGIN)
    bad = [r for r in rows if r[1] != r[2]]
    for n, w, g in rows:
        print("%-40s %-12s %s" % (n, g, "" if w == g else "<-- FAILS (want %s)" % w))
    print("\n%d case(s) failed" % len(bad) if bad else "\nOK — %d cases" % len(rows))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

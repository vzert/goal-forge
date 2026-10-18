#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/report-adversary-writes.sh (the Stop-side reporter).

Same shape as the other suites: one row per branch, `expect` asserted on every run, exit non-zero on
an assertion failure or an unexpected `--compare` diff.

Fully hermetic: no git, no network, no Claude Code. Each case writes a synthetic findings file the
way `watch-adversary-writes.sh` would, feeds the hook a synthetic `Stop` payload, and classifies.

WHY THIS HOOK EXISTS, because it is the thing the suite is really pinning. In 0.44.0 the
SubagentStop hook both measured and emitted. Measured on 2026-09-12 in a real session
(3-tier-memory, 035edc21): a SubagentStop hook's output is delivered to the SUBAGENT that just
stopped — it lands in that agent's transcript as `isSidechain: true`, and appears ZERO times in the
executor's. The message was written in the second person for the executor ("YOU edited under an
in-flight verifier ... decide what to keep or revert"), so the adversary that received it recorded
that it "misread it as a cue that I had become the executor" and wrote to five files in the
repository under review. Stop output, by contrast, lands in the executor's own transcript with
`isSidechain: false` — verified in that same file. Hence the split: measure there, report here.

Two assertions carry that lesson and must not be softened:
  * the message opens with an explicit AUDIENCE line that disarms an adversary reading it in a
    transcript (case 08) — the executor's transcript is exactly what an adversary reads for its
    principle-4 check, so this text will end up in front of one;
  * a finding is reported ONCE and the file is deleted (case 09), or every later turn re-reports a
    stale finding as if it were new.

THE BASELINE FOR THIS SUITE IS NOT 0.44.0, and saying so matters. This hook did not exist in
0.44.0, so "the case fails against the old hook" says nothing about it — an external partner caught
exactly that: case 09 passes against the 0.44.0 watcher for the WRONG reason (that hook never
reports anything, so "silent on the second call" is trivially true). The discriminating baseline is a
MUTATION of this hook, and `--selftest` runs them: break the assertion, require the case that names
it to fail. A check that has never been seen to fail is not yet a check.

    python3 test/adversary-report-branches.py
    python3 test/adversary-report-branches.py --selftest
"""
import argparse, json, os, subprocess, sys, tempfile
import tmp_cleanup  # this run's own TMPDIR, removed at exit (p-1a5a4e9828)
from suite_bash import BASH  # noqa: E402 — Git Bash on Windows, plain "bash" elsewhere
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import expected_check  # noqa: E402 — the --expected check every --compare suite shares

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "report-adversary-writes.sh")

SESSION = "sess-abc"

ONE_ROUND = """ts=2026-09-12T16:58:22Z agent=subagent_xyz repo=/tmp/repo
path CHANGELOG.md
path plugins/x/bin/tool.sh
end
"""

TWO_ROUNDS = ONE_ROUND + """ts=2026-09-12T17:10:03Z agent=subagent_xyz repo=/tmp/repo
path CHANGELOG.md
path new-file.md
end
"""

MALFORMED = """this line is not a record at all
ts=broken
path CHANGELOG.md
   garbage with no prefix
path
end
"""

MANY_PATHS = "ts=2026-09-12T16:58:22Z agent=subagent_xyz repo=/tmp/repo\n" + "".join(
    "path plugins/goalspec/hooks/some-fairly-long-file-name-%02d.sh\n" % i for i in range(12)) + "end\n"

SHORT_PATHS = "ts=2026-09-12T16:58:22Z agent=subagent_xyz repo=/tmp/repo\n" + "".join(
    "path src/f%02d.py\n" % i for i in range(20)) + "end\n"

# 0.65.0 (p-2bf372e6e3): a path whose whole change another session's record proves.
OTHER_ONLY = """ts=2026-10-17T22:10:00Z agent=subagent_xyz repo=/tmp/repo
other 831306ab tracked.txt
end
"""

OTHER_AND_PATH = """ts=2026-10-17T22:10:00Z agent=subagent_xyz repo=/tmp/repo
path CHANGELOG.md
other 831306ab tracked.txt
end
"""

NO_PATHS = """ts=2026-09-12T16:58:22Z agent=subagent_xyz repo=/tmp/repo
end
"""


def payload(session_id=SESSION, drop_session=False, raw=None, note=False, mode=0o700):
    if raw is not None:
        return raw
    d = {"transcript_path": "/nonexistent/t.jsonl", "cwd": "/tmp",
         "permission_mode": "default", "hook_event_name": "Stop"}
    if not drop_session:
        d["session_id"] = session_id
    return json.dumps(d)


# name, findings file content (None -> no file), findings filename stem, payload kwargs, expected
CASES = [
    # The normal case: one round, two paths, reported and named.
    ("01-one-round", ONE_ROUND, SESSION, {}, "reported:CHANGELOG.md,plugins/x/bin/tool.sh|rounds=1"),
    # Two rounds accumulate; paths are deduplicated across them and the round count is stated.
    ("02-two-rounds", TWO_ROUNDS, SESSION, {},
     "reported:CHANGELOG.md,new-file.md,plugins/x/bin/tool.sh|rounds=2"),
    # No findings file at all: the overwhelmingly common case. Silence, every turn, forever.
    ("03-no-findings", None, SESSION, {}, "silent"),
    # A findings file belonging to ANOTHER session must not be picked up — that is the whole point
    # of keying by session_id rather than dropping one file in a shared tmp dir.
    ("04-other-session", ONE_ROUND, "sess-OTHER", {}, "silent"),
    # Garbage in the file must be skipped, not fatal: a reporter that dies on bad input is a
    # reporter that stays silent about a real finding sitting in the same file.
    ("05-malformed-lines", MALFORMED, SESSION, {}, "reported:CHANGELOG.md|rounds=1"),
    # A record with no `path` lines names nothing, so there is nothing to report.
    ("06-record-without-paths", NO_PATHS, SESSION, {}, "silent"),
    # Fail-open on a payload that is not JSON at all.
    ("07-unparseable-payload", ONE_ROUND, SESSION, {"raw": "not json at all"}, "silent"),
    # THE audience assertion. The executor's transcript is what an adversary reads for its
    # principle-4 ask check, so this text lands in front of one. It must say who it is for AND say
    # that reading it changes nothing about an adversary's role.
    ("08-audience-line", ONE_ROUND, SESSION, {}, "reported:CHANGELOG.md,plugins/x/bin/tool.sh|rounds=1"),
    # Reported once: the file is consumed, so a second Stop in the same session is silent.
    ("09-reported-once", ONE_ROUND, SESSION, {}, "silent-on-second"),
    # No session id in the payload: nothing to key on, so nothing to read. Fail-open.
    ("10-no-session-id", ONE_ROUND, SESSION, {"drop_session": True}, "silent"),
    # ONE SHORT LINE (0.63.0, p-c6f0719a23; replaces the 0.44.7 split). On a Stop hook
    # additionalContext is shown to the human too, so the 0.44.7 split (short Spanish systemMessage,
    # long English additionalContext) never kept the long text off their screen. Now: no
    # systemMessage, Spanish, and the text above the path list at most 300 characters.
    ("11-one-short-line", ONE_ROUND, SESSION, {}, "one-line-ok"),
    # THE THIRD READING (p-55cec2045a). Observed 2026-10-06: a parallel session of the same project
    # wrote under .goalspec/ during an adversary round, and the message could only blame the adversary
    # or the executor. It must name a third writer, must stop claiming there are exactly two readings,
    # and — the half that keeps it from being a free pass — must say that the third reading needs
    # evidence naming the other writer, or the verdict stays UNVERIFIED. The human line names it too.
    ("12-third-reading", ONE_ROUND, SESSION, {}, "third-reading-ok"),
    # --- 0.62.0 (p-42d7c57137): the run directory is per session and checked. ---
    # The watcher could not use the run directory and left a note: reported once, on its own, in
    # Spanish for the human and with the audience line for the agent. Until 0.62.0 this failure was
    # silent (361 of 361 adversary runs of three VPS users, measured).
    ("13-failure-note-reported", None, SESSION, {"note": True}, "failure-reported"),
    ("14-failure-note-reported-once", None, SESSION, {"note": True}, "silent-on-second"),
    # A finding and a note in one session: the finding is reported and the note rides under it.
    ("15-finding-and-failure-note", ONE_ROUND, SESSION, {"note": True}, "reported+unmeasured"),
    # A run directory that fails the owner/mode check is never read: its content could be planted.
    ("16-run-dir-wrong-mode-not-read", ONE_ROUND, SESSION, {"mode": 0o755}, "silent"),
    # 0.63.0: the WHOLE notice, lists included, fits in 300 characters (it is shown to the human);
    # the paths that do not fit are counted, never silently dropped.
    ("17-many-paths-fit-and-counted", MANY_PATHS, SESSION, {}, "fits-and-counted"),
    # Both lists at once (paths and unmeasured rounds) still fit: the second list's title and count
    # are reserved while the first is filled (external review round 2 on 0.63.0).
    ("18-paths-and-failure-note-fit", SHORT_PATHS, SESSION, {"note": True}, "both-fit"),
    # 0.65.0 (p-2bf372e6e3): every changed path is another session's, proved by its record. The
    # notice names the session per path and says the reviewer left nothing there, and no longer asks
    # who wrote; it still says the tree moved under the verdict. Before 0.65.0: silent (no `path`).
    ("19-other-session-only", OTHER_ONLY, SESSION, {}, "other-only-ok"),
    # A path nobody's record explains AND one another session's record does: the question stays for
    # the first, and the second is listed apart with its session.
    ("20-other-session-and-unexplained", OTHER_AND_PATH, SESSION, {}, "mixed-ok"),
]


def classify(res, name, findings_path):
    out = res.stdout.strip()
    if not out:
        return "silent"
    try:
        d = json.loads(out)
        sysmsg = d.get("systemMessage") or ""
        agent_msg = (d.get("hookSpecificOutput") or {}).get("additionalContext") or ""
    except Exception:
        return "malformed-json"

    if name.startswith("11"):
        if sysmsg:
            return "has-systemMessage"
        # The WHOLE shown text, lists included (external review round 1 on 0.63.0 found the first
        # version measuring only the line above the path list).
        head = agent_msg
        if len(head) > 300:
            return "line-too-long:%d" % len(head)
        if head.isascii():
            return "line-looks-english"
        if "SKILL.md" not in head:
            return "line-without-skill-pointer"
        return "one-line-ok"

    if name.startswith("17"):
        listed = [ln for ln in agent_msg.splitlines() if ln.startswith("  - ") and "más" not in ln]
        # The rest are counted: "  - y N más" under the listed ones, or "Rutas: N" when none fits.
        counted = [int(ln.split()[2]) for ln in agent_msg.splitlines() if ln.startswith("  - y ") and "más" in ln]
        counted += [int(ln.split()[1]) for ln in agent_msg.splitlines()
                    if ln.startswith("Rutas: ") and ln.split()[1].isdigit()]
        if len(agent_msg) > 300:
            return "too-long:%d" % len(agent_msg)
        if len(counted) != 1 or len(listed) + counted[0] != 12:
            return "paths-dropped"
        return "fits-and-counted"

    if name.startswith("18"):
        if len(agent_msg) > 300:
            return "too-long:%d" % len(agent_msg)
        if "Rondas sin medir" not in agent_msg or "Rutas" not in agent_msg:
            return "a-list-dropped"
        return "both-fit"

    if name.startswith("19"):
        if len(agent_msg) > 300:
            return "too-long:%d" % len(agent_msg)
        if not agent_msg.startswith("Para quien ejecuta") or "verifica, no repara" not in agent_msg:
            return "no-audience-line"
        if "tracked.txt (831306ab)" not in agent_msg:
            return "session-not-named"
        if "¿Escribió" in agent_msg or "Rutas:" in agent_msg:
            return "still-asks-who-wrote"
        if "el revisor no dejó cambios" not in agent_msg or "veredicto" not in agent_msg:
            return "other-text-wrong"
        return "other-only-ok"

    if name.startswith("20"):
        if len(agent_msg) > 300:
            return "too-long:%d" % len(agent_msg)
        if "¿Escribió" not in agent_msg or "- CHANGELOG.md" not in agent_msg:
            return "unexplained-path-not-asked"
        if "tracked.txt (831306ab)" not in agent_msg:
            return "session-not-named"
        return "mixed-ok"

    if name.startswith("13"):
        if (not agent_msg.startswith("Para quien ejecuta") or "no midió" not in agent_msg
                or "verifica, no repara" not in agent_msg or sysmsg):
            return "failure-text-wrong"
        if len(agent_msg) > 300:
            return "failure-line-too-long"
        return "failure-reported"

    if name.startswith("15"):
        if "Rondas sin medir:" not in agent_msg or "- " not in agent_msg:
            return "finding-without-unmeasured-note"
        return "reported+unmeasured"

    if name.startswith("12"):
        if "otra sesión" not in agent_msg:
            return "third-reading-missing"
        if "evidencia que la nombre" not in agent_msg or "veredicto no vale" not in agent_msg:
            return "third-reading-without-evidence-bar"
        return "third-reading-ok"

    # Everything else — including the audience-line case (08) — reads the technical text, which now
    # lives in additionalContext only.
    msg = agent_msg
    paths = sorted(ln.strip()[2:] for ln in msg.splitlines() if ln.strip().startswith("- "))
    if not paths:
        return "reported-unnamed"
    rounds = "?"
    for token in msg.split():
        if token.startswith("(") and token[1:].isdigit():
            rounds = token[1:]
            break
    tag = "reported:" + ",".join(paths) + "|rounds=" + rounds

    if name.startswith("08"):
        # Both halves. Naming the audience is not enough on its own: 0.44.0's message also had an
        # implicit audience and an adversary still took it as its own instruction. The disarming
        # sentence is what makes it inert.
        named = msg.lstrip().startswith("Para quien ejecuta")
        disarms = "un revisor que lo lea verifica, no repara" in msg
        if not named:
            return "reported-no-audience-line"
        if not disarms:
            return "reported-audience-not-disarming"
    if all(os.path.isfile(f) for f in findings_path):
        # Not deleted: every later turn would re-report the same finding as if it were new.
        return tag + "|NOT-CONSUMED"
    return tag


def suite(hook, workdir):
    rows = []
    for name, body, stem, kw, expect in CASES:
        if os.name == "nt" and name.startswith("16"):
            # Windows has no mode bits: run_dir checks only "a real directory, not a link".
            rows.append((name, "skipped (windows): mode bits", "skipped (windows): mode bits"))
            continue
        kw = dict(kw)  # popped below; the table is reused by --compare and --selftest
        tmp = tempfile.mkdtemp(prefix="tmp-" + name + "-", dir=workdir)
        # Both layouts (pre-0.62.0 shared directory, 0.62.0 per-session run directory), so --compare
        # against the old reporter measures behaviour, not the path rename.
        snap = os.path.join(tmp, "goalspec-adversary-snap")
        os.makedirs(snap)
        run = os.path.join(tmp, "state", "goalspec", "run-" + stem)
        os.makedirs(os.path.dirname(run), 0o700)
        os.mkdir(run, 0o700)
        os.chmod(run, kw.pop("mode", 0o700))
        old_copy = os.path.join(snap, stem + ".findings")
        if body is not None:
            for f_path in (old_copy, os.path.join(run, "findings")):
                with open(f_path, "w") as f:
                    f.write(body)
        env = dict(os.environ)
        env["TMPDIR"] = tmp
        env["XDG_STATE_HOME"] = os.path.join(tmp, "state")
        env["LOCALAPPDATA"] = env["XDG_STATE_HOME"]  # what run_dir reads on Windows
        env["HOME"] = os.path.join(tmp, "home")  # the fallback state directory, never the real one
        env["CLAUDE_PLUGIN_ROOT"] = os.path.join(REPO, "plugins", "goalspec")  # where a copied hook finds hooks/lib
        if kw.pop("note", False):
            nd = os.path.join(tmp, "state", "goalspec")
            with open(os.path.join(nd, "run-dir-failed-" + stem), "w") as f:
                f.write("watch-adversary-writes: ~/.local/state/goalspec/run-%s belongs to uid 1001\n" % stem)
        if name.startswith("16"):
            os.remove(old_copy)  # only the unusable run directory holds a finding
        # classify() looks for THIS session's files; case 04 writes another session's. A finding
        # counts as consumed when the hook deleted the copy in the layout it reads.
        own = [os.path.join(snap, SESSION + ".findings"),
               os.path.join(tmp, "state", "goalspec", "run-" + SESSION, "findings")]
        res = subprocess.run([BASH, hook], input=payload(**kw), capture_output=True,
                             text=True, env=env, cwd=tmp, timeout=30)
        if name.startswith("09") or name.startswith("14"):
            res = subprocess.run([BASH, hook], input=payload(**kw), capture_output=True,
                                 text=True, env=env, cwd=tmp, timeout=30)
            rows.append((name, "silent-on-second" if not res.stdout.strip() else "RE-REPORTED",
                         expect))
            continue
        rows.append((name, classify(res, name, own), expect))
    return rows


# Each entry: label, the exact text to break in the hook, its replacement, and the case whose
# branch must change as a result. Breaking an assertion must be VISIBLE in the case written for it.
MUTATIONS = [
    ("the audience line removed",
     'HEAD="Para quien ejecuta; un revisor que lo lea verifica, no repara.\ngoalspec: el repo', 'HEAD="goalspec: el repo', "08"),
    ("the disarming half removed, audience kept",
     'HEAD="Para quien ejecuta; un revisor que lo lea verifica, no repara.\ngoalspec: el repo', 'HEAD="Para quien ejecuta.\ngoalspec: el repo', "08"),
    ("the findings file not consumed",
     'rm -f "$FINDINGS" 2>/dev/null || true', 'true', "09"),
    ("the session key ignored",
     'SNAP_DIR=$("$PY" "$RUN_DIR_PY" path "$SESSION_KEY" 2>/dev/null || true)',
     'SNAP_DIR=$(ls -d "$XDG_STATE_HOME"/goalspec/run-* 2>/dev/null | tail -1)', "04"),
    ("the run directory read without its check",
     'SNAP_DIR=$("$PY" "$RUN_DIR_PY" path "$SESSION_KEY" 2>/dev/null || true)',
     'SNAP_DIR="$XDG_STATE_HOME/goalspec/run-$SESSION_KEY"', "16"),
    ("the failure note never read",
     'FAILED=$("$PY" "$RUN_DIR_PY" failures "$SESSION_KEY" "$REPO_ROOT" 2>/dev/null || true)', 'FAILED=""', "13"),
    ("the failure note read but not consumed",
     'FAILED=$("$PY" "$RUN_DIR_PY" failures "$SESSION_KEY" "$REPO_ROOT" 2>/dev/null || true)',
     'FAILED=$(cat "${XDG_STATE_HOME}/goalspec/run-dir-failed-$SESSION_KEY" 2>/dev/null || true)', "14"),
    ("the failure note dropped when a finding is reported",
     '[ -n "$FAILED" ] && L2=', 'false && L2=', "15"),
    ("a systemMessage copy put back",
     'print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": out}}))',
     'print(json.dumps({"systemMessage": out, "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": out}}))',
     "11"),
    ("the line grown past the length budget",
     'Sin eso su veredicto no vale. SKILL.md paso 6."',
     'Sin eso su veredicto no vale. Se agrega aquí texto adicional de relleno para asegurar que la línea supere ampliamente los trescientos caracteres de longitud total. SKILL.md paso 6."',
     "11"),
    ("the line switched to English",
     'HEAD="Para quien ejecuta; un revisor que lo lea verifica, no repara.\ngoalspec: el repo cambió en la revisión (${ROUNDS} ronda(s)). ¿Escribió el revisor, tú u otra sesión (con evidencia que la nombre)? Sin eso su veredicto no vale. SKILL.md paso 6."',
     'HEAD="To the executor; a reviewer reading this verifies, does not repair.\ngoalspec: the repo changed during the review (${ROUNDS} round(s)). Say who wrote. See SKILL.md, step 6."',
     "11"),
    ("the third reading removed",
     "¿Escribió el revisor, tú u otra sesión (con evidencia que la nombre)?", "¿Escribió el revisor o tú?", "12"),
    ("the third reading kept, its evidence bar removed",
     "otra sesión (con evidencia que la nombre)? Sin eso su veredicto no vale.", "otra sesión?", "12"),
    ("the failure line without its audience line",
     'HEAD="Para quien ejecuta; un revisor que lo lea verifica, no repara.\ngoalspec: la vigilancia', 'HEAD="goalspec: la vigilancia', "13"),
    ("the second list not reserved",
     "    later = sum(floor(t, i) for t, i in lists[n + 1:])", "    later = 0", "18"),
    ("the 300-character budget lifted for the lists",
     "LIMIT = 300", "LIMIT = 3000", "17"),
    ("another session's lines ignored",
     "OTHERS=$(printf '%s\\n' \"$BODY\" | sed -n", "OTHERS=$(true | sed -n", "19"),
    ("the other-session notice dropped",
     'if [ -z "$PATHS" ]; then', 'if false; then', "19"),
    ("the other-session list dropped beside unexplained paths",
     'LIST3="$L3" emit_notice', 'emit_notice', "20"),
]


def selftest(hook):
    src = open(hook, encoding="utf-8").read()
    bad = 0
    with tempfile.TemporaryDirectory() as work:
        base_rows = suite(hook, tempfile.mkdtemp(dir=work))
        red = [n for n, b, e in base_rows if b != e]
        if red:
            # A mutation "caught" against a red base proves nothing (learning, 0.62.0).
            print("selftest: the unmutated hook is red (%s) — fix that first" % ", ".join(red))
            return 1
        base = dict((n, b) for n, b, _ in base_rows)
        for label, old, new, case in MUTATIONS:
            if old not in src:
                print("%-46s SETUP FAILED: pattern absent" % label)
                bad += 1
                continue
            mut = os.path.join(work, "mut.sh")
            with open(mut, "w", encoding="utf-8") as f:
                f.write(src.replace(old, new, 1))
            rows = dict((n, b) for n, b, _ in suite(mut, tempfile.mkdtemp(dir=work)))
            changed = [n for n in rows if rows[n] != base.get(n)]
            hit = any(n.startswith(case) for n in changed)
            print("%-46s case %s %s%s" % (label, case, "ok" if hit else "MISSED",
                                          "" if hit else "  <- branches that changed: %s"
                                          % (", ".join(changed) or "none")))
            if not hit:
                bad += 1
    print()
    if bad:
        print("selftest: %d mutation(s) not caught — those assertions do not work" % bad)
        return 1
    print("selftest: every mutation caught by the case written for it")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hook", nargs="?", default=DEFAULT_HOOK)
    ap.add_argument("--compare", metavar="OTHER_HOOK")
    ap.add_argument("--expected", default="", help="case-name prefixes whose diff is INTENDED")
    ap.add_argument("--selftest", action="store_true",
                    help="break each assertion in a copy and require its own case to notice")
    a = ap.parse_args()

    if a.selftest:
        return selftest(a.hook)

    expected = [s.strip() for s in a.expected.split(",") if s.strip()]
    with tempfile.TemporaryDirectory() as workdir:
        rows = suite(a.hook, workdir)
        other = suite(a.compare, workdir) if a.compare else None

    failures = 0
    for i, (name, branch, expect) in enumerate(rows):
        flag = ""
        if branch != expect:
            flag = "   <-- EXPECT FAILED: wanted %s" % expect
            failures += 1
        if other and other[i][1] != branch:
            tag = "EXPECTED-DIFF" if any(name.startswith(p) for p in expected) else "DIFFERS"
            flag += "   <-- %s: %s" % (tag, other[i][1])
        print("%-34s %-56s%s" % (name, branch, flag))

    rc = 0
    if failures:
        print("\n%d expect assertion(s) failed" % failures)
        rc = 1
    if other:
        diffs = [r[0] for r, o in zip(rows, other) if r[1] != o[1]]
        unexpected = [d for d in diffs if not any(d.startswith(p) for p in expected)]
        if diffs:
            print("\n%d branch(es) changed vs compare: %s" % (len(diffs), ", ".join(diffs)))
        if unexpected:
            print("REGRESSION: %d unexpected: %s" % (len(unexpected), ", ".join(unexpected)))
            rc = 1
        if expected_check.report(expected, [r[0] for r in rows], diffs):
            rc = 1
        elif not unexpected and not failures:
            print("\nparity OK — %d branches, %d intended change(s)" % (len(rows), len(diffs)))
    return rc


if __name__ == "__main__":
    sys.exit(main())

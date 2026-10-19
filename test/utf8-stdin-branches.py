#!/usr/bin/env python3
"""Branch suite: the hooks read their stdin, print and open() files as UTF-8 (0.65.5, p-ee6150b00b).

    python3 test/utf8-stdin-branches.py              # the cases
    python3 test/utf8-stdin-branches.py --selftest   # drop the UTF-8 line from each hook, require a red

Claude Code writes the hook payload as UTF-8 bytes, with accents written as they are (not as \\u
escapes). On Windows python decodes stdin, encodes stdout and opens files with the system code page
(cp1252), so up to 0.65.4 a path with an accent ("C:\\Users\\Peña") arrived garbled and the hook
could not find the transcript, and enable-autoupdate.sh rewrote known_marketplaces.json with every
accent turned into two wrong characters, or failed to read it on a byte cp1252 does not define (the
second byte of "Í" is 0x8D). Against 0.65.4 in CI run 39303554146: 4 of 7 fail on Windows, 5 on
macOS, 3 on Ubuntu.

So this suite sends the payload as UTF-8 bytes with ensure_ascii=False — the other suites send
text=True, which on Windows encodes with cp1252, the same code page the hook decodes with, and the
round trip hides the bug. On Windows the hooks run with PYTHONUTF8 and PYTHONIOENCODING removed from
their environment: the real default. On macOS and Linux the default is already UTF-8, so the hooks
run with PYTHONIOENCODING=cp1252 and PYTHONUTF8=0, which gives their std streams the Windows code
page; the open() case also needs a single-byte locale, and prints "skipped (posix)" when the machine
has none. Hermetic: synthetic transcripts in a temp dir whose name has an accent and an ene, no git.
"""
import json, os, shutil, subprocess, sys, tempfile
import tmp_cleanup  # this run's own TMPDIR, removed at exit (p-1a5a4e9828)
from suite_bash import BASH  # noqa: E402 — Git Bash on Windows, plain "bash" elsewhere

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="utf8-stdin-branches-")
NONASCII = os.path.join(TMP, "José Peña")   # what a Windows home folder can look like
ASCII_DIR = os.path.join(TMP, "plain")
os.makedirs(NONASCII)
os.makedirs(ASCII_DIR)
WINDOWS = os.name == "nt"
LATIN1_LOCALES = ("en_US.ISO8859-1", "en_US.ISO-8859-1", "de_DE.ISO8859-1")


def _single_byte_locale():
    """A locale whose encoding is not UTF-8, for the open() case on POSIX; None if there is none."""
    for loc in LATIN1_LOCALES:
        env = {**os.environ, "PYTHONUTF8": "0", "LC_ALL": loc}
        env.pop("PYTHONIOENCODING", None)
        r = subprocess.run([sys.executable, "-c",
                            "import locale; print(locale.getpreferredencoding(False))"],
                           capture_output=True, text=True, env=env)
        enc = r.stdout.strip().lower().replace("-", "").replace("_", "")
        if r.returncode == 0 and enc and "utf8" not in enc and enc not in ("ascii", "ansix3.41968"):
            return loc
    return None


LOCALE = None if WINDOWS else _single_byte_locale()


def hook_env(plugin, home=None, need_locale=False):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": plugin}
    for k in ("PYTHONUTF8", "PYTHONIOENCODING"):
        env.pop(k, None)
    if not WINDOWS:
        env["PYTHONUTF8"] = "0"
        env["PYTHONIOENCODING"] = "cp1252"
        if need_locale and LOCALE:
            env["LC_ALL"] = LOCALE
    if home:
        env["HOME"] = home
    return env


def run_hook(plugin, hook, payload, **kw):
    """payload is a dict; it goes to the hook as UTF-8 bytes, accents unescaped, as Claude Code sends it."""
    data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    out = subprocess.run([BASH, os.path.join(plugin, "hooks", hook)], input=data,
                         capture_output=True, env=hook_env(plugin, **kw))
    return out.stdout.decode("utf-8", errors="replace").strip()


def transcript(dirname, name, events):
    p = os.path.join(dirname, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            content = []
            if "skill" in ev:
                content.append({"type": "tool_use", "name": "Skill", "input": {"skill": ev["skill"]}})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}},
                                ensure_ascii=False) + "\n")
    return p


LOAD = {"skill": "goalspec:goalspec"}


def brake(plugin, dirname, name, command="ls"):
    p = transcript(dirname, name, [LOAD, {"text": "Empiezo por la señal de la cañería."}])
    raw = run_hook(plugin, "precheck-spec-before-work.sh",
                   {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                    "tool_input": {"command": command}, "transcript_path": p,
                    "session_id": "sess-ñ", "cwd": dirname})
    if not raw:
        return "allow"
    try:
        hso = json.loads(raw).get("hookSpecificOutput") or {}
    except Exception:
        return "unparseable"
    if hso.get("permissionDecision") == "deny" and "señal de la cañería" in (hso.get("permissionDecisionReason") or ""):
        return "deny-quotes"
    return "other-output"


def name_session(plugin, dirname, name):
    p = transcript(dirname, name, [{"text": "## Goal-spec\n\nAsked (your words): \"arreglá la señal\"\n\n"
                                            "Session name: goalspec-señal-ok\n\nSession name: goalspec-senal-ok\n"}])
    raw = run_hook(plugin, "name-session.sh",
                   {"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                    "prompt": "seguí con el índice", "transcript_path": p})
    if not raw:
        return "silent"
    try:
        hso = json.loads(raw).get("hookSpecificOutput") or {}
    except Exception:
        return "unparseable"
    return "title:" + str(hso.get("sessionTitle"))


def autoupdate(plugin, case, other_value):
    if not WINDOWS and not LOCALE:
        return "skipped"
    home = os.path.join(TMP, "home-" + case)
    km = os.path.join(home, ".claude", "plugins", "known_marketplaces.json")
    os.makedirs(os.path.dirname(km))
    with open(km, "w", encoding="utf-8") as fh:
        json.dump({"goal-forge": {"installLocation": "C:/Users/Peña/.claude/x", "autoUpdate": False},
                   "otra": {"nombre": other_value}}, fh, ensure_ascii=False, indent=2)
    raw = run_hook(plugin, "enable-autoupdate.sh", {"hook_event_name": "SessionStart"},
                   home=home, need_locale=True)
    try:
        with open(km, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:
        return "file-unreadable"
    flipped = (d.get("goal-forge") or {}).get("autoUpdate") is True
    intact = ((d.get("goal-forge") or {}).get("installLocation") == "C:/Users/Peña/.claude/x"
              and (d.get("otra") or {}).get("nombre") == other_value)
    return "%s,%s,%s" % ("flipped" if flipped else "not-flipped", "intact" if intact else "CORRUPTED",
                         "announced" if "enabled auto-update" in raw else "quiet")


CASES = [
    # Control: the same fixture under a folder with no accent works on every version.
    ("01-brake-ascii-path-control", lambda p: brake(p, ASCII_DIR, "01"), "deny-quotes", None),
    # The transcript sits under "José Peña": a garbled path and the hook cannot read it.
    ("02-brake-accent-in-path", lambda p: brake(p, NONASCII, "02"), "deny-quotes",
     "precheck-spec-before-work.sh"),
    # "Í" is C3 8D in UTF-8 and python's cp1252 has no 0x8D: under the POSIX stand-in json.load
    # fails and the brake lets it through. On the Windows runner's stdin it did not fail (passed
    # against 0.65.4 in run 39303554146), so this one is a POSIX case.
    ("03-brake-undefined-byte-in-command", lambda p: brake(p, ASCII_DIR, "03", "echo 'Índice'"),
     "deny-quotes", "precheck-spec-before-work.sh"),
    ("04-name-session-ascii-path-control", lambda p: name_session(p, ASCII_DIR, "04"),
     "title:goalspec-senal-ok", None),
    ("05-name-session-accent-in-path", lambda p: name_session(p, NONASCII, "05"),
     "title:goalspec-senal-ok", "name-session.sh"),
    # known_marketplaces.json holds the user's home in installLocation; an ene must survive.
    ("06-autoupdate-keeps-ene", lambda p: autoupdate(p, "06-" + os.path.basename(p), "Peña"),
     "flipped,intact,announced", "enable-autoupdate.sh"),
    ("07-autoupdate-undefined-byte", lambda p: autoupdate(p, "07-" + os.path.basename(p), "Índice"),
     "flipped,intact,announced", "enable-autoupdate.sh"),
]

UTF8_LINE = "export PYTHONUTF8=1 PYTHONIOENCODING=utf-8\n"


def suite(plugin):
    rows = []
    for name, build, want, _hook in CASES:
        got = build(plugin)
        rows.append((name, want, got))
    return rows


def ok(want, got):
    return got == want or got == "skipped"


def main():
    print("platform: %s; posix single-byte locale: %s" % ("windows" if WINDOWS else "posix", LOCALE))
    if "--selftest" in sys.argv:
        failed = []
        for hook in sorted({h for _n, _b, _w, h in CASES if h}):
            d = tempfile.mkdtemp(prefix="u8-mut-")
            mp = os.path.join(d, "goalspec-" + hook.split(".")[0])
            shutil.copytree(PLUGIN, mp)
            f = os.path.join(mp, "hooks", hook)
            with open(f, encoding="utf-8") as fh:
                s = fh.read()
            if UTF8_LINE not in s:
                failed.append("%s: the UTF-8 line is not in the hook (suite drifted from the code)" % hook)
                continue
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(s.replace(UTF8_LINE, "", 1))
            rows = [(n, w, g) for (n, w, g), c in zip(suite(mp), CASES) if c[3] == hook]
            caught = [n for n, w, g in rows if g != w and g != "skipped"]
            skipped = [n for n, w, g in rows if g == "skipped"]
            if caught:
                print("%-40s caught by %s" % ("UTF-8 line dropped from " + hook, ", ".join(caught)))
            elif skipped and len(skipped) == len(rows):
                print("%-40s skipped (posix): no single-byte locale on this machine" % ("UTF-8 line dropped from " + hook))
            else:
                print("%-40s NOT CAUGHT" % ("UTF-8 line dropped from " + hook))
                failed.append(hook)
            shutil.rmtree(d, ignore_errors=True)
        if failed:
            print("\nSELFTEST FAILURES: %d\n  %s" % (len(failed), "\n  ".join(failed)))
            return 1
        print("\nOK — every mutation caught by at least one case, or skipped as printed")
        return 0

    rows = suite(PLUGIN)
    bad = [(n, w, g) for n, w, g in rows if not ok(w, g)]
    for n, w, g in rows:
        note = "" if g == w else ("skipped (posix): no single-byte locale on this machine" if g == "skipped"
                                  else "<-- FAILS (want %s)" % w)
        print("%-40s %-28s %s" % (n, g, note))
    if bad:
        print("\nFAILURES: %d" % len(bad))
        return 1
    print("\nOK — %d cases, all as expected" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

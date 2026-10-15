#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/name-session.sh (0.56.0).

    python3 test/session-name-branches.py              # the cases
    python3 test/session-name-branches.py --selftest   # break the component, require a case to notice

On UserPromptSubmit the hook sets `sessionTitle` (inside hookSpecificOutput — measured 2026-10-14,
the top-level field is ignored) to the `Session name:` slug of the newest `## Goal-spec` in this
session, unless the session already carries a title that no spec of this session asked for (the
user's, lookout's or --name's). Hermetic: synthetic transcripts in a temp dir, no git.

The hook is new, so "fails against the previous version" would be vacuous. `--selftest` copies the
plugin to a temp dir, applies one mutation at a time to the component, and requires at least one
case to fail under each.
"""
import json, os, shutil, subprocess, sys, tempfile
import tmp_cleanup  # this run's own TMPDIR, removed at exit (p-1a5a4e9828)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="session-name-branches-")


def spec(name_line):
    return ("## Goal-spec\n\n**Asked (your words):** \"do the thing\"\n\n%s\n\n"
            "1. **Objective.** whatever.\n" % name_line)


def transcript(events, name):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            if "user" in ev:
                fh.write(json.dumps({"type": "user", "message": {"role": "user",
                                     "content": [{"type": "text", "text": ev["user"]}]}}) + "\n")
                continue
            content = []
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "name": "Write", "id": "w1",
                                "input": {"file_path": fp, "content": body}})
            if "thinking" in ev:
                content.append({"type": "thinking", "thinking": ev["thinking"]})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run(plugin, payload_text):
    out = subprocess.run(["bash", os.path.join(plugin, "hooks", "name-session.sh")],
                         input=payload_text, capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PLUGIN_ROOT": plugin})
    raw = out.stdout.strip()
    if not raw:
        return "silent"
    try:
        d = json.loads(raw)
    except Exception:
        return "unparseable"
    hso = d.get("hookSpecificOutput") or {}
    if hso.get("hookEventName") == "UserPromptSubmit" and isinstance(hso.get("sessionTitle"), str):
        return "title:" + hso["sessionTitle"]
    return "other-output"


def prompt(events, name, title=None, event="UserPromptSubmit"):
    d = {"hook_event_name": event, "session_id": "s1", "prompt": "next",
         "transcript_path": transcript(events, name)}
    if title is not None:
        d["session_title"] = title
    return json.dumps(d)


A = {"text": spec("**Session name:** goalspec-renombrar-sesion")}
B = {"text": spec("Session name: goalspec-otra-tarea")}
CASES = [
    ("01-spec-with-name-no-title-sets", lambda: prompt([A], "01"), "title:goalspec-renombrar-sesion"),
    ("02-no-spec-silent", lambda: prompt([{"text": "hola"}], "02"), "silent"),
    ("03-spec-without-name-line-silent",
     lambda: prompt([{"text": spec("Assumptions: none.")}], "03"), "silent"),
    # The user, lookout or --name named it: never overwritten.
    ("04-foreign-title-kept", lambda: prompt([A], "04", title="worker-pendiente-12"), "silent"),
    ("05-same-title-silent", lambda: prompt([A], "05", title="goalspec-renombrar-sesion"), "silent"),
    # goalspec set the old name; a new spec with a new task replaces it.
    ("06-own-old-title-replaced-by-new-spec",
     lambda: prompt([A, B], "06", title="goalspec-renombrar-sesion"), "title:goalspec-otra-tarea"),
    ("07-newest-spec-wins-no-title", lambda: prompt([A, B], "07"), "title:goalspec-otra-tarea"),
    ("08-name-in-checkpoint-only-sets",
     lambda: prompt([{"write": (".goalspec/checkpoint-ab12.md",
                                spec("Session name: goalspec-desde-checkpoint"))}], "08"),
     "title:goalspec-desde-checkpoint"),
    # A Write to any other file can carry the same text as documentation.
    ("09-name-in-other-file-silent",
     lambda: prompt([{"write": ("SKILL.md", spec("Session name: goalspec-doc-ejemplo"))}], "09"),
     "silent"),
    ("10-name-line-before-spec-heading-silent",
     lambda: prompt([{"text": "Session name: goalspec-fuera\n\n## Goal-spec\n\nObjective: x.\n"}], "10"),
     "silent"),
    ("11-malformed-slug-silent",
     lambda: prompt([{"text": spec("Session name: renombrar la sesion")}], "11"), "silent"),
    ("12-backticks-and-list-bullet-accepted",
     lambda: prompt([{"text": spec("- **Session name:** `goalspec-con-ticks`")}], "12"),
     "title:goalspec-con-ticks"),
    # The rule is lowercase only; a malformed name is ignored, never repaired.
    ("13-uppercase-ignored",
     lambda: prompt([{"text": spec("Session name: GoalSpec-Mayus")}], "13"), "silent"),
    ("14-name-only-in-thinking-silent",
     lambda: prompt([{"thinking": A["text"]}], "14"), "silent"),
    ("15-name-only-in-user-text-silent", lambda: prompt([{"user": A["text"]}], "15"), "silent"),
    ("16-other-event-silent", lambda: prompt([A], "16", event="Stop"), "silent"),
    ("17-malformed-stdin-silent", lambda: "not json {{{", "silent"),
    ("18-no-transcript-silent",
     lambda: json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "x"}), "silent"),
    # A title that differs only in case is the same title.
    ("19-title-case-insensitive-silent",
     lambda: prompt([A], "19", title="GoalSpec-Renombrar-Sesion"), "silent"),
    # The own old name, in another case, is still ours to replace.
    ("21-own-old-title-other-case-replaced",
     lambda: prompt([A, B], "21", title="GoalSpec-Renombrar-Sesion"), "title:goalspec-otra-tarea"),
    # One spec, two text blocks of the same turn (heading in one, the name line in the next).
    ("22-spec-split-across-blocks-sets",
     lambda: prompt([{"text": "## Goal-spec\n\n**Asked (your words):** \"x\""},
                     {"text": "**Session name:** goalspec-partido"}], "22"), "title:goalspec-partido"),
    # A name line in a later turn, after the user spoke, is not part of that spec.
    ("23-name-after-user-prompt-silent",
     lambda: prompt([{"text": "## Goal-spec\n\nObjective: x."}, {"user": "sigue"},
                     {"text": "Session name: goalspec-otro-turno"}], "23"), "silent"),
    ("20-slug-over-60-chars-silent",
     lambda: prompt([{"text": spec("Session name: " + "a" * 61)}], "20"), "silent"),
]

LIB = os.path.join("hooks", "lib", "terminal_actions.py")
HOOK = os.path.join("hooks", "name-session.sh")
# (description, file, old, new): each must make at least one case fail.
MUTATIONS = [
    ("event filter dropped", HOOK,
     'if data.get("hook_event_name") != "UserPromptSubmit":\n    sys.exit(0)\n', ""),
    ("field moved off sessionTitle", HOOK, '"sessionTitle": title', '"title": title'),
    ("existing title never respected", LIB,
     "if cur == want or cur not in names:", "if cur == want:"),
    ("oldest spec wins", LIB, "want = names[-1]", "want = names[0]"),
    ("spec heading not required", LIB,
     'names.extend(SESSION_NAME_LINE_RE.findall(text[m.end():]))',
     'names.extend(SESSION_NAME_LINE_RE.findall(text))'),
    ("checkpoint ignored", LIB,
     'if it["kind"] not in ("text", "goal_spec_file"):', 'if it["kind"] not in ("text",):'),
    ("uppercase accepted", LIB, "([a-z0-9][a-z0-9-]{0,59})", "([A-Za-z0-9][A-Za-z0-9-]{0,59})"),
    ("slug check loosened", LIB, "([a-z0-9][a-z0-9-]{0,59})", "(.+?)"),
    ("split spec ignored", LIB, 'elif open_spec and it["kind"] == "text":', "elif False:"),
    ("spec stays open across prompts", LIB,
     'open_spec = False\n            continue', 'continue'),
    ("current title not lowercased", LIB,
     "cur = current_title.strip().lower() if", "cur = current_title.strip() if"),
]


def suite(plugin):
    return [(name, want, run(plugin, build())) for name, build, want in CASES]


def main():
    if "--selftest" in sys.argv:
        failed = []
        for desc, rel, old, new in MUTATIONS:
            d = tempfile.mkdtemp(prefix="sn-mut-")
            mp = os.path.join(d, "goalspec")
            shutil.copytree(PLUGIN, mp)
            f = os.path.join(mp, rel)
            s = open(f).read()
            if old not in s:
                failed.append("%s: mutation target not found (suite drifted from the code)" % desc)
                continue
            open(f, "w").write(s.replace(old, new, 1))
            caught = [n for n, want, got in suite(mp) if want != got]
            print("%-45s %s" % (desc, ("caught by " + ", ".join(caught)) if caught else "NOT CAUGHT"))
            if not caught:
                failed.append(desc)
            shutil.rmtree(d, ignore_errors=True)
        if failed:
            print("\nSELFTEST FAILURES: %d\n  %s" % (len(failed), "\n  ".join(failed)))
            return 1
        print("\nOK — %d mutations, each caught by at least one case" % len(MUTATIONS))
        return 0

    rows = suite(PLUGIN)
    bad = [(n, w, g) for n, w, g in rows if w != g]
    for n, w, g in rows:
        print("%-45s %-35s %s" % (n, g, "" if w == g else "<-- FAILS (want %s)" % w))
    if bad:
        print("\nFAILURES: %d" % len(bad))
        return 1
    print("\nOK — %d cases, all as expected" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

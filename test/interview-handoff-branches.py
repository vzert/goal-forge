#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/nudge-interview-handoff.sh (0.46.0).

    python3 test/interview-handoff-branches.py              # the cases
    python3 test/interview-handoff-branches.py --selftest   # break the component, require a case to notice

The hook adds one line of agent-facing context when this session ran /goalspec:interview and has
neither invoked the goalspec loop nor written a `## Goal-spec` since. It fires on PostToolUse for
AskUserQuestion, and on UserPromptSubmit only once work (Bash/Write/Edit) followed the interview. Hermetic: synthetic transcripts in a temp dir, no git.

There is no predecessor to compare against (the hook is new in 0.46.0), so "fails against the old
version" would be vacuous. `--selftest` instead copies the plugin to a temp dir, applies one
mutation at a time to the component itself, and requires at least one case to fail under each.
"""
import json, os, re, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="interview-handoff-branches-")

TYPED = ("<command-message>goalspec:interview</command-message>\n"
         "<command-name>/goalspec:interview</command-name>\n<command-args>x</command-args>")
SPEC = "## Goal-spec\nObjective: whatever.\n"


def transcript(events, name):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            if "user" in ev:
                fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": ev["user"]}}) + "\n")
                continue
            content = []
            if "skill" in ev:
                content.append({"type": "tool_use", "name": "Skill", "input": {"skill": ev["skill"]}})
            if "bash" in ev:
                content.append({"type": "tool_use", "name": "Bash", "input": {"command": ev["bash"]}})
            if "edit" in ev:
                content.append({"type": "tool_use", "name": "Edit",
                                "input": {"file_path": ev["edit"], "old_string": "a", "new_string": "b"}})
            if "ask" in ev:
                content.append({"type": "tool_use", "name": "AskUserQuestion", "input": {"questions": []}})
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "name": "Write", "input": {"file_path": fp, "content": body}})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run(plugin, payload_text):
    out = subprocess.run(["bash", os.path.join(plugin, "hooks", "nudge-interview-handoff.sh")],
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
    ctx = hso.get("additionalContext") or ""
    if "goalspec:goalspec" in ctx and "## Goal-spec" in ctx:
        return "nudge:" + str(hso.get("hookEventName"))
    return "other-output"


def ups(events, name):
    return json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "sigue",
                       "transcript_path": transcript(events, name)})


def post(events, name, tool="AskUserQuestion"):
    return json.dumps({"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": {},
                       "transcript_path": transcript(events, name)})


# name -> (payload builder, expected)
CASES = [
    ("01-no-interview-silent", lambda: ups([{"text": "just work"}], "01"), "silent"),
    ("02-typed-interview-no-spec-UPS-nudges", lambda: ups([{"user": TYPED}, {"ask": 1}, {"bash": "npm test"}], "02"),
     "nudge:UserPromptSubmit"),
    ("03-typed-interview-after-ask-POST-nudges", lambda: post([{"user": TYPED}, {"ask": 1}], "03"),
     "nudge:PostToolUse"),
    ("04-interview-then-loop-invoked-silent",
     lambda: ups([{"user": TYPED}, {"ask": 1}, {"skill": "goalspec:goalspec"}, {"bash": "npm test"}], "04"),
     "silent"),
    ("05-interview-then-spec-text-silent",
     lambda: ups([{"user": TYPED}, {"ask": 1}, {"text": SPEC}], "05"), "silent"),
    ("06-interview-then-spec-in-checkpoint-silent",
     lambda: ups([{"user": TYPED}, {"write": (".goalspec/checkpoint-abc.md", SPEC)}], "06"), "silent"),
    # A spec from an EARLIER cycle does not discharge a new interview.
    ("07-spec-before-interview-only-nudges",
     lambda: ups([{"text": SPEC}, {"user": TYPED}, {"ask": 1}, {"edit": "src/a.js"}], "07"), "nudge:UserPromptSubmit"),
    ("08-post-other-tool-silent", lambda: post([{"user": TYPED}], "08", tool="Bash"), "silent"),
    ("09-malformed-stdin-silent", lambda: "not json {{{", "silent"),
    ("10-interview-via-skill-tool-nudges",
     lambda: ups([{"skill": "goalspec:interview"}, {"ask": 1}, {"bash": "ls"}], "10"), "nudge:UserPromptSubmit"),
    # The loop routed into the interview (loop entry BEFORE it): the spec is still owed.
    ("11-loop-then-interview-no-spec-nudges",
     lambda: ups([{"skill": "goalspec:goalspec"}, {"skill": "goalspec:interview"}, {"ask": 1}, {"edit": "src/a.js"}], "11"),
     "nudge:UserPromptSubmit"),
    ("12-other-event-silent",
     lambda: json.dumps({"hook_event_name": "Stop",
                         "transcript_path": transcript([{"user": TYPED}], "12")}), "silent"),
    ("13-tag-inside-tool-result-silent",
     lambda: ups([{"user": [{"type": "tool_result", "tool_use_id": "x", "content": TYPED}]}], "13"),
     "silent"),
    ("14-adversary-skill-only-silent", lambda: ups([{"skill": "goalspec:adversary"}], "14"), "silent"),
    # An interview that concluded "nothing to do", then plain conversation: no nudge on later
    # prompts (external adversary round on 0.46.0) ...
    ("16-no-op-interview-then-chat-UPS-silent",
     lambda: ups([{"user": TYPED}, {"ask": 1}, {"text": "Conclusion: nothing to do here."}], "16"), "silent"),
    # ... but right after an answered round it still speaks: that is the handoff moment.
    ("17-no-op-interview-POST-still-nudges",
     lambda: post([{"user": TYPED}, {"ask": 1}, {"text": "round done"}], "17"), "nudge:PostToolUse"),
    # A non-checkpoint Edit is work, not a spec: it keeps the handoff pending.
    ("18-interview-then-code-edit-UPS-nudges",
     lambda: ups([{"user": TYPED}, {"ask": 1}, {"edit": "src/app.js"}], "18"), "nudge:UserPromptSubmit"),
    ("15-no-transcript-silent",
     lambda: json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "x"}), "silent"),
]

LIB = os.path.join("hooks", "lib", "terminal_actions.py")
HOOK = os.path.join("hooks", "nudge-interview-handoff.sh")
# (description, file, old, new): each must make at least one case fail.
MUTATIONS = [
    ("pending always True", LIB, "    if last_iv is None:\n        return False",
     "    if last_iv is None:\n        return True"),
    ("loop invocation ignored", LIB,
     '        if it["kind"] == "goalspec_entry" and it.get("skill") == "goalspec":\n            return False',
     '        pass'),
    ("checkpoint spec ignored", LIB,
     '        if it["kind"] == "goal_spec_file":\n            return False', '        pass'),
    ("spec anywhere discharges (not only after)", LIB,
     "    for it in items[last_iv + 1:]:", "    for it in items:"),
    ("PostToolUse tool filter dropped", HOOK,
     '    if data.get("tool_name") != "AskUserQuestion":\n        sys.exit(0)', "    pass"),
    ("wrong hookEventName", HOOK, '{"hookEventName": event,', '{"hookEventName": "Stop",'),
    ("UserPromptSubmit no longer requires work", HOOK,
     'require_work=(event == "UserPromptSubmit")', "require_work=False"),
    ("work never recorded", LIB, '        if it["kind"] in ("bash", "edit"):\n            worked = True',
     '        if False:\n            worked = True'),
    ("interview kind lost on typed entry", LIB,
     '"skill": "interview" if "interview" in entry.group(0) else "goalspec"})',
     '"skill": "goalspec"})'),
]


def suite(plugin):
    rows = []
    for name, build, want in CASES:
        got = run(plugin, build())
        rows.append((name, want, got))
    return rows


def main():
    if "--selftest" in sys.argv:
        failed = []
        for desc, rel, old, new in MUTATIONS:
            d = tempfile.mkdtemp(prefix="ih-mut-")
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
        print("%-45s %-25s %s" % (n, g, "" if w == g else "<-- FAILS (want %s)" % w))
    if bad:
        print("\nFAILURES: %d" % len(bad))
        return 1
    print("\nOK — %d cases, all as expected" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

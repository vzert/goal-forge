#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/nudge-spec-on-entry.sh (0.48.0).

    python3 test/spec-on-entry-branches.py              # the cases
    python3 test/spec-on-entry-branches.py --selftest   # break the component, require a case to notice

The hook adds one line of agent-facing context right after the goalspec LOOP is loaded through the
Skill tool, when this session has no `## Goal-spec` yet (neither in assistant text nor in this
session's .goalspec/checkpoint). It is silent for the interview, the standalone adversary, any other
tool, and a re-entry after a spec already exists. Hermetic: synthetic transcripts in a temp dir, no git.

There is no predecessor to compare against (the hook is new in 0.48.0), so "fails against the old
version" would be vacuous. `--selftest` instead copies the plugin to a temp dir, applies one
mutation at a time to the component itself, and requires at least one case to fail under each.
"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="spec-on-entry-branches-")

SPEC = "## Goal-spec\nObjective: whatever.\n"


def transcript(events, name):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            content = []
            if "skill" in ev:
                content.append({"type": "tool_use", "name": "Skill", "input": {"skill": ev["skill"]}})
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "name": "Write", "input": {"file_path": fp, "content": body}})
            if "thinking" in ev:
                content.append({"type": "thinking", "thinking": ev["thinking"]})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run(plugin, payload_text):
    out = subprocess.run(["bash", os.path.join(plugin, "hooks", "nudge-spec-on-entry.sh")],
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
    # The two claims the line exists to make: post it visibly, and thinking does not count.
    if "## Goal-spec" in ctx and "thinking does not count" in ctx and "visible" in ctx:
        return "nudge:" + str(hso.get("hookEventName"))
    return "other-output"


def post(events, name, tool="Skill", skill="goalspec:goalspec"):
    return json.dumps({"hook_event_name": "PostToolUse", "tool_name": tool,
                       # Always carry the skill field, so case 06 tests the TOOL filter on its
                       # own instead of leaning on the skill filter (selftest found that).
                       "tool_input": {"skill": skill},
                       "transcript_path": transcript(events, name)})


LOAD = {"skill": "goalspec:goalspec"}
CASES = [
    ("01-loop-loaded-no-spec-nudges", lambda: post([LOAD], "01"), "nudge:PostToolUse"),
    ("02-bare-skill-name-nudges", lambda: post([{"skill": "goalspec"}], "02", skill="goalspec"),
     "nudge:PostToolUse"),
    ("03-interview-silent", lambda: post([{"skill": "goalspec:interview"}], "03",
                                         skill="goalspec:interview"), "silent"),
    ("04-adversary-silent", lambda: post([{"skill": "goalspec:adversary"}], "04",
                                         skill="goalspec:adversary"), "silent"),
    ("05-other-skill-silent", lambda: post([{"skill": "review"}], "05", skill="review"), "silent"),
    ("06-other-tool-silent", lambda: post([LOAD], "06", tool="Bash"), "silent"),
    ("07-spec-in-text-already-silent", lambda: post([{"text": SPEC}, LOAD], "07"), "silent"),
    ("08-spec-in-checkpoint-already-silent",
     lambda: post([{"write": (".goalspec/checkpoint-ab12.md", SPEC)}, LOAD], "08"), "silent"),
    # The observed failure: a spec that lives only in thinking is NOT a spec.
    ("09-spec-only-in-thinking-still-nudges",
     lambda: post([{"thinking": SPEC}, LOAD], "09"), "nudge:PostToolUse"),
    ("10-other-event-silent",
     lambda: json.dumps({"hook_event_name": "Stop", "tool_name": "Skill",
                         "tool_input": {"skill": "goalspec:goalspec"},
                         "transcript_path": transcript([LOAD], "10")}), "silent"),
    ("11-malformed-stdin-silent", lambda: "not json {{{", "silent"),
    # No transcript path: nothing proves a spec exists, so the reminder still goes out.
    ("12-no-transcript-nudges",
     lambda: json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Skill",
                         "tool_input": {"skill": "goalspec:goalspec"}}), "nudge:PostToolUse"),
]

LIB = os.path.join("hooks", "lib", "terminal_actions.py")
HOOK = os.path.join("hooks", "nudge-spec-on-entry.sh")
# (description, file, old, new): each must make at least one case fail.
MUTATIONS = [
    ("tool filter dropped", HOOK,
     'or data.get("tool_name") != "Skill":', ':'),
    ("skill filter widened to any goalspec skill", HOOK,
     'if skill not in ("goalspec:goalspec", "goalspec"):', 'if not skill.startswith("goalspec"):'),
    ("existing spec ignored", HOOK,
     'if ta.transcript_signals(data.get("transcript_path")).get("goal_spec"):', "if False:"),
    ("wrong hookEventName", HOOK, '{"hookEventName": "PostToolUse",', '{"hookEventName": "Stop",'),
    ("event filter dropped", HOOK, 'data.get("hook_event_name") != "PostToolUse" or ', ""),
    ("line loses the thinking clause", LIB,
     '"you only plan in your thinking does not count: thinking is not read, even when your screen "',
     '"you only plan in your head is fine: even when your screen "'),
    ("checkpoint spec ignored by the lib", LIB,
     'goal_spec = has_goal_spec(text) or any(it["kind"] == "goal_spec_file" for it in items)',
     "goal_spec = has_goal_spec(text)"),
]


def suite(plugin):
    return [(name, want, run(plugin, build())) for name, build, want in CASES]


def main():
    if "--selftest" in sys.argv:
        failed = []
        for desc, rel, old, new in MUTATIONS:
            d = tempfile.mkdtemp(prefix="soe-mut-")
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

#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/precheck-inline-grounding.sh (0.52.0).

    python3 test/inline-grounding-branches.py              # the cases
    python3 test/inline-grounding-branches.py --selftest   # break the component, require a case to notice

The hook denies, ONCE per session, an inline reading call (Bash, Read, Grep, Glob, WebFetch,
WebSearch) once GOAL_GROUNDING_INLINE_MAX (default 15) of them are on record after the goalspec
entry, with no non-adversary subagent spawned after it and no `## Goal-spec` with a body yet. A
call that a hook denied does not count; once its own deny is on record (a tool_result carrying
"goalspec: broad grounding") it is silent. Hermetic: synthetic transcripts in a temp dir, no git.

There is no predecessor to compare against (the hook is new in 0.52.0), so "fails against the old
version" would be vacuous. `--selftest` copies the plugin to a temp dir, applies one mutation at a
time to the component itself, and requires at least one case to fail under each.
"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="inline-grounding-branches-")

SPEC = ("## Goal-spec\nAsked (your words): whatever.\n1. Real objective: make the report exist.\n"
        "2. Measurable success: the file is committed and every figure re-derives.\n")
BARE = "## Goal-spec\nAsked (your words): x\n"
MARK_RESULT = "PreToolUse:Bash hook error: goalspec: broad grounding in your own context -- 15 ..."
BRAKE_RESULT = "PreToolUse:Bash hook error: goalspec: the loop is loaded and this session has no ## Goal-spec yet"
MODEL_DENY = "PreToolUse:Agent hook error: goalspec: this subagent spawn carries no `model`"


def transcript(events, name):
    p = os.path.join(TMP, name + ".jsonl")
    n = 0
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            if "typed" in ev:
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "text", "text": ev["typed"]}]}}) + "\n")
                continue
            if "result" in ev:  # a tool_result for the previous tool_use
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "t%d" % n, "is_error": True,
                     "content": ev["result"]}]}}) + "\n")
                continue
            content = []
            if "skill" in ev:
                content.append({"type": "tool_use", "id": "s", "name": "Skill", "input": {"skill": ev["skill"]}})
            for _ in range(ev.get("reads", 0)):
                n += 1
                content.append({"type": "tool_use", "id": "t%d" % n, "name": ev.get("tool", "Bash"),
                                "input": {"command": "cat x"}})
            if "spawn" in ev:
                n += 1
                content.append({"type": "tool_use", "id": "t%d" % n, "name": "Agent",
                                "input": {"description": "d", "prompt": "p", **ev["spawn"]}})
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "id": "w", "name": "Write",
                                "input": {"file_path": fp, "content": body}})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run(plugin, payload_text, env_extra=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("GOAL_GROUNDING_CHECK", "GOAL_GROUNDING_INLINE_MAX")}
    out = subprocess.run(["bash", os.path.join(plugin, "hooks", "precheck-inline-grounding.sh")],
                         input=payload_text, capture_output=True, text=True,
                         env={**env, "CLAUDE_PLUGIN_ROOT": plugin, **(env_extra or {})})
    raw = out.stdout.strip()
    if not raw:
        return "allow"
    try:
        hso = json.loads(raw).get("hookSpecificOutput") or {}
    except Exception:
        return "unparseable"
    reason = hso.get("permissionDecisionReason") or ""
    if hso.get("hookEventName") == "PreToolUse" and hso.get("permissionDecision") == "deny":
        if "goalspec: broad grounding" in reason and "goalspec:explorer" in reason \
                and "model: sonnet, effort: high" in reason and "denied once per session" in reason:
            return "deny-%s" % reason.split(" -- ")[1].split(" ")[0]  # the count it saw
        return "deny-other"
    return "other-output"


def pre(events, name, tool="Bash", **extra):
    extra.setdefault("session_id", "sess-1")
    ti = {"command": "cat y"} if tool == "Bash" else {"file_path": "a.py"}
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti,
                       "transcript_path": transcript(events, name), **extra})


LOAD = {"skill": "goalspec:goalspec"}
IV = {"skill": "goalspec:interview"}
GP = {"subagent_type": "general-purpose", "model": "haiku"}

CASES = [
    # The field shape: the interview, 15 inline reads, no subagent, no spec -> the 16th is denied.
    ("01-interview-15-reads-denied", lambda: pre([IV, {"reads": 15}], "01"), "deny-15"),
    ("02-loop-15-reads-denied", lambda: pre([LOAD, {"reads": 15}], "02"), "deny-15"),
    ("03-typed-entry-denied",
     lambda: pre([{"typed": "<command-name>/goalspec:interview</command-name>"}, {"reads": 15}], "03"), "deny-15"),
    ("04-14-reads-allowed", lambda: pre([IV, {"reads": 14}], "04"), "allow"),
    ("05-reads-over-turns-count", lambda: pre([IV, {"reads": 5}, {"reads": 5}, {"reads": 6}], "05"), "deny-16"),
    ("06-every-read-tool-counts",
     lambda: pre([IV, {"reads": 3, "tool": "Read"}, {"reads": 3, "tool": "Grep"}, {"reads": 3, "tool": "Glob"},
                  {"reads": 3, "tool": "WebFetch"}, {"reads": 3, "tool": "WebSearch"}], "06", tool="Read"),
     "deny-15"),
    ("07-reads-before-entry-do-not-count", lambda: pre([{"reads": 20}, IV, {"reads": 3}], "07"), "allow"),
    # Delegation after the entry silences it -- any non-adversary type, model or not.
    ("08-subagent-after-entry-allowed", lambda: pre([IV, {"reads": 3, "spawn": GP}, {"reads": 20}], "08"), "allow"),
    ("09-explorer-allowed",
     lambda: pre([IV, {"spawn": {"subagent_type": "goalspec:explorer"}}, {"reads": 20}], "09"), "allow"),
    ("10-adversary-is-not-delegation",
     lambda: pre([IV, {"spawn": {"subagent_type": "goalspec:goal-adversary", "model": "sonnet"}},
                  {"reads": 15}], "10"), "deny-15"),
    # Release round 1 (subagent adversary): a spawn a hook denied never ran, so it is not delegation.
    ("10b-denied-spawn-is-not-delegation",
     lambda: pre([IV, {"spawn": {"subagent_type": "general-purpose"}}, {"result": MODEL_DENY}, {"reads": 15}], "10b"),
     "deny-15"),
    ("10c-relaunched-spawn-is-delegation",
     lambda: pre([IV, {"spawn": {"subagent_type": "general-purpose"}}, {"result": MODEL_DENY},
                  {"spawn": GP}, {"reads": 15}], "10c"), "allow"),
    ("11-spawn-before-entry-is-not-delegation", lambda: pre([{"spawn": GP}, IV, {"reads": 15}], "11"), "deny-15"),
    # A spec ends the grounding window.
    ("12-spec-in-text-allowed", lambda: pre([LOAD, {"reads": 5, "text": SPEC}, {"reads": 20}], "12"), "allow"),
    ("13-spec-in-checkpoint-allowed",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-sess-1.md", SPEC)}, {"reads": 20}], "13"), "allow"),
    ("14-bare-heading-still-denied", lambda: pre([LOAD, {"text": BARE}, {"reads": 15}], "14"), "deny-15"),
    ("15-foreign-checkpoint-still-denied",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-other.md", SPEC)}, {"reads": 15}], "15"), "deny-15"),
    # Deny once: its own deny on record -> silent; a call another hook denied does not count.
    ("16-own-deny-on-record-allowed", lambda: pre([IV, {"reads": 15}, {"result": MARK_RESULT}, {"reads": 9}], "16"),
     "allow"),
    ("17-brake-denied-read-not-counted", lambda: pre([LOAD, {"reads": 15}, {"result": BRAKE_RESULT}], "17"),
     "allow"),
    ("18-brake-denied-then-one-more", lambda: pre([LOAD, {"reads": 15}, {"result": BRAKE_RESULT}, {"reads": 1}], "18"),
     "deny-15"),
    # Silent branches.
    ("19-inside-subagent-allowed", lambda: pre([IV, {"reads": 20}], "19", agent_id="a1"), "allow"),
    ("20-no-goalspec-allowed", lambda: pre([{"reads": 30}], "20"), "allow"),
    ("21-adversary-skill-only-allowed", lambda: pre([{"skill": "goalspec:adversary"}, {"reads": 30}], "21"), "allow"),
    ("22-other-tool-allowed", lambda: pre([IV, {"reads": 20}], "22", tool="Write"), "allow"),
    ("23-other-event-allowed",
     lambda: json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"},
                         "transcript_path": transcript([IV, {"reads": 20}], "23")}), "allow"),
    ("24-malformed-stdin-allowed", lambda: "not json {{{", "allow"),
    ("25-no-transcript-allowed",
     lambda: json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}),
     "allow"),
]
ENV_CASES = [
    ("26-opt-out-env-allowed", lambda: pre([IV, {"reads": 20}], "26"), {"GOAL_GROUNDING_CHECK": "0"}, "allow"),
    ("27-other-env-value-still-denies", lambda: pre([IV, {"reads": 15}], "27"), {"GOAL_GROUNDING_CHECK": "1"},
     "deny-15"),
    ("28-threshold-env-lower", lambda: pre([IV, {"reads": 5}], "28"), {"GOAL_GROUNDING_INLINE_MAX": "5"}, "deny-5"),
    ("29-threshold-env-higher", lambda: pre([IV, {"reads": 15}], "29"), {"GOAL_GROUNDING_INLINE_MAX": "30"}, "allow"),
    ("30-threshold-env-garbage-defaults", lambda: pre([IV, {"reads": 15}], "30"), {"GOAL_GROUNDING_INLINE_MAX": "x"},
     "deny-15"),
]


def run_cases(plugin, quiet=False):
    fails = 0
    for name, mk, want in CASES:
        got = run(plugin, mk())
        fails += got != want
        if not quiet:
            print(("PASS" if got == want else "FAIL") + "  %s  want=%s got=%s" % (name, want, got))
    for name, mk, env, want in ENV_CASES:
        got = run(plugin, mk(), env)
        fails += got != want
        if not quiet:
            print(("PASS" if got == want else "FAIL") + "  %s  want=%s got=%s" % (name, want, got))
    return fails


MUTATIONS = [
    ("no-deny-once", "or spawned or bounced or count < limit", "or spawned or count < limit"),
    ("ignore-spawn", "or spawned or bounced or count < limit", "or bounced or count < limit"),
    ("ignore-spec", "if not entered or spec or spawned", "if not entered or spawned"),
    # No "ignore-entry" mutation: before the entry nothing is counted, so dropping `not entered` from
    # the final test is an equivalent mutant (count is 0 < limit) and no case could notice it.
    # "count-before-entry" below is the mutation that does test the entry.
    ("count-before-entry", 'if not entered or ev.get("type") != "assistant"', 'if ev.get("type") != "assistant"'),
    ("adversary-delegates", 'if not ta.is_adversary_type(st if isinstance(st, str) else ""):', "if True:"),
    ("denied-reads-count", "count = sum(1 for k in reads if k not in denied)", "count = len(reads)"),
    ("off-by-one", "count < limit", "count <= limit"),
    ("denied-spawn-delegates", "spawned = any(k not in denied for k in spawns)", "spawned = bool(spawns)"),
    ("subagent-not-exempt", 'if data.get("agent_id"):', 'if data.get("__never__"):'),
    ("opt-out-ignored", '[ "${GOAL_GROUNDING_CHECK:-}" = "0" ] && exit 0', ":"),
    ("threshold-env-ignored", 'int(os.environ.get("MAXR") or "15")', "15"),
    ("bare-heading-releases", 'ta.spec_has_body(it.get("text") or ""):\n                    spec = True\n                elif',
     'ta.has_goal_spec(it.get("text") or ""):\n                    spec = True\n                elif'),
    ("any-checkpoint-releases", 'and own.search(it.get("path") or "")', ""),
    ("only-bash-counts", 'if blk.get("name") in READS:', 'if blk.get("name") == "Bash":'),
]


def selftest():
    bad = 0
    for label, old, new in MUTATIONS:
        d = tempfile.mkdtemp(prefix="inline-grounding-mut-")
        dst = os.path.join(d, "goalspec")
        shutil.copytree(PLUGIN, dst)
        hp = os.path.join(dst, "hooks", "precheck-inline-grounding.sh")
        src = open(hp, encoding="utf-8").read()
        if old not in src:
            print("SELFTEST-ERROR  %s: anchor not found" % label)
            bad += 1
            continue
        open(hp, "w", encoding="utf-8").write(src.replace(old, new, 1))
        caught = run_cases(dst, quiet=True)
        print(("CAUGHT" if caught else "MISSED") + "  %s  (%d case(s) failed)" % (label, caught))
        bad += not caught
        shutil.rmtree(d, ignore_errors=True)
    return bad


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        base = run_cases(PLUGIN, quiet=True)
        if base:
            print("SELFTEST-ERROR  the unmutated component fails %d case(s)" % base)
            sys.exit(1)
        missed = selftest()
        print("selftest: %d mutation(s), %d missed" % (len(MUTATIONS), missed))
        sys.exit(1 if missed else 0)
    f = run_cases(PLUGIN)
    total = len(CASES) + len(ENV_CASES)
    print("%d/%d passed" % (total - f, total))
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if f else 0)

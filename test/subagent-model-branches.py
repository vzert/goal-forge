#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/precheck-subagent-model.sh (0.50.0).

    python3 test/subagent-model-branches.py              # the cases
    python3 test/subagent-model-branches.py --selftest   # break the component, require a case to notice

The hook denies, ONCE per session and per kind (worker / goal-adversary), a Task/Agent spawn that
carries no `model`, in a session that entered goalspec. It allows a spawn that carries `model`, a
`fork`, a spawn made inside a subagent (agent_id), a session with no goalspec, a second model-less
spawn of the same kind after the entry, and anything when GOAL_SUBAGENT_MODEL_CHECK=0.
Hermetic: synthetic transcripts in a temp dir, no git.

There is no predecessor to compare against (the hook is new in 0.50.0), so "fails against the old
version" would be vacuous. `--selftest` copies the plugin to a temp dir, applies one mutation at a
time to the component itself, and requires at least one case to fail under each.
"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="subagent-model-branches-")


def transcript(events, name):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            if "typed" in ev:
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "text", "text": ev["typed"]}]}}) + "\n")
                continue
            content = []
            if "skill" in ev:
                content.append({"type": "tool_use", "id": "s", "name": "Skill",
                                "input": {"skill": ev["skill"]}})
            if "spawn" in ev:
                content.append({"type": "tool_use", "id": "t", "name": ev.get("tool", "Agent"),
                                "input": {"description": "d", "prompt": "p", **ev["spawn"]}})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run(plugin, payload_text, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k != "GOAL_SUBAGENT_MODEL_CHECK"}
    out = subprocess.run(["bash", os.path.join(plugin, "hooks", "precheck-subagent-model.sh")],
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
        # Which reason: the cost table for workers, the independence rule for the adversary.
        if "Subagent model by task" in reason and "model: haiku" in reason and "model: sonnet" in reason \
                and "effort" in reason and "unless its agent type pins one" in reason \
                and "goalspec:explorer" in reason:
            return "deny-worker"
        if "a fork always runs on YOUR model" in reason and "goalspec:explorer" in reason:
            return "deny-fork"
        if "Different model on every run" in reason and "ADVERSARY-MODEL" in reason \
                and "unless its agent type pins one" in reason:
            return "deny-adversary"
        return "deny-other"
    return "other-output"


def pre(events, name, tool_input=None, tool="Agent", **extra):
    if tool_input is None:
        tool_input = {"description": "d", "prompt": "p", "subagent_type": "general-purpose"}
    extra.setdefault("session_id", "sess-1")
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                       "transcript_path": transcript(events, name), **extra})


LOAD = {"skill": "goalspec:goalspec"}
GP = {"description": "d", "prompt": "p", "subagent_type": "general-purpose"}
ADV = {"description": "d", "prompt": "p", "subagent_type": "goalspec:goal-adversary"}

CASES = [
    # The field case: loop loaded, general-purpose spawn with no model -> denied with the table.
    ("01-loop-no-model-denied", lambda: pre([LOAD], "01"), "deny-worker"),
    ("02-task-tool-denied", lambda: pre([LOAD], "02", tool="Task"), "deny-worker"),
    ("03-no-subagent-type-denied",
     lambda: pre([LOAD], "03", tool_input={"description": "d", "prompt": "p"}), "deny-worker"),
    ("04-interview-entry-denied", lambda: pre([{"skill": "goalspec:interview"}], "04"), "deny-worker"),
    ("05-typed-command-denied",
     lambda: pre([{"typed": "<command-name>/goalspec:goalspec</command-name>"}], "05"), "deny-worker"),
    ("06-explore-type-denied",
     lambda: pre([LOAD], "06", tool_input={**GP, "subagent_type": "Explore"}), "deny-worker"),
    # A model on the spawn passes, whichever tier -- the agent's choice, made explicitly.
    ("07-haiku-allowed", lambda: pre([LOAD], "07", tool_input={**GP, "model": "haiku"}), "allow"),
    ("08-opus-explicit-allowed", lambda: pre([LOAD], "08", tool_input={**GP, "model": "opus"}), "allow"),
    ("09-blank-model-denied", lambda: pre([LOAD], "09", tool_input={**GP, "model": "  "}), "deny-worker"),
    # Deny once: a model-less worker spawn already on record after the entry -> the next one passes.
    ("10-second-model-less-allowed", lambda: pre([LOAD, {"spawn": GP}], "10"), "allow"),
    ("11-earlier-spawn-had-model-still-denied",
     lambda: pre([LOAD, {"spawn": {**GP, "model": "haiku"}}], "11"), "deny-worker"),
    ("12-model-less-before-entry-still-denied", lambda: pre([{"spawn": GP}, LOAD], "12"), "deny-worker"),
    # The adversary has its own counter and its own reason.
    ("13-adversary-no-model-denied", lambda: pre([LOAD], "13", tool_input=ADV), "deny-adversary"),
    ("14-adversary-bare-name-denied",
     lambda: pre([LOAD], "14", tool_input={**ADV, "subagent_type": "goal-adversary"}), "deny-adversary"),
    ("15-adversary-with-model-allowed",
     lambda: pre([LOAD], "15", tool_input={**ADV, "model": "sonnet"}), "allow"),
    ("16-worker-bounce-does-not-spend-adversary",
     lambda: pre([LOAD, {"spawn": GP}], "16", tool_input=ADV), "deny-adversary"),
    ("17-adversary-bounce-does-not-spend-worker",
     lambda: pre([LOAD, {"spawn": ADV}], "17"), "deny-worker"),
    ("18-second-adversary-allowed", lambda: pre([LOAD, {"spawn": ADV}], "18", tool_input=ADV), "allow"),
    ("19-lookalike-adversary-is-worker",
     lambda: pre([LOAD], "19", tool_input={**ADV, "subagent_type": "not-goal-adversary-x"}), "deny-worker"),
    # Silent branches.
    # 0.52.0: a fork always runs on the parent model -> its own kind, denied once even with `model`.
    ("20-fork-denied", lambda: pre([LOAD], "20", tool_input={**GP, "subagent_type": "fork"}), "deny-fork"),
    ("20b-fork-with-model-denied",
     lambda: pre([LOAD], "20b", tool_input={**GP, "subagent_type": "fork", "model": "haiku"}), "deny-fork"),
    ("20c-second-fork-allowed",
     lambda: pre([LOAD, {"spawn": {**GP, "subagent_type": "fork", "model": "haiku"}}], "20c",
                 tool_input={**GP, "subagent_type": "fork"}), "allow"),
    ("20d-fork-bounce-does-not-spend-worker",
     lambda: pre([LOAD, {"spawn": {**GP, "subagent_type": "fork"}}], "20d"), "deny-worker"),
    ("20e-worker-bounce-does-not-spend-fork",
     lambda: pre([LOAD, {"spawn": GP}], "20e", tool_input={**GP, "subagent_type": "fork"}), "deny-fork"),
    # 0.52.0: goalspec:explorer pins model: haiku in its definition -> no bounce, and spends nothing.
    ("20f-explorer-allowed",
     lambda: pre([LOAD], "20f", tool_input={**GP, "subagent_type": "goalspec:explorer"}), "allow"),
    ("20g-explorer-does-not-spend-worker",
     lambda: pre([LOAD, {"spawn": {**GP, "subagent_type": "goalspec:explorer"}}], "20g"), "deny-worker"),
    ("20h-bare-explorer-is-a-worker",
     lambda: pre([LOAD], "20h", tool_input={**GP, "subagent_type": "explorer"}), "deny-worker"),
    ("21-inside-subagent-allowed", lambda: pre([LOAD], "21", agent_id="a1"), "allow"),
    ("22-no-goalspec-allowed", lambda: pre([{"text": "hello"}], "22"), "allow"),
    ("23-adversary-skill-only-allowed", lambda: pre([{"skill": "goalspec:adversary"}], "23"), "allow"),
    ("24-other-tool-allowed",
     lambda: pre([LOAD], "24", tool="Bash", tool_input={"command": "ls"}), "allow"),
    ("25-other-event-allowed",
     lambda: json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Agent", "tool_input": GP,
                         "transcript_path": transcript([LOAD], "25")}), "allow"),
    ("26-malformed-stdin-allowed", lambda: "not json {{{", "allow"),
    ("27-no-transcript-allowed",
     lambda: json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": GP}),
     "allow"),
]
ENV_CASES = [
    ("28-opt-out-env-allowed", lambda: pre([LOAD], "28"), {"GOAL_SUBAGENT_MODEL_CHECK": "0"}, "allow"),
    ("29-other-env-value-still-denies", lambda: pre([LOAD], "29"),
     {"GOAL_SUBAGENT_MODEL_CHECK": "1"}, "deny-worker"),
]


def run_cases(plugin, quiet=False):
    fails = 0
    for name, mk, want in CASES:
        got = run(plugin, mk())
        ok = got == want
        fails += not ok
        if not quiet:
            print(("PASS" if ok else "FAIL") + "  %s  want=%s got=%s" % (name, want, got))
    for name, mk, env, want in ENV_CASES:
        got = run(plugin, mk(), env)
        ok = got == want
        fails += not ok
        if not quiet:
            print(("PASS" if ok else "FAIL") + "  %s  want=%s got=%s" % (name, want, got))
    return fails


# Each mutation breaks one behavior of the component; a case must notice every one.
MUTATIONS = [
    ("no-deny-once", 'if not entered or bounced:', 'if not entered:'),
    ("ignore-entry", 'if not entered or bounced:', 'if bounced:'),
    ("model-ignored", 'k == "fork" or not has_model(inp)', 'True'),
    ("fork-model-honored", 'k == "fork" or not has_model(inp)', 'not has_model(inp)'),
    ("fork-as-worker", 'return "fork"  #', 'return "worker"  #'),
    ("explorer-not-exempt", 'if st == "goalspec:explorer":', 'if st == "__never__":'),
    ("explorer-prefix-exempt", 'if st == "goalspec:explorer":', 'if st.endswith("explorer"):'),
    ("subagent-not-exempt", 'if data.get("agent_id"):', 'if data.get("__never__"):'),
    ("shared-counter", 'unpinned(bi) == kind:', 'unpinned(bi) is not None:'),
    ("adversary-as-worker", '"adversary" if ta.is_adversary_type(st) else "worker"', '"worker"'),
    ("count-before-entry", 'if not entered or ev.get("type") != "assistant":',
     'if ev.get("type") != "assistant":'),
    ("opt-out-ignored", '[ "${GOAL_SUBAGENT_MODEL_CHECK:-}" = "0" ] && exit 0', ':'),
    ("blank-model-counts", 'return isinstance(v, str) and v.strip() != ""', 'return isinstance(v, str)'),
]


def selftest():
    bad = 0
    for label, old, new in MUTATIONS:
        d = tempfile.mkdtemp(prefix="subagent-model-mut-")
        dst = os.path.join(d, "goalspec")
        shutil.copytree(PLUGIN, dst)
        hp = os.path.join(dst, "hooks", "precheck-subagent-model.sh")
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

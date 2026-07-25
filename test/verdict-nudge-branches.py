#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/remind-quote-verdict.sh (the PostToolUse verdict nudge).

Same shape and spirit as gate-branches.py: synthetic hook payloads, one row per branch, exit
non-zero if an observed branch changed.

    python3 test/verdict-nudge-branches.py                          # run against the repo's hook
    python3 test/verdict-nudge-branches.py --compare <other.sh>     # parity vs a pre-edit copy

The two payload SHAPES are the point of this file. Since Claude Code v2.1.198 a subagent spawn
returns asynchronously: the tool result is a handle (`status: "async_launched"`, no `content`
field) and the verdict arrives later. Until 0.18.0 the nudge required verdict-shaped text in the
response, so it exited silently on every default spawn — shipped and dead. The handle also echoes
the executor's own `prompt`, which this method fills with prior verdicts, so the fix must NOT read
that field as output that "came back" (case 04 pins exactly that).

Columns: case | branch the hook took (verdict / malformed / launched / silent).
"""
import argparse, json, os, re, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "remind-quote-verdict.sh")

VERDICT = ("[ADVERSARY-VERDICT: break ungrounded=1 unfalsified=0 incomplete=0 "
           "autonomy-violations=0 unsafe=0]")
MODEL = "[ADVERSARY-MODEL: Claude Sonnet 5 / claude-sonnet-5]"

# The real shape of a backgrounded spawn's result, keys taken from an observed transcript
# toolUseResult (2026-07-25 21:00:40Z): no `content`, and the executor's payload echoed in `prompt`.
ASYNC_HANDLE = {"isAsync": True, "status": "async_launched", "agentId": "aac762988cccd0456",
                "outputFile": "/tmp/tasks/aac762988cccd0456.output", "canReadOutputFile": True,
                "resolvedModel": "claude-sonnet-5",
                "prompt": "Sos el adversario independiente. Ronda previa: " + VERDICT}

CASES = [
    ("01-other-tool", {"tool_name": "Bash", "tool_input": {"command": "ls"},
                       "tool_response": MODEL + "\n" + VERDICT}),
    ("02-other-subagent", {"tool_name": "Task", "tool_input": {"subagent_type": "general-purpose"},
                           "tool_response": MODEL + "\n" + VERDICT}),
    ("03-lookalike-subagent", {"tool_name": "Task",
                               "tool_input": {"subagent_type": "not-goal-adversary-example"},
                               "tool_response": MODEL + "\n" + VERDICT}),
    # THE regression case: backgrounded spawn, no content, prior verdict echoed in `prompt`.
    # Must take the `launched` branch — never `verdict`, which would report the executor's own text.
    ("04-async-handle-echoes-prompt", {"tool_name": "Task",
                                       "tool_input": {"subagent_type": "goalspec:goal-adversary"},
                                       "tool_response": ASYNC_HANDLE}),
    # A synchronous result that really did carry the agent's output.
    ("05-sync-verdict", {"tool_name": "Task", "tool_input": {"subagent_type": "goal-adversary"},
                         "tool_response": {"content": [{"type": "text",
                                                        "text": MODEL + "\n" + VERDICT}]}}),
    ("06-sync-model-only", {"tool_name": "Task", "tool_input": {"subagent_type": "goal-adversary"},
                            "tool_response": {"content": [{"type": "text", "text": MODEL}]}}),
    # A spawn whose result is empty/unknown still gets the visibility reminder.
    ("07-empty-response", {"tool_name": "Agent", "tool_input": {"subagentType": "goal-adversary"},
                           "tool_response": {}}),
    ("08-missing-response", {"tool_name": "Task", "tool_input": {"subagent_type": "goal-adversary"}}),
]


def run(hook, payload):
    out = subprocess.run(["bash", hook], input=json.dumps(payload),
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return "silent"
    try:
        msg = json.loads(out).get("systemMessage") or ""
    except Exception:
        return "unparseable"
    if "just came back in this tool result" in msg:
        return "verdict"
    if "no well-formed" in msg:
        return "malformed"
    if "no adversary output" in msg:
        return "launched"
    return "unknown-message"


def suite(hook):
    return [(name, run(hook, payload)) for name, payload in CASES]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hook", nargs="?", default=DEFAULT_HOOK)
    ap.add_argument("--compare", metavar="OTHER_HOOK")
    ap.add_argument("--expected", default="", help="case-name prefixes whose diff is INTENDED")
    a = ap.parse_args()

    expected = [s.strip() for s in a.expected.split(",") if s.strip()]
    rows = suite(a.hook)
    other = suite(a.compare) if a.compare else None
    for i, (name, branch) in enumerate(rows):
        flag = ""
        if other and other[i][1] != branch:
            tag = "EXPECTED-DIFF" if any(name.startswith(p) for p in expected) else "DIFFERS"
            flag = "   <-- %s: %s" % (tag, other[i][1])
        print("%-32s %-12s%s" % (name, branch, flag))

    if other:
        diffs = [r[0] for r, o in zip(rows, other) if r[1] != o[1]]
        unexpected = [d for d in diffs if not any(d.startswith(p) for p in expected)]
        if diffs:
            print("\n%d branch(es) changed: %s" % (len(diffs), ", ".join(diffs)))
        if unexpected:
            print("REGRESSION: %d unexpected: %s" % (len(unexpected), ", ".join(unexpected)))
            return 1
        print("\nparity OK — %d branches, %d intended change(s)" % (len(rows), len(diffs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

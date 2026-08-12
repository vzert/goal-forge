#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/announce-checkpoint-name.sh.

    python3 test/announce-checkpoint-branches.py

Exit code is non-zero if any case does not produce its expected cell.

What the hook does: on SessionStart, emit ONE line of `additionalContext` naming the exact path
this session's durable checkpoint must use, `.goalspec/checkpoint-<session_id>.md`. It exists
because the harness knows the session id and the agent does not — which is what the naming rule in
`references/durable-artifact.md` had been asking the agent to substitute for by deriving a token of
its own. Two adversary rounds on that rule complained about exactly that substitution, from
different angles.

Hermetic: every case drives the hook directly with a synthetic payload, the same pattern
`usage-budget-branches.py` and `decompose-nudge-branches.py` use for theirs. No session, no
network, no filesystem state.

WHAT THIS SUITE DOES NOT COVER, stated so a green run does not imply more
(references/instrument-validity-own-tools.md): it asserts what the hook EMITS, never that the
agent then uses it. The consumer here is a model reading injected context, which no hermetic test
can stand in for. That half was observed once, live, in a headless child session during the
investigation that produced this hook (a probe injected the message and the child, asked with no
tools available, answered with the announced path) — one observation, in a throwaway project, not
a guarantee, and not something this file re-runs.

The other half this does not cover: nothing here proves the announced name is what a real run then
writes. There is no gate on it by design (the blocking `PreToolUse` half was deliberately left
out — see the hook's own header), so an agent that ignores the announcement is silently ignoring it.
"""
import json, os, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "announce-checkpoint-name.sh")

SID = "051d39c4-8a4e-4cf6-bb8e-a32cfd2ce134"   # shape of a real one, captured from a live payload

# (name, payload_or_RAW_string, expected)
#   expected: "announce" or "silent"
CASES = [
    # --- the normal path, on every source. A compacted session is precisely the one most likely to
    #     have lost the name, so no source is excluded. ---
    ("01-startup-announces", {"session_id": SID, "source": "startup"}, "announce"),
    ("02-resume-announces", {"session_id": SID, "source": "resume"}, "announce"),
    ("03-compact-announces", {"session_id": SID, "source": "compact"}, "announce"),
    ("04-no-source-field-announces", {"session_id": SID}, "announce"),

    # --- fail-open: anything it cannot read is silent, never an error and never a guess ---
    ("05-no-session-id-silent", {"source": "startup"}, "silent"),
    ("06-empty-session-id-silent", {"session_id": ""}, "silent"),
    ("07-whitespace-session-id-silent", {"session_id": "   "}, "silent"),
    ("08-non-string-session-id-silent", {"session_id": 12345}, "silent"),
    ("09-malformed-json-silent", "RAW:not json {{{", "silent"),
    ("10-empty-stdin-silent", "RAW:", "silent"),

    # --- the id lands in a FILENAME, so a value the read-side matchers would reject must not be
    #     announced at all. Announcing a name that `terminal_actions.py` CHECKPOINT_PATH_RE and
    #     `nudge-decompose.sh` cannot match would be worse than announcing nothing: the agent would
    #     obey it and then be invisible to both consumers. ---
    ("11-path-separator-in-id-silent", {"session_id": "abc/../../etc/passwd"}, "silent"),
    ("12-space-in-id-silent", {"session_id": "abc 123"}, "silent"),
    ("13-quote-in-id-silent", {"session_id": 'abc"123'}, "silent"),
]


def run_case(payload):
    if isinstance(payload, str) and payload.startswith("RAW:"):
        stdin = payload[4:]
    else:
        stdin = json.dumps(payload)
    out = subprocess.run(["bash", HOOK], input=stdin, capture_output=True, text=True).stdout.strip()
    return out


def main():
    failures = []
    for name, payload, expected in CASES:
        out = run_case(payload)
        got = "announce" if out else "silent"
        ok = got == expected
        if not ok:
            failures.append((name, expected, got))
        print("{:<34} {:<9} {}".format(name, got, "" if ok else "  <-- FAIL, expected " + expected))

    # --- content, not just announce/silent. Every case above collapses the output to presence, so
    # without this the hook could announce a WRONG path and stay green. Three separate claims:
    # the emitted path carries the session id in full (not truncated -- truncation would be a
    # probabilistic uniqueness claim, and defending that kind of claim is what this hook exists to
    # stop needing), it is shaped exactly as the read-side matchers expect, and it is delivered on
    # the field the harness actually feeds back to the model. ---
    print()
    raw = run_case({"session_id": SID, "source": "startup"})
    checks = []
    try:
        d = json.loads(raw)
        hso = d.get("hookSpecificOutput") or {}
        ctx = hso.get("additionalContext") or ""
        checks.append(("event-name", hso.get("hookEventName") == "SessionStart"))
        checks.append(("delivered-as-additionalContext", bool(ctx)))
        checks.append(("path-exact", ".goalspec/checkpoint-%s.md" % SID in ctx))
        checks.append(("id-not-truncated", SID in ctx))
        # The announced name must satisfy the two read-side matchers, or the agent obeying it goes
        # invisible to both. Re-derived here from the module itself rather than copied as a string.
        sys.path.insert(0, os.path.join(REPO, "plugins", "goalspec", "hooks", "lib"))
        import terminal_actions as ta
        checks.append(("matches-read-side-regex",
                       bool(ta.CHECKPOINT_PATH_RE.search(".goalspec/checkpoint-%s.md" % SID))))
    except Exception as exc:
        checks.append(("parse-output", False))
        print("  (output could not be parsed: %r)" % (exc,))

    for label, ok in checks:
        print("{:<34} {}".format("content:" + label, "ok" if ok else "FAIL"))
        if not ok:
            failures.append(("content:" + label, "ok", "FAIL"))

    total = len(CASES) + len(checks)
    print()
    if failures:
        print("{} check(s) FAILED".format(len(failures)))
        return 1
    print("all {} check(s) OK".format(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())

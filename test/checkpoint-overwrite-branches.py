#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/precheck-checkpoint-overwrite.sh.

    python3 test/checkpoint-overwrite-branches.py

Exit code is non-zero if any case does not produce its expected decision.

What the hook does: on `PreToolUse(Write|Edit)`, DENY one act — overwriting a durable checkpoint
that already exists and that this session cannot be shown to have successfully written. Everything
else allows.

Why the condition is ownership and not "the name is wrong": denying every non-announced name would
break a project that deliberately commits `.goalspec/` as a trail under its own names (a case
`references/durable-artifact.md` blesses) and would deny a fresh session creating a checkpoint
where nothing exists, which harms nobody. The dangerous act is taking somebody else's file. Cases
04/05/06 are the controls for that distinction and they are the ones that fail if the condition
ever drifts back to a name check.

Fail-open governs everything BEFORE ownership is asked about — a payload it cannot parse, a path
that is not a checkpoint, a file that does not exist yet (cases 10-15). Ownership itself fails
CLOSED: no readable transcript, or no successful write by this session, denies (cases 09, 16, 17).
That split is the correction an adversary round forced, after rating the older allow-everything
version unsafe: at that point in the flow the target is known to be an existing checkpoint in this
project, so "I cannot tell whose it is" is not a reason to let it be overwritten. Escaping a wrong
deny is always available and never blocked — write under your own name, which does not exist yet.

Hermetic: real files on disk in a temp dir (the hook stats the target, so a synthetic path is not
enough) plus a synthetic transcript. No session, no network, no git.

WHAT THIS SUITE DOES NOT COVER, stated so a green run does not imply more
(references/instrument-validity-own-tools.md): it drives the hook directly, so it proves the
decision the hook returns, never that the harness honors it for a `Write`. That half was observed
live during the investigation that produced this hook — a probe `deny` on a `Write|Edit` matcher
blocked a headless child session's write and the file was never created — and separately for
`ask` in three permission modes. Neither observation is re-run here. Nor does anything here
exercise two genuinely concurrent sessions; that gap is open and named as such.
"""
import json, os, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "precheck-checkpoint-overwrite.sh")

CHECKPOINT_BODY = "# Checkpoint\n\n## Coverage-floor table\n\n| e | s |\n|---|---|\n| a | done |\n"


def build(case, *, target_rel, exists=True, wrote_paths=(), tool="Write",
          transcript=True, cwd_override=None, extra_files=(), result="ok"):
    """One case fixture: a project dir, optionally the target file on disk, and a transcript whose
    Write/Edit tool_uses are `wrote_paths` (relative to the project dir).

    `result` decides what the paired tool_result says for each of those writes, and it is the whole
    point of several cases below: "ok" (succeeded), "error" (the write was DENIED or failed), or
    "none" (no result recorded at all). A tool_use alone is a request, not an act — modelling every
    recorded write as successful is exactly the blind spot that let a denied attempt count as
    ownership. Shape copied from a real transcript: results arrive in a `user`-type message as
    {"type": "tool_result", "tool_use_id": ..., "is_error": ...}.
    """
    root = tempfile.mkdtemp(prefix="ckpt-overwrite-%s-" % case)
    for rel in list(extra_files) + ([target_rel] if exists else []):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(CHECKPOINT_BODY)

    payload = {
        "tool_name": tool,
        "tool_input": {"file_path": os.path.join(root, target_rel), "content": "new body"},
        "cwd": cwd_override or root,
        "session_id": "051d39c4-8a4e-4cf6-bb8e-a32cfd2ce134",
    }
    if transcript:
        tp = os.path.join(root, "transcript.jsonl")
        with open(tp, "w", encoding="utf-8") as fh:
            for i, rel in enumerate(wrote_paths):
                tid = "toolu_%s_%d" % (case, i)
                ev = {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "id": tid, "name": "Write",
                     "input": {"file_path": os.path.join(root, rel)}}]}}
                fh.write(json.dumps(ev) + "\n")
                if result != "none":
                    res = {"type": "user", "message": {"content": [
                        {"type": "tool_result", "tool_use_id": tid,
                         "is_error": result == "error",
                         "content": "denied" if result == "error" else "File written"}]}}
                    fh.write(json.dumps(res) + "\n")
        payload["transcript_path"] = tp
    else:
        payload["transcript_path"] = os.path.join(root, "missing.jsonl")
    return payload


def run(payload):
    out = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return "allow", ""
    try:
        d = json.loads(out)
    except Exception:
        return "unparseable", out[:80]
    hso = d.get("hookSpecificOutput") or {}
    if hso.get("permissionDecision") == "deny":
        return "deny", hso.get("permissionDecisionReason") or ""
    return "allow", ""


CK = ".goalspec/checkpoint-aaaa.md"
LEGACY = ".goalspec/checkpoint.md"

CASES = [
    # --- THE incident: an existing checkpoint this session never wrote, under either name ---
    ("01-foreign-existing-session-scoped-DENY", dict(target_rel=CK), "deny"),
    ("02-foreign-existing-legacy-name-DENY", dict(target_rel=LEGACY), "deny"),
    ("03-foreign-existing-via-Edit-DENY", dict(target_rel=CK, tool="Edit"), "deny"),

    # --- the controls that keep this from becoming a name check ---
    # Creating where nothing exists harms nobody, whatever the name.
    ("04-does-not-exist-yet-ALLOW", dict(target_rel=CK, exists=False), "allow"),
    ("05-legacy-name-does-not-exist-ALLOW", dict(target_rel=LEGACY, exists=False), "allow"),
    # A project committing .goalspec/ as a trail under its own names: still its own session's file.
    ("06-own-file-rewritten-each-round-ALLOW",
     dict(target_rel=CK, wrote_paths=(CK,)), "allow"),
    ("07-own-legacy-name-ALLOW",
     dict(target_rel=LEGACY, wrote_paths=(LEGACY,)), "allow"),
    # Wrote a DIFFERENT checkpoint, not this one -> this one is still not ours.
    ("08-wrote-a-different-checkpoint-DENY",
     dict(target_rel=CK, wrote_paths=(".goalspec/checkpoint-bbbb.md",),
          extra_files=(".goalspec/checkpoint-bbbb.md",)), "deny"),

    # --- THE RETRY HOLE. Found by an adversary round, reproduced against a real transcript, and
    #     rated unsafe: a DENIED Write is still recorded as a tool_use. Counting that as ownership
    #     meant the first clobber attempt was denied, the denial became "evidence" the session had
    #     written the file, and the identical retry was ALLOWED — destroying the live state this
    #     gate exists to protect, on the second try. 16 is that exact scenario; 17 is the same for
    #     a write with no recorded result at all (at PreToolUse time an earlier write has already
    #     resolved, so no result means it did not happen); 18 is the positive control that a
    #     genuinely successful write still grants ownership, so the fix cannot be "always deny". ---
    ("16-denied-write-then-retry-DENY",
     dict(target_rel=CK, wrote_paths=(CK,), result="error"), "deny"),
    ("17-write-with-no-result-recorded-DENY",
     dict(target_rel=CK, wrote_paths=(CK,), result="none"), "deny"),
    ("18-successful-write-then-rewrite-ALLOW",
     dict(target_rel=CK, wrote_paths=(CK,), result="ok"), "allow"),

    # --- fail-open: every uncertainty allows, the opposite direction from nudge-decompose.sh ---
    # EXPECTATION CHANGED, deliberately: this used to ALLOW. An adversary round rated that unsafe —
    # a broken ownership instrument permitting exactly the destructive act the gate exists to
    # refuse, with documentation offered as the remedy, which is not a remedy. The justification
    # for allowing ("denying would break harnesses that supply no transcript") was then audited
    # against the official hooks reference and did not survive: `transcript_path` is a common field
    # of every hook event with no documented absence condition. So this branch now DENIES, and the
    # cost is always escapable — writing under your own announced name is never blocked, because
    # that file does not exist yet.
    ("09-missing-transcript-DENY", dict(target_rel=CK, transcript=False), "deny"),
    # ...and the control that keeps that from becoming "deny whenever anything is missing": the
    # allow-on-uncertainty rule still governs everything BEFORE ownership is even asked about.
    ("10-not-a-checkpoint-path-ALLOW", dict(target_rel="docs/checkpoint-notes.md"), "allow"),
    ("11-near-miss-suffix-ALLOW", dict(target_rel=".goalspec/checkpoint.md.bak"), "allow"),
    # A nested .goalspec/ is a sub-package's own run, not this one -- same anchor an adversary
    # round forced onto nudge-decompose.sh.
    ("12-nested-goalspec-dir-ALLOW", dict(target_rel="sub/.goalspec/checkpoint-aaaa.md"), "allow"),
]

# Payload-shaped cases that do not need a fixture at all.
RAW_CASES = [
    ("13-other-tool-ALLOW", {"tool_name": "Bash", "tool_input": {"command": "ls"}}, "allow"),
    ("14-no-file-path-ALLOW", {"tool_name": "Write", "tool_input": {}}, "allow"),
    ("15-malformed-json-ALLOW", "RAW:not json {{{", "allow"),
]


def main():
    failures = []
    deny_reason = None
    for name, kw, expected in CASES:
        payload = build(name.split("-")[0], **kw)
        got, reason = run(payload)
        if expected == "deny" and deny_reason is None:
            deny_reason = reason
        ok = got == expected
        if not ok:
            failures.append(name)
        print("{:<44} {:<7} {}".format(name, got, "" if ok else "  <-- FAIL, expected " + expected))

    for name, payload, expected in RAW_CASES:
        if isinstance(payload, str):
            out = subprocess.run(["bash", HOOK], input=payload[4:],
                                 capture_output=True, text=True).stdout.strip()
            got = "deny" if "deny" in out else "allow"
        else:
            got, _ = run(payload)
        ok = got == expected
        if not ok:
            failures.append(name)
        print("{:<44} {:<7} {}".format(name, got, "" if ok else "  <-- FAIL, expected " + expected))

    # --- the deny message is the whole remedy: a denial that does not say what to do instead is a
    # blocked agent with no next move. Every other case collapses the output to a decision, so
    # without this the hook could deny with an empty string and stay green. ---
    print()
    checks = [
        ("names-the-file-it-refused", ".goalspec/checkpoint" in (deny_reason or "")),
        ("names-the-path-to-use-instead", "051d39c4-8a4e-4cf6-bb8e-a32cfd2ce134" in (deny_reason or "")),
        ("says-read-then-write-your-own", "read that file" in (deny_reason or "")),
        ("points-at-the-governing-rule", "durable-artifact.md" in (deny_reason or "")),
    ]
    for label, ok in checks:
        print("{:<44} {}".format("reason:" + label, "ok" if ok else "FAIL"))
        if not ok:
            failures.append("reason:" + label)

    total = len(CASES) + len(RAW_CASES) + len(checks)
    print()
    if failures:
        print("{} check(s) FAILED: {}".format(len(failures), ", ".join(failures)))
        return 1
    print("all {} check(s) OK".format(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())

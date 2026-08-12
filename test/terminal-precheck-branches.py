#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/precheck-terminal-push.sh (+ hooks/lib/terminal_actions.py).

    python3 test/terminal-precheck-branches.py

Unlike test/gate-branches.py (pure transcript, no filesystem), this hook reads LIVE git state — it
diffs the actual prospective push before deciding. So each case gets its own synthetic git repo: a
working tree plus a bare "origin" created OUTSIDE the working tree (nesting the bare repo inside the
working tree was tried first and broke every case — `git add -A` sucks in the bare repo's own object
files as untracked content, which is a fixture bug, not a hook bug, but an easy one to reintroduce).

Each case declares a repo recipe (commits already pushed to origin, commits made locally afterward —
i.e. what a prospective `git push` would carry) and a transcript recipe (assistant turns, which may
carry a Bash tool_use in addition to/instead of text). The harness builds both, then invokes the hook
with a crafted PreToolUse payload and reads back its `permissionDecision`.

Columns: case | decision (`deny` / `allow` / `unparseable`) | detail (first ~60 chars of the deny
reason, for eyeballing WHICH branch fired, not just that one did).
"""
import json, os, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "precheck-terminal-push.sh")
PLUGIN_ROOT = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="terminal-precheck-branches-")

SPEC_TEXT = "## Goal-spec\nObjective: whatever.\n"
HOLD_TEXT = ("[ADVERSARY-MODEL: Claude Opus 5 / claude-opus-5]\n"
             "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]")
BREAK_TEXT = "[ADVERSARY-VERDICT: break ungrounded=1 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
WAIVER_TEXT = "[GOAL-CLOSE-WAIVED reason=adversary sandbox unreachable, verified separately by hand]"


def sh(args, cwd):
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert out.returncode == 0, "fixture setup failed: %s\n%s" % (args, out.stderr)
    return out.stdout


def make_repo(name, pushed_files, local_files):
    """pushed_files / local_files: dict of relpath -> content. `pushed_files` is committed and
    pushed to origin first; `local_files` is committed locally AFTERWARD, so it is exactly what a
    prospective `git push` would carry. Returns the working-tree path."""
    work = os.path.join(TMP, name, "work")
    bare = os.path.join(TMP, name, "bare.git")
    os.makedirs(work)
    sh(["git", "init", "-q", "-b", "main", "."], work)
    sh(["git", "config", "user.email", "t@t.com"], work)
    sh(["git", "config", "user.name", "t"], work)
    sh(["git", "init", "-q", "--bare", bare], TMP)
    sh(["git", "remote", "add", "origin", bare], work)
    for rel, content in (pushed_files or {"README.md": "init"}).items():
        p = os.path.join(work, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(content)
    sh(["git", "add", "-A"], work)
    sh(["git", "commit", "-qm", "pushed baseline"], work)
    sh(["git", "push", "-q", "-u", "origin", "main"], work)
    if local_files:
        for rel, content in local_files.items():
            p = os.path.join(work, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as fh:
                fh.write(content)
        sh(["git", "add", "-A"], work)
        sh(["git", "commit", "-qm", "local, not yet pushed"], work)
    return work


def make_feature_branch(work):
    sh(["git", "checkout", "-qb", "feature/x"], work)
    return work


def transcript(events, name):
    """events: list of dicts, each with any of "text" / "bash" / "write" (a tuple of
    (file_path, content)) — a turn can carry more than one, in that order."""
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            content = []
            if "bash" in ev:
                content.append({"type": "tool_use", "name": "Bash", "input": {"command": ev["bash"]}})
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "name": "Write", "input": {"file_path": fp, "content": body}})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run_hook(cwd, command, transcript_path=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    if transcript_path:
        payload["transcript_path"] = transcript_path
    out = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                         capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT})
    raw = out.stdout.strip()
    if not raw:
        return "allow", ""
    try:
        d = json.loads(raw)
    except Exception:
        return "unparseable", raw[:80]
    hso = d.get("hookSpecificOutput") or {}
    if hso.get("permissionDecision") == "deny":
        return "deny", (hso.get("permissionDecisionReason") or "")[:70]
    if d.get("systemMessage"):
        return "allow-with-message", d["systemMessage"][:70]
    return "allow", ""


CASES = []


def case(name, decision_fn):
    CASES.append((name, decision_fn))


# --- precondition: no goal-spec in session -> allow regardless of content -------------------------
case("01-no-goalspec-no-transcript", lambda: run_hook(
    make_repo("01", None, {"src/app.js": "code"}), "git push origin main"))

case("02-no-goalspec-with-transcript", lambda: run_hook(
    make_repo("02", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"text": "just doing routine work, no spec here"}], "02")))

# --- core policy: goal-spec present, protected-branch push -----------------------------------------
case("03-goalspec-no-verdict-code-push-DENY", lambda: run_hook(
    make_repo("03", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}], "03")))

case("04-goalspec-break-verdict-code-push-DENY", lambda: run_hook(
    make_repo("04", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}, {"text": BREAK_TEXT}], "04")))

case("05-goalspec-hold-code-push-ALLOW", lambda: run_hook(
    make_repo("05", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}, {"text": HOLD_TEXT}], "05")))

case("06-goalspec-waiver-code-push-ALLOW", lambda: run_hook(
    make_repo("06", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}, {"text": WAIVER_TEXT}], "06")))

# --- content exemption ------------------------------------------------------------------------------
case("07-goalspec-no-verdict-memory-only-push-ALLOW", lambda: run_hook(
    make_repo("07", None, {"memory/sessions/x.md": "session notes"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}], "07")))

case("08-goalspec-no-verdict-docs-only-push-ALLOW", lambda: run_hook(
    make_repo("08", None, {"docs/notes.md": "docs update"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}], "08")))

case("09-goalspec-no-verdict-root-md-push-ALLOW", lambda: run_hook(
    make_repo("09", None, {"CHANGELOG.md": "0.32.0 - stuff"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}], "09")))

case("10-goalspec-no-verdict-mixed-diff-DENY", lambda: run_hook(
    make_repo("10", None, {"memory/x.md": "notes", "src/app.js": "code"}), "git push origin main",
    transcript([{"text": SPEC_TEXT}], "10")))

# --- branch scoping: feature branch is out of scope, force-push is always terminal -----------------
case("11-goalspec-no-verdict-feature-branch-push-ALLOW", lambda: run_hook(
    make_feature_branch(make_repo("11", None, {"src/app.js": "code"})), "git push origin feature/x",
    transcript([{"text": SPEC_TEXT}], "11")))

case("12-goalspec-no-verdict-feature-branch-force-push-DENY", lambda: run_hook(
    make_feature_branch(make_repo("12", None, {"src/app.js": "code"})),
    "git push --force origin feature/x", transcript([{"text": SPEC_TEXT}], "12")))

# --- merge classification (gh not authenticated against a synthetic bare remote -> diff
# undeterminable -> NOT exempt by design, regardless of content) ------------------------------------
case("13-goalspec-no-verdict-gh-merge-DENY", lambda: run_hook(
    make_repo("13", None, None), "gh pr merge", transcript([{"text": SPEC_TEXT}], "13")))

# --- deploy / destructive: never content-exempt, branch-agnostic -----------------------------------
case("14-goalspec-no-verdict-wrangler-deploy-DENY", lambda: run_hook(
    make_repo("14", None, None), "wrangler deploy", transcript([{"text": SPEC_TEXT}], "14")))

case("15-goalspec-hold-wrangler-deploy-ALLOW", lambda: run_hook(
    make_repo("15", None, None), "wrangler deploy",
    transcript([{"text": SPEC_TEXT}, {"text": HOLD_TEXT}], "15")))

case("16-goalspec-no-verdict-rm-rf-DENY", lambda: run_hook(
    make_repo("16", None, None), "rm -rf build/", transcript([{"text": SPEC_TEXT}], "16")))

# --- not our tool / not a terminal command --------------------------------------------------------
case("17-not-bash-tool-ALLOW", lambda: run_hook_raw(
    {"tool_name": "Read", "tool_input": {"file_path": "x"}, "cwd": make_repo("17", None, None)}))

case("18-unrelated-bash-command-ALLOW", lambda: run_hook(
    make_repo("18", None, {"src/app.js": "code"}), "ls -la",
    transcript([{"text": SPEC_TEXT}], "18")))

# --- fail-open on malformed input -------------------------------------------------------------------
case("19-malformed-json-ALLOW", lambda: run_hook_raw_text("not json {{{"))

# --- goal-spec written to .goalspec/checkpoint.md (not posted as chat text) -------------------------
# Regression cases for a real break: a goal-adversary round run against THIS diff's own real
# session transcript found the text-only scan blind to a spec written via Write to
# .goalspec/checkpoint.md — exactly SKILL.md step 5's own checkpoint pattern for long tasks — so
# has_goal_spec() returned False and the hook silently ALLOWED the real prospective push it exists
# to gate. Fixed by narrowly tagging Write/Edit content whose file_path ends in
# .goalspec/checkpoint.md as a goal-spec signal (hooks/lib/terminal_actions.py, kind="goal_spec_file").
case("20-goalspec-only-in-checkpoint-write-no-verdict-DENY", lambda: run_hook(
    make_repo("20", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"write": (".goalspec/checkpoint.md", SPEC_TEXT)}], "20")))

case("21-goalspec-only-in-checkpoint-write-with-hold-ALLOW", lambda: run_hook(
    make_repo("21", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"write": (".goalspec/checkpoint.md", SPEC_TEXT)}, {"text": HOLD_TEXT}], "21")))

# The first attempt at the fix above captured ANY Write/Edit content as a text-equivalent signal,
# not just checkpoint.md — and broke immediately: editing a file that merely CONTAINS example
# marker text (this SKILL's own docs are full of literal `[GOAL-CLOSE-WAIVED reason=...]` samples)
# was read as a genuine waiver. This case pins the fix stays narrow: a Write to an unrelated file
# containing example waiver/verdict text must NOT be treated as a real declaration.
case("22-unrelated-write-with-example-marker-text-DENY", lambda: run_hook(
    make_repo("22", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"text": SPEC_TEXT},
               {"write": ("docs/some-doc.md",
                          "Example: declare " + WAIVER_TEXT + " to override.")}], "22")))

# The checkpoint is per-session since the concurrency fix (two concurrent sessions in one project
# used to clobber the single fixed path). Case 23 is case 20 at the new name: if the matcher had
# stayed pinned to the old exact filename, a session writing its spec to the per-session name would
# reproduce the exact break cases 20/21 exist for — this hook blind to the spec, silently ALLOWING
# the push it exists to gate. Case 24 is the narrowness control that must survive the widening: a
# near-miss path carrying a real `## Goal-spec` is not the checkpoint, so no spec is on record and
# the hook has nothing to gate (ALLOW) — and a matcher loose enough to swallow it would flip this
# to DENY.
case("23-goalspec-only-in-session-scoped-checkpoint-write-DENY", lambda: run_hook(
    make_repo("23", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"write": (".goalspec/checkpoint-a1b2c3.md", SPEC_TEXT)}], "23")))

# Windows separator — same inherited defect, same fix, same synthetic-only evidence as
# gate-branches' checkpoint-06. A backslash path must still be recognized as the checkpoint, or
# the hook is blind to the spec on that platform and silently allows the push.
case("25-goalspec-in-windows-separator-checkpoint-write-DENY", lambda: run_hook(
    make_repo("25", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"write": ("C:\\proj\\.goalspec\\checkpoint-a1b2c3.md", SPEC_TEXT)}], "25")))

case("24-goalspec-in-near-miss-checkpoint-path-ALLOW", lambda: run_hook(
    make_repo("24", None, {"src/app.js": "code"}), "git push origin main",
    transcript([{"write": ("docs/checkpoint-notes.md", SPEC_TEXT)},
               {"write": (".goalspec/checkpoint.md.bak", SPEC_TEXT)}], "24")))


def run_hook_raw(payload):
    out = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                         capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT})
    raw = out.stdout.strip()
    if not raw:
        return "allow", ""
    try:
        d = json.loads(raw)
    except Exception:
        return "unparseable", raw[:80]
    hso = d.get("hookSpecificOutput") or {}
    if hso.get("permissionDecision") == "deny":
        return "deny", (hso.get("permissionDecisionReason") or "")[:70]
    return "allow", ""


def run_hook_raw_text(text):
    out = subprocess.run(["bash", HOOK], input=text, capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT})
    raw = out.stdout.strip()
    return ("allow", "") if not raw else ("unparseable", raw[:80])


# EXPECT: case-name -> required decision. Every case name ends in what it must produce, so this is
# derived mechanically rather than hand-duplicated.
def expected(name):
    return "deny" if name.endswith("-DENY") else "allow"


def main():
    failures = []
    rows = []
    for name, fn in CASES:
        try:
            decision, detail = fn()
        except AssertionError as e:
            decision, detail = "FIXTURE-ERROR", str(e)[:70]
        rows.append((name, decision, detail))
        want = expected(name)
        got_ok = decision == want or (want == "allow" and decision == "allow-with-message")
        if not got_ok:
            failures.append("%s: want %s, got %s (%s)" % (name, want, decision, detail))

    for name, decision, detail in rows:
        print("%-52s %-20s %s" % (name, decision, detail))

    if failures:
        print("\nFAILURES: %d\n  %s" % (len(failures), "\n  ".join(failures)))
        return 1
    print("\nOK — %d cases, all decisions match their name's expectation" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

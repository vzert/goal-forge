#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/precheck-spec-before-work.sh (0.49.0).

    python3 test/spec-brake-branches.py              # the cases
    python3 test/spec-brake-branches.py --selftest   # break the component, require a case to notice

The hook denies Bash, Write, Edit, MultiEdit and NotebookEdit while this session has entered the
goalspec LOOP and posted no `## Goal-spec` as visible assistant text. It allows Read-class tools,
writes under .goalspec/, any call made inside a subagent (agent_id in the payload), sessions that
only ran the interview or the standalone adversary, sessions with no goalspec at all, and anything
when GOAL_SPEC_BRAKE=0. Hermetic: synthetic transcripts in a temp dir, no git.

There is no predecessor to compare against (the hook is new in 0.49.0), so "fails against the old
version" would be vacuous. `--selftest` copies the plugin to a temp dir, applies one mutation at a
time to the component itself, and requires at least one case to fail under each.
"""
import json, os, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
TMP = tempfile.mkdtemp(prefix="spec-brake-branches-")
PROJ = os.path.join(TMP, "proj")  # the session's working directory (not a git repo)
os.makedirs(os.path.join(PROJ, "sub"), exist_ok=True)
REPO2 = os.path.join(TMP, "repo2")  # a git repo: the agent works in a subdir, checkpoint at the top
os.makedirs(os.path.join(REPO2, "sub"), exist_ok=True)
subprocess.run(["git", "init", "-q", REPO2], check=True)

SPEC = ("## Goal-spec\nAsked (your words): whatever.\n1. Real objective: make the report exist.\n"
        "2. Measurable success: the file is committed and every figure re-derives.\n")
BARE = "## Goal-spec\nAsked (your words): x\n"


def transcript(events, name):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            if "typed" in ev:
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "text", "text": ev["typed"]}]}}) + "\n")
                continue
            if "result" in ev:  # the tool_result of an earlier call, by tool_use id
                tid, is_error = ev["result"]
                fh.write(json.dumps({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
                     "content": "Error: denied by hook" if is_error else "File created"}]}}) + "\n")
                continue
            content = []
            if "skill" in ev:
                content.append({"type": "tool_use", "name": "Skill", "input": {"skill": ev["skill"]}})
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "name": "Write", "id": ev.get("id", "w0"),
                                "input": {"file_path": fp, "content": body}})
            if "thinking" in ev:
                content.append({"type": "thinking", "thinking": ev["thinking"]})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run(plugin, payload_text, env_extra=None):
    out = subprocess.run(["bash", os.path.join(plugin, "hooks", "precheck-spec-before-work.sh")],
                         input=payload_text, capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PLUGIN_ROOT": plugin, **(env_extra or {})})
    raw = out.stdout.strip()
    if not raw:
        return "allow"
    try:
        d = json.loads(raw)
    except Exception:
        return "unparseable"
    hso = d.get("hookSpecificOutput") or {}
    reason = hso.get("permissionDecisionReason") or ""
    # The three claims the reason exists to make: post it visibly, in a LATER message, and
    # thinking does not count. A deny that drops any of them strands the agent in the observed loop.
    if (hso.get("hookEventName") == "PreToolUse" and hso.get("permissionDecision") == "deny"
            and "## Goal-spec" in reason and "LATER message" in reason
            and "only in your thinking does not count" in reason and "Evidence:" in reason):
        # Which evidence: the agent's own last visible text quoted back, or "no visible text".
        if "QUOTE-ME-BACK" in reason and "2 visible text block(s)" in reason:
            return "deny-quotes"
        if "1 visible text block(s)" in reason and "Asked (your words): x" in reason:
            return "deny-quotes-bare"
        if "no visible text from you at all" in reason:
            if ".goalspec/checkpoint-SID-42.md" in reason:
                return "deny-path"
            if "create .goalspec/checkpoint.md " in reason:
                return "deny-plainpath"
            return "deny-none"
        return "deny"
    return "other-output"


def pre(events, name, tool="Bash", tool_input=None, **extra):
    if tool_input is None:
        tool_input = {"command": "ls"} if tool == "Bash" else {"file_path": "src/app.py"}
    extra.setdefault("session_id", "sess-1")  # real payloads carry one; case 27 removes it
    extra.setdefault("cwd", PROJ)
    extra = {k: v for k, v in extra.items() if v is not None}
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                       "transcript_path": transcript(events, name), **extra})


LOAD = {"skill": "goalspec:goalspec"}
CASES = [
    ("01-loop-no-spec-bash-denied", lambda: pre([LOAD], "01"), "deny-none"),
    ("02-loop-no-spec-write-denied", lambda: pre([LOAD], "02", tool="Write"), "deny-none"),
    ("03-loop-no-spec-edit-denied", lambda: pre([LOAD], "03", tool="Edit"), "deny-none"),
    ("04-loop-no-spec-multiedit-denied", lambda: pre([LOAD], "04", tool="MultiEdit"), "deny-none"),
    ("05-loop-no-spec-notebook-denied",
     lambda: pre([LOAD], "05", tool="NotebookEdit", tool_input={"notebook_path": "a.ipynb"}), "deny-none"),
    ("06-bare-skill-name-arms", lambda: pre([{"skill": "goalspec"}], "06"), "deny-none"),
    ("07-typed-command-arms",
     lambda: pre([{"typed": "<command-name>/goalspec</command-name>"}], "07"), "deny-none"),
    # The observed failure: a spec that lives only in thinking does not release the brake.
    ("08-spec-only-in-thinking-denied", lambda: pre([LOAD, {"thinking": SPEC}], "08"), "deny-none"),
    # v3: a spec written with Write to the checkpoint releases it (show-checkpoint-spec.sh shows it).
    ("09-spec-in-checkpoint-allows",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-sess-1.md", SPEC)}], "09"), "allow"),
    ("09d-plain-checkpoint-allows",
     lambda: pre([LOAD, {"write": (os.path.join(PROJ, ".goalspec", "checkpoint.md"), SPEC)}], "09d"),
     "allow"),
    # Release round 3 (codex): a checkpoint outside the working directory never releases it.
    ("09g-checkpoint-outside-cwd-denies",
     lambda: pre([LOAD, {"write": ("../../outside/.goalspec/checkpoint-sess-1.md", SPEC)}], "09g"),
     "deny-none"),
    ("09i-git-toplevel-checkpoint-from-subdir-allows",
     lambda: pre([LOAD, {"write": (os.path.join(REPO2, ".goalspec", "checkpoint-sess-1.md"), SPEC)}],
                 "09i", cwd=os.path.join(REPO2, "sub")), "allow"),
    ("09h-absolute-foreign-dir-denies",
     lambda: pre([LOAD, {"write": (os.path.join(TMP, ".goalspec", "checkpoint-sess-1.md"), SPEC)}], "09h"),
     "deny-none"),
    # Release round (codex): another session's checkpoint never releases it, nor a bare heading.
    ("09e-foreign-checkpoint-denies",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-other-session.md", SPEC)}], "09e"), "deny-none"),
    # 0.51.0 (p-5b005aba6e): a checkpoint Write whose result is an error wrote nothing, so it
    # never releases the brake; a successful result, or another call's error, leaves it counted.
    ("09j-denied-checkpoint-write-denies",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-sess-1.md", SPEC), "id": "w1"},
                  {"result": ("w1", True)}], "09j"), "deny-none"),
    ("09k-successful-checkpoint-write-allows",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-sess-1.md", SPEC), "id": "w1"},
                  {"result": ("w1", False)}], "09k"), "allow"),
    ("09l-other-calls-error-still-allows",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-sess-1.md", SPEC), "id": "w1"},
                  {"result": ("b9", True)}], "09l"), "allow"),
    ("09f-bare-heading-checkpoint-denies",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-sess-1.md", BARE)}], "09f"), "deny-none"),
    ("10b-bare-heading-text-denies", lambda: pre([LOAD, {"text": BARE}], "10b"), "deny-quotes-bare"),
    ("09b-checkpoint-without-spec-still-denies",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-ab12.md", "# notes\n")}], "09b"), "deny-none"),
    ("09c-spec-in-other-file-still-denies",
     lambda: pre([LOAD, {"write": ("docs/plan.md", SPEC)}], "09c"), "deny-none"),
    ("10-spec-in-text-allows", lambda: pre([LOAD, {"text": SPEC}], "10"), "allow"),
    ("11-spec-before-reentry-allows", lambda: pre([{"text": SPEC}, LOAD], "11"), "allow"),
    ("12-checkpoint-write-allowed",
     lambda: pre([LOAD], "12", tool="Write",
                 tool_input={"file_path": "/repo/.goalspec/checkpoint-ab12.md"}), "allow"),
    ("13-relative-checkpoint-write-allowed",
     lambda: pre([LOAD], "13", tool="Edit", tool_input={"file_path": ".goalspec/checkpoint-ab12.md"}),
     "allow"),
    ("14-lookalike-path-denied",
     lambda: pre([LOAD], "14", tool="Write", tool_input={"file_path": "/repo/not.goalspec/x.md"}),
     "deny-none"),
    ("15-read-tool-allowed", lambda: pre([LOAD], "15", tool="Read",
                                         tool_input={"file_path": "src/app.py"}), "allow"),
    ("16-subagent-allowed", lambda: pre([LOAD], "16", agent_id="a1b2", agent_type="Explore"), "allow"),
    ("17-interview-only-allowed", lambda: pre([{"skill": "goalspec:interview"}], "17"), "allow"),
    ("18-adversary-only-allowed", lambda: pre([{"skill": "goalspec:adversary"}], "18"), "allow"),
    ("19-no-goalspec-allowed", lambda: pre([{"text": "hello"}], "19"), "allow"),
    ("20-other-event-allowed",
     lambda: json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                         "tool_input": {"command": "ls"}, "transcript_path": transcript([LOAD], "20")}),
     "allow"),
    ("21-malformed-stdin-allowed", lambda: "not json {{{", "allow"),
    ("22-no-transcript-allowed",
     lambda: json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                         "tool_input": {"command": "ls"}}), "allow"),
]
CASES += [
    ("26-reason-names-session-checkpoint", lambda: pre([LOAD], "26", session_id="SID-42"), "deny-path"),
    # Release round (codex): with no usable session_id the named path must still be one the
    # checkpoint detector accepts -- a "<session>" placeholder never released the brake.
    ("27-no-session-id-names-detectable-path", lambda: pre([LOAD], "27", session_id=None),
     "deny-plainpath"),
    ("27b-unsafe-session-id-names-detectable-path",
     lambda: pre([LOAD], "27b", session_id="../x y"), "deny-plainpath"),
    # 0.49.0 ronda 4: two agents insisted the spec was "already posted above". The deny quotes back
    # what they actually posted, so the claim can be checked against their own words.
    ("25-evidence-quotes-last-text",
     lambda: pre([LOAD, {"text": "first words"}, {"text": "the spec is above QUOTE-ME-BACK"}], "25"),
     "deny-quotes"),
]
ENV_CASES = [
    ("23-opt-out-env-allowed", lambda: pre([LOAD], "23"), {"GOAL_SPEC_BRAKE": "0"}, "allow"),
    ("24-other-env-value-still-denies", lambda: pre([LOAD], "24"), {"GOAL_SPEC_BRAKE": "1"}, "deny-none"),
]

def run_show(plugin, payload_text):
    out = subprocess.run(["bash", os.path.join(plugin, "hooks", "show-checkpoint-spec.sh")],
                         input=payload_text, capture_output=True, text=True,
                         env={**os.environ, "CLAUDE_PLUGIN_ROOT": plugin})
    raw = out.stdout.strip()
    if not raw:
        return "silent"
    try:
        msg = json.loads(raw).get("systemMessage") or ""
    except Exception:
        return "unparseable"
    if "## Goal-spec" in msg and "Asked (your words)" in msg:
        return "shown-cut" if "## Estado" not in msg and "STATE-LINE" not in msg else "shown-uncut"
    return "other-output"


CKPT = ".goalspec/checkpoint-ab12.md"
FULL = "# Checkpoint\n\n" + SPEC + "1. objective\n\n## Estado\nSTATE-LINE\n"


def post_write(events, name, tool="Write", path=CKPT, body=FULL, event="PostToolUse", **extra):
    ti = {"file_path": path, "content": body} if tool == "Write" else {"file_path": path, "new_string": body}
    return json.dumps({"hook_event_name": event, "tool_name": tool, "tool_input": ti,
                       "transcript_path": transcript(events + [{"write": (path, body)}], name), **extra})


SHOW_CASES = [
    ("s1-checkpoint-spec-shown-and-cut", lambda: post_write([LOAD], "s1"), "shown-cut"),
    ("s2-edit-new-string-shown", lambda: post_write([LOAD], "s2", tool="Edit"), "shown-cut"),
    ("s3-checkpoint-without-spec-silent", lambda: post_write([LOAD], "s3", body="# notes\n"), "silent"),
    ("s4-other-file-silent", lambda: post_write([LOAD], "s4", path="docs/plan.md"), "silent"),
    ("s5-visible-spec-already-silent", lambda: post_write([LOAD, {"text": SPEC}], "s5"), "silent"),
    ("s6-subagent-silent", lambda: post_write([LOAD], "s6", agent_id="a1"), "silent"),
    ("s7-pretooluse-silent", lambda: post_write([LOAD], "s7", event="PreToolUse"), "silent"),
    ("s8-malformed-silent", lambda: "{{{ nope", "silent"),
]

LIB = os.path.join("hooks", "lib", "terminal_actions.py")
SHOW = os.path.join("hooks", "show-checkpoint-spec.sh")
HOOK = os.path.join("hooks", "precheck-spec-before-work.sh")
# (description, file, old, new): each must make at least one case fail.
MUTATIONS = [
    ("show: path filter dropped", SHOW, "if not ta.CHECKPOINT_PATH_RE.search(fp):", "if False:"),
    ("show: visible-spec silence dropped", SHOW,
     'if ta.has_goal_spec("\\n".join(it["text"] for it in items if it["kind"] == "text")):', "if False:"),
    ("show: subagent exemption dropped", SHOW, 'if data.get("agent_id"):', "if False:"),
    ("show: event filter dropped", SHOW, 'data.get("hook_event_name") != "PostToolUse" or ', ""),
    ("show: excerpt not cut at the next section", LIB, "    if nxt:\n        body = body[:nxt.start() + 3]\n",
     "    if False:\n        body = body[:nxt.start() + 3]\n"),
    ("tool filter widened to every tool", HOOK,
     'if tool not in ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"):', "if False:"),
    ("NotebookEdit dropped from the filter", HOOK,
     '"MultiEdit", "NotebookEdit"):', '"MultiEdit"):'),
    ("subagent exemption dropped", HOOK, 'if data.get("agent_id"):', "if False:"),
    ("checkpoint exemption dropped", HOOK,
     'if path.startswith(".goalspec/") or "/.goalspec/" in path:', "if False:"),
    ("checkpoint exemption widened to a substring", HOOK,
     'if path.startswith(".goalspec/") or "/.goalspec/" in path:', 'if ".goalspec/" in path:'),
    ("event filter dropped", HOOK, 'if data.get("hook_event_name") != "PreToolUse":', "if False:"),
    ("opt-out dropped", HOOK, '[ "${GOAL_SPEC_BRAKE:-}" = "0" ] && exit 0', ":"),
    ("interview arms the brake", LIB,
     'it["kind"] == "goalspec_entry" and it.get("skill") == "goalspec" for it in items',
     'it["kind"] == "goalspec_entry" for it in items'),
    ("visible spec ignored", LIB,
     'return not spec_has_body("\\n".join(it["text"] for it in items if it["kind"] == "text"))',
     "return True"),
    ("evidence dropped from the deny", HOOK,
     "ta.SPEC_BRAKE_REASON.format(path=path) + ta.spec_brake_evidence(items)",
     "ta.SPEC_BRAKE_REASON.format(path=path)"),
    ("evidence counts nothing", LIB, "% (len(texts), last))", "% (0, last))"),
    ("reason loses the later-message clause", LIB, "call the tool again in a LATER message",
     "call the tool again"),
    ("reason loses the thinking clause", LIB,
     "reply. A spec you wrote or planned only in your thinking does not count, even if you believe ",
     "reply. Your plan counts, even if you believe "),
    ("checkpoint spec no longer releases", LIB,
     "           and spec_has_body(it[\"text\"]) for it in items):",
     "           and False for it in items):"),
    ("body requirement dropped", LIB,
     "        if len(re.sub(r\"\\s\", \"\", body)) >= SPEC_BRAKE_MIN_BODY:", "        if True:"),
    ("own-checkpoint restriction dropped", LIB,
     'it["kind"] == "goal_spec_file" and own.search(it.get("path") or "")', 'it["kind"] == "goal_spec_file"'),
    ("working-directory restriction dropped", LIB,
     '           and _in_own_root(it.get("path") or "", cwd, roots)\n', ""),
    ("denied checkpoint write still counts", LIB,
     'blk.get("type") == "tool_result" and blk.get("is_error") is True:',
     'blk.get("type") == "tool_result" and False:'),
    ("session id not validated", HOOK, 'if ta.SESSION_ID_RE.fullmatch(sid) else', 'if sid else'),
    ("fallback path back to a placeholder", HOOK, 'else ".goalspec/checkpoint.md"',
     'else ".goalspec/checkpoint-<session>.md"'),
    ("reason path not filled", HOOK, 'ta.SPEC_BRAKE_REASON.format(path=path)',
     'ta.SPEC_BRAKE_REASON.format(path=".goalspec/checkpoint-<session>.md")'),
]


def suite(plugin):
    rows = [(name, want, run(plugin, build())) for name, build, want in CASES]
    rows += [(name, want, run(plugin, build(), env)) for name, build, env, want in ENV_CASES]
    rows += [(name, want, run_show(plugin, build())) for name, build, want in SHOW_CASES]
    return rows


def main():
    if "--selftest" in sys.argv:
        failed = []
        for desc, rel, old, new in MUTATIONS:
            d = tempfile.mkdtemp(prefix="brake-mut-")
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
        print("%-45s %-14s %s" % (n, g, "" if w == g else "<-- FAILS (want %s)" % w))
    if bad:
        print("\nFAILURES: %d" % len(bad))
        return 1
    print("\nOK — %d cases, all as expected" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

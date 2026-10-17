#!/usr/bin/env python3
"""Branch suite for the ratify brake in plugins/goalspec/hooks/precheck-spec-before-work.sh (0.60.0).

    python3 test/ratify-brake-branches.py              # the cases
    python3 test/ratify-brake-branches.py --selftest   # break the component, require a case to notice

Once an interactive session (entrypoint cli or claude-vscode) that entered the goalspec loop has a
`## Goal-spec` with a body, the hook denies Bash, Write, Edit, MultiEdit and NotebookEdit until the
human was asked to ratify it: an answered AskUserQuestion (a result that is not an error) after the
first spec of the current cycle, or a typed user prompt after it (terminal_actions.ratify_brake_armed).
A cycle starts after a [COMPLETION-REVIEW: ...] in visible text, outside a code fence and outside
the spec's own text block. Not braked: headless (sdk-*)
or unknown entrypoints, a modal raised before the spec, writes under .goalspec/, subagent calls,
GOAL_RATIFY_BRAKE=0 or GOAL_SPEC_BRAKE=0. A spec re-emitted in the same cycle does not re-arm it.
Hermetic: synthetic transcripts in a temp dir, no git.

There is no predecessor to compare against (the brake is new in 0.60.0), so `--selftest` copies the
plugin to a temp dir, applies one mutation at a time to the component, and requires at least one
case to fail under each.
"""
import json, os, shutil, subprocess, sys, tempfile
import tmp_cleanup  # this run's own TMPDIR, removed at exit (p-1a5a4e9828)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")
HOOK = os.path.join("hooks", "precheck-spec-before-work.sh")
NOTICE_HOOK = os.path.join("hooks", "notice-ratify-release.sh")
LIB = os.path.join("hooks", "lib", "terminal_actions.py")
TMP = tempfile.mkdtemp(prefix="ratify-brake-branches-")
PROJ = os.path.join(TMP, "proj")
os.makedirs(PROJ, exist_ok=True)

SPEC = ("## Goal-spec\nAsked (your words): whatever.\n1. Real objective: make the report exist.\n"
        "2. Measurable success: the file is committed and every figure re-derives.\n")
CKPT = ".goalspec/checkpoint-sess-1.md"
CR = "[COMPLETION-REVIEW: adversary model=same backends=subagent-only]"


def transcript(events, name, entrypoint="cli"):
    p = os.path.join(TMP, name + ".jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for ev in events:
            base = {"entrypoint": entrypoint} if entrypoint else {}
            if "typed" in ev:
                fh.write(json.dumps({**base, "type": "user", "message": {"content": [
                    {"type": "text", "text": ev["typed"]}]}}) + "\n")
                continue
            if "deny" in ev:
                # How the harness records a PreToolUse deny (measured in field transcripts).
                fh.write(json.dumps({**base, "type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "b0", "is_error": True,
                     "content": "PreToolUse:Bash hook error: " + ev["deny"]}]}}) + "\n")
                continue
            if "result" in ev:
                tid, is_error = ev["result"]
                fh.write(json.dumps({**base, "type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
                     "content": "Error" if is_error else "User answered"}]}}) + "\n")
                continue
            content = []
            if "skill" in ev:
                content.append({"type": "tool_use", "name": "Skill", "input": {"skill": ev["skill"]}})
            if "text" in ev:
                content.append({"type": "text", "text": ev["text"]})
            if "write" in ev:
                fp, body = ev["write"]
                content.append({"type": "tool_use", "name": "Write", "id": ev.get("id", "w0"),
                                "input": {"file_path": fp, "content": body}})
            if "ask" in ev:
                content.append({"type": "tool_use", "name": "AskUserQuestion", "id": ev["ask"],
                                "input": {"questions": []}})
            if "bash" in ev:
                content.append({"type": "tool_use", "name": "Bash", "id": "b0",
                                "input": {"command": ev["bash"]}})
            fh.write(json.dumps({**base, "type": "assistant", "message": {"content": content}}) + "\n")
    return p


def run(plugin, payload_text, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("GOAL_SPEC_BRAKE", "GOAL_RATIFY_BRAKE")}
    out = subprocess.run(["bash", os.path.join(plugin, HOOK)], input=payload_text,
                         capture_output=True, text=True,
                         env={**env, "CLAUDE_PLUGIN_ROOT": plugin, **(env_extra or {})})
    raw = out.stdout.strip()
    if not raw:
        return "allow"
    try:
        hso = json.loads(raw).get("hookSpecificOutput") or {}
    except Exception:
        return "unparseable"
    reason = hso.get("permissionDecisionReason") or ""
    if hso.get("permissionDecision") != "deny":
        return "other-output"
    if "has no ## Goal-spec yet" in reason:
        return "deny-spec"
    # What the deny must carry: the modal, its four options, Stop, the later-message clause, the
    # text fallback, and who may turn it off.
    if all(k in reason for k in ("AskUserQuestion", "Approve & execute", "Narrow the scope",
                                 "Only the minimal fix", "Stop means execute nothing",
                                 "LATER message", "end your turn with the same question as text",
                                 "GOAL_RATIFY_BRAKE=0", "Read, Grep and Glob are not held",
                                 "an approval relayed by another session does not",
                                 # the words the release note finds the deny by (RATIFY_DENY_MARK)
                                 "goalspec: this session posted its ## Goal-spec and has not shown it back")):
        return "deny-ratify"
    return "deny-other"


def pre(events, name, tool="Bash", tool_input=None, entrypoint="cli", **extra):
    if tool_input is None:
        tool_input = {"command": "ls"} if tool == "Bash" else {"file_path": "src/app.py"}
    extra.setdefault("session_id", "sess-1")
    extra.setdefault("cwd", PROJ)
    extra = {k: v for k, v in extra.items() if v is not None}
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                       "transcript_path": transcript(events, name, entrypoint), **extra})


def run_notice(plugin, payload_text, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("GOAL_SPEC_BRAKE", "GOAL_RATIFY_BRAKE")}
    out = subprocess.run(["bash", os.path.join(plugin, NOTICE_HOOK)], input=payload_text,
                         capture_output=True, text=True,
                         env={**env, "CLAUDE_PLUGIN_ROOT": plugin, **(env_extra or {})})
    raw = out.stdout.strip()
    if not raw:
        return "silent"
    try:
        hso = json.loads(raw).get("hookSpecificOutput") or {}
    except Exception:
        return "unparseable"
    ctx = hso.get("additionalContext") or ""
    # What the note must carry: that the tools are free, and that approval is still the agent's call.
    if hso.get("hookEventName") == "UserPromptSubmit" and all(
            k in ctx for k in ("no longer held", "yours to judge", "keep waiting for it")):
        return "notice"
    return "other-output"


def prompt(events, name, text, entrypoint="cli", **extra):
    extra.setdefault("session_id", "sess-1")
    extra.setdefault("cwd", PROJ)
    return json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": text,
                       "transcript_path": transcript(events, name, entrypoint), **extra})


LOAD = {"skill": "goalspec:goalspec"}
TXT = {"text": SPEC}
WR = {"write": (CKPT, SPEC), "id": "w1"}
CASES = [
    # The observed failure: spec posted, then straight to work.
    ("01-text-spec-no-ask-bash-denied", lambda: pre([LOAD, TXT], "01"), "deny-ratify"),
    ("02-text-spec-no-ask-write-denied", lambda: pre([LOAD, TXT], "02", tool="Write"), "deny-ratify"),
    ("03-text-spec-no-ask-edit-denied", lambda: pre([LOAD, TXT], "03", tool="Edit"), "deny-ratify"),
    ("04-multiedit-denied", lambda: pre([LOAD, TXT], "04", tool="MultiEdit"), "deny-ratify"),
    ("05-notebook-denied",
     lambda: pre([LOAD, TXT], "05", tool="NotebookEdit", tool_input={"notebook_path": "a.ipynb"}),
     "deny-ratify"),
    ("06-checkpoint-spec-no-ask-denied", lambda: pre([LOAD, WR], "06"), "deny-ratify"),
    ("07-vscode-denied", lambda: pre([LOAD, TXT], "07", entrypoint="claude-vscode"), "deny-ratify"),
    # Released.
    ("10-ask-after-text-spec-allows", lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)}], "10"),
     "allow"),
    ("11-ask-after-checkpoint-spec-allows",
     lambda: pre([LOAD, WR, {"ask": "q1"}, {"result": ("q1", False)}], "11"), "allow"),
    # Release round 1 (external adversary): a modal with no answer yet is not a ratification.
    ("12-ask-no-result-yet-denied", lambda: pre([LOAD, TXT, {"ask": "q1"}], "12"), "deny-ratify"),
    ("13-typed-prompt-after-spec-allows", lambda: pre([LOAD, TXT, {"typed": "dale, adelante"}], "13"),
     "allow"),
    # Narrow: the spec re-emitted after the modal, and every later checkpoint update, ask nothing.
    ("14-respec-after-ask-allows",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)}, TXT,
                  {"write": (CKPT, SPEC), "id": "w2"}], "14"), "allow"),
    # Cycles (release round 1): a spec written after a completion-review is held again.
    ("15-new-cycle-after-close-denied",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)}, {"text": CR}, TXT], "15"),
     "deny-ratify"),
    ("16-new-cycle-asked-allows",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)}, {"text": CR}, TXT,
                  {"ask": "q2"}, {"result": ("q2", False)}], "16"), "allow"),
    ("17-closed-no-new-spec-allows",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)}, {"text": CR}], "17"), "allow"),
    ("18-new-cycle-respec-same-cycle-allows",
     lambda: pre([LOAD, TXT, {"text": CR}, TXT, {"typed": "si"}, TXT], "18"), "allow"),
    # Release round 2 (external adversary): the grammar quoted in prose is not a close.
    ("19-marker-quoted-in-spec-still-denied",
     lambda: pre([LOAD, {"text": SPEC + "\nClose with " + CR + " when done.\n"}], "19"), "deny-ratify"),
    ("19b-marker-own-line-in-spec-still-denied",
     lambda: pre([LOAD, {"text": SPEC + "\n" + CR + "\n"}], "19b"), "deny-ratify"),
    # Accepted direction (round 3): a marker quoted in prose after the modal starts a cycle, as
    # the Stop gate would read it; the cost is one more question, never a skipped one.
    ("19c-marker-inline-prose-asks-again",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)},
                  {"text": "Before closing I will write " + CR + " as the gate asks."}, TXT], "19c"),
     "deny-ratify"),
    ("19d-marker-in-code-fence-no-false-rearm",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)},
                  {"text": "The grammar:\n```\n" + CR + "\n```\n"}, TXT], "19d"), "allow"),
    ("19e-tilde-fence-no-false-rearm",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)},
                  {"text": "Grammar:\n~~~\n" + CR + "\n~~~\n"}, TXT], "19e"), "allow"),
    ("19f-unclosed-fence-no-false-rearm",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)},
                  {"text": "Grammar:\n```\n" + CR + "\n"}, TXT], "19f"), "allow"),
    # Round 3 (subagent): real closes as the project's sessions write them start a cycle.
    ("19g-bold-close-starts-cycle",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)},
                  {"text": "Declaro el cierre:\n\n**" + CR + "** -- listo."}, TXT], "19g"), "deny-ratify"),
    ("19h-backtick-close-starts-cycle",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)},
                  {"text": "CIERRE goalspec\n`" + CR + "`"}, TXT], "19h"), "deny-ratify"),
    ("19i-bullet-crlf-close-starts-cycle",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", False)},
                  {"text": "- " + CR + "\r\n"}, TXT], "19i"), "deny-ratify"),
    # Not released.
    ("20-ask-before-spec-does-not-count",
     lambda: pre([LOAD, {"ask": "q0"}, {"result": ("q0", False)}, TXT], "20"), "deny-ratify"),
    ("21-errored-ask-does-not-count",
     lambda: pre([LOAD, TXT, {"ask": "q1"}, {"result": ("q1", True)}], "21"), "deny-ratify"),
    ("22-harness-notification-is-not-a-prompt",
     lambda: pre([LOAD, TXT, {"typed": "<task-notification>done</task-notification>"}], "22"),
     "deny-ratify"),
    # Another session's checkpoint is not this session's first spec: the modal before the real
    # spec does not ratify it.
    ("23-foreign-checkpoint-spec-is-not-the-spec",
     lambda: pre([LOAD, {"write": (".goalspec/checkpoint-other.md", SPEC), "id": "w9"},
                  {"ask": "q0"}, {"result": ("q0", False)}, TXT], "23"), "deny-ratify"),
    # Out of scope of this brake.
    ("30-headless-sdk-cli-allows", lambda: pre([LOAD, TXT], "30", entrypoint="sdk-cli"), "allow"),
    ("31-headless-sdk-ts-allows", lambda: pre([LOAD, TXT], "31", entrypoint="sdk-ts"), "allow"),
    ("32-no-entrypoint-allows", lambda: pre([LOAD, TXT], "32", entrypoint=None), "allow"),
    ("33-no-loop-entry-allows", lambda: pre([TXT], "33"), "allow"),
    ("34-interview-only-allows", lambda: pre([{"skill": "goalspec:interview"}, TXT], "34"), "allow"),
    ("35-subagent-call-allows", lambda: pre([LOAD, TXT], "35", agent_id="a1"), "allow"),
    ("36-checkpoint-write-allows",
     lambda: pre([LOAD, TXT], "36", tool="Write", tool_input={"file_path": CKPT}), "allow"),
    ("37-read-tool-allows", lambda: pre([LOAD, TXT], "37", tool="Read"), "allow"),
    # The pre-spec brake still comes first.
    ("40-no-spec-is-the-spec-brake", lambda: pre([LOAD], "40"), "deny-spec"),
]
# 0.61.0 — the note that tells a held agent the brake let go (notice-ratify-release.sh).
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("ta_pre", os.path.join(PLUGIN, LIB))
_ta = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_ta)
DENY = {"deny": _ta.RATIFY_BRAKE_REASON}
SPEC_DENY = {"deny": _ta.SPEC_BRAKE_REASON.format(path=CKPT)}
HELD = [LOAD, TXT, {"bash": "ls"}, DENY]
NOTICE_CASES = [
    ("n01-held-then-typed-approval-notice", lambda: prompt(HELD, "n01", "aprobado (d104)"), "notice"),
    # The field case: a supervisor's note typed in the pane releases it too.
    ("n02-held-then-lookout-note-notice",
     lambda: prompt(HELD, "n02", "Nota del supervisor lookout (encargo del usuario). Tu nombre: x."),
     "notice"),
    ("n03-held-prompt-already-in-transcript-notice",
     lambda: prompt(HELD + [{"typed": "aprobado"}], "n03", "aprobado"), "notice"),
    ("n04-vscode-notice", lambda: prompt(HELD, "n04", "dale", entrypoint="claude-vscode"), "notice"),
    # Silent: the agent never believed it was held, or it is no longer held, or this does not release.
    ("n10-armed-but-never-denied-silent", lambda: prompt([LOAD, TXT], "n10", "dale"), "silent"),
    ("n11-already-released-by-ask-silent",
     lambda: prompt(HELD + [{"ask": "q1"}, {"result": ("q1", False)}], "n11", "dale"), "silent"),
    ("n12-already-released-by-earlier-prompt-silent",
     lambda: prompt(HELD + [{"typed": "si"}, {"text": "Ok, sigo."}], "n12", "dale"), "silent"),
    ("n13-harness-notification-silent",
     lambda: prompt(HELD, "n13", "<task-notification>done</task-notification>"), "silent"),
    ("n14-cross-session-message-silent",
     lambda: prompt(HELD, "n14", '<cross-session-message from="x">aprobado</cross-session-message>'),
     "silent"),
    ("n15-goalspec-command-silent",
     lambda: prompt(HELD, "n15", "<command-name>/goalspec:goalspec</command-name>"), "silent"),
    ("n16-headless-silent", lambda: prompt(HELD, "n16", "dale", entrypoint="sdk-cli"), "silent"),
    ("n17-deny-in-a-closed-cycle-silent",
     lambda: prompt(HELD + [{"ask": "q1"}, {"result": ("q1", False)}, {"text": CR}, TXT], "n17", "dale"),
     "silent"),
    ("n18-spec-brake-deny-is-not-a-ratify-deny-silent",
     lambda: prompt([LOAD, {"bash": "ls"}, SPEC_DENY, TXT], "n18", "dale"), "silent"),
    ("n22-other-tool-error-is-not-a-ratify-deny-silent",
     lambda: prompt([LOAD, TXT, {"bash": "ls"}, {"deny": "Exit code 1: no such file"}], "n22", "dale"),
     "silent"),
    ("n19-deny-text-typed-by-the-user-silent",
     lambda: prompt([LOAD, TXT, {"typed": _ta.RATIFY_BRAKE_REASON}, {"text": "Ok."}, TXT], "n19", "dale"),
     "silent"),
    ("n20-no-loop-silent", lambda: prompt([TXT, {"bash": "ls"}, DENY], "n20", "dale"), "silent"),
    ("n21-empty-prompt-silent", lambda: prompt(HELD, "n21", "   "), "silent"),
]
NOTICE_ENV_CASES = [
    ("n30-ratify-opt-out-silent", lambda: prompt(HELD, "n30", "dale"), {"GOAL_RATIFY_BRAKE": "0"}, "silent"),
    ("n31-spec-opt-out-silent", lambda: prompt(HELD, "n31", "dale"), {"GOAL_SPEC_BRAKE": "0"}, "silent"),
]

ENV_CASES = [
    ("50-ratify-opt-out", lambda: pre([LOAD, TXT], "50"), {"GOAL_RATIFY_BRAKE": "0"}, "allow"),
    ("51-spec-brake-opt-out-covers-both", lambda: pre([LOAD, TXT], "51"), {"GOAL_SPEC_BRAKE": "0"}, "allow"),
    ("52-ratify-opt-out-keeps-spec-brake", lambda: pre([LOAD], "52"), {"GOAL_RATIFY_BRAKE": "0"},
     "deny-spec"),
]

MUTATIONS = [
    ("ratify check never runs", HOOK,
     'if os.environ.get("GOAL_RATIFY_BRAKE") != "0" and ta.ratify_brake_armed(items, sid, cwd):',
     "if False:"),
    ("ratify opt-out dropped", HOOK, 'os.environ.get("GOAL_RATIFY_BRAKE") != "0" and ', ""),
    ("ask no longer releases", LIB, 'it["kind"] in ("ask", "user_prompt") for it in items[i0 + 1:]',
     'it["kind"] in ("user_prompt",) for it in items[i0 + 1:]'),
    ("typed prompt no longer releases", LIB,
     'it["kind"] in ("ask", "user_prompt") for it in items[i0 + 1:]',
     'it["kind"] in ("ask",) for it in items[i0 + 1:]'),
    ("ask before the spec counts", LIB, "for it in items[i0 + 1:])", "for it in items)"),
    ("keyed on the latest spec, not the first", LIB,
     "    for i, it in enumerate(items):\n        if i < start:",
     "    for i, it in reversed(list(enumerate(items))):\n        if i < start:"),
    ("entrypoint ignored", LIB, "    if ep not in RATIFY_ENTRYPOINTS:\n        return None\n", ""),
    ("vscode dropped", LIB, 'RATIFY_ENTRYPOINTS = ("cli", "claude-vscode")', 'RATIFY_ENTRYPOINTS = ("cli",)'),
    ("entrypoint never recorded", LIB, 'if isinstance(ep, str) and ep and "entrypoint" not in state:',
     "if False:"),
    ("errored ask still counts", LIB,
     '            elif isinstance(blk, dict) and blk.get("type") == "tool_result":',
     '            if isinstance(blk, dict) and blk.get("type") == "tool_result":'),
    ("ask item never recorded", LIB,
     'elif blk.get("type") == "tool_use" and blk.get("name") == "AskUserQuestion":',
     'elif False:'),
    ("loop entry not required", LIB,
     "    if not any(it[\"kind\"] == \"goalspec_entry\" and it.get(\"skill\") == \"goalspec\" for it in items):\n        return None\n    cr =",
     "    cr ="),
    ("foreign checkpoint counts as the spec", LIB,
     "            if own.search(p) and _in_own_root(p, cwd, roots):", "            if True:"),
    ("checkpoint spec ignored", LIB,
     '        if it["kind"] == "goal_spec_file" and spec_has_body(it["text"]):',
     '        if False:'),
    ("unanswered ask counts", LIB,
     '            and not (it["kind"] == "ask" and it.get("id") not in answered)\n', "\n"),
    ("answers never recorded", LIB,
     'state.setdefault("answered_tool_uses", set()).add(blk.get("tool_use_id"))', "pass"),
    ("completion-review does not start a cycle", LIB,
     "return _first_spec_index(items, session_id, cwd, 0 if cr is None else cr + 1)",
     "return _first_spec_index(items, session_id, cwd)"),
    ("cycle start ignored by the index", LIB, "        if i < start:\n            continue\n", ""),
    ("spec and fences not excluded", LIB, "    cr = _last_close_index(items)",
     "    cr = last_completion_review_index(items)"),
    ("close anchored to its own line", LIB, 'if re.search(CR_RE, FENCE_RE.sub("", it["text"]), re.I):',
     'if re.search(r"^\\[COMPLETION-REVIEW:[^\\]\\n]*\\]$", FENCE_RE.sub("", it["text"]), re.M):'),
    ("tilde fences not stripped", LIB, 'FENCE_RE = re.compile(r"^[ \\t]*(```|~~~)', 'FENCE_RE = re.compile(r"^[ \\t]*(```)'),
    ("unclosed fence not stripped", LIB, r'(^[ \t]*\1|\Z)', r'(^[ \t]*\1)'),
    ("spec block can be a close", LIB, '        if it["kind"] != "text" or has_goal_spec(it["text"]):',
     '        if it["kind"] != "text":'),
    ("code fences not stripped", LIB, 'if re.search(CR_RE, FENCE_RE.sub("", it["text"]), re.I):',
     'if re.search(CR_RE, it["text"], re.I):'),
    ("reason loses Stop", LIB, "Stop means execute nothing", "Stop is up to you"),
    ("reason loses the text fallback", LIB, "end your turn with the same question as text",
     "keep going"),
    # 0.61.0 — the release note.
    ("notice never printed", NOTICE_HOOK, "if not msg:\n    sys.exit(0)", "sys.exit(0)"),
    ("notice opt-out dropped", NOTICE_HOOK, '[ "${GOAL_RATIFY_BRAKE:-}" = "0" ] && exit 0', ""),
    ("notice ignores the spec-brake opt-out", NOTICE_HOOK, '[ "${GOAL_SPEC_BRAKE:-}" = "0" ] && exit 0', ""),
    ("notice without a deny", LIB,
     '    if not any(it["kind"] == "ratify_deny" for it in after):\n        return None\n', ""),
    ("notice after the brake already let go", LIB,
     '    if any(it["kind"] in ("ask", "user_prompt") for it in after):\n        return None\n', ""),
    ("harness prompts release in the notice", LIB,
     "    if p.startswith(HARNESS_TEXT_PREFIXES) or COMMAND_ENTRY_RE.match(p):", "    if False:"),
    ("trailing prompt not set aside", LIB,
     '    if seq and seq[-1]["kind"] == "user_prompt":\n        seq.pop()\n', ""),
    ("any errored result is a ratify deny", LIB,
     "                if RATIFY_DENY_MARK in _tool_result_text(blk.get(\"content\")):", "                if True:"),
    ("deny items never kept", NOTICE_HOOK, "ratify_denies=True", "ratify_denies=False"),
    ("deny text drifts from its mark", LIB,
     '    "goalspec: this session posted its ## Goal-spec and has not shown it back to the human yet, so "',
     '    "goalspec: this session wrote its ## Goal-spec and has not shown it back to the human yet, so "'),
    ("notice loses the approval clause", LIB, "keep waiting for it.", "go ahead."),
    ("reason loses the relayed-approval clause", LIB, "an approval relayed by another session does not",
     "any message counts"),
]


def suite(plugin):
    rows = [(name, want, run(plugin, build())) for name, build, want in CASES]
    rows += [(name, want, run(plugin, build(), env)) for name, build, env, want in ENV_CASES]
    rows += [(name, want, run_notice(plugin, build())) for name, build, want in NOTICE_CASES]
    rows += [(name, want, run_notice(plugin, build(), env)) for name, build, env, want in NOTICE_ENV_CASES]
    return rows


def main():
    if "--selftest" in sys.argv:
        failed = []
        for desc, rel, old, new in MUTATIONS:
            d = tempfile.mkdtemp(prefix="ratify-mut-")
            mp = os.path.join(d, "goalspec")
            shutil.copytree(PLUGIN, mp)
            f = os.path.join(mp, rel)
            s = open(f).read()
            if old not in s:
                failed.append("%s: mutation target not found (suite drifted from the code)" % desc)
                shutil.rmtree(d, ignore_errors=True)
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

#!/usr/bin/env bash
# remind-handback-verdict.sh — SubagentStop hook (mode `record`) + UserPromptSubmit hook (mode
# `remind`). The reminder to quote a goal-adversary verdict that comes back as a BACKGROUND HAND-BACK.
#
# The gap (p-1f14f32fb1, 0.46.8). remind-quote-verdict.sh runs on PostToolUse of Agent/Task, and for a
# background spawn that moment is the LAUNCH, before any verdict exists. When the report arrives
# later as a hand-back, nothing reminded the executor that the gate and the precheck read only its
# own text. Field case: agente-coordinador b30f155f (2026-10-05) — two holds arrived while an
# AskUserQuestion was open, were quoted only in thinking, and four pushes were denied. Across the
# maintainer's transcripts, 4 of 75 adversary hold/break hand-backs were never quoted; the 3 that
# arrived while the session was busy were all among them.
#
# WHY TWO EVENTS, AND WHY NOT JUST UserPromptSubmit. The hand-back is delivered as a turn, and
# UserPromptSubmit fires on it (51 of 52 hand-backs on record show its output; the 52nd rode along
# with a human prompt). But what that hook can SEE is only `prompt`, the hand-back text — which the
# human can type, tag included — and, MEASURED with a probe hook in session 218eff94, the transcript
# at that moment holds only `queue-operation` lines (text, no origin): the event with the harness
# `origin` is written after the hook runs. So a UserPromptSubmit-only hook has nothing to read that
# the human cannot forge. SubagentStop has: `agent_type`, `agent_id` and `agent_transcript_path`
# come from the harness. And it runs first — the harness must wait for it, since a SubagentStop hook
# can block and keep the subagent going (measured: finished 7 ms before UserPromptSubmit started,
# session idle; ~33 s before, session busy).
#
#   record (SubagentStop, matcher "(^|:)goal-adversary$", re-checked exactly here): read the
#     adversary's report from ITS OWN transcript — the `message` of its last SubagentHandback call
#     (how 291 of 381 background adversaries on record reported), else its last text block (the
#     other 79, harness 2.1.266..2.1.282) — and append its [ADVERSARY-MODEL]/[ADVERSARY-VERDICT]
#     lines to a per-session file. It PRINTS NOTHING: a SubagentStop hook's output is delivered to
#     the subagent that stopped, never to the executor (measured 0.44.1, see
#     watch-adversary-writes.sh). Printing here would hand the reminder to the adversary.
#   remind (UserPromptSubmit): if that file exists, read it, delete it, and add one agent-facing
#     context block with the exact lines to quote. It NEVER reads `prompt`. Whatever turn comes next
#     — the hand-back itself, or a human prompt it rode along with — carries the reminder.
#
# A verdict already quoted is skipped: a text block of the executor's own, written AFTER the record
# and containing the exact verdict line (timestamps compared, because an all-zero hold line repeats
# verbatim across rounds — equality alone would suppress a new round's reminder with an old quote).
# A foreground spawn also fires SubagentStop; remind-quote-verdict.sh already nudged it, and if the
# executor quoted it, this stays silent; if it did not, one more reminder is correct.
#
# Advisory only, never blocks. Fail-open everywhere: unparseable payload, no session id, unreadable
# transcript, no verdict in the report -> exit 0, silent.
#
# Registered by hooks/hooks.json. Usage: remind-handback-verdict.sh record|remind  (payload on stdin)

MODE="${1:-}"
[ "$MODE" = "record" ] || [ "$MODE" = "remind" ] || exit 0

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

printf '%s' "$INPUT" | MODE="$MODE" LIBDIR="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib" \
  SNAP_DIR="${TMPDIR:-/tmp}/goalspec-adversary-snap" "$PY" -c '
import json, os, re, sys, datetime

libdir = os.environ.get("LIBDIR", "")
if libdir and libdir not in sys.path:
    sys.path.insert(0, libdir)
try:
    import terminal_actions as ta
except Exception:
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

sid = data.get("session_id")
if not isinstance(sid, str) or not sid:
    sys.exit(0)
snap = os.environ["SNAP_DIR"]
path = os.path.join(snap, re.sub(r"[^A-Za-z0-9_.-]", "_", sid)[:120] + ".handback-verdicts")
MODEL_RE = r"\[ADVERSARY-MODEL:[^\n]*\]"


def report_text(transcript):
    """-> the adversary report: its last SubagentHandback message, else its last text block."""
    handback = text = None
    with open(transcript, encoding="utf-8") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            if ev.get("type") != "assistant":
                continue
            for blk in (ev.get("message") or {}).get("content") or []:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "tool_use" and blk.get("name") == "SubagentHandback":
                    msg = (blk.get("input") or {}).get("message")
                    if isinstance(msg, str):
                        handback = msg
                elif blk.get("type") == "text" and isinstance(blk.get("text"), str):
                    text = blk["text"]
    return handback if handback is not None else text


if os.environ["MODE"] == "record":
    if data.get("hook_event_name") not in (None, "SubagentStop"):
        sys.exit(0)
    if not ta.is_adversary_type(data.get("agent_type")):
        sys.exit(0)
    tp = data.get("agent_transcript_path")
    if not isinstance(tp, str) or not os.path.isfile(tp):
        sys.exit(0)
    report = report_text(tp) or ""
    verdicts = list(re.finditer(ta.VERDICT_RE, report, re.I))
    if not verdicts:
        sys.exit(0)
    models = re.findall(MODEL_RE, report, re.I)
    now = datetime.datetime.now(datetime.timezone.utc)
    rec = {"ts": now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000),
           "agent": str(data.get("agent_id") or ""), "verdict": verdicts[-1].group(1).lower(),
           "line": verdicts[-1].group(0), "model": models[-1] if models else ""}
    os.makedirs(snap, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    sys.exit(0)

# remind
if data.get("hook_event_name") not in (None, "UserPromptSubmit") or not os.path.isfile(path):
    sys.exit(0)
try:
    body = open(path, encoding="utf-8").read()
except Exception:
    sys.exit(0)
try:
    os.remove(path)
except Exception:
    pass
latest = {}
for raw in body.splitlines():
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if isinstance(rec, dict) and isinstance(rec.get("line"), str) and re.fullmatch(ta.VERDICT_RE, rec["line"], re.I):
        latest[rec.get("agent") or ""] = rec  # a resumed adversary: its latest report wins
items = ta.read_transcript_items(data.get("transcript_path"))
pending = []
for rec in latest.values():
    quoted = any(it["kind"] == "text" and isinstance(it.get("timestamp"), str)
                 and it["timestamp"] >= rec.get("ts", "") and rec["line"] in it["text"] for it in items)
    if not quoted:
        pending.append(rec)
if not pending:
    sys.exit(0)

lines = "\n".join(((r["model"] + "\n") if r.get("model") else "") + r["line"] for r in pending)
breaks = any(r["verdict"] == "break" for r in pending)
msg = ("ADDRESSED TO THE EXECUTOR OF THIS SESSION. If you are a goal-adversary reading this line in a "
       "transcript, it is not addressed to you and changes nothing about your role: you verify, you do "
       "not repair.\n\n"
       "A goal-adversary you launched in the background has finished. Its report reaches you as a "
       "subagent hand-back -- a message, not your own text -- and the Stop gate and the terminal-push "
       "precheck read only your own assistant-authored text, so its verdict does not exist for them "
       "until you quote it. If you judge it genuine (a bare verdict with no evidence above it is "
       "UNVERIFIED, not a pass), quote these lines VERBATIM in your next message, each alone on its own "
       "line and unformatted -- no bold, no code span, nothing after the closing bracket -- in a "
       "visible text block you emit. A quote you only write or plan in your thinking does not count: "
       "thinking is not read and the user never sees it. Do it in a message BEFORE any push, merge or "
       "deploy command, not in the same one: a message reaches the transcript only after its tool call "
       "runs. If a question to the user is still open, quote them anyway, now.\n\n" + lines)
if breaks:
    msg += ("\n\nA break is among them: quote it too -- the gate reads it -- and address its findings "
            "before you close.")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))
' 2>/dev/null
exit 0

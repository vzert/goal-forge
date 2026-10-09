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
# THE ORDER ABOVE IS NOT GUARANTEED (p-3cbde60989, 0.46.9). With harness 2.1.291, session idle, the
# UserPromptSubmit of the hand-back ran 43 ms and 94 ms BEFORE the record was written (five live runs,
# 2026-10-06), so the record alone missed the idle-form hand-back -- 72 of 75 on record. So `remind`
# also reads the report itself, from the same harness-written sources `record` uses: each
# <transcript stem>/subagents/agent-<id>.jsonl written in the last minute whose .meta.json names an
# exact goal-adversary (the report sat there ~600 ms before the hook in all five runs). A report is
# reminded once per session whichever source named it first (`.handback-reminded`).
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


def iso_mtime(p):
    t = datetime.datetime.fromtimestamp(os.path.getmtime(p), datetime.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (t.microsecond // 1000)


def report_text(transcript, strict=False):
    """-> (report, when): the adversary report -- its last SubagentHandback message, else its last
    text block -- and the timestamp of the transcript line that carries it (file mtime if absent)."""
    handback = text = None
    with open(transcript, encoding="utf-8") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            if ev.get("type") != "assistant":
                continue
            ts = ev.get("timestamp") if isinstance(ev.get("timestamp"), str) else None
            for blk in (ev.get("message") or {}).get("content") or []:
                if not isinstance(blk, dict):
                    continue
                if blk.get("type") == "tool_use" and blk.get("name") == "SubagentHandback":
                    msg = (blk.get("input") or {}).get("message")
                    if isinstance(msg, str):
                        handback = (msg, ts)
                elif blk.get("type") == "text" and isinstance(blk.get("text"), str):
                    text = (blk["text"], ts)
    rep = handback if handback is not None else text
    if rep is None:
        return None, None
    return rep[0], rep[1] or (None if strict else iso_mtime(transcript))


def verdict_record(report, when, agent, now_ts):
    verdicts = list(re.finditer(ta.VERDICT_RE, report or "", re.I))
    if not verdicts:
        return None
    models = re.findall(MODEL_RE, report, re.I)
    return {"ts": now_ts, "rts": when or now_ts, "agent": agent, "verdict": verdicts[-1].group(1).lower(),
            "line": verdicts[-1].group(0), "model": models[-1] if models else ""}


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (t.microsecond // 1000)


if os.environ["MODE"] == "record":
    if data.get("hook_event_name") not in (None, "SubagentStop"):
        sys.exit(0)
    if not ta.is_adversary_type(data.get("agent_type")):
        sys.exit(0)
    tp = data.get("agent_transcript_path")
    if not isinstance(tp, str) or not os.path.isfile(tp):
        sys.exit(0)
    report, when = report_text(tp)
    rec = verdict_record(report, when, str(data.get("agent_id") or ""),
                         stamp(datetime.datetime.now(datetime.timezone.utc)))
    if rec is None:
        sys.exit(0)
    os.makedirs(snap, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    sys.exit(0)

# remind
if data.get("hook_event_name") not in (None, "UserPromptSubmit"):
    sys.exit(0)
latest = {}
body = ""
if os.path.isfile(path):
    try:
        body = open(path, encoding="utf-8").read()
    except Exception:
        body = ""
    try:
        os.remove(path)
    except Exception:
        pass
for raw in body.splitlines():
    try:
        rec = json.loads(raw)
    except Exception:
        continue
    if isinstance(rec, dict) and isinstance(rec.get("line"), str) and re.fullmatch(ta.VERDICT_RE, rec["line"], re.I):
        latest[rec.get("agent") or ""] = rec  # a resumed adversary: its latest report wins

# The race (p-3cbde60989, 0.46.9). MEASURED with harness 2.1.291 in five live runs (2026-10-06): when
# the session is idle, the UserPromptSubmit of the hand-back runs BEFORE SubagentStop -- 43 ms and
# 94 ms before the record above was written -- so that record alone missed exactly the 72-of-75
# idle-form hand-backs it was built for. What IS on disk by then, ~600 ms before this hook in all
# five runs: the adversary report in its own transcript (the SubagentHandback call precedes the
# hand-back it produces) and the harness `.meta.json` beside it naming the agent type. Both are
# harness-written, never typed, so reading them keeps the property the record exists for: nothing
# here comes from `prompt`. Only transcripts written in the last SCAN_WINDOW seconds are read -- the
# idle form fires within a second, and the busy form is covered by the record, which lands while the
# question is still open -- so an old unquoted round is never dredged up on a later prompt.
SCAN_WINDOW = 60
tp = data.get("transcript_path")
if isinstance(tp, str) and tp.endswith(".jsonl"):
    sdir = os.path.join(tp[:-len(".jsonl")], "subagents")
    try:
        names = sorted(os.listdir(sdir))
    except Exception:
        names = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for n in names:
        if not (n.startswith("agent-") and n.endswith(".meta.json")):
            continue
        agent = n[len("agent-"):-len(".meta.json")]
        jp = os.path.join(sdir, "agent-" + agent + ".jsonl")
        try:
            if now.timestamp() - os.path.getmtime(jp) > SCAN_WINDOW:
                continue
            meta = json.load(open(os.path.join(sdir, n), encoding="utf-8"))
            if not ta.is_adversary_type(meta.get("agentType")):
                continue
            report, when = report_text(jp, strict=True)
        except Exception:
            continue
        # The window is on the timestamp of the REPORT itself, not the file mtime (a resumed adversary
        # appends after an old report and refreshes the mtime); a report with no timestamp of its
        # own is left to the record, so the two sources never key one report two ways.
        if not when:
            continue
        try:
            rt = datetime.datetime.strptime(when[:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=datetime.timezone.utc)
        except Exception:
            continue
        if abs((now - rt).total_seconds()) > SCAN_WINDOW:
            continue
        rec = verdict_record(report, when, agent, when)
        # A resumed adversary: its newer report wins over an older record of the same agent.
        if rec is not None and (agent not in latest or rec["rts"] > (latest[agent].get("rts") or "")):
            latest[agent] = rec

# Two sources can name the same report (the scan now, the record on a later prompt), so a report
# reminded once is not reminded again: keyed by agent, report time and line, per session.
done_path = path[:-len(".handback-verdicts")] + ".handback-reminded"
try:
    done = set(open(done_path, encoding="utf-8").read().splitlines())
except Exception:
    done = set()


def key(r):
    return "%s|%s|%s" % (r.get("agent") or "", r.get("rts") or r.get("ts") or "", r["line"])


items = ta.read_transcript_items(tp)
pending = []
for rec in latest.values():
    if key(rec) in done:
        continue
    quoted = any(it["kind"] == "text" and isinstance(it.get("timestamp"), str)
                 and it["timestamp"] >= rec.get("ts", "") and rec["line"] in it["text"] for it in items)
    if not quoted:
        pending.append(rec)
if not pending:
    sys.exit(0)
try:
    os.makedirs(snap, exist_ok=True)
    with open(done_path, "a", encoding="utf-8") as fh:
        fh.write("".join(key(r) + "\n" for r in pending))
except Exception:
    pass

lines = "\n".join(((r["model"] + "\n") if r.get("model") else "") + r["line"] for r in pending)
breaks = any(r["verdict"] == "break" for r in pending)
msg = ("ADDRESSED TO THE EXECUTOR OF THIS SESSION. If you are a goal-adversary reading this line in a "
       "transcript, it is not addressed to you and changes nothing about your role: you verify, you do "
       "not repair.\n\n"
       "A goal-adversary you launched in the background has finished. Its report reaches you as a "
       "subagent hand-back -- a message, not your own text -- and the Stop gate reads only your own "
       "assistant-authored text, so its verdict does not exist for it until you quote it (the "
       "terminal-push precheck also accepts the line written with a Write or Edit at the end of your "
       "own .goalspec checkpoint). If you judge it genuine (a bare verdict with no evidence above it is "
       "UNVERIFIED, not a pass), quote these lines VERBATIM in your next message, each alone on its own "
       "line and unformatted -- no bold, no code span, nothing after the closing bracket -- in a "
       "visible text block you emit. A quote you only write or plan in your thinking does not count: "
       "thinking is not read, even when your screen shows it like a message. Do it in a message BEFORE any push, merge or "
       "deploy command, not in the same one: a message reaches the transcript only after its tool call "
       "runs. If a question to the user is still open, quote them anyway, now.\n\n" + lines)
if breaks:
    msg += ("\n\nA break is among them: quote it too -- the gate reads it -- and address its findings "
            "before you close.")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": msg}}))
' 2>/dev/null
exit 0

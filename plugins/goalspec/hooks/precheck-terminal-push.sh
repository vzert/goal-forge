#!/usr/bin/env bash
# precheck-terminal-push.sh — PreToolUse hook (matcher: Bash).
#
# Closes the ordering gap the 0.31.0-era gate left open: SKILL.md already named push/merge/deploy
# terminal, and step 6 already routes terminal actions to the adversary — but step 6 runs AFTER
# step 5 (Execute), and "Execute" is exactly where the push/merge itself lives. Real transcript
# evidence (worker-cloudflare, 2026-08-01): the agent declared
# `[COMPLETION-REVIEW: none reason=sin acción terminal — PR abierto sin merge/deploy ...]`
# (correct, at that moment — the PR was open, not merged), then merged + deployed to production in
# the VERY NEXT turn, and only invoked the adversary after — 8 rounds, one of them a real security
# bug, all found against an already-live change. Nothing mechanical caught the gap between "no
# terminal action yet" and "terminal action just happened"; the agent's own discipline did, this
# time.
#
# What this hook does: intercepts a Bash command about to run. If it looks like a push to a
# protected branch, a merge, a deploy/publish, or a destructive op (hooks/lib/terminal_actions.py
# is the single source of truth for that list, shared with the Stop-gate staleness check below) AND
# this session is goalspec-tracked (see Precondition below) AND no operative `[ADVERSARY-VERDICT: hold ...]` is on
# record for it yet — DENY. The agent sees why and what to do (spawn the adversary on the real
# diff, get a hold, retry).
#
# Content exemption (shares the SAME allowlist as the Stop-gate check, not a copy — see
# hooks/lib/terminal_actions.py's module docstring for why a second copy would silently drift):
# if every file the push/merge would touch is under memory/, docs/, .goalspec/, or is a root-level
# *.md, this is a checkpoint-shaped commit, not the blast radius this gate exists for — allow
# silently. A MIXED diff (one non-exempt file alongside memory notes) is NOT exempt: that is
# exactly the smuggled-change pattern a gate should not wave through because half the diff looked
# safe. A diff that could not be determined (no upstream configured, git error) is also NOT
# exempt — "could not confirm this is safe" must fall through to the policy check, never to a
# silent allow.
#
# Precondition, deliberately narrow: only enforces inside a goalspec-tracked session — one that
# produced a `## Goal-spec` (the same signal gate-goal-close.sh uses) OR, since 0.45.0, one that
# ENTERED the method: a typed `/goalspec:interview` / `/goalspec:goalspec`, or the model invoking
# either skill (hooks/lib/terminal_actions.py, ENTRY_SKILLS). The widening is field evidence (VPS,
# 4 devs, 2026-09-08..29): 7 of 10 sessions that pushed or merged with no adversary had started
# with the interview and never written the spec, so every rail was off in exactly the session the
# developer believed was using goalspec. This is still NOT a universal git-push blocker — a quick
# untracked fix in a session that never touched goalspec is untouched, matching this plugin's own
# "not another rule in a wall for trivial work" design.
#
# Escape hatch, reusing existing vocabulary rather than inventing a parallel one: an explicit
# `[GOAL-CLOSE-WAIVED reason=<>=20 chars>]` — the same greppable, honest override SKILL.md already
# defines for closing over a residual break. Since 0.45.0 it is scoped: honored only when written
# after the last terminal command on record and after the last user prompt, so one waiver passes
# ONE terminal command, in the same turn
# (terminal_actions.waiver_covers_command). Before, a waiver anywhere in the transcript opened the
# rail for the rest of the session, and the deny text offered it as the retry recipe; a field
# session got one merge denied, wrote a waiver in the same minute, and ran three more merges over
# four hours with no adversary. The deny text now names the adversary as the way through and the
# waiver as a user-authorized exception for this one command.
#
# Fail-open, same contract as every other hook in this plugin: a missing/unparseable hook_input, a
# missing python interpreter, an import error on the shared module, or ANY internal exception
# produces empty stdout, and the bash wrapper below allows the tool call. The one thing that is
# NOT fail-open is "diff could not be determined" (see above) — that is a policy decision inside
# the python, not a hook-execution error, and it resolves toward blocking, not past it.
#
# Blocking mechanism: `hookSpecificOutput.permissionDecision: "deny"` — the current PreToolUse
# schema (superseding the older top-level `decision: "block"`, which is what gate-goal-close.sh's
# Stop hook still uses because Stop has different semantics). A deny here is a hard stop that runs
# ahead of the harness's own permission system — it is not gated behind GOAL_GATE_ENFORCE, per the
# explicit ratify-gate decision that chose hard-block-by-default for a PRE-execution check: warning
# after the fact is the posture that already failed twice; blocking before costs one extra
# adversary round, nothing more.
#
# Registered as a PreToolUse hook (matcher "Bash") by hooks/hooks.json.

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | LIBDIR="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib" "$PY" -c '
import json, os, sys

libdir = os.environ.get("LIBDIR", "")
if libdir and libdir not in sys.path:
    sys.path.insert(0, libdir)
try:
    import terminal_actions as ta
except Exception:
    sys.exit(0)  # fail-open: shared module unavailable -> allow, never block on our own defect


def allow(msg=None):
    if msg:
        print(json.dumps({"systemMessage": msg}))
    sys.exit(0)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }))
    sys.exit(0)


try:
    data = json.load(sys.stdin)
except Exception:
    allow()

if data.get("tool_name") != "Bash":
    allow()

command = (data.get("tool_input") or {}).get("command")
if not isinstance(command, str) or not command.strip():
    allow()

cwd = data.get("cwd") or os.getcwd()

# 0.55.0: the own-mktemp-dir exemption needs the names this session saw printed by Bash.
seen = ta.seen_temp_names(data.get("transcript_path")) if ta.DESTRUCTIVE_RE.search(command) else None
is_term, kind, diffable = ta.is_terminal(command, cwd, seen)
if not is_term:
    allow()

if diffable:
    paths = ta.diff_paths_for(kind, command, cwd)
    if ta.all_exempt(paths):
        allow()

transcript_path = data.get("transcript_path")
sig = ta.transcript_signals(transcript_path)

if not sig["goal_spec"] and not sig.get("goalspec_entered"):
    allow()  # precondition: only enforce inside a goalspec-tracked session (spec written, or the method entered)

if ta.waiver_covers_command(sig.get("items") or [], command, data.get("tool_use_id")):
    allow("goalspec terminal-push precheck: proceeding on a [GOAL-CLOSE-WAIVED ...] written "
          "in this turn after the last terminal command. It covers this one command only; the next "
          "terminal command needs an adversary hold or a new waiver.")

# 0.57.0 (p-83e65d6b6f): the same waiver, written with a Write/Edit into this session checkpoint
# (terminal_actions.file_waiver_line has the measurement and the rule). The human sees the line here.
sid = data.get("session_id")
fw = ta.file_waiver_line(sig.get("items") or [], command, data.get("tool_use_id"), sid, cwd)
if fw:
    allow(ta.FILE_WAIVER_ALLOW.format(line=fw, path=ta.checkpoint_name_for(sid)))

verdict = sig["verdict"]
items = sig.get("items") or []
# 0.51.0: a break that came back as an adversary report after the quoted hold is the most recent
# verdict, and it wins (before, the quoted hold passed over it).
if verdict == "hold" and not ta.relayed_break_after_text_hold(items):
    allow()

# 0.51.0: a hand-back hold the executor quoted with a Write/Edit to its own checkpoint counts as the
# visible-text quote does (terminal_actions.file_quoted_hold has the field case and the rule). The
# human sees the line here, since the quote went to a file.
sid = data.get("session_id")
fq = ta.file_quoted_hold(items, sid, cwd)
if fq:
    allow(ta.FILE_QUOTE_ALLOW.format(line=fq, path=ta.checkpoint_name_for(sid)))

KIND_LABEL = {
    "push": "a git push to a protected branch",
    "merge": "a merge",
    "deploy": "a deploy/publish",
    "destructive": "a destructive command",
}
kind_label = KIND_LABEL.get(kind, kind or "a terminal command")
verdict_note = "" if verdict is None else " (the most recent adversary verdict on record is break)"

if sig["goal_spec"]:
    next_step = ("Spawn goal-adversary on the actual diff/outcome, get a hold, then retry this "
                 "command.")
else:
    # Entered through /goalspec:interview or the goalspec skill, but no ## Goal-spec was ever
    # written: the adversary has nothing to verify against, so pointing only at it is a dead end.
    # p-d760440347 (0.55.2): 135589df (VPS, 2026-10-01) wrote the spec in the SAME message as the
    # merge and was told none was written. That is cause B of seen_note below, for the spec.
    next_step = ("This session entered goalspec (the goalspec skill or /goalspec:interview) but no "
                 "## Goal-spec was written in any earlier message: the interview hands off to the "
                 "goalspec loop, and the loop writes the spec. Write the ## Goal-spec, spawn "
                 "goal-adversary against it on the actual diff/outcome, get a hold, then retry this "
                 "command. If you wrote the ## Goal-spec as visible text in the SAME message as this "
                 "command, this hook cannot see it yet -- a message reaches the transcript only "
                 "after its tool call runs. And text you write in the middle of a turn can be stored "
                 "as a summary without the ## Goal-spec heading: write the spec with the Write tool "
                 "into " + ta.checkpoint_name_for(sid) + ", where a tool call is stored as written, "
                 "then run the adversary and this command in later messages. " + ta.BASH_WRITE_NOTE)

# The 2026-09-29 research (memory, p-87faebb038) measured two ways an executor believes it quoted a
# hold that this hook cannot see, and executors that hit either one blamed the transcript. Cause A:
# the quote lived only in thinking and was never emitted. Cause B: the quote was a visible text block
# in the SAME message as this command, and a message reaches the transcript only after its tool call
# runs. Cause C (p-840fef19be, 0.59.0; research 2026-10-14): the quote was visible text written in
# the middle of a turn, in a response that then called a tool, and the transcript stored a narration
# summary of it without the marker line -- in 6fd1cbfa this hook denied the same merge three times
# while the agent believed it had written the waiver. Until 0.58 this note told the executor that a
# quote in its following message was enough, which sends it straight into cause C. The way out
# that holds is a tool call (file_quoted_hold); text holds only when it ends the turn.
seen_note = (" If you believe you already quoted a hold, three causes are measured. (1) The quote is "
             "only in your thinking -- a quote you only write or plan in your thinking does not "
             "count: thinking is not read, even when your screen shows it like a message. (2) The quote is a visible "
             "text block in the SAME message as this command -- a message reaches the transcript "
             "only after its tool call runs, so this hook cannot see it yet. (3) The quote is "
             "visible text written in the middle of a turn: text you write in the middle of a turn "
             "can be stored as a summary without the marker line. The way that holds: use the Edit "
             "tool to append the exact [ADVERSARY-VERDICT: hold ...] line a goal-adversary subagent returned "
             "to " + ta.checkpoint_name_for(sid) + " (a Write replaces the whole file) and run the "
             "command in a later message -- a tool call is stored as written, and this hook accepts "
             "that line when it is the latest verdict a goal-adversary subagent returned; a verdict from the "
             "external backend counts only in your visible text. " + ta.BASH_WRITE_NOTE + " Visible text is stored as "
             "written almost always when it ends your turn, and not reliably in the middle of one.")

# p-473ba7b48b (2026-09-30): a heredoc or -c string that only MENTIONS a push/merge is denied too.
# The body is not stripped on purpose: the same text is data in one command and code in the next
# (python3 <<EOF with a string vs with os.system), and ssh/bash heredocs are a common deploy shape.
# test/terminal-precheck-branches.py cases 65-69 pin that. The way out names its own hole.
# A narrower exception (parse a Python body and pass it when it calls nothing) was considered and not
# built: it would cover the Python false positives only, not the first one observed (a heredoc fed
# to a bash script, whose stdin no parser can classify); the rule of terminal_actions.py is a canonical form,
# not a smarter matcher; and the file route costs one Write.
# p-64783f8057 (0.46.7): a hold that arrived as a subagent result and was never quoted. That is the
# cause, so it replaces both the spawn-the-adversary step and the list of possible causes, and gives
# the exact line to quote, and since 0.51.0 the checkpoint path to Write it into. The break note goes too: the break in your text is older than this hold.
relayed = sig.get("relayed_hold")
if relayed:
    verdict_note = ""
    next_step = ta.RELAYED_HOLD_NOTE.format(line=relayed, path=ta.checkpoint_name_for(sid))
    seen_note = ""

# 0.55.0 (p-ff03d9a39d): the one delete this hook lets through, named where the agent is denied,
# because it only passes when run in exactly that form (terminal_actions.is_temp_cleanup).
temp_note = ""
if kind == "destructive":
    temp_note = (" If this only deletes a temp directory this session made with mktemp, run it as "
                 "its own command, exactly `rm -rf <absolute path>` with the path written out (no "
                 "$VAR, no glob, nothing chained): a path inside a name.XXXXXX directory you own with "
                 "mode 0700 (what mktemp -d makes) under the system temp root, whose path an "
                 "earlier command of this session printed (mktemp does), symlinks checked at both "
                 "ends, is not terminal and passes.")
text_note = (" This hook matches the whole command text, heredoc bodies and -c strings included. "
             "If those words are only data (a string, a payload), write the text to a file with the "
             "Write tool and pass the file -- this hook reads the command text, never the contents of a "
             "file the command runs, so a file that itself "
             "runs the push, merge, deploy or delete needs the same adversary hold.")

reason = (
    "goalspec terminal-action precheck: this looks like " + kind_label + " (`" +
    command.strip()[:200] + "`) in a goalspec-tracked session, and no operative "
    "[ADVERSARY-VERDICT: hold ...] is on record for it yet" + verdict_note + ". Per SKILL.md, a "
    "terminal/irreversible action must be reviewed by the goal-adversary BEFORE it runs, not after "
    "the whole task closes. " + next_step + seen_note + temp_note + text_note +
    ta.WAIVER_DENY_NOTE.format(path=ta.checkpoint_name_for(sid))
)
deny(reason)
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

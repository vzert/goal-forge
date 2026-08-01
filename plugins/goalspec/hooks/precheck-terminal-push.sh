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
# this session has an open `## Goal-spec` AND no operative `[ADVERSARY-VERDICT: hold ...]` is on
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
# Precondition, deliberately narrow (same one gate-goal-close.sh already uses): only enforces
# inside a session that produced a `## Goal-spec`. This is NOT a universal git-push blocker — a
# quick untracked fix in a session that never ran goalspec is untouched, matching this plugin's own
# "not another rule in a wall for trivial work" design. Both real incidents this hook is a response
# to DID have a goal-spec, so this precondition would not have missed either one.
#
# Escape hatch, reusing existing vocabulary rather than inventing a parallel one: an explicit
# `[GOAL-CLOSE-WAIVED reason=<>=20 chars>]` anywhere in the transcript is honored here too — the
# same greppable, honest override SKILL.md already defines for closing over a residual break. No
# new marker, no new ceremony.
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

is_term, kind, diffable = ta.is_terminal(command, cwd)
if not is_term:
    allow()

if diffable:
    paths = ta.diff_paths_for(kind, command, cwd)
    if ta.all_exempt(paths):
        allow()

transcript_path = data.get("transcript_path")
sig = ta.transcript_signals(transcript_path)

if not sig["goal_spec"]:
    allow()  # precondition: only enforce inside a goalspec-tracked session, same as the Stop gate

if sig["waiver"]:
    allow("goalspec terminal-push precheck: proceeding on an existing "
          "[GOAL-CLOSE-WAIVED ...] already on record for this session.")

verdict = sig["verdict"]
if verdict == "hold":
    allow()

KIND_LABEL = {
    "push": "a git push to a protected branch",
    "merge": "a merge",
    "deploy": "a deploy/publish",
    "destructive": "a destructive command",
}
kind_label = KIND_LABEL.get(kind, kind or "a terminal command")
verdict_note = "" if verdict is None else " (the most recent adversary verdict on record is break)"

reason = (
    "goalspec terminal-action precheck: this looks like " + kind_label + " (`" +
    command.strip()[:200] + "`) in a session with an open ## Goal-spec, and no operative "
    "[ADVERSARY-VERDICT: hold ...] is on record for it yet" + verdict_note + ". Per SKILL.md, a "
    "terminal/irreversible action must be reviewed by the goal-adversary BEFORE it runs, not after "
    "the whole task closes. Spawn goal-adversary on the actual diff/outcome, get a hold, then "
    "retry this command. If this is genuinely a false positive (e.g. content that should have "
    "been exempt but was not detected as such), say so and add "
    "[GOAL-CLOSE-WAIVED reason=<>=20 chars explaining why>] to this turn, then retry."
)
deny(reason)
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

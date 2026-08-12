#!/usr/bin/env bash
# announce-checkpoint-name.sh — SessionStart hook. Non-blocking, one line of context.
#
# What it does: tells this session the exact filename its durable checkpoint must use —
# `.goalspec/checkpoint-<session_id>.md` — because the harness knows the session id and the agent
# does not.
#
# Why it exists. `references/durable-artifact.md` ("Where it lives") asks the agent to DERIVE a
# per-session token so two concurrent sessions in one project stop writing to one shared file.
# (Not "cannot clobber": nothing here guarantees that, and saying so is the overclaim two
# separate adversary rounds on this hook kept catching.) That rule was written after a live incident (two paperclip agents, one fixed path), and
# two adversary rounds on it landed the same complaint from different angles: a token the agent
# picks is not guaranteed distinct, and a token the agent derives from "a timestamp with seconds"
# or a pid is not distinct in the limit either. Both criticisms are about the agent having to
# invent uniqueness it has no access to.
#
# It never had to. The SessionStart payload carries `session_id` — verified by running it, not by
# reading about it: a probe hook in a throwaway project injected this exact message, and a child
# session asked (with no tools available) for its own checkpoint path answered with the announced
# name. So the token is not derived, not picked, and not probabilistic: it is handed over, and the
# naming rule degrades to "use the name you were given".
#
# What that is NOT, because an adversary round on this very hook caught the first draft claiming
# it: the harness DOCUMENTS the `session_id` field, it does not publish a uniqueness guarantee. So
# neither this hook nor the rule it serves may say two sessions "cannot" collide. What is
# supported, and all this claims: the token is the identifier the harness itself reports, the
# agent neither picks nor derives it, and in the one live check the announced id was exactly the
# session transcript basename. That is the third overclaim of the same class on this one rule --
# stating a guarantee nobody handed us -- which is why the wording here is deliberately narrow.
#
# What this is NOT: a gate. It cannot refuse a write and does not try to — `SessionStart` has no
# such power. The enforcing half lives in `hooks/precheck-checkpoint-overwrite.sh` (`PreToolUse` on
# `Write|Edit`) and is deliberately NARROWER than this announcement: it refuses only a write over a
# checkpoint that already exists and that this session never wrote, never a name that merely
# differs from the one announced here. So an agent that ignores this line and invents its own name
# is not stopped -- it is only stopped from taking somebody else-s file.
#
# Consumer of what it emits (instrument-consumer trace): the AGENT, via `additionalContext` — no
# code reads it. If it never arrives (older harness, no `session_id`, hook disabled, another
# harness entirely), nothing breaks and nothing is gated: the rule in `references/durable-artifact.md`
# still stands on its own and the agent derives a token as before. Fail-open is the whole contract.
#
# Behavior:
#   * `session_id` present -> one line of additionalContext naming the exact path. Always, on every
#     source (startup / resume / clear / compact) — a compacted session is precisely one that may
#     have lost the name.
#   * No `session_id`, unreadable stdin, malformed JSON -> silent exit 0. Never blocks, never errors.
#
# Registered by hooks/hooks.json alongside enable-autoupdate.sh (two SessionStart hooks, each
# fail-opening on its own — same shape as the three Stop hooks).

INPUT=$(cat)

# Portable interpreter resolver — same as every other hook in this plugin.
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | "$PY" -c '
import json, sys, re

def silent():
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    silent()

sid = data.get("session_id")
if not (isinstance(sid, str) and sid.strip()):
    silent()
sid = sid.strip()

# The id goes into a FILENAME, so it is constrained to what the read-side matchers accept
# (hooks/lib/terminal_actions.py CHECKPOINT_PATH_RE and nudge-decompose.sh, both
# `checkpoint(-[A-Za-z0-9._-]+)?\.md`). A real session id is a uuid and passes untouched; anything
# carrying a path separator or an exotic character would silently produce a name those matchers
# reject, so refuse to announce a name rather than announce a broken one.
if not re.match(r"^[A-Za-z0-9._-]+$", sid):
    silent()

# NOT truncated. Eight characters would read better and would be very unlikely to collide, but
# "very unlikely" is a probabilistic claim someone then has to defend -- and defending exactly that
# kind of claim is what cost this rule two adversary rounds. The full id carries whatever
# distinctness the harness put in it, no more and no less, and costs nothing but filename length.
msg = (
    "[GOALSPEC] If this session writes a durable checkpoint (SKILL.md Execute step -- only for a "
    "long or multi-round run; never create one speculatively), use this exact path: "
    ".goalspec/checkpoint-{}.md -- the token is the identifier the harness reports for this session, "
    "handed to you rather than chosen or derived by you. Do not invent a different name."
).format(sid)

print(json.dumps({
    "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg},
}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

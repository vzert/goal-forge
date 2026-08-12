#!/usr/bin/env bash
# precheck-checkpoint-overwrite.sh — PreToolUse(Write|Edit). Denies one thing: overwriting a
# durable checkpoint that EXISTS and that THIS SESSION cannot be shown to have successfully
# written. "Cannot be shown" covers both halves on purpose — a write that was denied or failed,
# and a transcript that cannot be read at all.
#
# The incident, and why this is a gate when almost nothing else here is. Two agents ran goalspec in
# one project at the same time and both wrote `.goalspec/checkpoint.md`; one destroyed the other-s
# live run state. The per-session filename (references/durable-artifact.md, "Where it lives") and
# the SessionStart announcement (hooks/announce-checkpoint-name.sh) make that collision unlikely.
# Neither makes it impossible: the legacy fixed name is still valid on the read side, a compacted
# session can lose the announcement, and a rule an agent merely reads is a rule an agent can skip.
# Until this hook, the announcement was an emission NO code consumed — which is this method-s own
# definition of a broken instrument (references/instrument-validity-own-tools.md). This is its
# consumer.
#
# WHY BEFORE AND NOT AFTER. A PostToolUse warning was the first candidate and it is worthless for
# this: it fires after the write, so the victim-s content is already gone, and the warning reaches
# the session that clobbered — not the one that lost. With `.goalspec/` gitignored there is nothing
# to recover from. Only a PreToolUse decision runs while the data still exists.
#
# WHY DENY AND NOT ASK. `permissionDecision: "ask"` was measured, not assumed, in three headless
# modes (default, acceptEdits, bypassPermissions). It never hangs and it always fails closed --
# and in every one of them there is no human to answer, so it degrades to a denial with a more
# confusing message and, in one run, 201 seconds of the agent deliberating first. `ask` buys
# "a human decides" only where a human is present; the fleet this was built for runs headless.
# (Worth recording from the same measurement: a hook-s `ask` is NOT bypassed by
# `--permission-mode bypassPermissions`.)
#
# WHY THIS CONDITION AND NOT "THE NAME IS WRONG". Denying every non-announced name would break a
# project that deliberately commits `.goalspec/` as a trail under its own names — a case
# durable-artifact.md explicitly blesses — and would deny a fresh session creating a checkpoint
# where nothing exists, which harms nobody. The dangerous act is not a wrong name, it is taking
# somebody else-s file. So the test is ownership, and it enforces a rule that was ALREADY ratified
# in prose ("never write to a checkpoint file this session did not create"), rather than inventing
# a new constraint to enforce.
#
# The resume case is NOT a false positive, though it looks like one. A session resuming a crashed
# run may legitimately want that file — and under per-session names, adopting it means READING it
# and continuing in your own file, which this never touches. That is now what
# durable-artifact.md-s retirement section says; the older "adopted an existing one and kept
# writing it" phrasing was a leftover of the fixed-path design, and it was the only apparent
# conflict this gate had.
#
# What it does NOT claim: it is not mutual exclusion and not a lock. It reads ownership from the
# transcript, so a checkpoint written through a shell heredoc is invisible to it, and `Bash` is not
# matched at all. It reduces the accidental clobber, which is the one that happened.
#
# TWO DIRECTIONS, and which applies depends on how far the check got. Everything BEFORE ownership
# is asked about fails OPEN: a payload that does not parse, a path that is not this project-s
# checkpoint, a file that does not exist yet. Denying there would block real work on the strength
# of a check that never ran. OWNERSHIP ITSELF fails CLOSED: by the time it is asked, the target is
# known to be an existing checkpoint here, so "I cannot establish this is yours" -- whether because
# the transcript is unreadable or because it records no successful write -- denies. An earlier cut
# allowed on an unreadable transcript and an adversary round rated that unsafe: a broken ownership
# instrument permitting exactly the destructive act the gate exists to refuse, with documentation
# offered as the remedy, which is not a remedy. A wrong deny is always escapable and never blocked:
# write under your own announced name, which does not exist yet.
#
# Behavior:
#   * Not Write/Edit, no file_path, path is not `<cwd>/.goalspec/checkpoint*.md` -> allow (silent).
#   * Path does not exist yet -> allow. Creating a checkpoint is never the dangerous act.
#   * Path exists and THIS session wrote it SUCCESSFULLY (a Write/Edit for it in this transcript
#     whose paired tool_result is not an error) -> allow. The normal case: a run rewrites its own
#     checkpoint every round.
#   * Path exists and this session never successfully wrote it -> DENY, naming the announced path
#     to use. A DENIED earlier attempt does not count as having written it, which is the retry hole
#     an adversary round found and rated unsafe.
#   * Missing or unreadable transcript -> DENY. Ownership cannot be established and the target is
#     already known to be an existing checkpoint here. (This branch allowed until an adversary
#     round rated it unsafe; suite case 09 pins the current behavior.)
#   * Malformed payload, or a failure before ownership is reached -> allow (silent).
#
# Registered by hooks/hooks.json as the third PreToolUse matcher group, alongside
# precheck-terminal-push.sh (Bash) and route-external-adversary.sh (Task|Agent).

INPUT=$(cat)

# Portable interpreter resolver — same as every other hook in this plugin.
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | "$PY" -c '
import json, os, re, sys

def allow():
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    allow()

if data.get("tool_name") not in ("Write", "Edit"):
    allow()

fp = (data.get("tool_input") or {}).get("file_path")
if not (isinstance(fp, str) and fp):
    allow()

# Same matcher, same lockstep, as hooks/lib/terminal_actions.py CHECKPOINT_PATH_RE and
# nudge-decompose.sh -- including the backslash normalization for Windows-shaped paths.
CHECKPOINT_RE = re.compile(r"(^|/)\.goalspec/checkpoint(-[A-Za-z0-9._-]+)?\.md$")
if not CHECKPOINT_RE.search(fp.replace("\\", "/")):
    allow()

cwd = data.get("cwd") or os.getcwd()
try:
    target = os.path.realpath(fp if os.path.isabs(fp) else os.path.join(cwd, fp))
    goalspec_dir = os.path.realpath(os.path.join(cwd, ".goalspec"))
except Exception:
    allow()

# Anchored to the checkpoint of the directory this session runs in, not any nested `.goalspec/`
# below it -- a sub-package running its own goalspec loop is its own run. Same anchor as
# nudge-decompose.sh, and it was an adversary round that caught that hook accepting a nested path.
if os.path.dirname(target) != goalspec_dir:
    allow()

# Creating is never the dangerous act. Only taking over an existing file is.
if not os.path.isfile(target):
    allow()

# No transcript, no ownership evidence -- and by this point we KNOW the target is an existing
# checkpoint in this project. Denying here is a deliberate exception to this hook-s
# allow-on-uncertainty rule, and it reverses the first cut, which allowed. Two things forced it:
# an adversary round rated the allow path unsafe (a broken ownership instrument permitting exactly
# the destructive act the gate exists to refuse, with documentation offered as the remedy -- which
# is not a remedy), and the justification for allowing turned out to be an UNAUDITED negative
# claim. Audited afterwards against the official hooks reference: `transcript_path` is a common
# input field of every hook event with no documented absence condition. So "denying would break
# normal operation on harnesses that supply no transcript" was not grounded, and the cost of
# denying here is small and always escapable: write under your own announced name instead, which
# is never blocked because that file does not exist yet.
tpath = data.get("transcript_path")
if not (isinstance(tpath, str) and tpath and os.path.isfile(tpath)):
    deny_no_evidence = True
else:
    deny_no_evidence = False

# Ownership: did THIS session SUCCESSFULLY write this exact path before?
#
# The word "successfully" is the whole check, and leaving it out made this gate defeat itself --
# found by an adversary round, reproduced against a real transcript, and it rated the defect
# unsafe. A denied Write is still recorded as a `tool_use` in the transcript. So the first attempt
# to clobber a foreign checkpoint was denied, that denial became "evidence" that this session had
# written the file, and an identical retry was ALLOWED -- destroying exactly the live state this
# hook exists to protect, on the second try. The evidence for a check must not be authored by the
# act the check refuses.
#
# So a tool_use only counts when its paired tool_result says it worked: results arrive in a
# `user`-type message as `{"type": "tool_result", "tool_use_id": ..., "is_error": ...}` (shape read
# off a real transcript, not assumed). Absence of a successful result is NOT ownership: at
# PreToolUse time every earlier write has already resolved, so "no successful result" means it did
# not happen. Both halves of "cannot be shown" deny here: a transcript that cannot be read at all,
# and one that records no successful write for this path.
candidate_ids = set()
ok_ids = set()
err_ids = set()
try:
    if deny_no_evidence:
        raise IOError("no transcript")
    with open(tpath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            content = (ev.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                btype = blk.get("type")
                if btype == "tool_use" and blk.get("name") in ("Write", "Edit"):
                    prev = (blk.get("input") or {}).get("file_path")
                    if not (isinstance(prev, str) and prev):
                        continue
                    if not CHECKPOINT_RE.search(prev.replace("\\", "/")):
                        continue
                    try:
                        p = os.path.realpath(prev if os.path.isabs(prev) else os.path.join(cwd, prev))
                    except Exception:
                        continue
                    if p == target and blk.get("id"):
                        candidate_ids.add(blk.get("id"))
                elif btype == "tool_result" and blk.get("tool_use_id"):
                    (err_ids if blk.get("is_error") else ok_ids).add(blk.get("tool_use_id"))
except Exception:
    # Unreadable or unparseable transcript: same position as no transcript at all -- we cannot
    # establish that this session wrote the file, so we do not let it overwrite one. See above.
    pass

if candidate_ids & ok_ids:
    allow()

sid = data.get("session_id")
mine = ".goalspec/checkpoint-{}.md".format(sid) if isinstance(sid, str) and re.match(r"^[A-Za-z0-9._-]+$", sid or "") else ".goalspec/checkpoint-<your session id>.md"

why = ("could not be verified as yours (no readable session transcript, so ownership cannot be "
       "established)") if deny_no_evidence else "was never successfully written by THIS session"

reason = (
    "goalspec: {} already exists and " + why + ", so it belongs to another run -- "
    "possibly one that is still going, whose live state you would destroy (this is the incident "
    "that made the checkpoint per-session in the first place). Nothing is lost by not writing it: "
    "read that file if it helps you resume, then continue in YOUR OWN checkpoint, {} -- adopting a "
    "stopped run means reading its file, not continuing to write it (references/durable-artifact.md, "
    "\"Where it lives\"). If the other run is genuinely finished and you are taking over its work, "
    "retire its file explicitly rather than overwriting it in passing."
).format(os.path.relpath(target, cwd) if target.startswith(cwd) else target, mine)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    },
}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

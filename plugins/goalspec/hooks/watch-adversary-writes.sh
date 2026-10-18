#!/usr/bin/env bash
# watch-adversary-writes.sh — SubagentStart/SubagentStop hook. The MEASURING half of the read-only
# rail for the SUBAGENT backend; the rule itself is a paragraph in agents/goal-adversary.md.
#
# The problem it fixes: the goal-adversary subagent holds `Bash` (it needs it — re-deriving a figure
# means running the query, the suite, the git command). Nothing stopped it from also WRITING, and
# some adversary runs take the initiative to fix what they find. An adversary that repairs the work
# then verifies a state it created — principle 1 turned on the verifier — and the resulting clean
# `hold` is indistinguishable from an honest one. The external backend got the same rail in
# hooks/external-adversary.sh; this is the subagent half, so the rule exists on BOTH carriers with a
# consumer on each rather than as prose on one of them.
#
# WHY THESE TWO EVENTS AND NOT THE Task HOOKS. The obvious seam looked like the PreToolUse/PostToolUse
# pair already registered on `Task|Agent` (route-external-adversary.sh, remind-quote-verdict.sh). It
# does not work: since Claude Code v2.1.198 subagents run in the BACKGROUND by default, so the Task
# tool result is a handle and PostToolUse fires at LAUNCH, not at completion — measured and documented
# at length in remind-quote-verdict.sh. A snapshot pair around the Task call would bracket the spawn,
# not the run: an instrument that measures nothing, which is the exact defect this rail exists to
# catch. SubagentStart/SubagentStop bracket the actual run and carry `agent_type` + `agent_id`, so the
# attribution is structural rather than guessed.
#
# What it does:
#   start -> fingerprint the repository CONTENT, stash it keyed by agent_id in this session's own
#            run directory, ${XDG_STATE_HOME:-~/.local/state}/goalspec/run-<session_id>/ (%LOCALAPPDATA% on Windows)
#            (hooks/lib/run_dir.py).
#   stop  -> fingerprint again, diff, RE-ARM the snapshot, and if anything changed RECORD the paths
#            to a per-session findings file. It emits NOTHING.
#
# IT EMITS NOTHING, AND THAT IS THE POINT (0.44.1). A SubagentStop hook's output goes to the subagent
# that just stopped, never to the executor — measured, see the long note at the bottom of this file.
# 0.44.0 emitted here, so the warning reached only the party it was about, written in the second
# person, and one goal-adversary read it as a role change and started editing. The reporting half now
# lives in hooks/report-adversary-writes.sh, on `Stop`, whose output does reach the executor.
#
# Deliberately NOT a revert and NOT a block: SubagentStop cannot un-write anything, undoing a change
# the human may have made themselves is precisely the no-harm violation this checks for, and the
# external half already refuses remove-verbs on artifacts it does not own. Naming the paths is the
# whole job.
#
# Fail-open everywhere: no git, no repo, no session id, unparseable payload, missing snapshot ->
# exit 0, silent. A run directory that cannot be used (someone else's, a symlink, wrong mode,
# state directory not writable) -> exit 0 too, but run_dir.py leaves a note that report-adversary-writes.sh
# reports on Stop: until 0.62.0 that failure was silent, and on a shared Linux /tmp it disabled this
# rail for every user but the first (361 of 361 runs, measured; see hooks/lib/run_dir.py). It never
# blocks a subagent and never blocks a close.
#
# Registered by hooks/hooks.json on SubagentStart and SubagentStop, matcher "(^|:)goal-adversary$".
# The matcher is belt; the agent_type re-check below is braces — a harness that passes the matcher
# loosely must not turn this into a fingerprint of every subagent in the session.
#
# WHICH TREE (0.64.0, p-4258624faf). Until 0.63.1 this measured the repository of the session's cwd.
# An executor that works in a separate git worktree (another session edits the main checkout) keeps
# its cwd in the main checkout and hands the adversary paths inside the worktree, so the rail
# measured the wrong tree: on 2026-10-17 five Stop notices named only other sessions' writes in the
# main checkout, and a write by the adversary in the worktree would have gone unseen. Neither
# SubagentStart nor SubagentStop carries the spawn prompt; PreToolUse on Task|Agent does
# (tool_input.prompt, read by route-external-adversary.sh and precheck-subagent-model.sh too). So a
# third mode, `spawn`, runs there: every absolute path in the prompt that sits in a worktree of the
# session's repository (same git common directory, main checkout included) names a tree to measure,
# recorded in this session's run directory. The next `start` takes that record and deletes it, and
# writes the roots into the snapshot so `stop` measures the same trees. No such path, no record, and
# the hook measures the cwd's repository exactly as before.
# Declared limits: a tree the prompt does not name is not measured; two adversaries spawned in one
# message share one record (the second spawn's), so the first may be measured on the wrong tree;
# and a write by another writer inside a measured tree looks like the adversary's unless another
# session's transcript records its whole change (0.65.0, p-2bf372e6e3: see WHO WROTE IT below).
# A path outside the cwd's repository is reported absolute, so the human sees which
# tree it is in; a path in the cwd's repository stays relative, as before.
# hooks/external-adversary.sh is not changed: it runs in the directory the executor runs it from,
# so the executor already picks its tree (and it reviews a private copy of it since 0.44.9).
#
# Usage: watch-adversary-writes.sh spawn|start|stop   (payload JSON on stdin)

MODE="${1:-}"
[ "$MODE" = "spawn" ] || [ "$MODE" = "start" ] || [ "$MODE" = "stop" ] || exit 0

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

# Pull the three fields we need. Prints "agent_id<TAB>cwd<TAB>session" only for a real
# goal-adversary; anything else -> empty, and this hook goes silent. In `spawn` mode the type comes
# from tool_input and the next lines are the absolute paths the prompt names, one per line.
FIELDS=$(printf '%s' "$INPUT" | GS_MODE="$MODE" "$PY" -c '
import json, os, sys, re
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
spawn = os.environ.get("GS_MODE") == "spawn"
inp = d.get("tool_input") if spawn else None
if spawn:
    # A spawn made from inside a subagent is not the executor naming its review (same exit as
    # precheck-subagent-model.sh).
    if d.get("tool_name") not in ("Task", "Agent") or d.get("agent_id") or not isinstance(inp, dict):
        sys.exit(0)
    at = inp.get("subagent_type") or ""
else:
    at = d.get("agent_type") or ""
# Same anchor remind-quote-verdict.sh uses: "goal-adversary" and "goalspec:goal-adversary" match,
# "not-goal-adversary-example" does not. That fabricated form slipped a bare substring check once.
if not (isinstance(at, str) and re.search(r"(^|:)goal-adversary$", at.strip().lower())):
    sys.exit(0)
aid = "spawn" if spawn else (d.get("agent_id") or d.get("session_id") or "")
cwd = d.get("cwd") or ""
sid = d.get("session_id") or ""
# No session id, no run directory (0.62.0). Until then the agent id stood in for it, which put the
# findings where neither the reporter nor the SessionEnd cleanup would ever look.
if not aid or not sid:
    sys.exit(0)
# Keys must be filesystem-safe: ids are harness-generated, so this is hygiene, not distrust.
safe = lambda v: re.sub(r"[^A-Za-z0-9_.-]", "_", str(v))[:120]
print(safe(aid) + "\t" + str(cwd).replace("\n", " ") + "\t" + safe(sid))
if spawn:
    seen = set()
    for m in re.finditer(r"/[^\s`\x27\"<>()\[\]{},;|*?]+", str(inp.get("prompt") or "")):
        p = m.group(0).rstrip(".:")
        # A path the review names may not exist yet (a file it will be asked about): its nearest
        # existing parent still says which tree it is in. The filesystem root says nothing.
        while p and p != "/" and not os.path.exists(p):
            p = os.path.dirname(p)
        if p and p != "/":
            p = p if os.path.isdir(p) else os.path.dirname(p)
            if p not in seen:
                seen.add(p)
                print(p)
' 2>/dev/null)

[ -z "$FIELDS" ] && exit 0
FIRST=$(printf '%s\n' "$FIELDS" | head -n 1)
AGENT_KEY=$(printf '%s' "$FIRST" | cut -f1)
PAYLOAD_CWD=$(printf '%s' "$FIRST" | cut -f2)
SESSION_KEY=$(printf '%s' "$FIRST" | cut -f3)
[ -n "$SESSION_KEY" ] || exit 0

# Resolve the repo from the payload cwd, not from this process cwd: a hook runs wherever the harness
# puts it, and the payload states where the session actually is.
[ -n "$PAYLOAD_CWD" ] && [ -d "$PAYLOAD_CWD" ] || PAYLOAD_CWD=$PWD
REPO_ROOT=$(git -C "$PAYLOAD_CWD" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$REPO_ROOT" ] || exit 0

# Snapshots live OUTSIDE the repository — writing them inside would make this instrument trip on
# itself, the most embarrassing way for a change-detector to fail. One directory per SESSION, owner
# and mode checked (hooks/lib/run_dir.py); empty output means it cannot be used and a note was left.
# A copy of this hook outside the plugin (a --compare baseline, a selftest mutant) finds the
# library through CLAUDE_PLUGIN_ROOT, as remind-handback-verdict.sh does.
RUN_DIR_PY="$(dirname "$0")/lib/run_dir.py"
[ -f "$RUN_DIR_PY" ] || RUN_DIR_PY="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib/run_dir.py"
# The repo root goes along: a state directory inside the repository under review (a repo rooted at
# the home directory) would make the snapshot one of the files it fingerprints, so run_dir.py
# refuses it and leaves a note outside the repository, or in its git directory when every state
# directory is inside it. Compared in Python, as real case-normalised paths: Git Bash on
# Windows gives a forward-slash root and Python a backslash path.
SNAP_DIR=$("$PY" "$RUN_DIR_PY" ensure "$SESSION_KEY" watch-adversary-writes "$REPO_ROOT" 2>/dev/null)
[ -n "$SNAP_DIR" ] || exit 0
SNAP="$SNAP_DIR/$AGENT_KEY.fp"
TARGETS="$SNAP_DIR/target-trees"

# The git common directory of a tree, as a real path: two worktrees of one repository share it.
_gs_common() {
  ( cd "$1" 2>/dev/null && _d=$(git rev-parse --git-common-dir 2>/dev/null) && cd "$_d" 2>/dev/null && pwd -P )
}

# spawn: record the trees the prompt names (see WHICH TREE at the top). Every spawn replaces the
# record, and a spawn that names none removes it, so a record never outlives the spawn that made it
# by more than one SubagentStart.
if [ "$MODE" = "spawn" ]; then
  MINE=$(_gs_common "$REPO_ROOT")
  NAMED=$(printf '%s\n' "$FIELDS" | sed -n '2,$p')
  ROOTS=""
  if [ -n "$MINE" ]; then
    while IFS= read -r _p; do
      [ -n "$_p" ] && [ -d "$_p" ] || continue
      _top=$(git -C "$_p" rev-parse --show-toplevel 2>/dev/null) || continue
      [ -n "$_top" ] || continue
      [ "$(_gs_common "$_top")" = "$MINE" ] || continue
      case "
$ROOTS
" in *"
$_top
"*) continue ;; esac
      ROOTS="${ROOTS:+$ROOTS
}$_top"
    done <<EOF_PATHS
$NAMED
EOF_PATHS
  fi
  if [ -n "$ROOTS" ]; then
    printf '%s\n' "$ROOTS" > "$TARGETS.tmp" 2>/dev/null && mv -f "$TARGETS.tmp" "$TARGETS" 2>/dev/null
  else
    rm -f "$TARGETS" 2>/dev/null
  fi
  exit 0
fi

# CONTENT, not `git status`. The tree under review is almost always ALREADY dirty (the uncommitted
# work being verified), so a partner that appends one line to an already-modified file leaves the
# byte-identical " M path" porcelain line before and after. Hash the blobs instead.
# KNOWN GAPS, stated rather than left to be discovered: gitignored paths are invisible to
# `--exclude-standard` (`.goalspec/` is the one that matters and is hashed explicitly below; others
# are out of reach), writes outside the repo root are out of scope by design (that is where scratch
# belongs), and a file changed and changed back reads as unchanged — correctly, nothing was left
# modified. This mirrors hooks/external-adversary.sh so the two backends measure the same thing; when
# one changes, change both.
# ANOTHER SESSION'S RUN STATE is left out (0.63.1). A parallel session of the same project writes
# its own .goalspec/checkpoint-<its id>.md while this adversary runs, and every such write was
# reported as this round's (observed on the team VPS, checkpoint-831306ab-… under session 23ebe429).
# A file named <kind>-<token>.<ext>, the token 8 hex digits or a full session id, belongs to the
# session the token names; it is skipped only when this session's id does not start with it AND a
# transcript of that session exists beside this session's own (below). This
# session's own files and files with no token stay measured: a warning too many, never one too few.
# Declared hole: an adversary that writes a file under a foreign-looking token is not seen.
# The token must name a session that EXISTS: a transcript <token>*.jsonl next to this session's own,
# in ${CLAUDE_CONFIG_DIR:-~/.claude}/projects/<project>/. Without that check any name ending in 8 hex
# digits passed as foreign — a date (report-20261017.md), a short sha, even this session's own id
# with a suffix — and an accidental write under such a name went unseen (adversary round, 0.63.1).
# No transcript directory found for this session -> nothing is skipped.
_gs_session_dir() {
  # $1 = this session's id. Prints the directory that holds its transcript, or nothing.
  [ -n "${1:-}" ] || return 0
  for _t in "${CLAUDE_CONFIG_DIR:-${HOME:-}/.claude}"/projects/*/"$1".jsonl; do
    [ -f "$_t" ] && { printf '%s\n' "${_t%/*}"; return 0; }
  done
  return 0
}
_gs_foreign_runstate() {
  # $1 = file name, $2 = this session's id, $3 = its transcript directory. Exit 0 = another
  # session's file.
  [ -n "${2:-}" ] && [ -n "${3:-}" ] || return 1
  case "$1" in *?.?*) ;; *) return 1 ;; esac  # <kind>-<token>.<ext>: no extension, not the shape
  _re='-([0-9a-f]{8}(-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?)$'
  [[ ${1%.*} =~ $_re ]] || return 1
  case "$2" in "${BASH_REMATCH[1]}"*) return 1 ;; esac
  for _t in "$3/${BASH_REMATCH[1]}"*.jsonl; do
    [ -f "$_t" ] && return 0
  done
  return 1
}
SESSION_DIR=$(_gs_session_dir "$SESSION_KEY")
fingerprint_tree() {
  # $1 = the tree's root. Its paths are relative when it is the cwd's repository (as before 0.64.0)
  # and absolute otherwise, so the notice says which tree a path is in.
  _r=$1
  _pre=""
  [ "$_r" = "$REPO_ROOT" ] || _pre="$_r/"
  printf 'HEAD %s\n' "$(git -C "$_r" rev-parse HEAD 2>/dev/null || echo unborn)"
  printf 'staged %s\n' "$(git -C "$_r" diff --cached 2>/dev/null | git hash-object --stdin 2>/dev/null || echo none)"
  git -C "$_r" ls-files -m -o -d --exclude-standard -z 2>/dev/null \
    | while IFS= read -r -d '' p; do
        if [ -f "$_r/$p" ]; then
          printf '%s %s\n' "$(git -C "$_r" hash-object -- "$_r/$p" 2>/dev/null || echo unreadable)" "$_pre$p"
        else
          printf 'absent %s\n' "$_pre$p"
        fi
      done
  for f in "$_r"/.goalspec/*; do
    [ -f "$f" ] || continue
    _gs_foreign_runstate "${f##*/}" "$SESSION_KEY" "$SESSION_DIR" && continue
    printf '%s %s\n' "$(git -C "$_r" hash-object -- "$f" 2>/dev/null || echo unreadable)" "$_pre${f#"$_r"/}"
  done
}

# Every tree in $ROOTS, each under a `root` line.
fingerprint() {
  while IFS= read -r _root; do
    [ -n "$_root" ] || continue
    printf 'root %s\n' "$_root"
    fingerprint_tree "$_root"
  done <<EOF_ROOTS
$ROOTS
EOF_ROOTS
}

if [ "$MODE" = "start" ]; then
  # Take the record a spawn left, once; without one, the cwd's repository.
  ROOTS=""
  if [ -f "$TARGETS" ]; then
    ROOTS=$(cat "$TARGETS" 2>/dev/null || true)
    rm -f "$TARGETS" 2>/dev/null
  fi
  [ -n "$ROOTS" ] || ROOTS=$REPO_ROOT
  fingerprint > "$SNAP" 2>/dev/null || true
  exit 0
fi

# stop: no snapshot means this hook did not see the start (installed mid-run, unwritable state directory,
# a harness that skipped the event). Silence is correct — claiming "no writes detected" from a
# measurement that never ran is the broken instrument this whole rail is about.
[ -f "$SNAP" ] || exit 0

# The trees the start measured, from its snapshot; a snapshot without them (0.63.1 or older) was the
# cwd's repository.
ROOTS=$(sed -n 's/^root //p' "$SNAP" 2>/dev/null || true)
[ -n "$ROOTS" ] || ROOTS=$REPO_ROOT

AFTER=$(fingerprint 2>/dev/null || true)
BEFORE=$(cat "$SNAP" 2>/dev/null || true)
# When this round began: the snapshot was last written by `start` or by the previous stop's re-arm.
# Read before the re-arm below rewrites it; other_writer.py looks only at writes since then.
START_TS=$("$PY" -c 'import os, sys; print(os.path.getmtime(sys.argv[1]))' "$SNAP" 2>/dev/null || echo 0)
# RE-ARM, do not delete. A subagent can stop and then keep going (a harness that resumes it, a
# teammate message, a hook that hands it more context), and 0.44.0 deleted the snapshot on the first
# stop — so everything the agent did afterwards was unmeasured, silently. That is exactly what
# happened in the recorded 2026-09-12 incident: the writes this rail exists to catch landed AFTER
# the first stop and no second firing could see them. Making AFTER the new baseline means the next
# stop measures only the new delta.
printf '%s\n' "$AFTER" > "$SNAP" 2>/dev/null || true

[ "$BEFORE" = "$AFTER" ] && exit 0

# Name the path column of every line present in exactly one capture. A changed blob yields two
# differing lines for the same path; sort -u collapses them. The two HEADER lines carry no path, so
# they get NAMED rather than stripped: without this the generic rule prints their bare hash as if it
# were a filename, which is how case 05 (a staged change) first came back reporting a 40-char hex
# string as a modified file. Keep this in step with the identical extractor in external-adversary.sh.
CHANGED=$(diff <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$AFTER") 2>/dev/null \
          | grep -E '^[<>]' \
          | sed -E -e 's/^[<>] HEAD .*/(HEAD moved: a commit or checkout happened during the run)/' \
                   -e 's/^[<>] staged .*/(the git index: content was staged or unstaged)/' \
                   -e 's/^[<>] [^ ]+ ?//' \
          | grep -v '^$' | sort -u || true)
[ -z "$CHANGED" ] && CHANGED="(content changed but no path could be named — inspect \`git status\` by hand)"

# WHO WROTE IT, when the record proves it (0.65.0, p-2bf372e6e3). A path whose whole change is
# another session's recorded Write/Edit calls, chained from the content before to the content after,
# becomes an `other <sid8> <path>` line; every other path stays a `path` line, as before.
# hooks/lib/other_writer.py has the chain and its limits. No library (a --compare baseline copied
# alone without CLAUDE_PLUGIN_ROOT) or any error -> every path stays a `path` line.
OTHER_PY="$(dirname "$0")/lib/other_writer.py"
[ -f "$OTHER_PY" ] || OTHER_PY="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib/other_writer.py"
LINES=""
if [ -f "$OTHER_PY" ]; then
  LINES=$(printf '%s\0%s\0%s' "$BEFORE" "$AFTER" "$CHANGED" \
          | "$PY" "$OTHER_PY" attribute "$SESSION_KEY" "$START_TS" "$REPO_ROOT" 2>/dev/null || true)
fi
[ -n "$LINES" ] || LINES=$(printf '%s\n' "$CHANGED" | sed 's/^/path /')

# DO NOT EMIT HERE. This is the half of 0.44.0 that was wrong, and it was worse than useless.
# MEASURED on 2026-09-12 in a real session (3-tier-memory, session 035edc21): a SubagentStop hook
# emitting `systemMessage`/`additionalContext` has its output delivered to the SUBAGENT THAT JUST
# STOPPED, not to the executor — it lands in that agent's own transcript as
# `type: attachment, isSidechain: true`, and the executor's transcript contains it ZERO times. So the
# party that needed the warning never saw it, and the party the warning is ABOUT received a text
# written in the second person ("YOU edited under an in-flight verifier... decide what to keep or
# revert"). The goal-adversary read it as addressed to itself, concluded it had become the executor,
# and wrote to five files in the repo under review. The detector of adversary writes had become their
# trigger.
#
# So the finding is RECORDED here and REPORTED from a hook whose output does reach the executor:
# hooks/report-adversary-writes.sh, on `Stop`. That routing is measured too, in the same transcript:
# a `hookName: "Stop"` attachment lands with `isSidechain: false` in the executor's own file.
#
# One record per firing, append-only, in this SESSION's run directory so a different session never
# picks it up. The reporter reads, emits, and deletes.
FINDINGS="$SNAP_DIR/findings"
{
  printf 'ts=%s agent=%s repo=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$AGENT_KEY" "$REPO_ROOT"
  printf '%s\n' "$LINES"
  printf 'end\n'
} >> "$FINDINGS" 2>/dev/null || true
exit 0

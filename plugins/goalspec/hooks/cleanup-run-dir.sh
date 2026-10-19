#!/usr/bin/env bash
# cleanup-run-dir.sh — SessionEnd hook. Removes this session's run directory,
# ${XDG_STATE_HOME:-~/.local/state}/goalspec/run-<session_id>/ (%LOCALAPPDATA% on Windows), its failure note, and any run directory of this user
# untouched for 30 days (hooks/lib/run_dir.py).
#
# Why (0.62.0): the run directory holds one snapshot per goal-adversary round, plus the findings and
# hand-back records the other hooks consume. The shared directory it replaced was never cleaned —
# 284 snapshots of one developer sat in /tmp on the VPS, measured 2026-10-17. The new directory lives in
# the user's home, which no system job cleans, so this hook is what keeps it bounded.
#
# It removes ONLY the directory whose name carries the session id in the payload, and only if
# run_dir.py's check passes: a real directory, not a symlink, owned by this uid, mode 0700. A
# directory under that name that belongs to someone else is not ours to delete. If SessionEnd never
# fires (a crash), the directory stays until a later session's SessionEnd prunes it after 30 days. If a
# resumed session keeps its id, the next hook simply creates it again.
#
# Fail-open everywhere and silent: no session id, unparseable payload, nothing to remove -> exit 0.
#
# Registered by hooks/hooks.json on SessionEnd.

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
# Claude Code writes the payload as UTF-8, but on Windows python reads stdin, prints and open()s
# with the system code page (cp1252): an accented path arrived garbled and the hook went silent,
# and a file with an accent was misread or rewritten (p-ee6150b00b). Force UTF-8 for every python.
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

SID=$(printf '%s' "$INPUT" | "$PY" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = d.get("session_id")
if isinstance(sid, str):
    print(sid)
' 2>/dev/null)

[ -n "$SID" ] || exit 0
# A copy of this hook outside the plugin (a --compare baseline, a selftest mutant) finds the
# library through CLAUDE_PLUGIN_ROOT, as remind-handback-verdict.sh does.
RUN_DIR_PY="$(dirname "$0")/lib/run_dir.py"
[ -f "$RUN_DIR_PY" ] || RUN_DIR_PY="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib/run_dir.py"
"$PY" "$RUN_DIR_PY" remove "$SID" >/dev/null 2>&1 || true
exit 0

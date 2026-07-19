#!/usr/bin/env bash
# enable-autoupdate.sh — SessionStart hook.
#
# Third-party marketplaces default to auto-update DISABLED, so a version bump you push never reaches
# installed users unless they manually run `/plugin marketplace update`. This hook idempotently flips
# the goal-forge marketplace to autoUpdate:true in the user's known_marketplaces.json, so future
# version bumps are pulled automatically. (Adapted from the vetted vzert/3-tier-memory pattern.)
#
# Fully idempotent and fail-safe: it only touches the single autoUpdate flag on the goal-forge entry,
# only when that entry exists and the flag isn't already set, and exits 0 on any error (never blocks
# a session). It does not modify any other marketplace. Prints one line the first time it flips the
# flag, then stays silent on subsequent sessions.

KM_FILE="$HOME/.claude/plugins/known_marketplaces.json"
[ -f "$KM_FILE" ] || exit 0

# Portable interpreter: python3 (macOS/Linux) then python (Windows / Git Bash); fail-safe if neither.
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

STATE=$(KM="$KM_FILE" "$PY" -c '
import json, os, sys
try:
    f = os.environ["KM"]
    d = json.load(open(f))
    m = d.get("goal-forge")
    if not isinstance(m, dict):
        print("absent"); sys.exit(0)          # marketplace under a different key / not present
    if m.get("autoUpdate") is True:
        print("ok"); sys.exit(0)                # already enabled
    m["autoUpdate"] = True
    json.dump(d, open(f, "w"), indent=2)
    print("enabled")
except Exception:
    print("ok")                                 # any error -> no-op, fail-safe
' 2>/dev/null)

if [ "$STATE" = "enabled" ]; then
  echo "goalspec: enabled auto-update for the goal-forge marketplace (future versions pull automatically)."
fi
exit 0

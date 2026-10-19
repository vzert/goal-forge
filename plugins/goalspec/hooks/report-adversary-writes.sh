#!/usr/bin/env bash
# report-adversary-writes.sh — Stop hook. The REPORTING half of the subagent read-only rail.
# hooks/watch-adversary-writes.sh measures; this one tells the executor.
#
# WHY THE HALVES ARE SPLIT, and it is the whole reason this file exists (0.44.1). In 0.44.0 the
# SubagentStop hook did both: it measured and it emitted. That was wrong in a way no synthetic test
# could show, and it was worse than doing nothing. MEASURED on 2026-09-12 in a real session
# (3-tier-memory, session 035edc21-2799-41e6-94da-e6f6472fb505):
#
#   * A SubagentStop hook's `systemMessage`/`additionalContext` is delivered to the SUBAGENT THAT
#     JUST STOPPED. It appears in that agent's own transcript as `type: attachment,
#     isSidechain: true`. The executor's transcript contains it ZERO times.
#   * The 0.44.0 message was written for the executor, in the second person: "(2) YOU edited under an
#     in-flight verifier ... decide what to keep or revert".
#   * The goal-adversary that received it recorded, in its own words, that it "misread it as a cue
#     that I had become the executor", and then wrote to five files in the repository under review.
#
# So the hook built to catch an adversary writing became the thing that told it to write, while the
# executor — the only party who can act on the finding — never learned anything. A rail with that
# shape is not a weak rail; it is a harmful one.
#
# THE ROUTING THIS FILE DEPENDS ON IS MEASURED, NOT ASSUMED, in that same transcript: a
# `hookName: "Stop"` hook_success attachment lands with `isSidechain: false` in the EXECUTOR's own
# file. Stop output reaches the executor; SubagentStop output does not. That asymmetry is the design.
#
# What it does: reads the findings file that watch-adversary-writes.sh appends to in this session's
# run directory (hooks/lib/run_dir.py), prints one message naming every path, and deletes the file so
# a finding is reported once. It also reports, once, any note run_dir.py left because that directory
# could not be used (0.62.0): that failure used to be silent, and on a shared Linux /tmp it switched
# the rail off for every user but the first.
#
# Deliberately NOT registered on the gate. `gate-goal-close.sh` is 54KB with a 48-case suite and a
# documented history of silent breakage; a second, small, independent Stop hook costs nothing and
# risks nothing there.
#
# Deliberately NOT blocking. Like the rest of this rail it reports and never reverts: undoing a
# change the human may have made themselves is the no-harm violation being checked for.
#
# Fail-open everywhere: no findings file, unparseable payload, no session id -> exit 0, silent. A run
# directory that fails the owner/mode check is never read (its content could be planted); when the
# watcher could not use it, it left a failure note, and that note is what this hook reports.
#
# Registered by hooks/hooks.json on Stop.

INPUT=$(cat)

PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
# Claude Code writes the payload as UTF-8, but on Windows python reads stdin, prints and open()s
# with the system code page (cp1252): an accent in a path or prompt arrived garbled, or made
# json.load fail and the hook go silent (p-ee6150b00b). Force UTF-8 for every python started here.
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

# 0.63.0 (p-c6f0719a23): print a Stop notice whose WHOLE shown text (the line and its lists) is at
# most 300 characters: on a Stop hook additionalContext is shown to the human too (learning 67).
# HEAD is the line; each list is "TITLE<TAB>items, one per line" in LIST1/LIST2. Items are added
# while they fit; the rest are counted ("y N más"). A first item that does not fit is cut from the
# left (0.65.3); a list with no room even for that keeps its title and count.
emit_notice() {
  "$PY" -c '
import json, os
LIMIT = 300
out = os.environ["HEAD"]
lists = []
for key in ("LIST1", "LIST2", "LIST3"):
    title, _, body = os.environ.get(key, "").partition("\t")
    items = [i for i in body.split("\n") if i.strip()]
    if title and items:
        lists.append((title, items))
# Each list always keeps its title and count, so that much is reserved up front for every list
# after the one being filled (external review round 2 on 0.63.0: a second list overflowed).
def floor(title, items):
    return len("\n%s %d" % (title, len(items)))
for n, (title, items) in enumerate(lists):
    later = sum(floor(t, i) for t, i in lists[n + 1:])
    out += "\n" + title
    shown = 0
    for it in items:
        line = "\n  - " + it
        rest = len(items) - shown - 1
        reserve = len("\n  - y %d más" % rest) if rest else 0
        if len(out) + len(line) + reserve + later > LIMIT:
            break
        out += line
        shown += 1
    # 0.65.3 (p-ab84769f53): a list never shows only its count. When even the first item does not
    # fit, it is cut from the left ("…" + its end, where a path keeps its file name), because the
    # findings file is deleted once read and "Rutas: 1" left no way to learn which path it was.
    if not shown and items:
        rest = len(items) - 1
        reserve = len("\n  - y %d más" % rest) if rest else 0
        room = LIMIT - len(out) - len("\n  - ") - reserve - later
        if room >= 2:
            it = items[0] if len(items[0]) <= room else "…" + items[0][-(room - 1):]
            out += "\n  - " + it
            shown = 1
    if shown < len(items):
        out += "\n  - y %d más" % (len(items) - shown) if shown else " %d" % len(items)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": out}}))
' 2>/dev/null || true
}

FIELDS=$(printf '%s' "$INPUT" | "$PY" -c '
import json, sys, re
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = d.get("session_id") or ""
if not sid:
    sys.exit(0)
print(re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid))[:120] + "\t" + str(d.get("cwd") or ""))
' 2>/dev/null)
SESSION_KEY=$(printf '%s' "$FIELDS" | cut -f1)
PAYLOAD_CWD=$(printf '%s' "$FIELDS" | cut -f2)

[ -z "$SESSION_KEY" ] && exit 0

# A copy of this hook outside the plugin (a --compare baseline, a selftest mutant) finds the
# library through CLAUDE_PLUGIN_ROOT, as remind-handback-verdict.sh does.
RUN_DIR_PY="$(dirname "$0")/lib/run_dir.py"
[ -f "$RUN_DIR_PY" ] || RUN_DIR_PY="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib/run_dir.py"
# The session's repository, so a note left in its git directory (every state directory inside the
# repository, e.g. a repository rooted at the home directory) is found too.
REPO_ROOT=""
[ -n "$PAYLOAD_CWD" ] && [ -d "$PAYLOAD_CWD" ] && REPO_ROOT=$(git -C "$PAYLOAD_CWD" rev-parse --show-toplevel 2>/dev/null || true)
FAILED=$("$PY" "$RUN_DIR_PY" failures "$SESSION_KEY" "$REPO_ROOT" 2>/dev/null || true)
SNAP_DIR=$("$PY" "$RUN_DIR_PY" path "$SESSION_KEY" 2>/dev/null || true)
FINDINGS="$SNAP_DIR/findings"
BODY=""
if [ -n "$SNAP_DIR" ] && [ -f "$FINDINGS" ]; then
  # Read then delete: a finding is reported once. Deleting first would lose it if this process dies
  # between the read and the print, so read into a variable and unlink after.
  BODY=$(cat "$FINDINGS" 2>/dev/null || true)
  rm -f "$FINDINGS" 2>/dev/null || true
fi

# The measurement could not run (0.62.0). Said on its own, because a finding cannot come with it:
# the run directory was unusable, so no snapshot was taken.
if [ -n "$FAILED" ] && [ -z "$BODY" ]; then
  # 0.63.0 (p-c6f0719a23): one short line in additionalContext only — on a Stop hook that field is
  # shown to the human too (learning 67), so a systemMessage beside it showed the notice twice.
  # The audience line stays first and keeps its two halves (who is addressed; that a goal-adversary
  # reading it is not), shortened.
  HEAD="Para quien ejecuta; un revisor que lo lea verifica, no repara.
goalspec: la vigilancia del revisor no guardó su estado: no midió si cambió archivos y un hold de esas rondas no lo prueba. Dilo al cerrar; no borres esa carpeta si no es tuya. SKILL.md paso 6." \
  LIST1="Motivo:	$FAILED" emit_notice
  exit 0
fi
[ -z "$BODY" ] && exit 0

# Collect the distinct paths across every record. A malformed line is skipped, not fatal: a
# reporter that dies on bad input is a reporter that stays silent about a real finding.
PATHS=$(printf '%s\n' "$BODY" | sed -n 's/^path //p' | grep -v '^$' | sort -u || true)
# 0.65.0 (p-2bf372e6e3): `other <sid8> <path>` = another session's recorded writes make the whole
# change of that path (hooks/lib/other_writer.py). Shown as "<path> (<sid8>)".
OTHERS=$(printf '%s\n' "$BODY" | sed -n 's/^other \([^ ]*\) \(..*\)$/\2 (\1)/p' | sort -u || true)
ROUNDS=$(printf '%s\n' "$BODY" | grep -c '^ts=' || true)
[ -z "$PATHS" ] && [ -z "$OTHERS" ] && exit 0
L2=""
[ -n "$FAILED" ] && L2="Rondas sin medir:	$FAILED"
L3=""
[ -n "$OTHERS" ] && L3="De otra sesión:	$OTHERS"

# Every changed path is another session's, proved by its record: the adversary left nothing there,
# so the question to the executor is gone. What stays is that the tree under review moved during
# the round, so a verdict about one of those files may describe content that is no longer there.
if [ -z "$PATHS" ]; then
  HEAD="Para quien ejecuta; un revisor que lo lea verifica, no repara.
goalspec: otra sesión cambió lo revisado en la ronda; el revisor no dejó cambios ahí. El veredicto puede ser de otro contenido. SKILL.md paso 6."
  HEAD="$HEAD" LIST1="$L3" LIST2="$L2" emit_notice
  exit 0
fi

# ONE short line (0.63.0, p-c6f0719a23), in additionalContext only. 0.44.7 split it into a short
# Spanish systemMessage and a long English additionalContext, but on a Stop hook additionalContext
# is shown to the human as well (learning 67), so the long text never left their screen. The detail
# the long text carried — the three readings and the evidence the third one costs — is in SKILL.md
# step 6, which the executor carries; the line keeps what the executor must do and that bar.
#
# AUDIENCE LINE FIRST. The executor's transcript is what a goal-adversary reads for its own
# principle-4 dead-handoff check, so this text WILL end up in front of a future adversary. In
# 0.44.0 an adversary read a second-person message of exactly this kind and concluded its role had
# changed. So it says who is addressed and that reading it changes nothing for a reviewer. HONEST
# LIMIT: this is a PROSE GUARD and its effect on a model is NOT measured; the suite checks the
# line is here, not that an adversary reading it behaves differently.
# THE THIRD READING (p-55cec2045a): another writer (a parallel session, the human) can change the
# repository during a round, and the hook cannot tell who wrote — so "otra sesión" is offered, and
# only with evidence that names it; without that the verdict does not count. Since 0.65.0 a path
# whose whole change another session's record proves is not in this list (see OTHERS above).
# The paths, and the unmeasured rounds when there are any, are listed while the whole notice fits in
# 300 characters (emit_notice); the rest are counted.
HEAD="Para quien ejecuta; un revisor que lo lea verifica, no repara.
goalspec: el repo cambió en la revisión (${ROUNDS} ronda(s)). ¿Escribió el revisor, tú u otra sesión (con evidencia que la nombre)? Sin eso su veredicto no vale. SKILL.md paso 6."
HEAD="$HEAD" LIST1="Rutas:	$PATHS" LIST2="$L2" LIST3="$L3" emit_notice
exit 0

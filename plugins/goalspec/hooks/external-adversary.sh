#!/usr/bin/env bash
# external-adversary.sh — optional independence backend for the goal-adversary.
#
# Implements the community "partner reviews, never the host" pattern: instead of a same-model
# subagent (structured self-critique with correlated bias), route the adversarial verification to a
# DIFFERENT model/CLI for true independence. Reads the POINTER PAYLOAD on stdin — where the goal-spec
# and outcome are written, where the work lives, the session transcript path and which decisions to
# look for in it — pipes it with the adversary prompt to the configured external command, and prints
# the same [ADVERSARY-VERDICT: ...] block the subagent backend produces.
#
# Paths, not prose, and this backend is where it matters most: 0.18.0 replaced the narrated payload
# (SKILL.md step 6, which is its single home — this file mirrors it, it does not restate it) after a
# runaway in which the majority of adversary invocations went through THIS path and most confirmed
# breaks landed on prose the same run had just written. Freshly written narration is the least
# verifiable material there is: it IS the claim, so an adversary told to resolve what it cannot
# verify as `break` is handed one by construction, every round, by rule rather than by chance.
#
# The dead-handoff check (principle 4) needs the session log. Whether this partner can reach it is a
# property of the CLI, NOT of "being external": a file-capable partner on the same host (e.g.
# "claude -p --model ...", or codex/gemini with fs access) can read it and must; one without file
# access reports UNVERIFIABLE-BY-THIS-BACKEND. The prompt tells it to CHECK rather than assume.
# (0.4.0 drafted the assumption "external cannot read the log" as fact; a Sonnet partner falsified it
# by reading the log, before release. Do not re-introduce it.) See references/external-adversary-setup.md.
#
# Config (adversary.external_cmd, read per-key from project .claude/goal.config.json, else user-global
# ~/.claude/goal.config.json), e.g.:
#   "codex exec"      (OpenAI Codex CLI)
#   "gemini -p"       (Google Gemini CLI)
#   "claude -p --model claude-sonnet-5"   (a different Claude model as the partner)
#
# Usage:  printf '%s' "$POINTERS_TO_SPEC_OUTCOME_WORK_AND_TRANSCRIPT" | external-adversary.sh
# The external command is passed the full prompt on stdin.
#
# Anti-recursion: if this backend routes to another Claude that itself has goalspec
# installed, GOAL_ADVERSARY_ACTIVE=1 is exported so its Stop gate / any nested /goalspec can detect
# the loop and no-op. A nested invocation (already inside an external adversary) exits immediately.

set -euo pipefail

if [ "${GOAL_ADVERSARY_ACTIVE:-}" = "1" ]; then
  echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]" >&2
  echo "external-adversary: recursion guard tripped (GOAL_ADVERSARY_ACTIVE=1) — refusing to re-enter." >&2
  exit 0
fi
export GOAL_ADVERSARY_ACTIVE=1

# Resolve the external command from env, arg, or config. Default: codex exec.
# Config precedence: project (CWD .claude/goal.config.json) OVERRIDES user-global
# (~/.claude/goal.config.json). The global file exists so a user who has chosen an external backend
# sets external_cmd ONCE and every project inherits it — no per-repo file. GOAL_CONFIG_PATH, if set,
# pins the project layer explicitly. The SKILL reads adversary.backend with the SAME precedence, so
# the gate that decides to call this hook and the command it runs stay in agreement.
PROJECT_CONFIG="${GOAL_CONFIG_PATH:-.claude/goal.config.json}"
GLOBAL_CONFIG="${HOME:-}/.claude/goal.config.json"
# Portable interpreter: python3 (macOS/Linux) then python (Windows / Git Bash). The trailing `|| echo`
# keeps this safe under `set -e` when neither is found (config read then just yields empty -> default).
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
_read_ext_cmd() { "$PY" -c "import json,sys; print((json.load(open(sys.argv[1])).get('adversary',{}) or {}).get('external_cmd','') or '')" "$1" 2>/dev/null || true; }
EXT_CMD="${GOAL_ADVERSARY_CMD:-}"
if [ -z "$EXT_CMD" ] && [ -n "${1:-}" ]; then EXT_CMD="$1"; fi
if [ -z "$EXT_CMD" ] && [ -f "$PROJECT_CONFIG" ]; then EXT_CMD=$(_read_ext_cmd "$PROJECT_CONFIG"); fi
if [ -z "$EXT_CMD" ] && [ -n "${HOME:-}" ] && [ -f "$GLOBAL_CONFIG" ]; then EXT_CMD=$(_read_ext_cmd "$GLOBAL_CONFIG"); fi
[ -z "$EXT_CMD" ] && EXT_CMD="codex exec"

# Verify the external binary exists — else fail-open with a hold + a note (never block the host).
BIN=$(printf '%s' "$EXT_CMD" | awk '{print $1}')
if ! command -v "$BIN" >/dev/null 2>&1; then
  echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
  echo "external-adversary: '$BIN' not found on PATH — no independent check ran; treat 'hold' as UNVERIFIED." >&2
  exit 0
fi

PAYLOAD=$(cat)

# EDITING THE PROMPT BELOW: keep single quotes/apostrophes BALANCED inside this heredoc. It sits in a
# command substitution, and bash 3.2 (the /bin/bash macOS still ships) pairs quotes while scanning for
# the closing paren, so one stray apostrophe in prose makes the whole file a syntax error — a hook
# that dies at parse time, silently, on the platform this is most used on. Caught by `bash -n` in the
# 0.18.0 edit; prefer rewording ("the account the executor typed") over adding a second apostrophe.
#
# SECOND HOME, DELIBERATE: the checkpoint.md paragraph inside this prompt restates the per-section
# authority rule whose single source is references/durable-artifact.md ("Who reads which section").
# The external partner cannot read files on this host, so the rule must travel inline — this is the
# one carrier that cannot be reduced to a pointer. When that section changes, the rule-surface
# enumeration must catch this block (grep terms: checkpoint, coverage-floor, Rounds).
PROMPT=$(cat <<EOF
You are an INDEPENDENT adversarial verifier. You did not do the work. Your job is to try to BREAK
the claimed outcome against this 5-principle constitution — not to approve it:
  1. Grounding — every load-bearing claim must cite verifiable ground-truth; a proxy is not the thing;
     a broken instrument (empty tracking, bad scope, failing harness) invalidates its evidence. This
     applies to the executor own tooling: if the work added or changed a check/marker/gate, an
     emission that no code path, gate, or agent reads is itself a broken instrument — requested-in-a-
     prompt is not consumed-by-anyone; and a consumer satisfiable by non-evidence (its own template
     text, an echoed prompt, a wrapper that resolves but does not run) is no consumer at all.
  2. Falsification — inherited claims must be re-derived, not trusted; numbers that don't reconcile = bad input.
  3. Completeness — done = achieved AND verified, not diagnosed; every surfaced factor needs an owner.
     If the work changed a written rule, every surface carrying that rule (skill text, agent defs,
     hook scripts, references, prompts) must be updated or explicitly exempted — enumerate the
     carriers by grepping the rule key terms; a carrier left stale is incomplete.
  4. Autonomy — two opposite failures, both count: nothing an agent could execute should be handed to
     a human; AND no decision assigned to the human may go unasked. A decision narrated in prose ("two
     decisions are yours", in any language) with no question ever raised is a DEAD HANDOFF — the human
     cannot answer a paragraph. Judge the act, not a phrase list. The payload gives you POINTERS, not
     the account the executor typed: the decisions their Q5 assigned to the human, and where the session log
     is. Anything narrated in it is a claim the executor authored — a pointer, never evidence. TEST YOUR REACH FIRST: if you can read
     files on this host, go verify the ask yourself in the session log (Claude Code: the top-level
     <session-id>.jsonl under ~/.claude/projects/<cwd, every non-alphanumeric mapped to a dash>; read
     the parent file, never a subagents/ child, never newest-mtime; never exclude a file because it
     contains your own input — the parent session records the very invocation that produced your
     stdin, so overlap with your payload identifies the LIVE parent, it does not make the file
     yours; match the AskUserQuestion tool_use + its user tool_result by STRUCTURE, not by
     text-grep; confirm it is this run — the file holds the invocation that launched you — and this
     decision). A claimed ask you can reach and cannot find is a confirmed DEAD HANDOFF. Only if you
     genuinely have no file access, report UNVERIFIABLE-BY-THIS-BACKEND and do NOT count it — do not
     manufacture a violation with an instrument that cannot see; that is principle 1 turned on you.
     Do not assume you cannot reach it: check.
  5. No-harm — don't remove/pause/scale something that works without a validated, reversible replacement.

NEGATIVE CLAIMS — audit the option surface, not just the measurement. This fires on a CLAIM SHAPE, in
any domain: whenever a load-bearing claim says something CANNOT be done, is unavailable, no longer
exists, is not supported, or is impossible, AND the action follows from that impossibility (a removal,
a withdrawal, a stub, a downgrade, a workaround, a we-cannot-so-we-will-not). Here your normal method
inverts on you: re-deriving their measurement CANNOT verify a negative. Reproduce their query exactly
and you confirm the thing is absent in the configuration that was queried — which is not the claim.
The claim is about the option space, and it is unfalsifiable from inside the terrain they measured. So
enumerate that space yourself and name each surface you checked: the settings/config object that
decides the behavior of the thing, the flags and modes it exposes, its documented options (vendor or
product docs, --help, the schema), its administrative surface (console, plan or permission tier,
whoever grants it), and any adjacent instance where the capability demonstrably still works — if a
comparable case has it, the claim is about THIS configuration, not about the world. Two rules make
this bite: an impossibility claim needs a POSITIVE record of what was ruled out (absence of a mention
is not a check performed, and "they looked and found nothing" is prose, not ground truth); and if the
payload never points you at the surfaces that GOVERN the capability, that gap is itself the finding —
count it ungrounded, and count it even when every figure in the outcome re-derives correctly, because
that is exactly the case this check exists for.

FIRST LINE OF YOUR OUTPUT — identify yourself. The executor claims model-independent verification
and the only ground-truth for that claim is your own self-report (a spawn/config parameter proves
nothing; harnesses fall back silently). Emit, quoted from your own context/knowledge of what model
you are — never a guess, and UNKNOWN if you genuinely do not know:

[ADVERSARY-MODEL: <model name> / <exact model id, or UNKNOWN>]

Attack every load-bearing figure. Default to skeptical: if you cannot verify a claim, count it as a
violation, not a pass — the one exception is the dead-handoff check in principle 4, and ONLY if you
truly cannot reach the session log (an unreachable instrument is not a finding; an unchecked one is
just laziness).

ACCOUNT FOR EVERY ATTACK THE PAYLOAD ENUMERATED. If it lists hypotheses, angles, or attacks it wants
tried, every one of them comes back in your bullets under one of three dispositions: pursued and
refuted (name the ground truth that held), pursued and confirmed (it is a finding), or out of reach
(say why). A silent drop is worse than the attack never having been listed: the executor reads your
verdict as covering that angle and now believes it was tried. And that list is a FLOOR, never a
ceiling — it is written by the party whose frame you exist to distrust, so the attack it does NOT
contain is the one most likely to matter, and an invitation to attack in one direction is not a
boundary on where you may look.

Then output EXACTLY ONE line, and nothing after it:

[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]

Use 'break' if any confirmed count is >=1, else 'hold'. Above that line, list each confirmed
violation with the ground-truth that proves it.

=== POINTERS TO WHAT IS UNDER REVIEW (paths, not a narrated account — go read them) ===
Anything below that reads as narration rather than a location is text the executor typed: treat it
as a claim to check against the artifact, never as the outcome itself, and never as attack surface
in its own right. If a pointer names a file that does not exist, THAT is the finding.

If the outcome pointer resolves to a .goalspec/checkpoint*.md (the checkpoint is per-session:
checkpoint-<session>.md, or the legacy checkpoint.md): that file is run state, not a
deliverable, and the per-section authority that follows is DECLARED in the plugin reference
references/durable-artifact.md (section: Who reads which section) — you cannot read that file from
where you run, so it is restated here as a citation of that declaration, not as a rule this prompt
owns. The live goal-spec and the coverage-floor table are the authoritative current state: verify
them exactly as you would any other load-bearing figure in the outcome — a row claiming done for an
entity you can show is not done, or two rows that contradict each other, is a normal, reportable
finding. Rounds is append-only history and Next is a pointer, neither with authority over current
state: a stale or unreconciled sentence there is not a break. Beyond those sections, use the file
to locate where the real outcome lives (files, commits, docs) and verify that with the usual rigor.
Exception: if the payload states explicitly that the goal-spec lives nowhere else and points at the
checkpoint.md live goal-spec section as the goal-spec itself (the case where the spec only existed
in conversation and was durably copied there), that section IS the object to verify, exactly like
any other goal-spec.

$PAYLOAD
EOF
)

# Partners burn findings on the limits of their own sandbox, systematically (two consecutive
# phases observed it): an unwritable TMPDIR fails their suite runs, a cwd outside the repo hides
# the work — and both come back as ungrounded/UNVERIFIED counts, a broken instrument fabricating
# findings (principle 1 turned on this script). So: when the invocation cwd is inside a git repo,
# run the partner from that repo root — which relocates a wrong-subdir invocation and nothing
# more. From OUTSIDE any repo (the cwd class of the recorded Fase 1 incident: codex refusing a
# scratchpad as untrusted) there is no root to resolve, and that branch gets a stderr warning,
# not a fix. And hand the partner a TMPDIR THIS process can write to — the host-side half only:
# the recorded v0.19.1 contra-dato (repo root, TMPDIR=/tmp exported, codex still denied the
# write: errno=Operation not permitted) was the partner OWN sandbox refusing writes this process
# could make — a mode this fix does not and cannot remove. Weigh both limits when reading a
# partner ungrounded count.
# Deliberately NOT paired with any /tmp cleanup: this script writes nothing to /tmp, and deleting
# files it does not own is a remove-verb on artifacts that are not its own.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -n "$REPO_ROOT" ]; then
  cd "$REPO_ROOT"
else
  echo "external-adversary: invocation cwd is not inside any git repo — no repo root to relocate to; partner CLIs (e.g. codex) may refuse this directory as untrusted. Invoke from the repo under review." >&2
fi
if [ ! -w "${TMPDIR:-/nonexistent}" ]; then TMPDIR=$(mktemp -d 2>/dev/null || echo /tmp); export TMPDIR; fi

# Pipe the prompt to the external CLI on stdin. Some CLIs accept a prompt on stdin (codex exec,
# claude -p); others want it as an argument (gemini -p) — wrap those in a small adapter.
#
# Instrument-validity rail: `command -v` only proves a WRAPPER is on PATH, not that the CLI runs. A
# broken install (e.g. codex whose vendored binary is missing) exits non-zero with a stack trace and
# NO verdict — which would hand the caller silence and let it read as "no objection". So capture the
# run and require a FILLED verdict; anything else degrades to an explicit UNVERIFIED hold.
#
# The pattern demands literal counts, NOT the grammar template. This matters: the prompt above contains
# the template `[ADVERSARY-VERDICT: break|hold ungrounded=<n> ...]`, so any CLI that echoes its stdin
# (a debug/verbose wrapper, or a plain `cat`) and exits 0 would satisfy a naive
# `grep '\[ADVERSARY-VERDICT:'` and get its echoed PLACEHOLDER printed back as a real verdict. Requiring
# `(break|hold)` followed by numeric counts rejects both `break|hold` and `<n>`. Take the LAST match, so
# a partner that quotes the template before answering still resolves to its real verdict.
VERDICT_RE='\[ADVERSARY-VERDICT:[[:space:]]*(break|hold)[[:space:]]+ungrounded=[0-9]+[[:space:]]+unfalsified=[0-9]+[[:space:]]+incomplete=[0-9]+[[:space:]]+autonomy-violations=[0-9]+[[:space:]]+unsafe=[0-9]+[[:space:]]*\]'

# NB: `set -euo pipefail` is active. A no-match `grep` exits 1, which under pipefail would kill this
# script on exactly the path that exists to handle a bad partner — so both the run and the match stay
# inside `set +e` and the match is guarded with `|| true`.
set +e
OUT=$(printf '%s' "$PROMPT" | $EXT_CMD 2>&1)
RC=$?
VERDICT=$(printf '%s' "$OUT" | grep -Eo "$VERDICT_RE" | tail -1 || true)
# The model self-report is requested by the prompt, so requesting it is not enforcing it (two
# different-model reviews confirmed this gap by reading this very file). Extract it mechanically;
# reject the prompt's own literal template (`<model name>`) the same way VERDICT_RE rejects `<n>`.
# Deliberately EXEMPT from the greedy-to-last-"]" fix 0.19.1 applied to gate-goal-close.sh, for two
# reasons, both checked rather than assumed: (1) MODEL_LINE's only consumer is the emptiness test
# below -- it is never printed, and stdout carries the partner's raw $OUT, so a truncated capture
# cannot reach any reader; (2) the `<>` exclusion is what rejects the prompt's own `<model name>`
# template, and going greedy to end-of-line would give that up. Truncation here costs nothing that
# is read; there it cost a real id its has_real_id check.
MODEL_LINE=$(printf '%s' "$OUT" | grep -Eo '\[ADVERSARY-MODEL:[^]<>]+\]' | tail -1 || true)
set -e

if [ $RC -ne 0 ] || [ -z "$VERDICT" ]; then
  echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
  {
    echo "external-adversary: '$EXT_CMD' exited $RC without a filled [ADVERSARY-VERDICT:] line —"
    echo "no independent check ran. Treat this 'hold' as UNVERIFIED, not as a pass. Partner output:"
    printf '%s\n' "$OUT" | head -20
  } >&2
  exit 0
fi

# Verdict is valid either way (fail-open); but an absent self-report degrades the INDEPENDENCE
# claim, and silence here is how a degraded pass gets read as an independent one.
if [ -z "$MODEL_LINE" ]; then
  echo "external-adversary: partner returned no [ADVERSARY-MODEL:] self-report — independence UNVERIFIED; report model=same in the completion-review, not model=different." >&2
elif printf '%s\n' "$OUT" | grep -E '\[ADVERSARY-MODEL:' | tail -1 \
     | grep -qiE '/[[:space:]]*(UNKNOWN|N/A)?[[:space:]]*\]?[[:space:]]*$'; then
  # Tested against the RAW last line, not $MODEL_LINE: that capture stops at the first "]", so a
  # bracketed model name ("[ADVERSARY-MODEL: Claude [x] / UNKNOWN]") truncates before the id and
  # this branch would stay silent on a form gate-goal-close.sh explicitly rules on (its case 33).
  # Hook and consumer must not diverge on a shape the consumer already tests.
  # KNOWN GAP, on purpose: decorated lines (bold/code-span wrapping, or text after the "]") still
  # go silent here while the gate still rejects them. Closing that cross-product means the smarter
  # matcher this project already watched fail 5 rounds running; the lever is the same one the gate
  # uses — demand the line undecorated — not a cleverer regex.
  # The partner named itself but could not resolve its own exact id. Observed 6/6 rounds with the
  # `codex` CLI (2026-08-09) — and it is the honest answer, not a partner defect: a model generally
  # cannot read its own snapshot id from inside its context. Before this branch existed the case was
  # SILENT: only a wholly ABSENT [ADVERSARY-MODEL:] line said anything, so the executor met the
  # commonest real case with no guidance and either overclaimed independence or dropped it.
  #
  # Deliberately NOT a smarter id resolver, and deliberately NOT a third grammar: matching model ids
  # out of agent-authored text is a proxy with no floor (that design broke 5 rounds straight; the
  # design was ungameable, not the wording), and gate-goal-close.sh already RULES on this exact case
  # — an UNKNOWN self-report cannot back `model=different`, and the honest degrade is `model=same`.
  # A hook that told you to write anything else would contradict its own consumer (caught in review,
  # 2026-08-09 r4). So this branch adds no new claim; it only ends the silence and points at the
  # existing rule, plus the one fact this script KNOWS rather than infers: what it executed.
  _EXT_BIN=$(command -v "${EXT_CMD%% *}" 2>/dev/null || echo "${EXT_CMD%% *} (not on PATH)")
  {
    echo "external-adversary: partner self-reported a name but NOT an exact id (\"$MODEL_LINE\")."
    echo "  Per gate-goal-close.sh, an UNKNOWN id cannot back model=different — write model=same in"
    echo "  the completion-review. That is the honest degrade, not a defect, and not a claim that"
    echo "  the same model reviewed you."
    echo "  What this host actually executed:  cmd='$EXT_CMD'  bin='$_EXT_BIN'"
    echo "  That is a resolved first argument, NOT proof of vendor: a wrapper, an adapter script, or"
    echo "  'env'/'bash' as the leading word can front any model. If the difference is real and you"
    echo "  want it on the record, say so in PROSE next to the marker — never by upgrading the field."
  } >&2
fi

# Bare-verdict floor: a verdict with NO evidence of work above it (no bullets, no ground-truth —
# observed in the wild: a real partner's last round returned a naked hold after two rounds of showing
# all its work) is not a pass. This is a FLOOR, not proof of diligence — filler lines can game it
# (you cannot gate your way out of specification gaming; the lever is the executor treating
# UNVERIFIED as UNVERIFIED) — but it catches the lazy-partner case that actually happened.
#
# Count ONLY between the LAST real [ADVERSARY-MODEL:] line and the final verdict — the answer
# block, where the prompt places the violation list. Counting over ALL of $OUT (the original
# implementation) made this floor blind: $OUT is the partner CLI's whole run transcript (banners,
# reasoning traces, its file reads echoing the fixture and this very prompt), so nearly any
# non-trivial run counted >0 and a truly naked hold sailed through unwarned — observed live
# 2026-07-26, where the echoed text also read as "reasoning" to a human until counted. With no
# self-report line to anchor on, fall back to the 12 lines above the verdict (a heuristic window;
# the missing-self-report warning above already fired on that path).
VLINE=$(printf '%s\n' "$OUT" | grep -nE "$VERDICT_RE" | tail -1 | cut -d: -f1 || true)
MLINE=$(printf '%s\n' "$OUT" | grep -nE '\[ADVERSARY-MODEL:[^]<>]+\]' | tail -1 | cut -d: -f1 || true)
if [ -z "$VLINE" ] || [ "$VLINE" -le 1 ]; then
  EVIDENCE_LINES=0
else
  if [ -n "$MLINE" ] && [ "$MLINE" -lt "$VLINE" ]; then WSTART=$((MLINE + 1)); else WSTART=$((VLINE > 12 ? VLINE - 12 : 1)); fi
  EVIDENCE_LINES=$(printf '%s\n' "$OUT" | sed -n "${WSTART},$((VLINE - 1))p" | grep -vE '^[[:space:]]*$|\[ADVERSARY-VERDICT:|\[ADVERSARY-MODEL:' | grep -c . || true)
fi
if [ "$EVIDENCE_LINES" -eq 0 ]; then
  echo "external-adversary: partner returned a bare verdict with no evidence of work (no bullets/ground-truth above it) — treat it as UNVERIFIED, not a pass; re-run or route to the other backend." >&2
fi

# This line only runs after $VERDICT was confirmed non-empty and well-formed above (line ~150) — a
# structural guarantee, not a guess, that $EXT_CMD actually ran and produced matching output (NOT a
# guarantee that its content is genuine adversarial reasoning rather than an echo — that judgment
# stays the executor's, same as every other self-report this method accepts). That is why this
# reminder lives HERE rather than in a separate hook trying to detect "was this Bash call an
# invocation of this script" from the command string alone: that detection was tried and reviewed
# by an external adversary, which broke it twice (a fabricated subagent_type substring slipped
# through once; then, after tightening, real invocation forms like a bare `./external-adversary.sh`
# were missed while `cat`/`nl` of THIS SOURCE FILE — which contains literal fallback verdict text
# above — still risked a false positive that could induce quoting non-evidence into the transcript
# the Stop gate reads). Emitting the reminder from inside the one code path that only executes on
# genuine success removes the guessing game entirely.
# Deliberately does NOT assert this verdict is authentic adversarial work -- exit 0 plus a
# regex-matching format only proves $EXT_CMD produced well-formed OUTPUT, never that it actually did
# adversarial reasoning (a misconfigured external_cmd pointing at something that merely echoes a
# verdict-shaped string would satisfy this exact same check). That is the same self-report
# limitation this method already documents everywhere else (the bare-verdict floor above is a
# floor, not proof of diligence) -- caught by adversary review when this line still said "a real
# verdict." Judging genuineness stays the executor's job, same as for every other self-report.
echo "external-adversary: a verdict-shaped block was just produced above -- whether it reflects genuine adversarial work is still yours to judge (see the bare-verdict-floor note above). If you judge it genuine, quote the [ADVERSARY-MODEL: ...] and [ADVERSARY-VERDICT: ...] lines VERBATIM in your very next assistant turn -- each on its OWN line, in plain text, nothing before it and nothing after the closing bracket on that same line: no bold or code-span wrapping, no trailing citation. The gate matches the marker only when its line ends at that bracket, so decorating it while quoting degrades a genuine model=different to model=same, silently. The Stop gate cannot see this script's stdout directly, only text you personally author — this is far easier to forget once you move on to other work than it is right now." >&2

printf '%s\n' "$OUT"

#!/usr/bin/env bash
# external-adversary.sh — optional independence backend for the goal-adversary.
#
# Implements the community "partner reviews, never the host" pattern: alongside the subagent (a
# different tier of the same family, which keeps some correlated bias), add the adversarial
# verification of a DIFFERENT vendor's model/CLI. Since 0.47.0 this backend is additive: the subagent
# runs on every goalspec run, and this one joins it on terminal actions and after two subagent breaks. Reads the POINTER PAYLOAD on stdin — where the goal-spec
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
# The same token also marks a suite the partner own sandbox could not run (0.46.4): see the
# A RED YOU RUN paragraph of the prompt and SKILL.md step 6 for what the executor does with it.
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

# Advisory only — never add a sandbox flag here. -s read-only was tried against a real codex partner
# and broke it: legitimate scratch writes failed and came back disguised as `ungrounded` findings (see
# references/external-adversary-setup.md, "Your partner keeps its write sandbox"). external_cmd belongs
# to the operator; this hook cannot impose a mode portably. What actually catches an overreaching
# partner is the before/after content fingerprint below, not a mode picked here.
case "$BIN" in
  codex)
    case "$EXT_CMD" in
      *-s\ *|*--sandbox*|*sandbox_*) ;;
      *) echo "external-adversary: '$EXT_CMD' sets no sandbox mode — codex's own ~/.codex/config.toml trust level for this cwd decides, and a trusted repo gets workspace-write here. Repo writes are DETECTED after the run (content fingerprint), not prevented. See references/external-adversary-setup.md." >&2 ;;
    esac
    ;;
esac

PAYLOAD=$(cat)

# EDITING THE PROMPT BELOW: keep single quotes/apostrophes BALANCED inside this heredoc. It sits in a
# command substitution, and bash 3.2 (the /bin/bash macOS still ships) pairs quotes while scanning for
# the closing paren, so one stray apostrophe in prose makes the whole file a syntax error — a hook
# that dies at parse time, silently, on the platform this is most used on. Caught by `bash -n` in the
# 0.18.0 edit; prefer rewording ("the account the executor typed") over adding a second apostrophe.
#
# SECOND HOME, DELIBERATE: the checkpoint.md paragraph inside this prompt restates the per-section
# authority rule whose single source is references/durable-artifact.md ("Who reads which section").
# The rule must travel INLINE because the partner cannot reliably RESOLVE that reference's path from
# where it runs (its cwd is the project, not the plugin, and an installed cache holds many plugin
# versions) — not because it cannot read files, which is false and which the header of this very file
# warns at length against re-introducing. This comment asserted the false version until 0.44.0, and
# an external partner falsified it the same way the 0.4.0 draft was falsified: by reading this repo
# and the session log from inside the invocation that is supposedly unable to. Reach is a property of
# the CLI you configured, never of "being external". When that section changes, the rule-surface
# enumeration must catch this block (grep terms: checkpoint, coverage-floor, Rounds, claim surface).
# The CLAIM SURFACE paragraph above the checkpoint one is a second such restatement: its single
# source is skills/goalspec/SKILL.md step 6 (first bullet), restated here for the same reason.
# HAZARD when editing the prose below: this is an UNQUOTED heredoc inside $( ), and bash 3.2 (the
# system bash on macOS) parses the command substitution by scanning for the matching `)` — an ODD
# number of apostrophes in the body makes it swallow the rest of the file. `bash -n` reports it as
# "unexpected EOF" hundreds of lines later, and the only thing that catches it in practice is
# test/external-adversary-branches.py (13 assertions failed on one added "the human's" in 0.39.0).
# Write "theirs" instead of "the human's", or keep apostrophes paired. Run `bash -n` after editing.
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
     ONE narrow carve-out: a self-reported tally of the run OWN process events (how many modals were
     raised, how many rounds ran, how many forks the human settled) goes stale BY CONSTRUCTION — the run
     keeps producing those events, so any such count in run state is wrong one event later and its
     correction is wrong one event after that. Report it as a NOTE naming the ground truth (the session
     log for asks, the VCS diff for touched files) and do NOT count it. Do not widen this: it covers how
     many times the method did something, never what the outcome is or what the human was told. A file
     count disclosed in a ratify modal, an entity count in the coverage floor, a measured figure, a
     version — all still break. Ask what the number is ABOUT: the work, or the bookkeeping. If a wrong
     tally would have changed what the human authorized, it is about the work.
  3. Completeness — done = achieved AND verified, not diagnosed; every surfaced factor needs an owner.
     If the work changed a written rule, every surface carrying that rule (skill text, agent defs,
     hook scripts, references, prompts) must be updated or explicitly exempted — enumerate the
     carriers by grepping the rule key terms; a carrier left stale is incomplete.
  4. Autonomy — two opposite failures, both count: nothing an agent could execute should be handed to
     a human; AND no decision assigned to the human may go unasked. A decision narrated in prose ("two
     decisions are yours", in any language) with no question ever raised is a DEAD HANDOFF — the human
     cannot answer a paragraph. Judge the act, not a phrase list. This holds on EVERY ending, not just
     a completion-review: a waiver or a stop that emits no marker at all is still the end of the run,
     and a decision dies in prose identically in each. Work deferred to "another session" is the same
     violation wearing a schedule unless they named the blocker — a permission that is theirs to give, a
     hard limit (context, usage ceiling), or an external dependency not answering. The payload gives you POINTERS, not
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

YOU VERIFY, YOU DO NOT REPAIR. Your reach is reading and running what already exists: read any file,
run the suites and commands the work already ships, inspect the VCS history. Do NOT create, edit,
delete or revert any file in the repository under review, do not stage or commit, and do not run a
command whose purpose is to change the work. Something you believe is broken is a FINDING you report,
never a task you take on — repairing it destroys the very thing you were sent to measure, because the
state you would then verify is one you created, and principle 1 turns on you. Scratch space is the one
exception and it lives OUTSIDE the repository: write temporary files under TMPDIR, which this host has
already pointed at a directory you can write. This is MEASURED, not trusted: the hook that invoked you
fingerprints the repository content before and after your run, names every path whose bytes changed,
and degrades a clean verdict to UNVERIFIED when it finds one — a repair does not quietly become a
pass, it voids your own verdict.

A RED YOU RUN IS NEVER "UNRELATED" WITHOUT A CAUSE. Your sandbox very likely denies writes outside
the repository and TMPDIR — including under the home directory, where many suites keep state
(observed in the field: a suite that creates a state file under ~/.claude/projects failed 12 of 23
cases in three consecutive rounds, and the partner filed it each time as "one unrelated failure").
For EVERY failing test or suite you run, whatever it covers: name it, quote its first error line
with the path and errno, and classify it. SANDBOX/ENVIRONMENT (the path is outside the repo and
TMPDIR, or the errno is a permission denial your sandbox produces) means that suite is
UNVERIFIABLE-BY-THIS-BACKEND: say so, do not count it as passing, and do not count it as a finding
either. It is a MINOR note, never BLOCKING, and the skeptical default below does not turn it into
one: the executor adjudicates it against its own host run (host green there is an environment
divergence it must name; host red is a real finding). Measured 2026-10-09: of 17 rounds that broke
on a tree another verifier had held and found no defect in the work, 6 counted a red only their own
sandbox produced (mkdtemp under .git, a missing module). REAL means a genuine failure:
report it, and say whether the work under review caused it or it predates the work. Never write "unrelated",
"environmental" or "not counted" for a red without the path and the class; an unexplained red is an
instrument you did not read. This half is NOT measured by the hook that invoked you.

THE SAME RULE HOLDS BEYOND THE REPOSITORY, AND THERE IT IS NOT MEASURED. Every system you can reach
is under it: a remote host over SSH, a server, a database, a cloud account, an API, a deploy, a
queue. Observe with commands that only read (status, log, show, diff, fetch into scratch, a
SELECT, an HTTP GET); never run one that changes state there. A git pull, checkout, reset, merge,
push or commit on a remote host, a restart, a deploy or rollback, a migration, a write query, a
POST that mutates: each is a repair of the system you were sent to observe, however harmless it
looks. Observed in the field: an adversary sent to verify a production deploy ran git pull on the
production host over SSH as a side effect of checking it. If the only way to verify a claim is a
command that changes state, do NOT run it: report the claim as unverifiable by this backend, name
the read-only evidence that would settle it, and count it ungrounded. This half is NOT measured
by the hook that invoked you: its fingerprint sees the local repository only, so a remote change
leaves no trace in it, and your restraint here is the only rail there is.

THE TERMINAL ACTION THIS ROUND GATES HAS NOT HAPPENED YET, BY DESIGN. When the payload says this
round gates a push, merge, deploy, publish or send, that action not having happened is NOT
incomplete, and neither is whatever can only exist after it (CI on the pushed commit, a merged PR,
the published state): your verdict is what authorizes it. Do not count it under any category, even
when a success criterion names it; attack instead everything that must be true BEFORE it fires. It
counts only when a statement claims the action already happened (that statement is false), or when
the payload does not say the round gates it. Measured 2026-10-09: 9 of those 17 rounds counted the
gated push or its CI as incomplete.

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

Grammar, inside the brackets too, not just around them: exactly one "/" separating the two fields,
and the id field is ONE whitespace-free token — the bare id (e.g. "claude-opus-5" or
"claude-opus-5[1m]"), nothing else. If you want to disclose an independence caveat (e.g. same tier
as the executor, or an uncertain id), put that in ordinary prose on the line AFTER the marker —
never inside the brackets, never appended to the id field. A real incident: an adversary wrote a
model line as name-plus-explanatory-clause with no "/" at all, prose where the id belonged — true
content, wrong place — and the executor gate could not find a valid id in it, so a genuine
model-different verification silently degraded to model=same. Emit the marker bare; say anything
else on the next line.

Attack every load-bearing figure. Default to skeptical: if you cannot verify a claim, count it as a
violation, not a pass — with two exceptions: the dead-handoff check in principle 4, ONLY if you truly
cannot reach the session log, and a suite your own sandbox could not run (above). An unreachable
instrument is not a finding; an unchecked one is just laziness.

ACCOUNT FOR EVERY ATTACK THE PAYLOAD ENUMERATED. If it lists hypotheses, angles, or attacks it wants
tried, every one of them comes back in your bullets under one of three dispositions: pursued and
refuted (name the ground truth that held), pursued and confirmed (it is a finding), or out of reach
(say why). A silent drop is worse than the attack never having been listed: the executor reads your
verdict as covering that angle and now believes it was tried. And that list is a FLOOR, never a
ceiling — it is written by the party whose frame you exist to distrust, so the attack it does NOT
contain is the one most likely to matter, and an invitation to attack in one direction is not a
boundary on where you may look.

PROBE, DO NOT ONLY READ. For every rule, check, gate, parser or validator the outcome adds or
changes, build at least three inputs aimed at breaking it within the threat model the goal-spec
declares, and RUN them, read-only, in a temporary directory. Report each input and what happened.
Measured 2026-10-07: where a reading verifier and a probing one reviewed the same tree and
disagreed, the reading one held 9 times out of 10, mostly over holes the probing one found by
running crafted inputs.

SEVERITY: COUNT ONLY BLOCKING FINDINGS; A MINOR ONE IS A NOTE. Measured 2026-10-07 over 65 break
rounds: one in five mixed a blocking finding with minor ones, and fixing the minor ones grew the
next delta; in 6 the executor called wording 8 findings that were blocking, some of them false. So you classify every confirmed
finding, by this rubric, and the executor may not reclassify it.
BLOCKING (counted): a success criterion of the goal-spec is not met, or a claim the outcome rests
on is false or unverified; harm, an unsafe action, or a hole WITHIN the threat model the work
declares; a statement a reader will act on is FALSE (check it against the code or the data before
you call it wording); an autonomy violation.
MINOR (a bullet that starts with MINOR, not counted): wording that is ambiguous but not false
against ground truth; an edge case OUTSIDE the declared threat model, such as a crafted evasion of
a rail built to catch an accidental omission; a pre-existing defect outside the delta that no
success criterion rests on (one that makes a criterion fail is BLOCKING); style or naming.
If the goal-spec declares no threat model, nothing is outside it and a hole counts. THE THREAT
MODEL IS FIXED WHEN THE SPEC IS WRITTEN AND ONLY GROWS: test the declared line against what the user
actually asked, and a line narrower than that ask, or one written or narrowed after a finding, is
itself a BLOCKING finding. When you cannot
tell false from ambiguous, it is BLOCKING. A MINOR note asks for nothing: the executor fixes it on
the spot only if the fix changes no behavior, or leaves it; it opens no round and no pending item.

Then output EXACTLY ONE line, and nothing after it:

[ADVERSARY-VERDICT: break|hold ungrounded=<n> unfalsified=<n> incomplete=<n> autonomy-violations=<n> unsafe=<n>]

Use 'break' if any confirmed BLOCKING count is >=1, else 'hold'. Above that line, list each
confirmed violation with the ground-truth that proves it, and each MINOR note on its own bullet.

=== POINTERS TO WHAT IS UNDER REVIEW (paths, not a narrated account — go read them) ===
Anything below that reads as narration rather than a location is text the executor typed: treat it
as a claim to check against the artifact, never as the outcome itself, and never as attack surface
in its own right. If a pointer names a file that does not exist, THAT is the finding.

THE PAYLOAD MAY DECLARE A CLAIM SURFACE, and it bounds what you may COUNT, never what you may
read. The success criteria of the outcome are checked against a specific set of artifacts, and the
payload names them as paths. Findings on that surface count normally. A defect you find OFF it --
in the executor checkpoint sentences, its session log, its run narrative, or a probe it built for
its own reassurance that no claim in the outcome rests on -- you report as a bullet and do NOT
count, exactly as you already do for a stale process tally. Why this exists: observed repeatedly in
one deployment of this method (2026-09-10), corrective rounds converged onto freshly written prose
and broke on it while the deliverable went untouched for rounds. A false sentence in an artifact
someone reads is ON the surface however recently it was written; that is guard 2, and nothing here
licenses calling a document line narrative. This is not a lighter bar and not a carve-out you
may widen. Two rules keep it honest. (1) An artifact is ON the surface the moment a load-bearing
claim rests on it, whoever wrote it and whenever it appeared: an instrument added mid-run is on the
surface as soon as the claim depends on what that instrument measured, and an instrument that does
not cover what it was said to cover is a real break, not a note. (2) Text a reader will act on is a
claim about the world and breaks wherever it lives, prose or not -- a false assertion in a published
doc, a figure disclosed to a human to obtain authorization, a coverage-floor row. Test it the way
you test a tally: what is it about -- the work, or the bookkeeping of the method itself? If the
payload names no claim surface, do NOT infer one: attack the outcome exactly as you otherwise
would, and say in a bullet that the payload declared none.

THE ACCOUNT OF THE RUN BY THE EXECUTOR IS A POINTER, NOT THE WORK — EVEN WHEN THE PAYLOAD NAMES IT. A
checkpoint section that narrates the run (Outcome, a list of what was done, Delta notes, Rounds,
Next: any section other than the live goal-spec and the coverage-floor table) and the sentences of
the payload itself are the account of the executor. Check each line against the artifact it describes. Where they
disagree and the ARTIFACT is right (a stale commit or HEAD label, a figure the deliverable states
correctly, "no decision is pending" made false by a later question), that is a MINOR note about
the record: report it, do not count it. It is BLOCKING when the artifact itself is wrong, when the
line is text a human was shown to obtain a decision (rule 2 above), or when the line claims an
action or mutation happened that did not (pushed, merged, deployed, applied, executed): a false
action claim counts wherever it lives, and the gated-action rule below says the same. The live goal-spec and the coverage-floor table are not an account: a criterion
there is attacked as written. Measured 2026-10-09: 4 of those 17 rounds counted a line of the
account whose artifact was right.

If the outcome pointer resolves to a .goalspec/checkpoint*.md (the checkpoint is per-session:
checkpoint-<session>.md, or the legacy checkpoint.md): that file is run state, not a
deliverable, and the per-section authority that follows is DECLARED in the plugin reference
references/durable-artifact.md (section: Who reads which section) — restated here because you cannot
reliably RESOLVE that path from where you run (your cwd is the project, not the plugin, and an
installed cache holds many plugin versions), so this is a citation of that declaration, not a rule
this prompt owns. If you CAN locate the file, read it: it wins where it and this paragraph differ. The live goal-spec and the coverage-floor table are the authoritative current state: verify
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
# A third class, 2026-09-30 (3 of 3 rounds, codex exec with no sandbox flag, workspace-write by
# trust): the partner sandbox denies writes under HOME too (probe: codex sandbox -P :workspace --
# mkdir -p ~/.claude/projects/x gives "Operation not permitted"; repo and TMPDIR writes pass). A
# suite that keeps state there went red and the partner called it "unrelated" every round.
# Deliberately NOT fixed by exporting HOME=<scratch>: external_cmd is the operator, so this script
# cannot know where the CLI keeps its auth and config (codex: ~/.codex), and a redirected HOME
# changes the world the repo suite measures, and hides the real ~/.claude/projects from the
# dead-handoff check. The prompt instead makes the partner classify every red it runs.
# Deliberately NOT paired with any /tmp cleanup: this script writes nothing to /tmp, and deleting
# files it does not own is a remove-verb on artifacts that are not its own.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -n "$REPO_ROOT" ]; then
  cd "$REPO_ROOT"
else
  echo "external-adversary: invocation cwd is not inside any git repo — no repo root to relocate to; partner CLIs (e.g. codex) may refuse this directory as untrusted. Invoke from the repo under review." >&2
fi
if [ ! -w "${TMPDIR:-/nonexistent}" ]; then TMPDIR=$(mktemp -d 2>/dev/null || echo /tmp); export TMPDIR; fi

# READ-ONLY RAIL (measuring half; the rule itself is a paragraph in the prompt above).
# A partner that REPAIRS what it was sent to measure then verifies a state it created — principle 1
# turned on the adversary. Observed in the field: partners run with a write-capable sandbox (they
# need it: in the ONE configuration this project measured, a read-only sandbox failed their suite runs
# and fabricated ungrounded counts, which is why the recorded fix was to widen the sandbox. Read that
# as a measurement, not as proof that no restrictive sandbox can work — the option surface was never
# exhausted, and an external partner broke that overreach in review) and some of them take the
# initiative to fix what they find. The rule alone would be an emission with no consumer — exactly
# the instrument-validity defect this prompt warns about — so it is measured here.
#
# CONTENT, not `git status`. The tree under review is almost always ALREADY dirty (the uncommitted
# work being verified). A partner that appends one line to an already-modified file leaves the
# byte-identical " M path" porcelain line before and after, so a status-only fingerprint is blind to
# the commonest case. Hash the blobs instead.
# KNOWN GAPS, stated rather than discovered in review: (1) `--exclude-standard` hides gitignored
# paths, so a write into an ignored directory is invisible — `.goalspec/` is the one that matters
# here (it is run state, not a deliverable) and is therefore hashed explicitly; other ignored paths
# are out of reach. (2) A write outside the repo root is not covered, by design: TMPDIR is where the
# partner is told to put scratch. (3) A partner that changes a file and changes it back is a no-op
# to this check, and that is the correct answer — nothing was left modified. (4) Isolation (below)
# only protects reads the partner makes RELATIVE to its cwd — a payload pointer that names an
# ABSOLUTE path under the live repo root still resolves there, bypassing isolation for that one
# read; narrows to the "paths, not prose, relative-in-repo" calling convention holding, not removed.
_adv_fingerprint() {
  # $1 = repo root. Prints one line per fact; the caller diffs two of these captures.
  [ -z "${1:-}" ] && return 0
  printf 'HEAD %s\n' "$(git -C "$1" rev-parse HEAD 2>/dev/null || echo unborn)"
  # The staged set as CONTENT: a partner that `git add`s its edit moves the path out of `ls-files -m`,
  # so the unstaged scan below would stop seeing it.
  printf 'staged %s\n' "$(git -C "$1" diff --cached 2>/dev/null | git hash-object --stdin 2>/dev/null || echo none)"
  # Modified, deleted and untracked-but-not-ignored paths, content-hashed.
  git -C "$1" ls-files -m -o -d --exclude-standard -z 2>/dev/null \
    | while IFS= read -r -d '' p; do
        if [ -f "$1/$p" ]; then
          printf '%s %s\n' "$(git -C "$1" hash-object -- "$1/$p" 2>/dev/null || echo unreadable)" "$p"
        else
          printf 'absent %s\n' "$p"
        fi
      done
  # Run state: gitignored (see .gitignore), so the scan above never lists it.
  for _f in "$1"/.goalspec/*; do
    [ -f "$_f" ] || continue
    printf '%s %s\n' "$(git -C "$1" hash-object -- "$_f" 2>/dev/null || echo unreadable)" "${_f#"$1"/}"
  done
}
# --- Isolate the reviewed state in a private linked worktree (best-effort, fail-open) ------------
# The rail above measures MUTATION by diffing this fingerprint before/after — but a fingerprint of
# the LIVE, shared REPO_ROOT cannot tell "the partner wrote this" from "anything else sharing this
# working tree wrote this during the same window": another local session checkpointing (a plain
# `git commit`), a background hook, a human's own concurrent edit. Observed live 2026-09-17/18: a
# sibling session's routine checkpoint commit landed on a shared repo mid-round and was reported as
# "the partner MODIFIED the repository" — a false accusation of the adversary for work a different
# local process did. Materializing the exact reviewed state (staged + unstaged + untracked + the
# gitignored .goalspec/ run state — the same set _adv_fingerprint already enumerates) into a
# PRIVATE linked worktree removes the shared-tree precondition entirely: nothing else on this host
# writes to that path, so a mutation found there is the partner's, full stop — no more heuristic
# needed for that half.
# Placed under the repo's own git-common-dir (never system /tmp): (1) `.git/` is never scanned by
# `git status`/`ls-files`, so the scratch worktree cannot contaminate what it exists to protect, on
# ANY repo, not only one with `.goalspec/` gitignored; (2) it is a physical descendant of REPO_ROOT,
# which gives an external CLI's directory-trust resolution (see the codex sandbox advisory above)
# the best available chance of inheriting the operator's own trust decision for this project — a
# bet, not a verified guarantee, since no CLI's trust algorithm is queried here.
# Fail-open, matching every other rail in this file: an unborn HEAD (no commits yet), a git too old
# for `worktree add`, or any failure along the way falls back to reviewing REPO_ROOT directly —
# today's un-isolated behavior, with the landed-commit note below as the remaining defense. Wrapped
# in `set +e`/`set -e` rather than relied on via if-condition scoping alone, matching this file's
# own convention elsewhere (around the partner invocation below) rather than trusting that nuance
# identically across bash versions.
_adv_materialize_reviewed_state() {
  # $1 = live repo root (source), $2 = isolated worktree (already a clean checkout at HEAD). Copies
  # exactly what _adv_fingerprint enumerates: unstaged tracked changes, untracked non-ignored files,
  # staged changes (mirrored into $2's own index — every linked worktree keeps one separately), and
  # the gitignored .goalspec/ run state. `--no-renames` on purpose: a rename becomes delete-old plus
  # add-new to a NUL-delimited name-only scan, exactly how _adv_fingerprint itself already treats
  # one — no separate rename-pair parsing to get wrong.
  _src="$1"; _dst="$2"
  _adv_cp_one() {
    _d="$_dst/$1"
    if [ -e "$_src/$1" ] || [ -L "$_src/$1" ]; then
      mkdir -p "$(dirname "$_d")" && cp -p "$_src/$1" "$_d"
    else
      rm -f "$_d"
    fi
  }
  git -C "$_src" diff --no-renames --name-only -z 2>/dev/null \
    | while IFS= read -r -d '' _p; do _adv_cp_one "$_p" || return 1; done || return 1
  git -C "$_src" ls-files -o --exclude-standard -z 2>/dev/null \
    | while IFS= read -r -d '' _p; do _adv_cp_one "$_p" || return 1; done || return 1
  git -C "$_src" diff --cached --no-renames --name-only -z 2>/dev/null \
    | while IFS= read -r -d '' _p; do
        _adv_cp_one "$_p" || return 1
        if [ -e "$_dst/$_p" ]; then
          git -C "$_dst" add -- "$_p" >/dev/null 2>&1 || return 1
        else
          git -C "$_dst" rm -q --cached -- "$_p" >/dev/null 2>&1 || true
        fi
      done || return 1
  if [ -d "$_src/.goalspec" ]; then
    mkdir -p "$_dst/.goalspec" || return 1
    for _f in "$_src"/.goalspec/*; do
      [ -f "$_f" ] || continue
      cp -p "$_f" "$_dst/.goalspec/" || return 1
    done
  fi
  return 0
}

REVIEW_ROOT="$REPO_ROOT"
ISOLATED=0
WORKTREE_DIR=""
_adv_cleanup_worktree() {
  if [ -n "$WORKTREE_DIR" ] && [ -d "$WORKTREE_DIR" ]; then
    git -C "$REPO_ROOT" worktree remove --force "$WORKTREE_DIR" >/dev/null 2>&1 \
      || rm -rf "$WORKTREE_DIR" 2>/dev/null || true
  fi
}
trap _adv_cleanup_worktree EXIT

set +e
if [ -n "$REPO_ROOT" ] && git -C "$REPO_ROOT" rev-parse HEAD >/dev/null 2>&1; then
  _GCD_REL=$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null)
  GIT_COMMON_DIR=""
  if [ -n "$_GCD_REL" ]; then
    GIT_COMMON_DIR=$(cd "$REPO_ROOT" && cd "$_GCD_REL" 2>/dev/null && pwd)
  fi
  if [ -n "$GIT_COMMON_DIR" ] && [ -d "$GIT_COMMON_DIR" ]; then
    # Deliberately NOT paired with `git worktree prune`: bare `prune` has no name filter and
    # removes ANY stale worktree registration in this repo, not only ones this hook created — a
    # worktree the operator has elsewhere (e.g. on an unmounted device or network share; git's own
    # docs name exactly this and prescribe `worktree lock` against it) loses its administrative
    # data immediately, with no grace period `git gc`'s own default (`gc.worktreePruneExpire`,
    # 3 months) gives it. Tried and reverted, 2026-09-17: an external adversary reproduced the
    # data-loss path directly. A prior run killed before its EXIT trap ran (SIGKILL, a crash)
    # leaves a stale goalspec-review-* registration and directory behind — harmless (nothing under
    # .git/ is visible to `git status`/`ls-files`) and left alone rather than risk this.
    # The fallback notice names WHY isolation failed (p-e4b53e7c57): through 0.49.1 the stderr of
    # `mktemp` and `worktree add` went to /dev/null, so a write-restricted partner sandbox reported
    # case 09 red four times with no cause anyone could read. Only the first line of each — git's
    # `fatal: ...` is one line — so the notice stays one line. A failed mktemp was silent outright.
    # The line that names the failure: the first `fatal:`/`error:` line (git may print a `warning:`
    # or `hint:` before it), else the first non-empty line. awk, not sed: BSD sed has no `\|`.
    _adv_first_err() {
      printf '%s\n' "$1" | awk 'NF && f == "" { f = $0 } /^(fatal|error):/ { print; e = 1; exit }
        END { if (!e && f != "") print f }'
    }
    # mktemp prints the path on stdout only on success, so merging stderr in yields EITHER the path
    # OR the error — one call, no second directory created to read the message.
    WORKTREE_DIR=""
    if _ADV_ISO_ERR=$(mktemp -d "$GIT_COMMON_DIR/goalspec-review-XXXXXX" 2>&1); then
      WORKTREE_DIR="$_ADV_ISO_ERR"
    fi
    if [ -n "$WORKTREE_DIR" ]; then
      rmdir "$WORKTREE_DIR" 2>/dev/null
      _ADV_ISO_ERR=""
      _ADV_ISO_OK=0
      if _ADV_ISO_ERR=$(git -C "$REPO_ROOT" worktree add --detach -q "$WORKTREE_DIR" HEAD 2>&1 >/dev/null); then
        # git succeeded, so what it printed is not a cause: a post-checkout hook's output (husky,
        # git-lfs) lands on git's stderr and was once reported as the reason a later copy failed.
        _ADV_ISO_ERR=""
        _adv_materialize_reviewed_state "$REPO_ROOT" "$WORKTREE_DIR" && _ADV_ISO_OK=1
      fi
      if [ "$_ADV_ISO_OK" = 1 ]; then
        REVIEW_ROOT="$WORKTREE_DIR"
        ISOLATED=1
        cd "$WORKTREE_DIR"
      else
        _ADV_ISO_ERR=$(_adv_first_err "$_ADV_ISO_ERR")
        echo "external-adversary: could not materialize an isolated review copy — reviewing $REPO_ROOT directly (un-isolated; same behavior as before this rail existed). Cause: ${_ADV_ISO_ERR:-git worktree add succeeded; copying the uncommitted state into it failed (see any cp/mkdir error above)}" >&2
        _adv_cleanup_worktree
        WORKTREE_DIR=""
      fi
    else
      echo "external-adversary: could not create a directory for an isolated review copy under $GIT_COMMON_DIR — reviewing $REPO_ROOT directly (un-isolated). Cause: $(_adv_first_err "$_ADV_ISO_ERR")" >&2
    fi
  fi
fi
set -e

# Captured OUTSIDE the `set +e` region above on purpose: this must run before the partner does, and
# a failure here is a broken instrument, not a finding. `|| true` keeps a git-less host fail-open —
# REVIEW_ROOT is empty there and the function returns immediately anyway.
FP_BEFORE=$(_adv_fingerprint "$REVIEW_ROOT" 2>/dev/null || true)
HEAD_BEFORE=$(git -C "$REVIEW_ROOT" rev-parse HEAD 2>/dev/null || echo unborn)

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

# READ-ONLY RAIL (verdict half). Name the paths whose content differs between the two captures.
FP_AFTER=$(_adv_fingerprint "$REVIEW_ROOT" 2>/dev/null || true)
HEAD_AFTER=$(git -C "$REVIEW_ROOT" rev-parse HEAD 2>/dev/null || echo unborn)
MUTATED=""
if [ -n "$REVIEW_ROOT" ] && [ "$FP_BEFORE" != "$FP_AFTER" ]; then
  # Report the PATH column of every line present in exactly one capture, deduplicated. A changed
  # blob shows up as two differing lines for the same path; `sort -u` on the path collapses them.
  # The two HEADER lines carry no path, so they get named rather than stripped — without this the
  # generic rule prints their bare hash as if it were a filename (caught by case 05 of
  # test/adversary-writes-branches.py, on the sibling copy of this extractor).
  MUTATED=$(diff <(printf '%s\n' "$FP_BEFORE") <(printf '%s\n' "$FP_AFTER") 2>/dev/null \
            | grep -E '^[<>]' \
            | sed -E -e 's/^[<>] HEAD .*/(HEAD moved: a commit or checkout happened during the run)/' \
                     -e 's/^[<>] staged .*/(the git index: content was staged or unstaged)/' \
                     -e 's/^[<>] [^ ]+ ?//' \
            | grep -v '^$' | sort -u || true)
  [ -z "$MUTATED" ] && MUTATED="(the fingerprint changed but no path could be named — inspect \`git status\` by hand)"
fi

# If HEAD moved, name what actually landed instead of leaving "(HEAD moved: ...)" as the only clue.
# Isolated (ISOLATED=1): REVIEW_ROOT is a private worktree nothing else on this host writes to, so a
# HEAD move there can only be the partner's own `git commit`/`checkout` — a real violation of the
# read-only rail (it was told never to). Un-isolated (fallback): the partner is instructed never to
# commit either, so an advancing HEAD on the LIVE shared repo is more likely a concurrent process —
# another session, a hook — than the partner itself; the commit's author is the fastest way to tell.
LANDED_COMMITS=""
if [ -n "$MUTATED" ] && [ -n "$REVIEW_ROOT" ] && [ "$HEAD_BEFORE" != "$HEAD_AFTER" ] \
   && [ "$HEAD_BEFORE" != "unborn" ] && [ "$HEAD_AFTER" != "unborn" ]; then
  LANDED_COMMITS=$(git -C "$REVIEW_ROOT" log --format='  %h %an <%ae> %s' \
                    "$HEAD_BEFORE..$HEAD_AFTER" 2>/dev/null || true)
fi

# A FILLED BREAK SURVIVES A NONZERO EXIT. Until 0.44.0 this branch tested `RC -ne 0` first, so a
# partner that produced a well-formed `break` and then exited nonzero (a crash on the way out, a
# wrapper propagating its own status, a CLI that exits on a nonzero finding count) had its confirmed
# findings REPLACED by a synthetic clean hold — the gate made weaker by exactly the path that exists
# to keep it honest. Found by an external partner attacking the 0.44.0 claim "a break is never
# weakened" against this code path rather than against the prose that made it. The rule now holds
# uniformly: silence and a bad hold degrade to UNVERIFIED; a break is never suppressed, whatever the
# exit status, because a nonzero exit is a reason to distrust a PASS, never a reason to discard
# findings. The loud warning below is what the nonzero exit buys instead.
if printf '%s' "$VERDICT" | grep -qE '\[ADVERSARY-VERDICT:[[:space:]]*break'; then
  VERDICT_IS_BREAK=1
else
  VERDICT_IS_BREAK=0
fi

# The LAST line on every path that marks a hold UNVERIFIED (0.48.2). Executors read this hook through
# filters, and the observed one deletes exactly these warnings: 2026-10-07 on the team VPS, an
# executor ran it as `2>&1 | grep -v '^external-adversary\|^  ' | tail -14`, the partner returned the
# template's own `break|hold` placeholder, and the synthetic hold (printed first) fell off the tail
# while the prefixed warning fell to the grep — what remained was the partner's unparseable verdict
# line, read as if it were one. So this line has no `external-adversary:` prefix, no leading
# whitespace, no bracket marker (a verdict-shaped string here would feed the verdict nudge and the
# gate), and it prints after everything else. Cases 33-35 pipe the hook through that filter.
_adv_unverified_last_line() {
  echo "UNVERIFIED (goalspec external adversary): $1 It is NOT a pass. Re-run the round or route it to the other backend." >&2
}
if [ -z "$VERDICT" ] || { [ $RC -ne 0 ] && [ "$VERDICT_IS_BREAK" -eq 0 ]; }; then
  echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
  {
    echo "external-adversary: '$EXT_CMD' exited $RC without a filled [ADVERSARY-VERDICT:] line —"
    echo "no independent check ran. Treat this 'hold' as UNVERIFIED, not as a pass. Partner output:"
    printf '%s\n' "$OUT" 2>/dev/null | head -20
    if [ -n "$MUTATED" ]; then
      echo "AND it left the repository modified — these paths changed during its run:"
      printf '%s\n' "$MUTATED" | sed 's/^/  /'
    fi
  } >&2
  _adv_unverified_last_line "the partner (exit $RC) returned no well-formed verdict line (a template echo such as 'break|hold' or '<n>' does not parse), so the 'hold' this hook printed is synthetic and no verdict-looking line in the partner output counts as a verdict."
  exit 0
fi

# A partner that MODIFIED the work verified a state it created. Two rules, and the asymmetry is the
# point: never make this gate weaker than it was.
#   * verdict 'hold'  -> degrade to the same synthetic UNVERIFIED hold the broken-instrument rail
#     emits. A clean bill of health from a tree the reviewer just repaired is precisely the failure
#     mode this rail exists for, and it must not read as a pass.
#   * verdict 'break' -> print it UNCHANGED. The findings stand; suppressing them would turn a
#     detected side effect into a lost violation. The warning goes to stderr instead.
# Deliberately NOT paired with an automatic revert: this script refuses remove-verbs on artifacts it
# does not own (same rule that keeps it out of /tmp cleanup), and undoing a change the human may have
# made themselves is exactly the no-harm violation it would be checking for. Naming the paths is the
# whole job; what to do about them is the operator decision.
_adv_print_landed_commits() {
  [ -z "$LANDED_COMMITS" ] && return 0
  if [ "$ISOLATED" = "1" ]; then
    echo "HEAD advanced via the commit(s) below — REVIEW_ROOT is a private review copy nothing else"
    echo "on this host writes to, so this is the partner's OWN git commit/checkout, a violation of"
    echo "\"you verify, you do not repair\" (it was told never to):"
  else
    echo "HEAD advanced via the commit(s) below during the run — the partner is instructed never to"
    echo "commit (see the read-only rail), so this is more likely a CONCURRENT process (another"
    echo "session, a hook) sharing this un-isolated repo than the partner itself. Verify the author"
    echo "before treating this as adversary tampering:"
  fi
  printf '%s\n' "$LANDED_COMMITS"
}
# THE OTHER-WRITER HEDGE for file content, un-isolated fallback only (p-55cec2045a). Commits already
# got this hedge above; paths did not, so the 2026-10-06 shape — a parallel session of the same
# project writing a file (no commit) during a round — read as a flat "the partner MODIFIED the
# repository". Isolated, nothing else writes to REVIEW_ROOT and the partner reading stands alone
# (case 24 pins that); un-isolated, the hook cannot tell who wrote. The verdict stays degraded either
# way — the reviewed tree changed mid-flight whoever did it — so this changes the attribution, never
# the gate. Same evidence bar as hooks/report-adversary-writes.sh, so the third reading is not a free
# pass. Case 32 requires it; cases 16/17/19 require its absence when isolated.
_adv_print_other_writer_hedge() {
  [ "$ISOLATED" = "1" ] && return 0
  echo "This review ran UN-ISOLATED, on the live shared repository, so ANOTHER WRITER — a parallel"
  echo "session on the same project, the human, a hook — may have changed these paths instead of the"
  echo "partner; this hook cannot tell which. Claim that only with evidence naming the other writer"
  echo "(the session and what it wrote); without it, the partner reading stands."
}
if [ -n "$MUTATED" ]; then
  if printf '%s' "$VERDICT" | grep -qE '\[ADVERSARY-VERDICT:[[:space:]]*hold'; then
    echo "[ADVERSARY-VERDICT: hold ungrounded=0 unfalsified=0 incomplete=0 autonomy-violations=0 unsafe=0]"
    {
      echo "external-adversary: the partner MODIFIED the repository during its own review, then"
      echo "returned a clean 'hold' — a verdict over a state it created. Degraded to UNVERIFIED; do"
      echo "not read it as a pass. Paths whose content changed during the run:"
      printf '%s\n' "$MUTATED" | sed 's/^/  /'
      _adv_print_landed_commits
      _adv_print_other_writer_hedge
      echo "Decide yourself whether to keep or revert them — this hook does not touch files it does"
      echo "not own. Then re-run the review over a tree nobody edited mid-flight. Partner output:"
      printf '%s\n' "$OUT" 2>/dev/null | head -40
    } >&2
    _adv_unverified_last_line "the repository content changed during the partner's run, so the 'hold' this hook printed is synthetic: the partner's own hold describes a tree nobody reviewed as it stands."
    exit 0
  fi
fi

# The partner transcript goes out HERE, before every notice below, not after them (0.46.5). $OUT can
# run to thousands of lines, and executors read this hook through `2>&1 | tail -N`: observed
# 2026-09-30, a `| tail -60` kept the transcript end and cut the sandbox relay and the quote
# reminder, which were printed first. Every notice from here down lands after the transcript, so a
# tail keeps it (test cases 28, 30 and 31 pipe the hook through `tail -20`). Placed after the
# mutated-hold exit on purpose: that path emits a synthetic hold and must never print $OUT to
# stdout (cases 16 and 19 assert it does not). The two break notices below sat before this line
# until 0.46.6.
printf '%s\n' "$OUT"

# Reached only with a filled verdict. If RC is nonzero here, the verdict is a BREAK that was
# deliberately preserved above — say so, loudly, because a partner that crashed may have stopped
# short of attacks it had not run yet: the findings stand, the COVERAGE does not. Case 30.
if [ $RC -ne 0 ]; then
  {
    echo "external-adversary: '$EXT_CMD' exited $RC but returned a filled 'break' — the findings are"
    echo "printed unchanged rather than discarded (a nonzero exit is a reason to distrust a pass, not"
    echo "to drop violations). Treat its COVERAGE as incomplete: it may have died before running"
    echo "attacks it had not reached. Re-run or route to the other backend once you have acted on"
    echo "what it did find."
  } >&2
fi

# MUTATED with a hold already exited above, so here the verdict is a break. Case 31.
if [ -n "$MUTATED" ]; then
  {
    echo "external-adversary: the partner MODIFIED the repository during its own review. Its 'break'"
    echo "stands (findings are not suppressed), but every one of them was measured against a tree it"
    echo "had already changed — re-derive each before acting. Paths whose content changed:"
    printf '%s\n' "$MUTATED" | sed 's/^/  /'
    _adv_print_landed_commits
    _adv_print_other_writer_hedge
  } >&2
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

# Forward the partner declared sandbox to the executor (0.46.4). Codex prints it as a header line,
# e.g. "sandbox: workspace-write [workdir, /tmp, $TMPDIR]". Observed 2026-09-30: that line sat in
# 7000 lines of $OUT for three rounds while a suite that writes under HOME went red inside the
# partner, the partner called it unrelated, and the executor (green on the host) never joined the
# two. Relayed, not interpreted — same class as the [ADVERSARY-MODEL:] self-report. Its consumer is
# SKILL.md step 6 (every red the adversary ran and did not count is the executor to adjudicate).
# First match only: the header precedes every tool output, so a later file read that happens to
# contain such a line does not win. A CLI that prints no such line gets no message. The message is
# conditional on purpose: danger-full-access restricts nothing, and an adversary round caught the
# first wording asserting HOME writes fail for any declared mode.
# Deliberately NOT an errno grep of $OUT: the observed failure surfaced as "No such file or
# directory", not "Operation not permitted" (the denied mkdir was silenced upstream).
# printf's stderr is silenced because grep -m1 closes the pipe at the first match: with a large $OUT
# (observed live 2026-09-30, 7431 lines) printf then fails with "write error: Broken pipe", and that
# noise lands among the notices a tail keeps. Same for the two `| head` reads above. Case 29.
SANDBOX_LINE=$(printf '%s\n' "$OUT" 2>/dev/null | grep -m1 -E '^sandbox: [^[:space:]]' || true)
if [ -n "$SANDBOX_LINE" ]; then
  echo "external-adversary: the partner declared its own sandbox -- \"$SANDBOX_LINE\". If that mode restricts writes, a write outside the roots that line lists fails inside its run (HOME included, unless the line lists it), and a red it reports in a suite that writes there may be its environment, not the work. Cross every red it ran and did not count against your host run before a hold closes (SKILL.md step 6)." >&2
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
echo "external-adversary: a verdict-shaped block was just produced above -- whether it reflects genuine adversarial work is still yours to judge (see the bare-verdict-floor note above). If you judge it genuine, quote the [ADVERSARY-MODEL: ...] and [ADVERSARY-VERDICT: ...] lines VERBATIM in your very next assistant turn -- each on its OWN line, in plain text, nothing before it and nothing after the closing bracket on that same line: no bold or code-span wrapping, no trailing citation. It must be a visible text block you emit -- a quote you only write or plan in your thinking does not count: thinking is not read, even when your screen shows it like a message. The gate matches the marker only when its line ends at that bracket, so decorating it while quoting degrades a genuine model=different to model=same, silently. The Stop gate cannot see this script's stdout directly, only text you personally author — this is far easier to forget once you move on to other work than it is right now." >&2
# Bare verdict: the partner's own line is printed and stays well-formed, so only the filter-proof
# last line is added here (case 35) — the prefixed floor warning above is the one the grep deletes.
if [ "$EVIDENCE_LINES" -eq 0 ]; then
  _adv_unverified_last_line "the partner's verdict above came with no evidence of work (no bullets or ground truth above it), so it is a bare verdict, not a verified one."
fi


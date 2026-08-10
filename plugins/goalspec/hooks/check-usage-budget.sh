#!/usr/bin/env bash
# check-usage-budget.sh — Stop hook. OPT-IN ONLY. Advisory 5-hour/7-day usage-ceiling nudge.
#
# What it does: if (and only if) `usage_budget.enabled` resolves to true (per-key project
# .claude/goal.config.json, else user-global ~/.claude/goal.config.json — same fallback the
# adversary.backend / sweep_files keys already use), reads the local Claude Code OAuth credential,
# calls Anthropic's own account-usage endpoint, and — only when utilization crosses the configured
# threshold — prints a non-blocking nudge to checkpoint state (see SKILL.md's "Execute" step).
#
# Why this is DIFFERENT from every other hook in this plugin, and why it is OFF by default:
# every other hook here reads project-local markdown or spawns a subagent. This one reads the
# user's live OAuth access token (from Claude Code's own credentials file, or macOS Keychain) and
# sends it to api.anthropic.com. That is a materially larger trust surface — a public plugin should
# never do this silently. It requires an explicit, documented opt-in; the token itself is never
# logged, cached, or printed — only the resulting utilization percentages are cached, locally.
#
# Behavior:
#   * `usage_budget.enabled` not truthy (the default, absent) -> silent exit 0. No credential read,
#     no network call, no behavior change whatsoever for the overwhelming majority of installs.
#   * Only checks within a goalspec-tracked session (a `## Goal-spec` in this run), same
#     conditionality gate-goal-close.sh already applies — this is advisory to the method, not a
#     general-purpose usage monitor.
#   * Own on-disk cache with a short TTL so a real Stop-hook-per-turn cadence does not hammer the
#     API; a fetch failure (no credential found, network error, non-200, malformed JSON) is fully
#     fail-open and silent — never blocks the stop, never raises an error to the user.
#   * Nudges only when utilization >= threshold (default 80). Below threshold: silent, by design —
#     this is a nudge for the rare case that matters, not a persistent status readout (that's what
#     your own statusline is for).
#   * Never blocks. Always exit 0. This is advisory only, in the same spirit as every hook in this
#     plugin — see references/outcome-loop-beats-gates.md. Read that exactly: never blocking is not
#     never re-asking. The advisory payload re-enters the turn by design (that is what gives the
#     nudge an agent-facing consumer); what keeps it bounded is the re-entrant guard at step 0.
#   * Silent on a re-entrant Stop (`stop_hook_active`) — step 0.
#
# Registered as a Stop hook by hooks/hooks.json. See references/usage-budget-setup.md for the full
# security model and setup.

INPUT=$(cat)

# Portable interpreter: python3 (macOS/Linux) then python (Windows / Git Bash) — same resolver every
# other hook in this plugin uses. Fail-open if neither resolves cleanly.
PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)

RESULT=$(printf '%s' "$INPUT" | GOAL_CONFIG_PATH="${GOAL_CONFIG_PATH:-}" LIBDIR="${CLAUDE_PLUGIN_ROOT:-}/hooks/lib" "$PY" -c '
import json, sys, os, re, time, subprocess

_libdir = os.environ.get("LIBDIR", "")
if _libdir and _libdir not in sys.path:
    sys.path.insert(0, _libdir)
try:
    import terminal_actions as ta
except Exception:
    ta = None
from urllib import request, error

def silent():
    sys.exit(0)

try:
    data = json.load(sys.stdin)
except Exception:
    silent()

# 0. Re-entrant Stop: say nothing (0.18.1, mirrors step 0 of gate-goal-close.sh). This hook is
#    advisory and never blocks, but "advisory" is not "inert": its payload carries
#    hookSpecificOutput.additionalContext, which the harness feeds back to the model, so the turn is
#    re-entered even though the stop was never prevented. This hook always emits that shape, and so
#    does the gate on every branch except one, so guarding only the gate would leave the budget
#    nudge able to re-ask on its own. NOTE for whoever edits this comment: it lives INSIDE a
#    single-quoted shell string, so an apostrophe here terminates that string and silently disables
#    the hook — measured, 2026-08-10, on the word that used to sit before "convergence-floor".
#    (Since 0.36.0 the convergence-floor branch of the gate emits
#    `systemMessage` only and therefore defers this guard rather than applying it — that exception
#    is specific to a payload that cannot re-ask, and does not travel to this hook, which can.)
if data.get("stop_hook_active"):
    silent()

# 1. Only within a goalspec-tracked session (mirrors gate-goal-close.sh conditionality).
lam = data.get("last_assistant_message")
lam_text = lam if isinstance(lam, str) else ""
tx_parts = []
tpath = data.get("transcript_path")
if isinstance(tpath, str) and tpath and os.path.isfile(tpath):
    try:
        with open(tpath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("type") != "assistant":
                    continue
                msg = ev.get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    tx_parts.append(content)
                elif isinstance(content, list):
                    for blk in content:
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            tx_parts.append(blk.get("text") or "")
    except Exception:
        pass
text = lam_text + "\n" + "\n".join(tx_parts)
# Text-only regex, same as the equivalent check in gate-goal-close.sh, and the SAME blind spot: a goal-spec
# written to disk (.goalspec/checkpoint.md) instead of posted as chat text is invisible to it —
# confirmed live (goal-adversary round 2, 2026-08-01) as a stale carrier of this exact rule. `ta`
# may be None (import failed); the OR degrades to the original text-only check, unchanged.
_goal_spec_present = bool(re.search(r"(^|\n)#{1,6}\s*Goal-spec\b", text, re.I))
if ta is not None and not _goal_spec_present:
    try:
        _goal_spec_present = ta.transcript_signals(tpath).get("goal_spec", False)
    except Exception:
        pass
if not _goal_spec_present:
    silent()

# 2. Resolve usage_budget.{enabled,warn_threshold} per key: project overrides global — the SAME
#    precedence adversary.backend / sweep_files already use.
def read_config(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("usage_budget") or {}
    except Exception:
        return {}

proj_path = os.environ.get("GOAL_CONFIG_PATH") or ".claude/goal.config.json"
home = os.environ.get("HOME") or os.path.expanduser("~")
glob_path = os.path.join(home, ".claude", "goal.config.json")

proj_cfg = read_config(proj_path)
glob_cfg = read_config(glob_path)

def resolve(key, default):
    if key in proj_cfg:
        return proj_cfg[key]
    if key in glob_cfg:
        return glob_cfg[key]
    return default

if not resolve("enabled", False):
    silent()

threshold = resolve("warn_threshold", 80)
try:
    threshold = float(threshold)
except Exception:
    threshold = 80.0

# 3. Claude config dir (respects CLAUDE_CONFIG_DIR, same as Claude Code itself).
def get_claude_config_dir():
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        return os.path.expanduser(env_dir)
    return os.path.join(home, ".claude")

config_dir = get_claude_config_dir()
cache_file = os.path.join(config_dir, "goalspec-usage-cache.json")
CACHE_TTL = 300  # seconds — own instrument, independent of any other tool cache

# 4. Serve from cache if fresh. Cache holds ONLY the resulting percentages — never the token.
now = time.time()
cached = None
try:
    with open(cache_file, "r", encoding="utf-8") as fh:
        cached = json.load(fh)
    if not (isinstance(cached, dict) and now - cached.get("_fetched_at", 0) < CACHE_TTL):
        cached = None
except Exception:
    cached = None

usage = cached
if usage is None:
    # 5. Resolve the OAuth token. Never logged, never cached, never printed.
    #
    # IMPORTANT: on macOS, the Keychain secret is the SAME JSON shape as .credentials.json
    # ({"claudeAiOauth": {"accessToken": "..."}}) -- it is NOT a bare token string. Treating the
    # raw `security` stdout as the token (an earlier draft of this script did) sends the whole
    # JSON blob -- which may carry other credential fields -- into the Authorization header.
    # Caught by an external adversary review before this ever shipped; verified directly against
    # ccstatuslines own `parseUsageAccessToken` (it JSON-parses the Keychain secret exactly like
    # the file). Precedence also mirrors ccstatusline: Keychain first on macOS, file as fallback.
    def parse_access_token(raw):
        try:
            return (json.loads(raw).get("claudeAiOauth") or {}).get("accessToken")
        except Exception:
            return None

    cred_file = os.path.join(config_dir, ".credentials.json")

    def read_credentials_file():
        try:
            with open(cred_file, "r", encoding="utf-8") as fh:
                return parse_access_token(fh.read())
        except Exception:
            return None

    token = None
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                capture_output=True, timeout=5, text=True,
            )
            if out.returncode == 0 and out.stdout.strip():
                token = parse_access_token(out.stdout)
        except Exception:
            token = None
        if not token:
            token = read_credentials_file()
    else:
        token = read_credentials_file()
    if not token:
        silent()

    # 6. Call the account-usage endpoint directly. Fail-open on anything but a clean 200.
    req = request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                silent()
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        silent()
    finally:
        token = None  # never let it linger

    five = (body or {}).get("five_hour") or {}
    seven = (body or {}).get("seven_day") or {}
    usage = {
        "_fetched_at": now,
        "five_hour_utilization": five.get("utilization"),
        "five_hour_resets_at": five.get("resets_at"),
        "seven_day_utilization": seven.get("utilization"),
        "seven_day_resets_at": seven.get("resets_at"),
    }
    try:
        os.makedirs(config_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as fh:
            json.dump(usage, fh)
    except Exception:
        pass

five_u = usage.get("five_hour_utilization")
if not isinstance(five_u, (int, float)):
    silent()
if five_u < threshold:
    silent()

resets = usage.get("five_hour_resets_at") or "unknown"
seven_u = usage.get("seven_day_utilization")
seven_note = ""
if isinstance(seven_u, (int, float)) and seven_u >= threshold:
    seven_note = " Your 7-day window is also at {:.0f}%.".format(seven_u)

msg = (
    "[USAGE-BUDGET] Your Claude Code 5-hour usage window is at {:.0f}% (resets at {}).{} "
    "This is a real account ceiling, not context — if this task still has several rounds to go, "
    "checkpoint state to .goalspec/checkpoint.md now (see SKILL.md Execute step) so a mid-round cutoff loses at most "
    "the in-flight round."
).format(five_u, resets, seven_note)

print(json.dumps({
    "systemMessage": msg,
    "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": msg},
}))
' 2>/dev/null)

[ -z "$RESULT" ] && exit 0
printf '%s\n' "$RESULT"
exit 0

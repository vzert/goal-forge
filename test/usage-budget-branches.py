#!/usr/bin/env python3
"""Branch suite for plugins/goalspec/hooks/check-usage-budget.sh.

Why this exists, and what changed to make it possible.

Until 0.19.1 the re-entrant-Stop guard in this hook (0.18.1, `stop_hook_active` -> silent) was
verified **by placement and syntax only**, and the CHANGELOG said so: the belief was that the hook
"cannot emit anything without real credentials", so it would exit silently with the flag `true` and
with the flag `false` alike, and no offline test could tell the two apart. A guard whose only
evidence is that it is spelled correctly is not a verified guard.

That premise was false, and the seam is in the hook's own ordering: step 4 **serves from its local
cache before step 5 resolves any credential**, and both the config path (`GOAL_CONFIG_PATH`) and the
cache directory (`CLAUDE_CONFIG_DIR`) are environment-overridable. So a seeded cache with a fresh
`_fetched_at` drives the hook all the way to a real emission with **no credential read and no
network call** — which makes the guard discriminable offline after all.

    python3 test/usage-budget-branches.py

Exit code is non-zero if any case does not produce its expected cell, so it works in a pipeline.

WHAT THIS SUITE DOES NOT COVER — stated because an instrument that hides its own blind spot is the
defect this plugin keeps cataloguing (references/instrument-validity-own-tools.md):
  * The **credential path** (step 5: `.credentials.json`, macOS Keychain) is never exercised. Every
    case here is served from the seeded cache. A stale-cache case would fall through to a real
    Keychain lookup and potentially a live API call with the user's own token, which a test must
    never do. That path stays covered only by the manual end-to-end run recorded in memory/.
  * The **nudge at real utilization** is not observed. Seeding the cache with 95% proves the
    threshold comparison and the payload shape; it does not observe a real account crossing 80%.
    That is a separate open observation item, not something this suite closes.
Both limits are the point of writing them here rather than letting a green run imply more.
"""
import json, os, subprocess, sys, tempfile, time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "plugins", "goalspec", "hooks", "check-usage-budget.sh")

SPEC = "## Goal-spec\nObjective: whatever.\n"
NO_SPEC = "Just some text. No spec anywhere in this run."

# (name, enabled, cache_utilization, last_assistant_message, extra_payload, expected)
#   expected: "nudge" (the hook printed a payload) or "silent" (it printed nothing)
CASES = [
    # --- the discrimination the old "verified by placement" note could not make ---
    # Identical inputs; the ONLY difference is the flag. Before 0.18.1's guard, 01 emitted too.
    ("01-guard-active-silent", True, 95.0, SPEC, {"stop_hook_active": True}, "silent"),
    ("02-guard-absent-nudges", True, 95.0, SPEC, {}, "nudge"),
    # explicit false must behave exactly like absent, not like "key present -> skip"
    ("03-guard-false-nudges", True, 95.0, SPEC, {"stop_hook_active": False}, "nudge"),

    # --- controls: prove 01's silence comes from the GUARD and not from some other early exit ---
    # Below threshold is silent by design, so a suite that only ever fed 95% could not tell a
    # working guard from a hook that never emits at all.
    ("04-below-threshold-silent", True, 12.0, SPEC, {}, "silent"),
    # opt-in default: not enabled -> silent before any cache or credential work happens
    ("05-not-enabled-silent", False, 95.0, SPEC, {}, "silent"),
    # goalspec conditionality: no `## Goal-spec` in the run -> not our business
    ("06-no-goalspec-silent", True, 95.0, NO_SPEC, {}, "silent"),
    # Regression pin (goal-adversary round 2/3, 2026-08-01): the goal-spec precondition above is
    # blind to a spec written to disk (.goalspec/checkpoint.md via `Write`) instead of posted as
    # chat text — the SAME blind spot gate-goal-close.sh had, fixed here with the same
    # `ta.transcript_signals()` OR. Round 3 found this specific fix shipped with NO case
    # exercising it (every other case here only ever sets last_assistant_message, never
    # transcript_path) — so the fix could have been silently broken (e.g. CLAUDE_PLUGIN_ROOT not
    # wired into this hook's own env) and nothing would have failed. `transcript_events` in extra
    # is a signal run_case() below builds a real transcript file from.
    ("07-goalspec-only-in-checkpoint-write-nudges", True, 95.0, "still working, no spec in chat",
     {"transcript_events": [{"write": (".goalspec/checkpoint.md", SPEC)}]}, "nudge"),
]


def run_case(name, enabled, util, lam, extra, tmp):
    """Drive the hook with a hermetic HOME, config and cache. Returns "nudge" or "silent"."""
    case_dir = os.path.join(tmp, name)
    os.makedirs(case_dir, exist_ok=True)

    cfg_path = os.path.join(case_dir, "goal.config.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump({"usage_budget": {"enabled": enabled, "warn_threshold": 80}}, fh)

    # The seeded cache IS the seam: step 4 reads it before step 5 touches any credential.
    with open(os.path.join(case_dir, "goalspec-usage-cache.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "_fetched_at": time.time(),          # fresh: inside CACHE_TTL, so no fetch is attempted
            "five_hour_utilization": util,
            "five_hour_resets_at": "2026-07-25T23:00:00Z",
            "seven_day_utilization": 40.0,
            "seven_day_resets_at": "2026-08-01T00:00:00Z",
        }, fh)

    payload = {"last_assistant_message": lam}
    extra = dict(extra)  # copy — do not mutate the CASES tuple's dict across runs
    transcript_events = extra.pop("transcript_events", None)
    payload.update(extra)
    if transcript_events is not None:
        tx_path = os.path.join(case_dir, "tx.jsonl")
        with open(tx_path, "w", encoding="utf-8") as fh:
            for ev in transcript_events:
                content = []
                if "write" in ev:
                    fp, body = ev["write"]
                    content.append({"type": "tool_use", "name": "Write", "input": {"file_path": fp, "content": body}})
                if "text" in ev:
                    content.append({"type": "text", "text": ev["text"]})
                fh.write(json.dumps({"type": "assistant", "message": {"content": content}}) + "\n")
        payload["transcript_path"] = tx_path

    env = dict(os.environ)
    # HOME too, not just GOAL_CONFIG_PATH: without it the resolver falls back to the developer's own
    # ~/.claude/goal.config.json, and this repo's author has usage_budget enabled there — case 05
    # would then pass for the wrong reason.
    env["HOME"] = case_dir
    env["GOAL_CONFIG_PATH"] = cfg_path
    env["CLAUDE_CONFIG_DIR"] = case_dir
    # Required for the hook's own LIBDIR-based import of hooks/lib/terminal_actions.py to resolve —
    # round 3 found this exact omission made an earlier draft of case 07 pass for the wrong reason
    # (silently falling back to the text-only check, which case 07's spec-free lam cannot satisfy).
    env["CLAUDE_PLUGIN_ROOT"] = os.path.join(REPO, "plugins", "goalspec")

    out = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                         capture_output=True, text=True, env=env).stdout.strip()
    return "nudge" if out else "silent"


def main():
    tmp = tempfile.mkdtemp(prefix="usage-budget-branches-")
    failures = []
    for name, enabled, util, lam, extra, expected in CASES:
        got = run_case(name, enabled, util, lam, extra, tmp)
        ok = got == expected
        if not ok:
            failures.append((name, expected, got))
        print("{:<28} {:<8} {}".format(name, got, "" if ok else "  <-- FAIL, expected " + expected))

    print()
    if failures:
        print("{} case(s) FAILED".format(len(failures)))
        return 1
    print("all {} case(s) OK — guard discriminated offline (cache seam, no credential, no network)"
          .format(len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

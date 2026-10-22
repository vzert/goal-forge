"""external_review.py — the external partner reports facts; code decides what blocks and when to stop.

WHY (0.68.0, p-d33dc17af4). Severity rules written in the prompt were not obeyed reliably, and the
rounds did not converge. Measured on one production change plan (#9064, 2026-10-21): 7 external
rounds broke in a row, 32 blocking findings, 7 of them defects of ordinary execution, 9 needing an
actor the partner supposed, 14 repeating a root an earlier round had raised; a prompt rule that
made a supposed actor MINOR was ignored in a real run, and two runs on the same content shared
almost no findings. Outside this repo the same lesson: the severity a model gives its own finding is
close to random (Greptile), and what worked was structure outside the model. So, for `codex exec`:

  schema   the hook passes `--output-schema` (SCHEMA below) and `-o <file>`; each finding carries
           what it attacks, what triggers it and what evidence it has, never a severity.
  render   code computes BLOCKING or MINOR per finding (severity()), demotes a root an earlier round
           of this cycle already raised unless the finding brings a new failing scenario, says NOT
           CONVERGED when the blocking count did not fall, and prints the same
           [ADVERSARY-MODEL: ...] / [ADVERSARY-VERDICT: ...] lines every consumer already reads.
  cap      before a round runs: once this cycle has used the rounds the human allowed
           (adversary.max_external_rounds, default 3), the partner does not run; the human decides.

A cycle starts at the latest `## Goal-spec` this session wrote (as text or into a file); with no
transcript found, the whole session is one cycle. Every step fails open: an unreadable answer, a
missing state directory or a broken transcript leaves the hook on its text path, never blocks it.

Declared limits: the fields are the model's report, and a model can fill them falsely (all
`ordinary_use`); the evidence it gives is printed for the executor and the human to read. The
fingerprint of a root (category + file + the root slug the model names) is approximate: it can merge
two findings or miss a repeat.
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_dir  # noqa: E402

HOOK = "external-rounds"
LEDGER = "external-rounds"
DEFAULT_CAP = 3
CATEGORIES = ("ungrounded", "unfalsified", "incomplete", "autonomy", "unsafe")
VERDICT_KEYS = ("ungrounded", "unfalsified", "incomplete", "autonomy-violations", "unsafe")


def _obj(props, required=None):
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": list(required if required is not None else props)}


_S = {"type": "string"}
SCHEMA = _obj({
    "model_self_report": {"type": "string", "description": "Your model name and exact id as your own context states them, or UNKNOWN."},
    "attacks": {"type": "array", "items": _obj({
        "angle": _S,
        "outcome": {"type": "string", "enum": ["pursued_refuted", "pursued_confirmed", "out_of_reach"]},
        "note": _S})},
    "findings": {"type": "array", "items": _obj({
        "title": _S,
        "root": {"type": "string", "description": "A short kebab-case name of the root cause, the same words each time you meet the same root."},
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "about": {"type": "string", "enum": ["work", "record", "process"]},
        "reader_acts_on_it": {"type": "boolean"},
        "trigger": {"type": "string", "enum": ["ordinary_use", "supposed_actor", "crafted_input", "environment", "not_applicable"]},
        "evidence_kind": {"type": "string", "enum": ["observed_in_run", "cited_file_line", "in_real_data", "documented", "none"]},
        "actor_evidence": {"type": "string", "enum": ["not_applicable", "none", "seen_in_real_data", "named_producer",
                                                       "named_in_threat_model", "documented_as_supported"],
                           "description": "For a supposed actor or a crafted input only: what shows that actor or input occurs here. A line of the code that has the hole is not this."},
        "evidence": _S,
        "repro": _S,
        "file": _S,
        "criterion": _S,
        "introduced_by_change": {"type": "boolean"},
        "new_scenario": {"type": "boolean"}})},
})


def severity(f):
    """-> (BLOCKING|MINOR, reason). The rubric of agents/goal-adversary.md, decided from the facts."""
    about, trig = f.get("about"), f.get("trigger")
    has_ev = f.get("evidence_kind") not in (None, "", "none") and str(f.get("evidence") or "").strip()
    if trig == "environment":
        return "MINOR", "the verifier's own environment (sandbox, network, a stale ref), not the work"
    if f.get("category") == "autonomy":
        return ("BLOCKING", "autonomy, with evidence") if has_ev else ("MINOR", "autonomy claim with no evidence from the transcript")
    if about == "process":
        return "MINOR", "the run's own bookkeeping, not the work"
    if about == "record":
        if f.get("reader_acts_on_it") and has_ev:
            return "BLOCKING", "a false statement a reader will act on"
        return "MINOR", "a line of the record that no reader acts on, or no evidence it is false"
    if trig in ("supposed_actor", "crafted_input") and f.get("actor_evidence") in (None, "", "none", "not_applicable"):
        return "MINOR", ("needs an actor or an input nobody showed occurs here (no evidence from real data, "
                         "a named producer, the threat model or the documentation)")
    if not f.get("introduced_by_change") and str(f.get("criterion") or "none").strip().lower() in ("", "none"):
        return "MINOR", "pre-existing, and no success criterion rests on it"
    return "BLOCKING", "the work, " + ("in ordinary use" if trig == "ordinary_use" else trig or "no trigger")


def _norm_file(p):
    p = str(p or "").strip().replace("\\", "/")
    p = re.sub(r":\d+(-\d+)?$", "", p)
    return p.split("/.git/")[-1].split("goalspec-review-")[-1].lstrip("/").lower()


def fingerprint(f):
    root = re.sub(r"[^a-z0-9]+", "-", str(f.get("root") or f.get("title") or "").lower()).strip("-")
    tail = "/".join(_norm_file(f.get("file")).split("/")[-2:])
    return "%s|%s|%s" % (f.get("category"), tail, root)


def _now():
    # Microseconds: the transcript stamps a ## Goal-spec with milliseconds, and a round recorded in the
    # same second must still sort after (or before) it (external round on 0.68.0).
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _epoch(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def cycle_start(session_id):
    """-> the epoch of the latest `## Goal-spec` this session wrote, or None (no transcript)."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    if not session_id or not os.path.isabs(base):
        return None
    import glob
    files = glob.glob(os.path.join(base, "projects", "*", glob.escape(session_id) + ".jsonl"))
    if not files:
        return None
    last = None
    spec = re.compile(r"(^|\n)## Goal-spec")
    for f in files:
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if "## Goal-spec" not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") != "assistant":
                    continue
                for b in (e.get("message") or {}).get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    t = ""
                    if b.get("type") == "text":
                        t = b.get("text") or ""
                    elif b.get("type") == "tool_use" and b.get("name") in ("Write", "Edit", "MultiEdit"):
                        inp = b.get("input") or {}
                        t = str(inp.get("content") or inp.get("new_string") or "")
                    if spec.search(t):
                        ts = _epoch(e.get("timestamp"))
                        if ts is not None and (last is None or ts > last):
                            last = ts
    return last if last is not None else 0.0


def _ledger(session_id, repo):
    snap = run_dir.ensure(session_id, HOOK, repo) if session_id else None
    return os.path.join(snap, LEDGER) if snap else None


def rounds(session_id, repo):
    """-> this cycle's recorded rounds, oldest first."""
    path = _ledger(session_id, repo)
    if not path or not os.path.isfile(path):
        return []
    start = cycle_start(session_id) or 0.0
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = _epoch(r.get("ts"))
            if isinstance(r, dict) and t is not None and t >= start:
                out.append(r)
    return out


def _append(session_id, repo, rec):
    path = _ledger(session_id, repo)
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def _config_cap(cwd):
    """adversary.max_external_rounds, per key: project .claude/goal.config.json, else user-global."""
    paths = [os.environ.get("GOAL_CONFIG_PATH") or os.path.join(cwd, ".claude", "goal.config.json"),
             os.path.join(os.path.expanduser("~"), ".claude", "goal.config.json")]
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                v = ((json.load(fh) or {}).get("adversary") or {}).get("max_external_rounds")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
            return v
    return DEFAULT_CAP


def cap(session_id, cwd, repo):
    """-> (run: bool, reason)."""
    limit = _config_cap(cwd)
    if limit == 0:
        return True, "no round cap (adversary.max_external_rounds = 0)"
    if not session_id:
        return True, "no session id"
    done = rounds(session_id, repo)
    if len(done) >= limit:
        return False, ("this goal-spec cycle already used the %d external rounds the human allowed "
                       "(adversary.max_external_rounds). Stop and hand the decision to the human: say what is "
                       "still open; only the human raises the cap, or a new ## Goal-spec starts a new cycle."
                       % limit)
    return True, "round %d of %d in this cycle" % (len(done) + 1, limit)


def _clean(s, n=600):
    return " ".join(str(s or "").split())[:n]


def render(data, session_id="", repo="", record=True):
    """-> the text block the hook prints: findings with code-computed severity, then the verdict line."""
    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    prev = rounds(session_id, repo) if session_id else []
    seen = {}
    for i, r in enumerate(prev, 1):
        for fp in r.get("blocking", []):
            seen.setdefault(fp, i)
    counts = dict.fromkeys(CATEGORIES, 0)
    lines, blocking_fps = [], []
    for f in findings:
        if not isinstance(f, dict):
            continue
        sev, why = severity(f)
        fp = fingerprint(f)
        if sev == "BLOCKING" and fp in seen and not (f.get("new_scenario") and str(f.get("repro") or "").strip()):
            sev, why = "MINOR", ("the same root was BLOCKING in round %d of this cycle; it reopens only with a new "
                                 "failing scenario and its repro" % seen[fp])
        if sev == "BLOCKING":
            counts[f.get("category") if f.get("category") in counts else "incomplete"] += 1
            blocking_fps.append(fp)
        head = "- %s (%s; about=%s; trigger=%s; evidence=%s; actor_evidence=%s): %s" % (
            sev, f.get("category"), f.get("about"), f.get("trigger"), f.get("evidence_kind"), f.get("actor_evidence"),
            _clean(f.get("title"), 300))
        lines.append(head)
        lines.append("    why %s: %s" % (sev, why))
        if str(f.get("evidence") or "").strip():
            lines.append("    evidence: " + _clean(f.get("evidence")))
        if str(f.get("repro") or "").strip():
            lines.append("    repro: " + _clean(f.get("repro")))
        if str(f.get("file") or "").strip():
            lines.append("    file: " + _clean(f.get("file"), 300))
    for a in data.get("attacks") or []:
        if isinstance(a, dict):
            lines.append("- %s: %s%s" % (a.get("outcome"), _clean(a.get("angle"), 300),
                                         (" -- " + _clean(a.get("note"), 300)) if a.get("note") else ""))
    n = sum(counts.values())
    notes = []
    # Compared with the last round that carried findings: a text-path round records none.
    last = max((i for i, r in enumerate(prev, 1) if r.get("schema")), default=0)
    if last and n and n >= len(prev[last - 1].get("blocking", [])):
        notes.append("external-adversary: NOT CONVERGED -- round %d of this cycle has %d BLOCKING finding(s), round %d had %d. "
                     "The count did not fall: stop spending rounds and hand the decision to the human (SKILL.md step 6, "
                     "convergence guard). This is a break, never a pass." % (len(prev) + 1, n, last, len(prev[last - 1].get("blocking", []))))
    model = re.sub(r"[\]\[<>\n]", " ", str(data.get("model_self_report") or "UNKNOWN")).strip()
    model = re.sub(r"^(ADVERSARY-MODEL:\s*)+", "", model).strip() or "UNKNOWN"
    if "/" not in model:
        model += " / UNKNOWN"
    verdict = "[ADVERSARY-VERDICT: %s %s]" % ("break" if n else "hold", " ".join(
        "%s=%d" % (k, counts[c]) for k, c in zip(VERDICT_KEYS, CATEGORIES)))
    if record and session_id:
        _append(session_id, repo, {"ts": _now(), "blocking": blocking_fps, "schema": True})
    return "\n".join(["[ADVERSARY-MODEL: %s]" % model, "(severity computed by the hook from the fields of each finding)"]
                     + lines + notes + [verdict])


def record_text_round(session_id, repo):
    """A round on the text path (no schema): counted toward the cap, no fingerprints."""
    if session_id:
        _append(session_id, repo, {"ts": _now(), "blocking": [], "schema": False})


if __name__ == "__main__":
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    try:
        cmd = sys.argv[1] if len(sys.argv) > 1 else ""
        if cmd == "schema":                      # schema <out file>
            with open(sys.argv[2], "w", encoding="utf-8") as fh:
                json.dump(SCHEMA, fh)
            sys.exit(0)
        if cmd == "cap":                         # cap <cwd> <repo>  -> RUN|BLOCK<TAB>reason
            ok, why = cap(sid, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
            print(("RUN" if ok else "BLOCK") + "\t" + why)
            sys.exit(0)
        if cmd == "render":                      # render <answer file> <repo>  -> block, or exit 2
            with open(sys.argv[2], encoding="utf-8", errors="replace") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
                sys.exit(2)
            print(render(data, sid, sys.argv[3] if len(sys.argv) > 3 else ""))
            sys.exit(0)
        if cmd == "text-round":                  # text-round <repo>
            record_text_round(sid, sys.argv[2] if len(sys.argv) > 2 else "")
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        if len(sys.argv) > 1 and sys.argv[1] == "cap":
            print("RUN\tthe round cap failed (fail-open)")
            sys.exit(0)
        sys.exit(2)
    sys.exit(2)

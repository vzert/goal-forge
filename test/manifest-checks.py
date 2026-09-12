#!/usr/bin/env python3
"""Manifest and wiring checks — the silent-failure classes no branch suite can see.

The nine branch suites drive hook CODE. Nothing checked the things that break a release without
breaking a single test, each of which this project has actually been bitten by:

* **A version that was not bumped.** The install cache is keyed by version
  (`~/.claude/plugins/cache/goal-forge/goalspec/<version>/`), so a push without a bump is never
  delivered to installed users — the change ships to GitHub and reaches nobody. `plugin.json` and
  `marketplace.json` must agree, every time.
* **Frontmatter that stopped being YAML.** A bare `: ` (colon-space) inside a `description:` makes
  the block unparseable; the skill then loads with EMPTY metadata and simply never auto-triggers.
  Nothing errors. `claude plugin validate` does not catch it either.
* **A hook wired to a path that does not exist.** `hooks.json` names scripts by path; a typo or a
  renamed file makes that hook silently never run, which is the instrument-validity defect this
  whole plugin is about, aimed at itself.
* **A suite the docs forgot.** `test/README.md` and `CLAUDE.md` both state how many suites exist.
  That count went stale in 0.44.0 and an external adversary found it, not a test.

Hermetic: reads files, runs nothing, needs no network and no Claude Code install. PyYAML is the one
non-stdlib dependency, and it is the point — the check is "does a real YAML parser accept this".

    python3 test/manifest-checks.py
"""
import json, os, re, shutil, subprocess, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")

try:
    import yaml
except ImportError:
    print("manifest-checks: PyYAML is required (pip install pyyaml).\n"
          "It is not optional here: the whole point of the frontmatter check is that a REAL YAML\n"
          "parser accepts the block, which a hand-rolled regex cannot establish.", file=sys.stderr)
    sys.exit(2)


def selftest():
    """Break each thing this file checks, in a throwaway copy, and require a non-zero exit.

    A check that has never been seen to FAIL is not yet a check — and this file has already shipped
    two that passed on a healthy repo while silently missing the defect they named (a typo in the
    hooks directory, and a document stating two contradictory suite counts). Both were found by an
    external partner reproducing them in a copy, not by the checker. So the reproduction lives here
    now, runnable by anyone, instead of in one session's scratch directory.

    Copies the tracked WORKING tree (`git ls-files`), not `git archive HEAD`: what matters is
    whether the checks work on what you are about to commit. Testing HEAD instead makes the tool
    unusable before the commit that fixes something — the first version did exactly that and its
    own control case failed on a fix that was written but not yet committed.
    """
    repo_head = subprocess.run(["git", "-C", REPO, "rev-parse", "--verify", "HEAD"],
                               capture_output=True, text=True)
    if repo_head.returncode != 0:
        print("selftest: needs a git repo with at least one commit", file=sys.stderr)
        return 2

    # Each entry declares the check it is probing. Asserting only "exit != 0" is not enough: the
    # "new suite no document names" mutation also trips BOTH count checks, so the naming check could
    # be entirely broken and the probe would still show a green `exit=1`. An external partner caught
    # exactly that — a self-test that passes for the wrong reason proves nothing about the check it
    # was written for. So the expected check name must appear among the FAILED ones.
    MUTATIONS = [
        ("typo in the hooks DIRECTORY (/hookz/)", "canonical shape",
         lambda d: _sub(os.path.join(d, "plugins/goalspec/hooks/hooks.json"),
                        "/hooks/gate-goal-close.sh", "/hookz/gate-goal-close.sh")),
        ("a second, contradictory suite count", "every stated suite count",
         lambda d: _sub(os.path.join(d, "test/README.md"), "mechanical suites",
                        "mechanical suites (not eight mechanical suites)", once=True)),
        ("a carrier claiming there is no CI", "no carrier still claims",
         lambda d: _prepend(os.path.join(d, "test/verdict-nudge-branches.py"),
                            "# There is no CI here.\n")),
        ("versions out of sync", "versions agree",
         lambda d: _json_set(os.path.join(d, ".claude-plugin/marketplace.json"),
                             ["metadata", "version"], "0.0.0-desync")),
        ("frontmatter that is no longer YAML", "frontmatter is valid YAML",
         lambda d: _sub(os.path.join(d, "plugins/goalspec/skills/goalspec/SKILL.md"),
                        "description:", "description: broken: like this", once=True)),
        ("a new suite no document names", "names unnamed-branches.py",
         lambda d: shutil.copyfile(os.path.join(d, "test/gate-branches.py"),
                                   os.path.join(d, "test/unnamed-branches.py"))),
        ("a hook file deleted", "watch-adversary-writes.sh exists",
         lambda d: os.remove(os.path.join(d, "plugins/goalspec/hooks/watch-adversary-writes.sh"))),
        ("the plugin renamed", "plugin name is still",
         lambda d: _json_set(os.path.join(d, "plugins/goalspec/.claude-plugin/plugin.json"),
                             ["name"], "goalspec-renamed")),
    ]

    bad = 0
    with tempfile.TemporaryDirectory() as work:
        for label, expect, mutate in MUTATIONS + [
                ("NOTHING (control — must pass)", None, lambda d: None)]:
            d = tempfile.mkdtemp(dir=work)
            listed = subprocess.run(["git", "-C", REPO, "ls-files", "-z"],
                                    capture_output=True, check=True)
            for rel in listed.stdout.decode().split("\0"):
                if not rel:
                    continue
                src = os.path.join(REPO, rel)
                if not os.path.isfile(src):
                    continue  # tracked but deleted in the working tree
                dst = os.path.join(d, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
            try:
                mutate(d)
            except Exception as e:
                print("%-46s SETUP FAILED: %s" % (label, e))
                bad += 1
                continue
            r = subprocess.run([sys.executable, "test/manifest-checks.py"], cwd=d,
                               capture_output=True, text=True)
            # The failure list the checker prints at the end, one "  - <check name>" per line.
            failed_names = [ln.strip()[2:] for ln in r.stdout.splitlines()
                            if ln.startswith("  - ")]
            if expect is None:
                ok = r.returncode == 0
                why = "" if ok else "control should have passed"
            elif r.returncode != 1:
                ok, why = False, "exit %s, expected 1" % r.returncode
            elif not any(expect in nm for nm in failed_names):
                # THE case this assertion exists for: something failed, but not the check this
                # mutation was written to probe.
                ok, why = False, ("wrong check failed — wanted one naming %r, got: %s"
                                  % (expect, "; ".join(failed_names) or "none"))
            else:
                ok, why = True, ""
            print("%-46s exit=%-2s %s%s" % (label, r.returncode, "ok" if ok else "MISSED",
                                            "" if ok else "  <- " + why))
            if not ok:
                bad += 1
                for line in r.stdout.splitlines()[-6:]:
                    print("    " + line)
    print()
    if bad:
        print("selftest: %d mutation(s) not caught — those checks do not work" % bad)
        return 1
    print("selftest: every mutation caught, control clean")
    return 0


def _sub(path, old, new, once=False):
    t = open(path, encoding="utf-8").read()
    if old not in t:
        raise RuntimeError("pattern not present in %s: %r" % (path, old))
    open(path, "w", encoding="utf-8").write(t.replace(old, new, 1 if once else -1))


def _prepend(path, text):
    t = open(path, encoding="utf-8").read()
    open(path, "w", encoding="utf-8").write(text + t)


def _json_set(path, keys, value):
    d = json.load(open(path, encoding="utf-8"))
    node = d
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    json.dump(d, open(path, "w", encoding="utf-8"), indent=2)


if "--selftest" in sys.argv:
    sys.exit(selftest())


failures = []


def check(name, ok, detail=""):
    print("%-52s %s" % (name, "ok" if ok else "FAIL" + (" — " + detail if detail else "")))
    if not ok:
        failures.append(name)


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# --- 1. Manifests parse, and the two versions agree -------------------------------------------
plugin_json = os.path.join(PLUGIN, ".claude-plugin", "plugin.json")
market_json = os.path.join(REPO, ".claude-plugin", "marketplace.json")

try:
    plugin = load_json(plugin_json)
    check("plugin.json parses", True)
except Exception as e:
    plugin = {}
    check("plugin.json parses", False, str(e))

try:
    market = load_json(market_json)
    check("marketplace.json parses", True)
except Exception as e:
    market = {}
    check("marketplace.json parses", False, str(e))

pv = plugin.get("version", "")
# The marketplace carries ONE version, at top-level `metadata.version` — the per-plugin entries hold
# name/source/description only. CLAUDE.md names that field explicitly as the one to keep in sync.
mv = (market.get("metadata") or {}).get("version") or ""
listed = [e.get("name") for e in (market.get("plugins") or [])]
check("plugin.json has a version", bool(pv), "empty")
check("marketplace.json metadata.version is set", bool(mv), "not found or empty")
check("marketplace lists the goalspec plugin", "goalspec" in listed,
      "listed: %s" % (", ".join(str(x) for x in listed) or "nothing"))
check("versions agree (%s vs %s)" % (pv or "?", mv or "?"), bool(pv) and pv == mv,
      "a push whose version was not bumped is never delivered to installed users")

# The name is load-bearing: a rename breaks auto-update, which only bumps same-name versions.
check("plugin name is still 'goalspec'", plugin.get("name") == "goalspec",
      "renaming forces every installed user through a manual migration")

# --- 2. Frontmatter is real YAML, with a usable name and description ---------------------------
FRONTMATTER_FILES = []
for sub in ("skills", "agents"):
    base = os.path.join(PLUGIN, sub)
    for root, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                FRONTMATTER_FILES.append(os.path.join(root, f))

check("found skill/agent definitions to check", len(FRONTMATTER_FILES) > 0, "none found")

for path in sorted(FRONTMATTER_FILES):
    rel = os.path.relpath(path, REPO)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        check("%s has frontmatter" % rel, False, "no leading --- block")
        continue
    try:
        meta = yaml.safe_load(m.group(1))
    except Exception as e:
        # THE case this check exists for: a bare ": " inside description makes the block
        # unparseable and the skill loads with empty metadata, silently, with no auto-trigger.
        check("%s frontmatter is valid YAML" % rel, False, str(e).replace("\n", " ")[:120])
        continue
    ok = isinstance(meta, dict) and bool(meta.get("name")) and bool(meta.get("description"))
    check("%s frontmatter: name + description survive" % rel, ok,
          "parsed but a required field is empty — the skill would load with no metadata")

# --- 3. Every hook hooks.json references actually exists ----------------------------------------
hooks_json = os.path.join(PLUGIN, "hooks", "hooks.json")
try:
    hooks = load_json(hooks_json)
    check("hooks.json parses", True)
except Exception as e:
    hooks = {}
    check("hooks.json parses", False, str(e))

# CANONICAL SHAPE, not a shell parser. Two rounds of an external partner beat a regex-based
# extractor here: it passed a single-quoted `bash \'${CLAUDE_PLUGIN_ROOT}/hooks/x.sh\'` (where the
# quotes PREVENT expansion, so that hook would fail at runtime) and it failed a perfectly valid path
# containing a space. Parsing arbitrary shell with a regex is the game this project has already
# documented losing twice ("simplify, do not out-clever it" — see the model-id matcher in
# gate-goal-close.sh). So stop parsing: every hook here is written one way, and anything that is not
# written that way is reported for a human to look at rather than silently judged.
CANONICAL = re.compile(
    r'^bash "\$\{CLAUDE_PLUGIN_ROOT\}"/(hooks/[A-Za-z0-9_.-]+\.sh)(?: [A-Za-z0-9_.-]+)*$')

referenced = set()
odd_shapes = []
for _event, groups in (hooks.get("hooks") or {}).items():
    for group in groups or []:
        for hook in (group.get("hooks") or []):
            cmd = (hook.get("command") or "").strip()
            m = CANONICAL.match(cmd)
            if m:
                referenced.add(m.group(1))
            else:
                odd_shapes.append(cmd)

check("every hooks.json command uses the canonical shape", not odd_shapes,
      "not canonical (check by hand): " + " | ".join(odd_shapes[:3]))
check("hooks.json references at least one script", len(referenced) > 0, "none parsed")
for rel_hook in sorted(referenced):
    target = os.path.join(PLUGIN, rel_hook)
    check("hooks.json -> %s exists" % rel_hook, os.path.isfile(target),
          "a hook wired to a missing path silently never runs")

# The exec bit is NOT checked: the canonical shape runs every hook as `bash <path>`, which ignores
# the file mode. Demanding +x would assert something false about what makes a hook run — and if a
# non-canonical shape ever appears, the check above flags it for a human instead of guessing.

# Mirror check: a hook script that exists but nothing registers. Not a failure — external-adversary
# is invoked by the skill, not by an event — so this only reports, to keep the wiring visible.
all_hooks = {"hooks/" + f for f in os.listdir(os.path.join(PLUGIN, "hooks"))
             if f.endswith(".sh")}
unregistered = sorted(all_hooks - referenced)
if unregistered:
    print("%-52s note: %s" % ("hook scripts not registered on any event",
                              ", ".join(os.path.basename(u) for u in unregistered)))

# --- 4. The documented suite count matches reality ----------------------------------------------
suites = sorted(f for f in os.listdir(os.path.join(REPO, "test")) if f.endswith("-branches.py"))
n = len(suites)
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
         8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
word = WORDS.get(n, str(n))

# Every place either document states a suite count must state the RIGHT one. The first version of
# this check just looked for the correct word anywhere in the header, which a contradictory sentence
# satisfies trivially — an external partner proved it with "Eight ... not Nine" and got rc=0. So:
# find EVERY "<word> mechanical/branch suites" phrase and require each to match reality. A check
# satisfiable by prose that says the opposite is not a check.
# Words AND digits, and the noun is optional-ish: an external partner slipped "8 branch suites",
# "eight suites" and "eight mechanical checks" past the first version, which only matched a WORD
# followed by "mechanical|branch suites".
# STATED LIMITS, because a checker that overclaims is the defect this file exists to catch. (a) It
# is a FLOOR over the phrasings anyone here has actually written, not a proof that no wrong count can
# be expressed — a count worded as "eight mechanical CHECKS" still slips through. (b) The noun is
# deliberately "suites" only: widening it to "checks" was tried and immediately fired on the correct
# sentence "and one check by hand", and a checker that flags healthy documentation is worse than one
# with a gap you can read here. What makes it bite anyway is that the count lives in exactly two
# documents and is written the same way in both.
COUNT_RE = re.compile(
    r"\b([A-Za-z]+|\d+)\s+(?:mechanical\s+|branch\s+)?suites?\b", re.I)
DIGITS = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
          "7": "seven", "8": "eight", "9": "nine", "10": "ten", "11": "eleven", "12": "twelve"}

for doc in ("test/README.md", "CLAUDE.md"):
    text = open(os.path.join(REPO, doc), encoding="utf-8").read()
    # Strip markdown emphasis so **Nine** reads as Nine.
    flat = text.replace("**", "").replace("*", "")
    raw = [m.group(1).lower() for m in COUNT_RE.finditer(flat)]
    found = []
    for f in raw:
        f = DIGITS.get(f, f)
        if f in WORDS.values() or f.isdigit():
            found.append(f)
    check("%s states a suite count at all" % doc, len(found) > 0,
          "no count phrase found — the check has nothing to verify")
    wrong = sorted({f for f in found if f != word})
    check("%s: every stated suite count is %d (%s)" % (doc, n, word), not wrong,
          "also says: " + ", ".join(wrong) + " — %d *-branches.py files are present" % n)

# Every suite should also be named somewhere in CLAUDE.md's run list, or nobody will run it.
claude_md = open(os.path.join(REPO, "CLAUDE.md"), encoding="utf-8").read()
for s_name in suites:
    check("CLAUDE.md names %s" % s_name, s_name in claude_md,
          "a suite no document tells anyone to run is a suite nobody runs")

# No carrier may still claim this project has no CI — it does, and a doc saying otherwise sends a
# contributor to run things by hand believing nothing else will. Sweep the tracked tree, not a list.
no_ci = []
for root, dirs, files in os.walk(REPO):
    dirs[:] = [d for d in dirs if d not in (".git", "memory", "__pycache__", ".goalspec")]
    for f in files:
        if not f.endswith((".md", ".py", ".yml", ".sh")):
            continue
        fp = os.path.join(root, f)
        try:
            body = open(fp, encoding="utf-8").read()
        except Exception:
            continue
        # Match the ASSERTION ("No CI — ...", "There is no CI here"), not every mention. A bare
        # `no CI` substring also matches prose ABOUT this check ("...still claims the project has
        # no CI"), which made the check fail on its own documentation the first time it ran. So:
        # only at the start of a line or sentence, which is where a claim lives.
        for m in re.finditer(
                r"^.*?(?:^|[.!?]\s+|—\s*|\"\"\"|#\s*)(?:No CI\b|There is no CI\b).*$",
                body, re.I | re.M):
            line = m.group(0).strip()
            # The CHANGELOG is a historical record: a past entry describing the then-current state
            # is not a stale claim, it is the log doing its job.
            if os.path.basename(fp) in ("CHANGELOG.md", "manifest-checks.py"):
                # CHANGELOG is a historical record; this file necessarily contains the phrase it
                # searches for. Neither is a stale claim.
                continue
            no_ci.append("%s: %s" % (os.path.relpath(fp, REPO), line[:70]))
check("no carrier still claims this project has no CI", not no_ci,
      " | ".join(no_ci[:3]))

print()
if failures:
    print("%d check(s) failed:" % len(failures))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all manifest checks passed")
sys.exit(0)

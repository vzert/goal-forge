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
import json, os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(REPO, "plugins", "goalspec")

try:
    import yaml
except ImportError:
    print("manifest-checks: PyYAML is required (pip install pyyaml).\n"
          "It is not optional here: the whole point of the frontmatter check is that a REAL YAML\n"
          "parser accepts the block, which a hand-rolled regex cannot establish.", file=sys.stderr)
    sys.exit(2)

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

referenced = set()
direct = set()  # invoked WITHOUT an interpreter prefix -> the exec bit is load-bearing there
for _event, groups in (hooks.get("hooks") or {}).items():
    for group in groups or []:
        for hook in (group.get("hooks") or []):
            cmd = hook.get("command") or ""
            # Commands look like: bash "${CLAUDE_PLUGIN_ROOT}"/hooks/foo.sh [args]
            for token in re.findall(r"/hooks/[A-Za-z0-9_.-]+\.sh", cmd):
                rel = token.lstrip("/")
                referenced.add(rel)
                # The exec bit only matters when the harness execs the file itself. Every hook here
                # is invoked as `bash <path>`, which ignores the mode — so demanding +x everywhere
                # would assert something false about what makes a hook run, the exact defect class
                # this plugin exists to catch. Check it only where it is real.
                if not re.match(r"^\s*(bash|sh|/bin/bash|/bin/sh|env\s+bash)\b", cmd):
                    direct.add(rel)

check("hooks.json references at least one script", len(referenced) > 0, "none parsed")
for rel_hook in sorted(referenced):
    target = os.path.join(PLUGIN, rel_hook)
    check("hooks.json -> %s exists" % rel_hook, os.path.isfile(target),
          "a hook wired to a missing path silently never runs")

for rel_hook in sorted(direct):
    target = os.path.join(PLUGIN, rel_hook)
    check("hooks.json -> %s is executable" % rel_hook, os.access(target, os.X_OK),
          "it is exec'd directly, with no interpreter prefix — chmod +x it")

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

test_readme = open(os.path.join(REPO, "test", "README.md"), encoding="utf-8").read()
head = test_readme[:400]
check("test/README.md states %d (%s) branch suites" % (n, word),
      re.search(r"\*\*%s\*\*" % word, head, re.I) is not None,
      "header says a different count than the %d *-branches.py files present" % n)

claude_md = open(os.path.join(REPO, "CLAUDE.md"), encoding="utf-8").read()
check("CLAUDE.md states %d (%s) branch suites" % (n, word),
      re.search(r"the %s branch suites" % word, claude_md, re.I) is not None,
      "CLAUDE.md's count drifted from the %d files present" % n)

# Every suite should also be named somewhere in CLAUDE.md's run list, or nobody will run it.
for s in suites:
    check("CLAUDE.md names %s" % s, s in claude_md,
          "a suite no document tells anyone to run is a suite nobody runs")

print()
if failures:
    print("%d check(s) failed:" % len(failures))
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print("all manifest checks passed")
sys.exit(0)

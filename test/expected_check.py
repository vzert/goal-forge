"""The `--expected` half of `--compare`, shared by every suite that has one.

`--expected` names, BEFORE the comparison runs, the cases whose diff is intended. Until this module
a suite checked only one direction: a diff nobody declared is a regression. The other direction went
unchecked — a declared change that never happened printed "parity OK" with rc=0. That is how
external-adversary case 38 passed EMPTY in 0.49.2: a global `core.hooksPath` skipped the hook the
fixture planted, the case read the same against the broken code, and `--expected 36,37,38` reported
"parity OK, 3 intended change(s)" with only two of them real (p-6dd59b09af). A declaration that
nothing checks is the muted alarm gate-branches' docstring already warns about.

Judged PER PREFIX, not per case: a prefix such as `stale-` legitimately covers several cases of
which only some change. So each prefix must (1) name at least one case — else it is a typo or a
renamed case — and (2) cover at least one case that changed. What this cannot see: a prefix wide
enough that one real diff under it hides an empty case beside it. Name the cases you mean.

Imported by the suites as `import expected_check` (their own directory is on sys.path when run as
`python3 test/<suite>.py`). Not a suite: the name does not end in `-branches.py`, so the suite
counts in manifest-checks do not see it.
"""


def unmet(expected, names, diffs):
    """[(prefix, why)] for every declared prefix that no case changed under. Empty means all met."""
    out = []
    for p in expected:
        matched = [n for n in names if n.startswith(p)]
        if not matched:
            out.append((p, "names no case"))
        elif not any(d.startswith(p) for d in diffs):
            shown = ", ".join(matched[:3]) + (", ..." if len(matched) > 3 else "")
            out.append((p, "covers %s, none changed" % shown))
    return out


def report(expected, names, diffs):
    """Print each unmet prefix; True when there is one, which the caller turns into rc=1."""
    bad = unmet(expected, names, diffs)
    if bad:
        print("UNMET EXPECTED: %d declared change(s) did not happen — %s"
              % (len(bad), "; ".join("%s (%s)" % b for b in bad)))
    return bool(bad)

# Worked examples — well-formed vs ill-formed goal-specs

Read this when writing the `## Goal-spec` (step 4 of the loop), especially in an unfamiliar
domain. Two pairs: a generic BAD/GOOD spec, and the minimal-fix-lens pair (the only concrete
demo of Q2's surface-the-minimal-fix lens).

**BAD (narrative, proxy, no baseline):**
> Objective: audit the service. Success: improve latency. Done: when I've reviewed performance.

Fails: objective = the ticket's narrative; "improve" is not measurable; no baseline or source; "reviewed" ≠ achieved.

**GOOD (grounded, falsifiable, complete):**
> **Objective**: determine whether the checkout endpoint can meet its SLO at real traffic and, if not, find the config that does — or prove with clean evidence that it can't.
> **Success**: (a) p95 latency ≤ 300ms under the load-test profile (baseline today = 520ms); (b) error rate ≤ 0.1% on the same run; (c) zero contradiction between the APM number and the load-test client's number (delta ≤ 20%).
> **Pre-mortem**: (1) the "DB is the bottleneck" claim inherited from the prior ticket may be a phantom — I re-derive it from a fresh trace; (2) "all latency is server-side" may be a weak proxy — I decompose by span; (3) it may be a client/network artifact, not the service — I check the load generator's own timing.
> **No-harm**: there are healthy replicas serving traffic; I don't drain them without a live replacement. I don't raise the connection pool before I've fixed a diagnosed leak.
> **Autonomy**: I run the load test and the trace analysis myself; only authorizing a production config rollout is a human decision — I raise it as a modal when I have the number to decide on, not as a line in the summary.
> **Done**: actionable config applied and verified by read-back, every non-owned factor assigned to an agent, no live contradiction.

**BAD (systemic frame eats the symptom-fix — the over-reach mirror of Q1):**
> Objective: the app must store and display all timestamps correctly and permanently. Success: a migration corrects the historical data across all affected tables.

Fails the surface-the-minimal-fix lens: the user reported *one* field displaying "6h off." The spec jumped to a system-wide, irreversible prod migration and offered only *sizes* of it — the minimal reversible option (a read-layer fix for the reported field, touching no prod data) was never on the table, so the user could pick *how big a migration* but never *migration vs. none*.

**GOOD (both forks surfaced; the user picks depth):**
> **Objective**: make the timestamp the user flagged display correctly, and *separately* decide whether to also correct the stored historical data.
> **Success**: (a) minimal — the flagged `synced_at` renders in the right zone via a reversible read-layer cast, verified against a fresh sync, no prod data mutated; (b) systemic (opt-in, ratify-gated) — *if* the user chooses it, `+6h` on the uniformly-shifted columns, verified by read-back, mixed-source webhook columns excluded.
> **Autonomy**: I ship (a) reversibly now; (b) is a terminal prod mutation — I put *migrate vs. leave-history* to the user through the ratify gate with the blast-radius (columns, reversibility) visible, not chosen by omission.

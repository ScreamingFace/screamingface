# OME-1118 — Phase 1 build order, and what each deploy makes validatable in SigNoz

**Spec:** `docs/spec/2026-08-22-observability-traceability-review.md` §6 (`OME-936`, merged).
**Epic:** `OME-1118`. **Children:** `OME-1119`, `OME-1120`, `OME-1121`.
**Depends on, not owned:** `OME-938`, `OME-940` (Phase 0, epic `OME-935`).
**Local acceptance:** `packages/screamingface/tests/e2e/test_correlation_chain.py` (`OME-1105`).

The spec fixes *what* Phase 1 does. This plan fixes the order, and answers one question the
spec does not: **after a change merges, is built, and is deployed — what can actually be
seen in SigNoz?** That question has a sharper answer than expected, and it changes the
ordering.

## 1. What SigNoz holds today — logs, not traces

Verified, not assumed:

- **SigNoz is deployed** at `https://signoz.pulse.dev.openmined.org`, and PR previews already
  link into its logs explorer filtered by `k8s.namespace.name` — see
  `.github/scripts/preview_contract.py:315`. So a k8s collector ships pod stdout into it.
- **Nothing in this repo exports traces.** A search across every Python file for
  `opentelemetry|OTLP` returns exactly one hit: `packages/url4/tests/unit/
  test_import_isolation.py`, a test asserting OTel is **not** imported. The frame→OTLP
  exporter is Phase 2 and unbuilt. `apps/aigateway/DEPLOYMENT.md:365` says so directly —
  "SigNoz/Prometheus integration are follow-up infrastructure work".

**Consequence for Phase 1: the trace view and service map stay empty for us. Everything below
is log search.** Any acceptance criterion phrased as "see the trace in SigNoz" is
unsatisfiable this phase, and should not be written into a ticket.

## 2. The constraint that decides filter-vs-grep

**Our services emit plain text, not JSON.** The engine formats records as
`"%(levelname)s:     %(name)s %(run_context)s%(message)s"`
(`screamingface_engine/logs.py:43`); aigateway configures no formatter at all and inherits
uvicorn's.

The collector attaches `k8s.*` resource attributes — namespace, pod, container — so those
**are** filterable. But `trace_id` and `gateway_call_id` will live *inside the message body*,
so in SigNoz they are **full-text body search**, not attribute filters.

That is enough to deliver the spec's stated payoff, which is deliberately modest: *"one
trace_id greppable across every pod's logs with zero new infrastructure."* It is **not**
enough to group by trace, chart per-trace latency, or alert on a correlation attribute.

**Recommendation, not folded into this phase:** a follow-up to emit JSON logs, which turns
every id into a real attribute. Doing it *inside* `OME-938`/`OME-1120` would couple a
log-format migration to a correlation change and make both harder to review. Flagged here so
the ceiling is a decision rather than a surprise.

The engine already has the right seam for its half: `RunContextFilter` and the
`run_context` field exist (`logs.py:125`), so `OME-940` has somewhere to put a trace id
without inventing a mechanism.

## 3. Deployment path — merging is not deploying

| Component | Release lane | Reaches the cluster when |
|---|---|---|
| `apps/aigateway` | release-please → `aigateway-v*` → `release-aigateway.yml` (GHCR + Helm) | a release tag is cut **and** the chart is rolled out |
| `apps/screamingface-engine` | release-please → `screamingface-engine-v*` → `release-screamingface-engine.yml` | same |
| `packages/screamingface` | release-please → PyPI (Trusted Publishing) | **never** — it is the client; the *user* upgrades |

Two things follow, and both matter for sequencing:

- **`OME-1121` (`Report.trace_id`) is not a deployment at all.** It ships to PyPI and takes
  effect when a user upgrades. It cannot be validated in SigNoz — it is validated in a
  notebook or a REPL.
- A merged PR changes nothing observable until a release tag is cut and rolled out. "Merged"
  and "validatable" are separated by a release, so the table below is keyed on **deployed**.

## 4. What becomes validatable, in order

Each row is a SigNoz logs-explorer query and the answer it returns once that row's change is
deployed. `TID` is a client-minted trace id; `NS_GW` is `sf-aigw`; `NS_ENG` is the engine's
namespace (one of `sf-fusion` / `sf-scoreboard` — **unconfirmed**, see §6).

| # | Deployed | SigNoz query | Returns |
|---|---|---|---|
| 0 | *today* | `k8s.namespace.name="NS_GW"` + body contains `TID` | **nothing** — no service writes an id to a log |
| 1 | `OME-1119` engine → gateway | *(unchanged)* | **still nothing** |
| 2 | `OME-938` `gateway_call_id` | `NS_GW`, body contains `gateway_call_id` | every gateway line carries a call id; one run's lines groupable **by eye**, not by attribute |
| 3 | `OME-1120` gateway joins trace | `NS_GW` + body contains `TID` | **the gateway's lines for that run** — first row where a trace id is findable at all |
| 4 | `OME-940` engine logs identity | `NS_ENG` + body contains `TID` | the engine's control-plane lines for that run |
| 5 | 3 **and** 4 | body contains `TID`, no namespace filter | **lines from both namespaces — the end-to-end claim** |

**Row 1 is the point of this plan.** `OME-1119` puts the id on the wire and produces **no
observable change in SigNoz whatsoever**. It is a prerequisite whose payoff appears only at
row 3. Shipping it and then looking for it in SigNoz would read as a failed change; it is not.
Anyone validating after that deploy must check the *e2e rung*, not the log backend.

**Row 5 is the phase's actual acceptance.** Rows 3 and 4 are each half a join.

## 5. Build order, and why

```
OME-1121  Report.trace_id        (client; unblocks a human obtaining an id at all)
OME-1119  engine -> gateway      (wire; no SigNoz signal on its own)
OME-938   gateway_call_id        (Phase 0; the contextvar OME-1120 needs)
OME-1120  gateway joins trace    (first SigNoz-visible correlation)
OME-940   engine logs identity   (closes the join)
```

- **`OME-1121` first** even though it is the least technical. Until it lands, a user cannot
  obtain an id from a completed run, so nothing downstream can be validated by a human
  end-to-end — only by tests. It is also independent of every other item.
- **`OME-938` before `OME-1120`** — `OME-1120` joins the trace id to the contextvar `OME-938`
  installs. Reversing them means building the contextvar twice.
- **`OME-940` last** because it is the second half of the join; landing it before `OME-1120`
  leaves rows 4 and 5 indistinguishable to a validator.

Each of `OME-1119`, `OME-1120`, `OME-940` must delete its strict xfail in
`test_correlation_chain.py` in the same PR. That is not a convention — a strict xfail that
starts passing fails the suite, so CI enforces it.

## 6. Open questions this plan cannot close

1. **Which namespace runs the engine.** Firecall grants `sf-aigw`, `sf-fusion`,
   `sf-scoreboard`. `sf-aigw` is evidently the gateway; the engine is inferred, not verified —
   nobody here has cluster access (`OME-1122` carries the same gap for the notebook).
2. **Whether the k8s collector already parses any structure** out of our plain-text lines. If
   it applies a regex/parser at ingest, some fields may be attributes after all. Checking it
   requires SigNoz access.
3. **`SIGNOZ_TOKEN`'s type** — SigNoz API key or Cloudflare Access service token. Decides
   whether validation can be automated or stays a browser task; a single value cannot be an
   Access client-id/secret pair.

None of the three blocks implementation. All three block *automated* SigNoz validation, which
is why the local ladder (`OME-1105`) remains the gate that actually holds.

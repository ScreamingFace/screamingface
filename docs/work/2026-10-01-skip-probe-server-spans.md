---
ticket: OME-1217
stack: aigateway
status: done   # planned | in_progress | done | blocked
started: 2026-10-01
finished: 2026-10-01
---

# skip-probe-server-spans — stop emitting server spans for health-check probes

## Intent

`GET /healthz` is 60.2% of aigateway's spans (14,403 / 23,906 in 24h) and they are ROOT spans, so
they bury real requests in the trace list. aigateway's server spans come from our own
`middleware/call_id.py`, not `FastAPIInstrumentor`, so the stock OTel env knob does nothing today.
Skip span creation for probe routes in the middleware — the span only; call-id binding, the
`x-aigw-trace-id` header and request handling all still run.

## Owner decision (2026-10-01, Sergey Bershadsky) — option A

First pass stopped on a stale premise: `_route_name(scope)` returns the RAW path, and FastAPI
0.141's private `_IncludedRouter.matches()` returns FULL with an empty child scope, so the route
template is not resolvable before routing through any public API. It IS public after routing, as
`scope["route"].path`. Decision: **build the span as today; after routing, flag probe-route spans;
drop flagged spans in a SpanProcessor so they are built but never exported.** Public APIs only.

## Design

- **Setting:** `OTEL_PYTHON_EXCLUDED_URLS`, OTel's own semantics (comma-separated regexes,
  `re.search`). Unset → `^/healthz$`. Set-but-blank → exclude nothing. Invalid regex → warning +
  default (never raises).
- **Matched against:** the resolved route template (`scope["route"].path`) when routing resolved
  one. When it did not (Starlette answered without dispatching — e.g. the `/healthz/` slash
  redirect), against the raw path with trailing slashes stripped, so `/healthz/` is dropped too
  (owner requirement). Query strings never reach either. Only flagged on NORMAL completion: a probe
  that raises keeps its span (fails toward more telemetry).
- **Drop:** `DropExcludedSpans(delegate)` — a SpanProcessor wrapping the exporter's processor; it
  forwards everything except spans carrying the `aigw.span.excluded` flag. `tracing.install` wraps
  the batch processor with it.
- **Name/parent of real spans unchanged.** `server_span` now yields the span (or None when off).
- **Engine-reusable:** `span_exclusion.py` holds the setting parser, the matcher and the
  processor; it imports only stdlib + `opentelemetry-sdk`, no aigateway module — liftable into the
  engine's control plane (OME-1218: `url4.run` becomes a child of the accept span; probes excluded
  there with the same knob and semantics).

## Planned changes

- `apps/aigateway/src/aigateway/span_exclusion.py` (new) — `SpanExclusion`, `DropExcludedSpans`,
  `mark_excluded`.
- `apps/aigateway/src/aigateway/tracing.py` — `server_span` yields the span; `install` wraps the
  processor.
- `apps/aigateway/src/aigateway/middleware/call_id.py` — flag after the app returns.
- `apps/aigateway/tests/unit/test_probe_span_exclusion.py` (new).

## Test plan

- Through the middleware on a real FastAPI app, exporter wired with the dropper as `install` wires
  it: probe → no exported span, still 200, call id + `x-aigw-trace-id` intact; real request →
  one span, same name, same parent; `/healthz/` and `/healthz?x=1` → dropped; a parametrised route
  template pattern drops `/items/42` but not `/work`; a probe that raises keeps its span.
- `create_app`'s `/healthz` dropped by default, `/v1/models` exported.
- `tracing.install` wires the dropper (exporter/processor classes substituted in-memory).
- Setting parsing: unset / blank / OTel regex semantics / invalid → default + warning.

## Acceptance

- Tests green, prior tests untouched, `run_gates.py aigateway` green.
- After deploy (owner): `GET /healthz` disappears from the SigNoz span-name breakdown.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus a new `docs/tasks` mirror (none existed) at `in_review`.
- **Commits:** see the PR (single commit, `feat(aigateway): …`).
- **Gates:** `run_gates.py aigateway --base origin/main` — ALL GATES GREEN (append-only check
  included: no prior test touched).
- **Deviations:**
  - First pass BLOCKED on the stale premise (see Owner decision); resolved by option A.
  - Probe spans are built in-process and dropped at export ("never exported", not "never created")
    — the accepted cost of public APIs only.
  - Unresolved requests (no route dispatched) fall back to the slash-stripped raw path so
    `/healthz/` is also dropped, per the owner's test list.
  - Separate finding, not fixed here: `tracing._span`'s off-path check tests `NoOpTracerProvider`,
    but an un-installed OTel global is a `ProxyTracerProvider`, so the "off path is free" claim
    does not hold (non-recording proxy spans are still created). Harmless, untouched.
  - Linear stayed in Backlog during the work (lane rule: only In Review + PR link + this decision
    comment).

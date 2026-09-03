---
ticket: OME-1105
stack: screamingface
started: 2026-09-03
status: in_progress
finished:
---

# OME-1105 — Correlation-chain ladder in the local e2e harness

## Intent

Make the tracing roadmap's rungs testable **without cluster access**. The live-k8s notebook
(`OME-1074`) turned out to need credentials gated behind a break-glass tool the owner does
not currently have, so the roadmap's acceptance evidence was blocked on someone else. The
local harness needs only Docker and already boots the real spine — real engine subprocess,
real aigateway subprocess against a Postgres testcontainer, log files on disk.

k8s adds deployment realism (the Runner Job indirection, the mesh edge). It adds nothing to
the question *does a traceparent survive engine → gateway*, which is what rungs 2–4 ask.

## Design decisions

**D1 — `FakeGateway` for rungs 1–2, not `CacheSeededGateway`.** The cache-seeded backend is
the *real* aigateway as a **subprocess**, so a test in this process cannot observe the headers
it received; its only channel is `aigateway.log`, and aigateway does not log an inbound
traceparent until rung 4 exists. `FakeGateway` is an in-process `BaseHTTPRequestHandler`, so
inbound headers are directly observable. Rungs 3–4 are log assertions and therefore keep the
real gateway.

**D2 — capture lives in the concrete backend, never on the port.** `harness/ports.py` states
the invariant outright: `ReplayBackend` is exactly `start() -> base_url` / `stop()`, and
growing it with introspection would couple the engine boot to one backend's internals. The
recorder is a `FakeGateway` attribute, mirroring the existing `refusals` accessor, and the
test holds the concrete type.

**D3 — `xfail(strict=True)`, not plain xfail.** A strict xfail that *starts passing* fails
the suite. That is the whole mechanism: the PR implementing a rung is forced to delete its
marker in the same change, so the ladder cannot drift out of date and a later regression
cannot slip back to "expected failure". A non-strict xfail would silently absorb both.

**D4 — rung 1 is NOT xfail.** `OME-967` is merged, so it must pass today. It is the
regression guard for the one rung that already works.

## Planned changes

- `packages/screamingface/tests/e2e/harness/fake_gateway.py` — record inbound request headers
  alongside the existing refusal record; expose them read-only.
- `packages/screamingface/tests/e2e/test_correlation_chain.py` *(new)* — four rungs.
- This ledger + the `docs/tasks/` mirror.

## Test plan

The tests *are* the deliverable, so the plan is what each rung pins:

1. **Rung 1** (passes today) — the client mints one well-formed W3C trace id and holds it;
   the id it reports is the id it sent. Guards `OME-967` against regression.
2. **Rung 2** (`xfail(strict=True)`) — the gateway received a `traceparent` whose trace id
   equals the client's. Fails today: the engine sends none.
3. **Rung 3** (`xfail(strict=True)`) — every `aigateway.log` line carries `gateway_call_id`.
   Fails today: `OME-938` unbuilt.
4. **Rung 4** (`xfail(strict=True)`) — the same trace id appears in `engine.log` **and**
   `aigateway.log`. Fails today: nothing joins the id to either log.

## Acceptance

- Rung 1 passes; rungs 2–4 xfail strictly.
- The lane stays opt-in (`SCREAMINGFACE_TEST_E2E=1` + Docker) and out of CI.
- `ReplayBackend` is unchanged.
- No prior test modified; `run_gates.py screamingface` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `tests/e2e/harness/fake_gateway.py` (header recorder),
  `tests/e2e/test_correlation_chain.py` (new, 5 rungs), the ledger and the mirror.
- **Commits:** `test(screamingface): add the correlation-chain ladder to the e2e harness`
  (sha at squash-merge).
- **Gates:** `run_gates.py screamingface` — see below. The ladder itself was **observed
  running against the real stack**: `SCREAMINGFACE_TEST_E2E=1 pytest tests/e2e/
  test_correlation_chain.py -m e2e` → **5 xfailed, 0 failed**, with the real engine
  subprocess, the real aigateway (Postgres testcontainer) and `FakeGateway` all booting.
  Prerequisite discovered: the lane needs `uv sync --extra runtime` and
  `screamingface prepare draco` (100 cases) — without assets every rung skips, exactly like
  `test_failures.py` and `test_boards.py`.
- **Deviations:**
  - **Rung 1 became a strict xfail, and that is the unit's most valuable finding.** It was
    planned to PASS, since `OME-967` is merged. It cannot: from the PUBLIC SDK surface there
    is no way to read a completed run's trace id. `trace_id` reaches only the error hierarchy,
    `Report` carries no trace field, and a board run **does not raise** — DRACO collects case
    errors into rows (`on_error="collect"`), so a run whose every model call failed still
    returns a Report with no id anywhere. The frame stream did not fill the gap either: no
    event reaching `on_event` carried a traceparent. This does not retract `OME-967`, which is
    pinned by `tests/test_client_protocol.py` against the wire — it says the *user-facing*
    half is missing, and it is the user with bad results rather than an exception who most
    needs to quote an id. **Closing rung 1 means giving `Report` a trace id.**
  - **Rung 4 split into 4a (engine log) and 4b (gateway log).** They land in different
    changes and therefore cannot share one marker.
  - **A vacuous-pass bug was caught by running it.** Rung 2 first reported `XPASS(strict)`:
    both `trace_ids_seen()` and the client's id set were empty, and `set() == set()` is true,
    so a rung asserting propagation passed while nothing propagated. The non-empty assertion
    now comes first, with a comment recording why. Worth noting that only *executing* the
    ladder surfaced this — review would not have.
  - Fixture paths initially pointed at `FIXTURES_DIR` rather than `SNAPSHOTS_DIR`.

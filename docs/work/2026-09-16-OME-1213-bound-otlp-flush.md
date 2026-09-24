---
ticket: OME-1213
stack: screamingface-engine
status: done
started: 2026-09-16
finished: 2026-09-16
---

# OME-1213 — Bound the OTLP flush and say when spans were dropped

## Intent

`OME-1211` (#958) reverted a bad chart default. This unit fixes the reason that bad default
stayed **invisible for a day**, and it is a real defect independent of any chart value.

`OtlpSpanSink.close()` discards the one signal the SDK gives it:

```python
def close(self) -> None:
    self._processor.force_flush()   # return value DISCARDED
    self._processor.shutdown()      # internal default timeout 30_000 ms
```

Verified against the installed SDK (opentelemetry-sdk **1.44.0**):
`force_flush(self, timeout_millis: int | None = None) -> bool`. It tells us the flush failed and
we throw the answer away. Against an unreachable collector that is (a) the full retry budget paid
at every process exit and (b) a failure recorded only in OTel's internal logger — at the engine's
own log level the run looks clean.

The start-up line compounds it:

```python
logger.info("otlp span export enabled service=%s", ...)
```

It means **configured**, not **working**. `sink_from_env` checks that an endpoint string is
non-blank; it has never spoken to the collector. "Enabled" reads as a success report.

This is not only about the NetworkPolicy case. `https://signoz.pulse.dev.openmined.org/v1/traces`
answers `200 text/html` (the SigNoz UI's SPA catch-all — a nonsense path answers identically);
OTel treats any 2xx as success, so that hostname discards every span while reporting perfect
health. Naming the endpoint in the log is what makes that diagnosable rather than mystifying.

## Design decisions

**D1 — the warning names the endpoint, so the sink must know it.** `OtlpSpanSink` is constructed
with a `SpanProcessor` and never saw the endpoint; the exporter keeps it private (`_endpoint`).
Adding a keyword-only `endpoint: str = ""` set by `sink_from_env` is the honest route. Reading
the environment from inside the adapter was rejected: the adapter's whole point is that it is
handed its collaborators, and `sink_from_env` is already the composition seam that reads env.

Defaulted rather than required, because prior tests construct `OtlpSpanSink(SimpleSpanProcessor(
exporter))` directly and rule 5 forbids editing them to fit new code.

**D2 — 5 s flush bound.** The internal default is 30 s. The process is *exiting*: the question is
"how long is it worth blocking a finished run to save its spans?" 5 s clears a healthy collector
with a queued batch by a wide margin, and caps the pathological case at something a human reads
as a pause rather than a hang. A named constant, not a literal, so the number is arguable in one
place.

**D3 — `shutdown` moves into a `finally`.** If `force_flush` raises, the old code leaked the
exporter thread. One keyword, and it makes the failure path have exactly one shape.

**D4 — the flush-failure branch is tested with a STUB processor, not the real SDK.** This file's
ethos is "drive the real SDK path" and that is right for the *span conversion* — the sampled-flag
trap lives there. It is wrong here: making a real `BatchSpanProcessor` return `False` needs an
exporter that sleeps past a deadline, i.e. a race dressed as a test. What is new in this unit is
OUR branch — do we read the return, do we warn, do we still shut down — and a stub tests exactly
that, deterministically. The real-SDK path keeps a test too: a successful flush must NOT warn.

**D5 — NOT in scope: a start-up liveness probe.** It would catch the `200 text/html` footgun
head-on, but it adds a network round-trip to the runner's ~227 ms cold-start budget — the exact
constraint the lazy OTel import exists to protect (~62 ms, measured in `OME-1130`). A design fork
with a real cost, not a bug fix. Owner's call, separate issue.

**D6 — the error-swallowing contract (`OME-1130` D4) is unchanged.** A collector outage must never
fail a run. This unit makes the outage *audible*, not fatal. No new raise, no new exit code.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/tracing/otlp.py`
  - `_FLUSH_TIMEOUT_MS` constant (D2).
  - `OtlpSpanSink.__init__` gains keyword-only `endpoint: str = ""` (D1).
  - `close()` bounds the flush, warns on a `False` return, shuts down in a `finally` (D2, D3).
  - `sink_from_env` resolves the endpoint, passes it, and logs *configured* with it.
- `apps/screamingface-engine/tests/unit/test_otlp_sink.py` — new tests appended (rule 5: nothing
  above is edited).

## Test plan

- A flush that returns `False` logs exactly one WARNING, naming the endpoint — asserted on
  `caplog.records` (`levelname` + the resolved message), **never** on `repr()`. A `repr()`-based
  assertion is what let a security test survive mutation in `OME-1132`.
- A successful flush through the REAL SDK path logs no warning — the guard against a warning that
  always fires.
- `shutdown` still runs after a failed flush (no leaked exporter thread).
- The flush is called with a bounded timeout, not the SDK default.
- `sink_from_env` logs the endpoint and does not claim "enabled".
- Both endpoint variables resolve for the log line, matching `otlp_configured`'s contract.

Mutation check: drop the timeout argument, invert the `if`, and remove the `endpoint` from the
message — each must kill a test.

## Acceptance

- `run_gates.py screamingface-engine` green.
- An unreachable collector yields one bounded, explicit WARNING per run instead of an unexplained
  delay and a clean-looking log.

## Outcome

- **Actual files:**
  - `apps/screamingface-engine/src/screamingface_engine/tracing/otlp.py` — `FLUSH_TIMEOUT_MS`
    (public, not the planned `_FLUSH_TIMEOUT_MS`: the tests import it, and a leading underscore
    crossing a module boundary is a lie about the contract); `OtlpSpanSink.__init__` gains
    keyword-only `endpoint`; `close()` bounds the flush, shuts down in a `finally`, warns on a
    `False` return; `sink_from_env` logs *configured* with the endpoint; new `_endpoint()` helper.
  - `apps/screamingface-engine/tests/unit/test_otlp_sink.py` — 7 tests appended, nothing above
    edited except two import lines.
  - This ledger and `docs/tasks/2026-09-16-OME-1213-bound-otlp-flush.md`.

- **Gates:** `run_gates.py screamingface-engine` **ALL GATES GREEN** — append-only, ruff check,
  ruff format, pyright, `check_layering.py`, pytest with coverage ≥80. The append-only gate
  PASSED this time (assertions rise), unlike `OME-1211` where a revert drove them down.

- **Verification beyond the gates:**
  - **Six mutations, six killed** — drop the timeout bound; invert `if not flushed`; blank the
    endpoint in the warning; remove the `finally`; revert the log line to "enabled"; reverse the
    `OTLP_ENDPOINT_VARS` precedence. Each named a different test, so no test is carrying another.
  - **Cold start re-verified, not assumed.** `import screamingface_engine.runner.main` still
    loads **0** `opentelemetry` modules. This unit touches only the lazily-imported adapter, and
    `_endpoint` reuses `OTLP_ENDPOINT_VARS` from `relay` — a module already imported — so it adds
    no import cost to the ~227 ms budget.

- **Deviations:**
  - **One test beyond the plan: `test_the_exporter_is_shut_down_even_when_the_flush_raises`.**
    Writing the mutation list exposed that the planned tests covered the `False` return but not
    the RAISE, so D3's `finally` was an untested claim — removing it killed nothing. The
    exporter can genuinely throw (DNS failure on the collector host, TLS error), so the branch is
    real, not defensive padding.
  - **The constant is public.** Planned as `_FLUSH_TIMEOUT_MS`; shipped as `FLUSH_TIMEOUT_MS` in
    `__all__`, matching `DEFAULT_SERVICE_NAME` beside it.
  - **Not verified against a real collector.** Nothing here has failed to export to a live SigNoz.
    The behaviour is proven through the SDK's own contract and a stub; the deployed proof needs
    the platform to open the network path (see `OME-1211`).

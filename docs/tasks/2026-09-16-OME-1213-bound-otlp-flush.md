---
id: OME-1213
linear_url: https://linear.app/openmined/issue/OME-1213
status: done
type: null
priority: 2
labels: [screamingface-engine, agentic, autonomous]
created: 2026-09-16
closed: 2026-09-16
---

# Bound the OTLP flush and say when spans were dropped

`OME-1211` reverted a bad chart default. This is the reason that default stayed **invisible for a
day** — and it is a defect independent of any chart value.

`OtlpSpanSink.close()` discards `force_flush`'s return. Verified against the installed SDK
(opentelemetry-sdk **1.44.0**): `force_flush(timeout_millis: int | None = None) -> bool`. The SDK
reports the failure and the code throws the answer away, then calls `shutdown()` whose internal
default timeout is 30 s. Against an unreachable collector: the full retry budget at every process
exit, recorded only in OTel's internal logger.

Three things worth knowing before touching this area:

- **"enabled" in the start-up line means CONFIGURED, not working.** `sink_from_env` only checks
  that an endpoint string is non-blank; it has never spoken to the collector. Reworded, and the
  endpoint is named — which is what makes the footgun below diagnosable.

- **⚠️ `https://signoz.pulse.dev.openmined.org/v1/traces` answers `200 text/html`** — the SigNoz
  UI's SPA catch-all, identical to a nonsense path. OTel treats any 2xx as success, so that
  hostname discards every span while reporting perfect health.

- **The error-swallowing contract (`OME-1130` ledger D4) is deliberate and UNCHANGED.** A
  collector outage must never fail a run. This unit makes the outage audible, not fatal — no new
  raise, no new exit code.

Two traps recorded so they are not re-introduced:

- **Do not assert on `repr()` of log records or span events.** It renders as
  `<object at 0x...>` and the assertion passes against almost anything — that is exactly how a
  security test survived mutation in `OME-1132`. Walk `caplog.records` and assert on `levelname`
  and the resolved message.

- **Do not test the flush-failure branch through a real `BatchSpanProcessor`.** Making it return
  `False` requires an exporter that sleeps past a deadline, which is a race dressed as a test.
  The stub processor is deliberate (ledger D4); the real-SDK path still covers the success case.

**Explicitly out of scope: a start-up liveness probe.** It would catch the `200 text/html` case
head-on, but costs a network round-trip against the runner's ~227 ms cold-start budget — the
constraint the lazy OTel import exists to protect (~62 ms, measured in `OME-1130`). Design fork,
owner's call.

Ledger: `docs/work/2026-09-16-OME-1213-bound-otlp-flush.md`

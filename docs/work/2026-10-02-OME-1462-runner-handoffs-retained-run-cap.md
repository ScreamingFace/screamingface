---
ticket: OME-1462
stack: screamingface-engine
status: done
started: 2026-10-02
finished: 2026-10-05
---

# runner-handoffs-retained-run-cap — cover the #1215/#1216 hand-offs, cap retained runs

## Intent

Follow-ups from the reviews of #1215 (OME-946) and #1216 (OME-1218). (1) Two production
hand-offs in `runner/main.py::_run_process` survived mutation: `SpanRelay(...,
traceparent=traceparent)` (the only thing that makes `url4.run` a child of `url4.accept`) and
the no-pool `retain=` wiring. Each gets a test that kills its mutation. (2) Owner decision
(Sergey, 2026-10-02, Linear comment): a **per-subject cap for retained (failed/timed_out)
runs** on the shared `url4-events` stream, messages AND bytes, so a failure storm cannot fill
the stream and evict other runs' terminal frames under `discard=OLD`. No separate stream.
(3) Move the duplicated span-sink loader into the `tracing/` shared leaf without importing
OTel on the runner cold path. (4) Triage the three unconfirmed minors.

## Design — the retained-run cap (D1..D5)

- **D1 — what is capped.** A retained subject keeps at most `retained_max_msgs = 256`
  messages AND at most `retained_max_bytes = 1 MiB` of payload, counted from the TAIL (the
  newest frames — the failure, its last logs, the terminal frame — are the post-mortem).
  Constants on `EventsStreamConfig` (code defaults, not chart values: the run child builds its
  publisher with defaults, so a chart value would not reach the no-pool path without new env
  plumbing — out of scope, noted below).
- **D2 — enforcement: trim, don't skip.** Where the reclaim paths used to SKIP the purge for a
  retained run, they now call `trim_retained(topic)`:
  1. `purge_stream(filter=subject, keep=256)` — the message cap, enforced by the broker in one
     call;
  2. forward scan of the ≤256 survivors with `get_msg(next_by_subj)` (bounded: at most 256
     round trips, on a detached reclaim task, never on a run's slot), collecting
     `(stream seq, payload bytes)`;
  3. walk back from the tail summing bytes; the first message that would overflow the budget
     sets the cut, and `purge_stream(filter=subject, seq=cut)` drops everything below it.
- **D3 — INVARIANT: the terminal frame is never trimmed.** The cut is computed with the tail
  always kept, even when it alone exceeds the byte budget (a frame is ≤ `max_msg_size`,
  2 MiB). Dedupe (worker claim gate) and App admission read exactly that frame.
- **D4 — worst-case footprint.** Per retained subject ≤ max(1 MiB, one frame ≤ 2 MiB). Before:
  up to 20 000 msgs × 2 MiB, i.e. bounded only by the whole 1 GiB stream. After: ~1024
  retained failures (at the 1 MiB budget) inside one 24 h `max_age` window before retained
  runs alone could fill the stream. Residual risk, stated: a storm beyond that still evicts
  oldest-first under `discard=OLD`; that is the accepted shape of "per-subject cap, no
  separate stream".
- **D5 — failure direction.** Trim is best-effort like the purge it replaces: any error is
  logged and the subject waits for `max_age` (the backstop that already existed). A trim never
  raises into the run's outcome.

## Planned changes

- `src/screamingface_engine/adapters/jetstream.py` — `EventsStreamConfig.retained_max_msgs`
  / `retained_max_bytes`; `_JetStreamConnection.trim_retained`; pure `retained_cut`.
- `src/screamingface_engine/runner/main.py` — `run_and_reclaim(trim=)`; `_run_process` passes
  `trim=publisher.trim_retained`; `span_sink` becomes the shared loader.
- `src/screamingface_engine/worker/supervisor.py`, `worker/loop.py` — thread `trim_retained`
  next to `reclaim`; the retained branch trims.
- `src/screamingface_engine/evidence_retention.py` — docstring (retention is now capped);
  minor 3 (below).
- `src/screamingface_engine/tracing/loader.py` (new) — `load_span_sink`; `tracing/__init__`
  exports it; `app.control_plane_span_sink` and `runner.main.span_sink` become the shared one.
- Tests (new files only): `tests/unit/test_runner_process_handoffs.py`,
  `tests/unit/test_retained_run_cap.py`, `tests/unit/test_span_sink_loader.py`,
  `tests/integration/test_retained_run_cap_jetstream.py` (real NATS; CI runs it).

## Test plan

- Hand-offs: drive `_run_process` with a fake publisher + fake sink; assert the exported
  `url4.run` root's parent is the span named by `URL4_CLOUD_TRACEPARENT`; assert a failed
  run's subject is trimmed, never deleted, on the no-pool path. Verify both by mutation.
- Cap: `retained_cut` table (under budget, over budget, tail alone over budget, empty, exact
  boundary); `trim_retained` against a fake JetStream context (purge keep, scan, cut purge,
  no cut purge when under budget, missing stream); runner + worker retained branches call the
  trim and never the delete; a raising trim never escapes.
- Loader: one function, both aliases are it; off when unconfigured; never raises; importing
  `tracing` does not load OTel (clean subprocess).

## Acceptance

- Both mutations are killed by a new test. Retained subjects are capped by messages and bytes,
  the terminal frame always survives. One span-sink loader. `run_gates.py
  screamingface-engine` green incl. `check_layering`. No prior test edited.

## Minors (unconfirmed) — triage

- **sampled=00 exported and forwarded as -01** — NOT fixed. The engine records every run it
  accepts (a server-side decision), and the flag it forwards states that decision, so `-01`
  is consistent with what is exported. Honouring an inbound `00` means dropping the accept
  AND run spans for that caller — a sampling-policy decision, not a cheap fix. Note for the
  owner.
- **401/403 from the token dependency gets no accept span** — NOT fixed. The dependency runs
  before the handler opens the span; covering it means a middleware/exception-handler hook.
  It is also arguably desirable: unauthenticated requests minting root spans is an
  unauthenticated write amplifier into the tracing backend. Note for the owner.
- **failed-run subject left for `max_age` on a non-`QueueReadError`** — FIXED (cheap, and
  the documented rule already says "an unknown ending purges"): `subject_retained` treats any
  failure to read the tail as unknown and returns False (purge), logged with the trace.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `adapters/jetstream.py`, `app.py`, `evidence_retention.py`,
  `runner/main.py`, `tracing/__init__.py`, `tracing/loader.py` (new), `worker/loop.py`,
  `worker/supervisor.py`; tests `tests/unit/test_runner_process_handoffs.py`,
  `tests/unit/test_retained_run_cap.py`, `tests/unit/test_span_sink_loader.py`,
  `tests/integration/test_retained_run_cap_jetstream.py`.
- **Commits:** one squash-ready commit on `OME-1462-runner-handoffs` (from origin/main
  2026-10-05).
- **Gates:** `run_gates.py screamingface-engine` ALL GREEN (append-only, ruff, format, pyright,
  check_layering, pytest+cov). Integration file green against a local `nats:2.10-alpine -js`
  (skips without `URL4_CLOUD_TEST_NATS_URL`; CI provides NATS). Mutation check by hand: removing
  `traceparent=` from `SpanRelay(...)`, the no-pool `retain=` wiring, or the `trim=` wiring each
  fails a new test (KILLED ×3).
- **Deviations:** the WIP was authored 2026-10-02 in another session's lane and never committed;
  it was ported onto origin/main 2026-10-05 (applied cleanly, no edits). The two unfixed minors
  (sampled=00 forwarding, no accept span on 401/403) are left to separate
  `improvement-ideas` issues, not this PR.

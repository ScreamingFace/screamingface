---
ticket: OME-1718, OME-1719, OME-1720
stack: url4
status: in_progress   # planned | in_progress | done | blocked
started: 2026-10-26
finished:
---

# url4-guard-followups — address fallback, bounded host pools, deadline through decoding

## Intent

Three follow-ups to the url4 source destination guard (OME-1544, merged PR #1521), all in
`packages/url4/src/url4/io/`. (1) OME-1718: a DNS name whose first vetted address is
unreachable fails although a later vetted address would answer — fall back among the
already-vetted answers on connection-phase failures only, never re-resolving and never after
the request was sent. (2) OME-1719: `GuardedTransport` keeps one inner transport per host name
forever, and the owned adapter is reused for the life of a `Client`/`Url4Node` — bound the
retained per-host pools (LRU) without ever closing one under an in-flight request. (3)
OME-1720: the total deadline is an `asyncio.timeout` around the fetch, but body decoding is a
synchronous loop that never yields on input that decodes to nothing (empty gzip members), so a
fetch can finish after its deadline and still succeed — carry one absolute deadline through
body processing with cooperative checkpoints.

## Planned changes

- `packages/url4/src/url4/io/_guarded_transport.py` — vetted-address list + bounded fallback
  (1718); LRU-bounded per-host pool registry with in-flight tracking and deferred close
  (1719); deadline checkpoints in `_CappedStream` (1720).
- `packages/url4/src/url4/io/_body_decode.py` — the inflater yields control after every
  decompress step (an empty piece) so the caller can checkpoint the deadline (1720).
- `packages/url4/src/url4/io/http.py` — one absolute deadline per fetch, carried in
  `FetchState` across redirect hops; never return success after it (1720).
- New test files (append-only; no existing test edited):
  `packages/url4/tests/unit/test_source_guard_fallback.py`,
  `packages/url4/tests/unit/test_source_guard_pools.py`,
  `packages/url4/tests/unit/test_source_guard_deadline.py`.
- `docs/tasks/2026-10-26-OME-17{18,19,20}-*.md` mirrors.

## Test plan

- 1718: unreachable first + reachable second succeeds via second (Host/SNI kept, one lookup);
  mixed public/private answer set refused before any connection; a failure after the request
  was sent (read error) is not retried; all addresses failing → `x.source_timeout`/
  resolution failure within connect and total deadlines; attempt bound honoured.
- 1719: many hostnames never exceed the bound; evicted idle pool is closed; a pool with an
  in-flight (streaming) request is evicted from the map but closed only after its response
  closes, without interrupting it; overlapping requests on one host; adapter `aclose` closes
  retained and retired pools.
- 1720: a body of many empty gzip members delivered without suspension fails with
  `x.source_timeout` (never succeeds after the deadline); stream closed on timeout and on
  cancellation; the deadline is shared across redirect hops; valid decoding and caps intact.

## Acceptance

- Verbatim Linear acceptance for OME-1718, OME-1719, OME-1720 (see the issues); url4 gates
  green via `uv run .claude/scripts/run_gates.py url4`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** _pending_
- **Commits:** _pending_
- **Gates:** _pending_
- **Deviations:** _pending_

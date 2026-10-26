---
ticket: OME-1718, OME-1719, OME-1720
stack: url4
status: done   # planned | in_progress | done | blocked
started: 2026-10-26
finished: 2026-10-26
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

- **Actual files:** as planned, plus a new `packages/url4/src/url4/io/_host_pools.py` (the LRU
  registry was split out of `_guarded_transport.py` to keep that file focused, 330 lines).
  Tests: `test_source_guard_fallback.py` (12), `test_source_guard_pools.py` (12),
  `test_source_guard_deadline.py` (8), 32 new tests in all. No pre-existing test was edited, and no
  manifest was needed. Mirrors: `docs/tasks/2026-10-26-OME-17{18,19,20}-*.md`.
- **Commits:** `70d10ceff` fix(url4): fall back to the next vetted DNS answer after a
  connection failure (OME-1718); `e6b0bb59c` fix(url4): bound the guarded transport's
  per-host connection pools (OME-1719); `e47661226` fix(url4): enforce the source deadline
  through compressed-body decoding (OME-1720); then this docs commit.
- **Gates:** `run_gates.py url4`: append-only, ruff check, ruff format, pyright and pytest
  (cov ≥95%) were all green after each commit. `check_mirror_status.py` exits 0.
- **Deviations / open questions (conservative defaults picked, for Sergey):**
  1. `MAX_ADDRESS_ATTEMPTS = 3`: each hop tries at most 3 vetted answers, and a module
     constant sets the cap (it is not a `SourceGuard` field).
  2. Connect timeout is **per attempt**: each fallback attempt gets the full
     `connect_timeout`, and only the total deadline bounds the sum (worst case 3×10s
     < 60s). The other reading is one connect budget shared across attempts, but then a
     blackholed first address would starve the fallback.
  3. `MAX_HOST_POOLS = 32`, a constructor kwarg on `GuardedTransport` that is not exposed on
     `HttpIOLayer`/`SourceGuard` (YAGNI). When every retained pool is busy, the LRU pool still
     leaves the map, so the bound on retained pools holds. It closes only after its last
     in-flight response closes, so for that short time open pools can exceed the bound.
  4. The deadline uses `time.monotonic` (`_guarded_transport._now`, which tests replace) next to
     `asyncio.timeout` on the loop clock. The capped stream yields to the loop once per 64 KiB
     raw step.
  5. The `ConnectError` fallback also covers TLS handshake failures, which httpx reports as
     `ConnectError` too. That is still the connection phase, so the request was never sent.
     **Accepted as intended** (review): each attempt still verifies the certificate for the
     original host name (SNI), so a fallback can never accept a wrong certificate.
  6. Linear actor labels are now `agentic`; the mirrors were updated to match.
- **Review round (sf-code-review @613b0a981):** (1, blocking) a cancelled `HostPools.acquire`
  during a victim's close leaked a phantom in-flight count and left the victim half-closed:
  fixed with a synchronous undo on `BaseException` and one shielded, tracked close task per pool
  (shutdown awaits them). (2) Earlier fallback failures were dropped: now attached as an
  exception note on the final error (address and class name only; the mapping is unchanged).
  (3) The per-step `asyncio.sleep(0)` was unpinned: a cancellation test now fails if it is
  removed (checked by mutation). 4 tests added (36 new in all); gates green.

---
ticket: OME-1010
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1010 — Retry pending deliveries in the background

## Intent

`apps/report-intake` files a report inline under spec §6's 3 s deadline and, when that attempt
gets nowhere, leaves the row `pending` with the retry deadline exactly where the insert put it.
Nothing picks it up. This unit makes `pending` mean what the column implies: a background sweep
claims the due rows, re-delivers them through the **same** `TicketDispatcher` the request path
uses, backs off exponentially over roughly 24 h, and marks the report terminally `failed` — with
a log line an operator can alarm on — when the attempt budget is spent.

Four properties matter more than the loop:

- **`replicaCount > 1` must not double-file a bug report.** Rows are claimed by a conditional
  UPDATE against `lease_expires_at`, which is a compare-and-set the database arbitrates. A
  sweeper that reads-then-writes would let two pods deliver the same report.
- **The due-scan reads `pending` only.** `queued` is terminal success (plan §2.3): a sweep that
  read it as "no attempt scheduled" would retry every successfully-queued report six times and
  then alarm on it.
- **Retries must not stampede the sink.** A bounded batch per sweep is the ceiling, not the
  backoff — an outage clusters every row's deadline into the same instant, so the backoff alone
  paces nothing.
- **A rendered ticket must be byte-identical to the inline one.** The sweeper re-validates
  `row.payload` into a `ReportDocument` and hands that to the dispatcher, which is exactly why
  `render_ticket` takes a document rather than a `BoundedReport` (`OME-1009`'s contract).

Plan section: `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md` §8, against the
frozen contracts in §2 (§2.1 module ownership, §2.2 the `TicketSink` port, §2.3 the `reports`
table and its states, §2.4 the environment surface) and §11's 18 resolved conflicts —
particularly 7 (every column already exists), 8 (`queued` is a state, not a null timestamp) and
12 (a sweeper on `on_startup` is a silent no-op).

## Planned changes

- `apps/report-intake/src/report_intake/reports/retry.py` — NEW. `RetryQueue`: the policy object
  with `sweep()` split from `run()`, an injected clock, the backoff schedule, and the terminal
  `failed` log line. Mirrors `reports/retention.py`, which is the same shape.
- `apps/report-intake/src/report_intake/reports/store.py` — EDIT: `claim_due()` (the conditional
  UPDATE with the lease) and `DueReport`; `record_delivery()` gains an optional
  `next_attempt_at`, supplied only by the retry queue, so one write records the outcome *and*
  the schedule.
- `apps/report-intake/src/report_intake/main.py` — EDIT as a diff: keep the dispatcher on
  `app.state.ticket_dispatcher` and start the retry loop inside `_lifespan`, owned and cancelled
  like the purge.
- `apps/report-intake/tests/unit/test_retry_queue.py` — NEW, behaviour-named.
- `apps/report-intake/tests/unit/test_report_store.py` — EDIT: the claim's own tests.
- `apps/report-intake/README.md`; `docs/complexity-baseline.md` if a high-water mark moves.
- This ledger.

**No migration** (plan §2.3: `0001_initial` already carries `attempts`, `next_attempt_at` and
`lease_expires_at`). **No new `Settings` field** — plan §2.4 freezes the environment surface and
§8 gives this item none, so the interval, the batch and the lease are module constants with the
same justification `PURGE_INTERVAL` already carries. The retry attempt reuses
`delivery_timeout_s` and the dispatcher instance rather than growing a second delivery path.

## Test plan

- a pending report past its deadline is re-delivered and the row carries the sink's verdict.
- a `queued` row is never re-delivered — terminal success is not a retry candidate.
- a `delivered` and a `failed` row are likewise never scanned.
- a row whose deadline has not arrived is left alone.
- the backoff after each attempt is the schedule's next step, and the schedule spans exactly 24 h.
- the sixth attempt that gets nowhere is terminal `failed`, and it says so in the log.
- a second sweeper claims nothing a first one is holding — the lease is what stops
  `replicaCount > 1` double-filing.
- a lease that has expired makes the row claimable again, so a replica that died mid-attempt
  does not strand the report.
- a sweep claims at most one batch, and attempts them one at a time — the sink is never handed
  two reports at once.
- a sweep that cannot reach the database does not raise and does not stop the loop.
- a stored payload that no longer validates is terminal `failed`, not an exception in the sweep.
- the loop runs from the lifespan, asserted through the deployed wiring, and is cancelled on
  shutdown.

## Acceptance

- Due-scan predicate is `delivery_state='pending' AND next_attempt_at <= now AND
  lease_expires_at <= now`, and the claim is a conditional UPDATE whose row count is the
  arbitration.
- The schedule is the plan's: `720 + 2160 + 6480 + 19440 + 57600 = 86400 s`, six attempts,
  then terminal `failed` with a log line.
- No migration, no new environment variable, no new problem status, no change to the route or
  to `PROBLEM_CATALOGUE`.
- `record_delivery` remains the only writer of `delivery_state` / `attempts` / `ticket_id` /
  `ticket_url`.
- Gates green from `apps/report-intake`: `uv sync`, `uv run pytest -q`, `uv run ruff check`,
  `uv run ruff format --check`, `uv run pyright`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. New: `src/report_intake/reports/retry.py`,
  `tests/unit/test_retry_queue.py`. Edited: `src/report_intake/reports/store.py`
  (`DueReport`, `claim_due`, `record_delivery`'s optional `next_attempt_at`),
  `src/report_intake/main.py`, `tests/unit/test_report_store.py`, `README.md`,
  `docs/complexity-baseline.md`, this ledger. No migration, no `config.py` change, no route
  change, no `PROBLEM_CATALOGUE` change.
- **`create_app` diff is three lines**, as plan §2.1 requires: the dispatcher is named,
  `app.state.ticket_dispatcher` holds it, and `StorePipeline` takes it rather than building one
  inline. `_lifespan` gained one task and LOST two statements, because cancelling both loops
  moved into `_stop`.
- **Gates (from `apps/report-intake`):** `uv sync` clean · `uv run pytest -q` **306 passed**
  (was 266: 29 in the new `test_retry_queue.py`, 11 added to `test_report_store.py` for the
  claim itself) · `uv run ruff check` clean · `uv run ruff format --check` 67 files ·
  `uv run pyright` **0 errors, 0 warnings**. `uv run .claude/scripts/run_gates.py report-intake`
  from the repo root: ALL GATES GREEN, including the append-only test check and the 80% coverage
  floor — actual **99%**, with `retry.py` and `main.py` at 100% and `store.py` at 99% (the one
  uncovered line is the pre-existing `raise` in `_record`'s `IntegrityError` branch).
- **Complexity:** one headline number moved. PLR0915 18 → **20**, entirely `create_app`, six
  under its threshold of 26. C901 7, PLR0912 6, PLR0911 3 all unchanged. Baseline refreshed with
  real `file:line` marks, and the roadmap's "26 → 20 is reachable" entry corrected: 20 is now the
  high-water mark itself, so that ratchet would leave zero headroom.
- **Three mutations were run to prove the tests bite**, not just pass: setting `CLAIM_GRACE` to
  zero, replacing the conditional UPDATE with an unconditional claim, and replacing the lifespan's
  retry task with a sleep. Each reddened exactly the tests written for it (2, 3 and 1
  respectively) and nothing else.

### Decisions worth carrying forward

- **The lease is not the whole of the double-delivery story, and `CLAIM_GRACE` is the rest.** The
  inline attempt takes NO lease: `StorePipeline` commits the row `pending`, due at `created_at`
  and unleased, and only then calls the sink. A sweeper on another replica would happily claim a
  report the request path is mid-way through delivering — two tickets for one bug report, through
  the one door the lease does not cover. Nothing is a candidate until it has been due for longer
  than a whole inline attempt (3 s dispatch + two 5 s storage deadlines), and a test asserts the
  grace still exceeds that if either deadline is raised.
- **The budget counts the inline attempt, so the first retry is prompt rather than 12 minutes
  late.** `record_delivery` leaves the deadline at `created_at` (`OME-1009`'s deliberate choice),
  so the row is claimed on the first sweep after the grace; the schedule's remaining gaps then
  apply, giving six attempts across ~23.8 h. A row that reaches the sweep with `attempts = 0` —
  the narrow case where even the inline outcome could not be written — gets the full 24 h. Both
  readings of "6 attempts over roughly 24 h" hold; what does not hold is pretending the collapsed
  first gap is not there, so it is written into the module docstring rather than discovered.
- **`record_delivery` gained an optional `next_attempt_at` rather than a second method.** One
  statement writes the outcome AND the schedule, so a crash cannot leave a row whose attempt was
  counted and whose next attempt was never booked — and `record_delivery` stays the single writer
  of the delivery columns, which is the contract `OME-1009` froze. The request path passes
  nothing and its behaviour is byte-identical to before.
- **The batch is the rate limit; the backoff is not.** A sink outage fails every row in the same
  sweep and books all of their next attempts into the same instant, so the backoff paces nothing
  under exactly the conditions that produce a backlog. `BATCH_LIMIT` rows per `SWEEP_INTERVAL`,
  attempted one at a time (never `gather`), is a ceiling of 20 attempts a minute whatever the
  backlog — and a test watches the sink's in-flight count to prove the second half.
- **A stored payload that no longer validates is terminal, not retryable.** A row lives 90 days
  and this schema will change; five more attempts would re-read the same bytes. Its log line
  names the failing locations and never the `ValidationError`, whose `input` carries the
  offending value — `binding.py`'s rule does not stop applying because the destination is a log.
- **Log assertions do not use `caplog` here.** `logs.configure` sets `propagate = False` across
  the `report_intake` tree on purpose, and `caplog` installs its handler on the ROOT logger — so
  once any test in the session has built an app, a `caplog` assertion passes for the wrong reason
  and then fails for a worse one. The tests attach a handler to the module's own logger.

### Handover to `OME-1012`

Plan §1 says this item's only chart-shaped output is a values block. **There is none**: plan §2.4
freezes the environment surface and lists no retry setting, so the interval, the batch, the lease
and the grace are module constants with the same justification `PURGE_INTERVAL` already carries,
and the retry attempt reuses `REPORT_INTAKE_DELIVERY_TIMEOUT_S` through the dispatcher the request
path uses. The chart renders §2.4's list unchanged.

The one deployment fact the chart needs: **the retry loop runs in every replica**, and the
conditional-UPDATE lease is what makes `replicaCount > 1` safe. It is not a leader-elected
singleton and must not be turned into one.

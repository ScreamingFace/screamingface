---
ticket: OME-1009
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-26
---

# OME-1009 — `TicketSink` port and the `QueueSink` adapter

## Intent

`apps/report-intake` stores a report and stops. This unit gives it the last stage of spec §3's
pipeline — `deliver` — behind the port plan §2.2 froze: a `TicketSink` that receives
already-rendered `TicketContent` strings and never a report object, so an adapter cannot leak a
payload it was never handed. `QueueSink` is the v1 adapter: it marks the record `queued` for an
agent to file via MCP during triage, and returns no ticket id, which is exactly the success
shape spec §2.2 already models.

Three properties matter more than the wiring:

- **A sink outage costs nothing.** Delivery is attempted inline under spec §6's **3 s** deadline
  (plan §11 conflict 18 — 3 s, not the draft's 10 s) *after* the commit, so a slow or dead sink
  degrades to a `pending` row and a `202`, never a failed request.
- **The rendered body is re-checked fail-closed** with `scan_text` (plan §2.7), never
  `classify_report` — a rendered body is one string and the structural detectors are scoped by
  JSON pointer, which a bare string has none of. Passing it to the document classifier would
  mark every report as content and nothing would ever be delivered.
- **The ticket carries an allow-list, not an error object.** Named fields only, so `error.details`
  and `error.cause` (arbitrary client-shaped JSON) and the preserved unknown keys inside `client`
  and `context` never reach third-party SaaS. That is what excludes an `api_key` a client dropped
  into an extension point *structurally*, by name, rather than by pattern-matching values.

Plan section: `docs/plan/2026-08-26-OME-1002-report-intake-implementation.md` §7, against the
frozen contracts in §2 (§2.1 module ownership, §2.2 the `TicketSink` signature, §2.3 the
`reports` table, §2.4 the environment surface, §2.7 the classification seam) and §11's 18
resolved conflicts.

## Planned changes

- `apps/report-intake/src/report_intake/delivery/ports.py` — the port, `TicketContent`,
  `Delivered` / `Queued`, and the `Retryable` / `Permanent` error taxonomy in ONE module
  (plan §2.2), never a separate `delivery/errors.py`.
- `apps/report-intake/src/report_intake/delivery/render.py` — `render_ticket()`: the envelope,
  `trace_id`, `ref`, note, `reply_to`, mesh caller email, as strings. Allow-listed field by
  field.
- `apps/report-intake/src/report_intake/delivery/queue_sink.py` — `QueueSink`, the v1 adapter.
- `apps/report-intake/src/report_intake/delivery/registry.py` — name → sink, `build_sink()`;
  wiring by registry, so core never imports an adapter (CLAUDE.md architecture rule).
- `apps/report-intake/src/report_intake/delivery/dispatch.py` — `TicketDispatcher`: render,
  fail-closed re-check, call the sink under the deadline, return an outcome. The branching
  lives here so `StorePipeline` keeps one.
- `apps/report-intake/src/report_intake/reports/store.py` — EDIT: `record_delivery()`, the only
  writer of `delivery_state` / `attempts` / `ticket_id` / `ticket_url`.
- `apps/report-intake/src/report_intake/reports/store_pipeline.py` — EDIT: deliver AFTER the
  commit, and never for a replay.
- `apps/report-intake/src/report_intake/config.py` — EDIT: `ticket_sink`,
  `delivery_timeout_s` (§2.4's two names this item owns).
- `apps/report-intake/src/report_intake/main.py` — EDIT as a diff: build the sink, hand it to
  the pipeline through a dispatcher.
- `apps/report-intake/tests/**` — behaviour-named tests.
- `apps/report-intake/README.md`; `docs/complexity-baseline.md` if a high-water mark moves.
- This ledger.

## Test plan

- a report is delivered inline and the row carries the sink's verdict before the response.
- `QueueSink` leaves the row `queued` with no ticket, and `queued` is terminal — `OME-1010`'s
  due-scan reads `pending` only.
- a sink that hangs past the deadline leaves the row `pending` and the response `202` — the
  reporter's request is never failed by a slow sink.
- a `RetryableDeliveryError` leaves `pending`; a `PermanentDeliveryError` leaves `failed` with
  a log line, because a permanent failure retried six times is six pointless calls.
- a sink raising outside its declared taxonomy does not turn a committed `202` into a `500`.
- an idempotent replay does NOT deliver again — one report, one ticket (spec §5).
- a rendered body carrying a marker is refused before the sink is called, and the sink sees
  nothing.
- the rendered ticket carries the envelope, `ref`, `trace_id`, note, `reply_to`, caller email —
  and carries neither `error.details`, `error.cause`, nor an unknown key from `client`.
- delivery is attempted only after the row exists (persist before deliver, asserted at the seam).
- `build_sink` refuses an unknown name at boot, naming the valid ones.

## Acceptance

- The port matches plan §2.2 exactly: `async deliver(content: TicketContent) -> SinkResult`,
  `SinkResult = Delivered | Queued`, both error classes in `delivery/ports.py`.
- `PersistedReport` does not cross the seam; a sink is handed strings.
- Inline timeout is 3 s and is a `Settings` field; `REPORT_INTAKE_TICKET_SINK` and
  `REPORT_INTAKE_DELIVERY_TIMEOUT_S` are the only two environment names this item adds.
- No migration (plan §2.3: `0001_initial` already carries every column).
- `PROBLEM_CATALOGUE` is unchanged — delivery never fails a request.
- Gates green: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
  `uv run pyright`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus two the plan did not name and one it did not anticipate.
  New: `delivery/{__init__,ports,render,queue_sink,registry,dispatch}.py`,
  `tests/unit/test_ticket_{render,dispatch,sinks}.py`. Edited: `reports/store.py`
  (`record_delivery`), `reports/store_pipeline.py`, `config.py`, `main.py`, `README.md`,
  `docs/complexity-baseline.md`, and four existing test modules whose assertions this item
  legitimately changed (below).
- **`create_app` diff is three lines**, as plan §2.1 requires: `build_sink(settings.ticket_sink)`,
  `app.state.ticket_sink`, and the pipeline gaining a `TicketDispatcher`. Nothing existing moved.
- **Gates (run from `apps/report-intake`):** `uv sync` clean · `uv run pytest -q` **266 passed** ·
  `uv run ruff check` clean · `uv run ruff format --check` 65 files formatted ·
  `uv run pyright` **0 errors, 0 warnings**. `uv run .claude/scripts/run_gates.py report-intake`
  from the repo root: ALL GATES GREEN, including the append-only test check and the 80% coverage
  floor — actual **99.55%**; every new module is at 100%.
- **Complexity:** no headline number moved. C901 7, PLR0915 18, PLR0912 6, PLR0911 3, all
  unchanged. `create_app` grew 16 → 18 statements, eight under the threshold. Baseline refreshed
  with real `file:line` marks rather than left stale.

### Four existing tests changed, deliberately and out loud

Delivery is now attempted inline, so the row a fresh `POST` leaves behind is `queued` with
`attempts == 1`, not `pending` with `attempts == 0`. Three assertions in
`test_persistence_route.py` / `test_reports_route.py` and one name in `test_store_pipeline.py`
moved to say so, with the reason in the test. `StorePipeline` gained a required second
constructor argument (the dispatcher), which is the contract change `OME-1008`'s handover named:
a pipeline that could be built without a sink would be a service that silently files nothing.

### Decisions worth carrying forward

- **The renderer is an allow-list, and that is the whole security story of this item.**
  `error.details` and `error.cause` do not travel: they are arbitrary client-shaped JSON, and
  spec §2.1 calls `details` "unbounded server JSON". Neither do the unknown keys `client` and
  `context` preserve — reading declared attributes excludes an `api_key` a client dropped into
  an extension point by NAME, at the point of rendering, rather than by guessing which values
  look like secrets. Both exclusions have a test that asserts the value IS in the stored payload
  and is NOT in the body, so the point is visible rather than incidental.
- **`record_delivery` is called after every attempt, including one that got nowhere.** `attempts`
  is `OME-1010`'s backoff input, and a row claiming zero attempts after the inline one ran
  understates how hard the report has been tried. `next_attempt_at` is deliberately untouched:
  the retry schedule has one owner and it is not this item, and a row left due at `created_at` is
  exactly what that sweep is built to find.
- **A replay delivers nothing.** One report, one ticket (spec §5). Re-dispatching on a replay
  would make the idempotency window a way to file the same bug twice, and would overwrite a
  `delivered` row's state with whatever the second attempt got.
- **A `StorageUnavailable` from `record_delivery` is caught, not propagated.** The report is
  already committed there, so a `503` would tell a client with a durable report that nothing was
  stored — and it would file it again. Accepted imprecision, written into the code: if the
  outcome was `delivered`, the row still says `pending` and `OME-1010` files a duplicate. A
  duplicate ticket is visible and cheap; a lost bug report is neither.
- **The broad `except Exception` in `_attempt` is the second in this app and is justified in
  place.** An adapter is third-party-shaped code; the row is committed by the time it runs, so
  letting an undeclared error out is a `500` for a report that IS stored. `CancelledError`
  derives from `BaseException` and is not caught, so shutdown still cancels.
- **The fail-closed re-check is tested through a document built WITHOUT `bind`** — which is the
  honest shape of the case it exists for (a row stored before a detector existed, re-delivered by
  `OME-1010`; or a renderer that grew a field). Constructing a report that passes
  `classify_report` and fails `scan_text` on the rendered body turned out to be genuinely hard,
  because every section join in the body is `\n\n` followed by `-`, `#` or a fence — which is
  itself evidence the two halves agree.
- **Free text is fenced with a computed fence.** A `note` is user prose and may contain its own
  ` ``` `; a fixed three-backtick fence lets the rest of it render as Markdown in the ticket, and
  `## Error` inside one forges a section heading.

### Follow-up this session could not file

Plan §7 says `LinearSink` should be **filed as an issue rather than left implicit**, gated on
`OME-976` *and* on a decision about where the Linear credential lives and who rotates it. This
session is forbidden from touching Linear, so it is recorded here instead and needs filing by
whoever owns the board. The code side is ready for it: one adapter file plus one line in
`delivery/registry.py`, with `Delivered` and the `ticket_id`/`ticket_url` columns already
exercised by tests.
</content>
</invoke>

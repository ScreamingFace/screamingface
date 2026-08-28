---
ticket: OME-1009
stack: report-intake
status: done
started: 2026-08-26
finished: 2026-08-27
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

---

## 2026-08-27 — follow-up pass: `LinearSink`, the adapter this item deferred

The section above closes with a follow-up this session could not file: `LinearSink`, "one adapter
file plus one line in `delivery/registry.py`". This pass builds it. It is the same unit of work
and the same port, so it lands in this ledger rather than a new one.

### What is new, and what it deliberately does not change

- **`src/report_intake/delivery/linear_sink.py`** — an httpx adapter implementing the EXISTING
  `TicketSink` port. One `issueCreate` mutation per report, inside a deadline, answering
  `Delivered(ticket_id=<identifier>, ticket_url=<url>)`. `delivery/ports.py` is untouched: the
  signature, `SinkResult`, and the `Retryable`/`Permanent` taxonomy are what this adapter was
  built to fit, not the other way round.
- **`delivery/registry.py`** — `linear` beside `queue`, plus two contract changes this needed:
  a factory now takes `Settings` (an adapter talking to a third party needs credentials, and
  this is the one module allowed to know which fields those are), and `close_sink()` closes a
  sink holding a connection pool through a structural `ClosingSink` Protocol.
- **`config.py`** — `linear_api_key` (`SecretStr`), `linear_team_id`, `linear_api_url`
  (defaulted), `linear_timeout_s`. No `NoDecode` on any of them: none is a collection, and
  `NoDecode` exists on the two tuple fields only because pydantic-settings JSON-decodes complex
  types read from the environment.
- **`main.py` — two lines.** `build_sink(settings)` in place of `build_sink(settings.ticket_sink)`,
  and `await close_sink(app.state.ticket_sink)` in the lifespan's `finally`. The composition root
  still does not import an adapter, still does not know which ones exist, and
  `test_create_app_wires_the_named_sink_rather_than_importing_one` still holds.
- **The chart** — three ConfigMap keys, one optional `secretKeyRef`, a `linear:` values block, and
  a render-time refusal mirroring the boot guard. Forced by the equality between the chart and
  `Settings`, not optional: a field the chart never renders can only ever hold its declared
  default in production, which is exactly what `test_chart_environment.py` exists to catch.
- **Plan §2.4's frozen surface** — amended in the plan document as well as in the test that
  transcribes it, with the four names and why they are inert. The list is frozen, not sealed;
  what it forbids is a field arriving with neither entry.

### CLAUDE.md rule 9 — said in the code, not worked around

Rule 9 says product code reaches Linear through MCP only, and `OME-976` has not amended it. This
pass does not amend it either — the file says so in its module docstring, and the design makes
that statement structural rather than decorative: nothing imports the adapter except one line of
the registry's name table, `queue` is still the default, and `build_sink` refuses to start a
`linear` deployment with no API key or no team id. **Shipping the adapter is not selecting it.
Selecting it is the decision rule 9 governs**, it costs an operator a credential and a team id,
and both the chart and the app stop when it is made halfway.

### Decisions worth carrying forward

- **HTTP 200 is not success, and that is the whole reason this adapter needs care.** GraphQL
  answers `200` for a request it refused: the response carries an `errors` array, and
  `data.issueCreate.success` can be `false`, both under a healthy status line. An adapter that
  checked `response.status_code` alone would mark the row `delivered` with a null `ticket_id`,
  alarm nothing, and lose a report the reporter was already told `202` about. Both are checked,
  `errors` BEFORE `data` (a GraphQL response may legitimately carry both, and a reader that
  trusts `data` first reports a refused mutation as a filed ticket), and each has its own test.
- **The retryable/permanent split was decided case by case, not with a catch-all.** Retryable: a
  transport failure or timeout, `5xx`, `429`, `408`, and a rate-limit or server-error
  `extensions.code`. Permanent: `401`/`403`, any other `4xx` (this adapter builds the same
  request every time), a non-transient GraphQL error, and `success: false`. **Anything
  unclassifiable is retryable**, per `ports.py`'s own rule — and the retry budget running out
  turns persistent uncertainty into `failed` on its own, so "unsure" still ends up alarmed.
- **A rate limit is matched on a NORMALIZED code.** The reference page publishes no thresholds
  and no code enumeration, so `RATE_LIMITED`, `RATELIMITED` and `rate-limited` all have to mean
  the same thing. Generous on exactly the one condition a healthy deployment actually meets.
- **`success: true` with an unnameable issue is permanent, not retried.** The issue very probably
  exists, so a retry would file a duplicate of a ticket nobody can name. `failed` sends a human
  to look, and what they find is this adapter and Linear's response shape having stopped
  agreeing — a defect in this repo rather than an outage.
- **The API key never reaches a log record, a `repr`, or an exception message.** It is held in one
  private attribute, set once as a client header, and `__repr__` is written by hand so a future
  `@dataclass` on the class cannot start printing it. The transport-failure message names the
  exception's TYPE rather than repeating its text. Three tests assert it rather than trusting it:
  over every failure path's exception, over every log record the DISPATCHER writes while driving
  the adapter (formatted, so a `%s` argument cannot hide), and over the `repr`. The registry's
  boot refusal is covered too — it is the other place the value is in scope.
- **No `linear.enabled` chart flag.** `config.ticketSink` is the switch; a second one could
  disagree with it, and both directions are bad — a credential mounted for nobody, or a pod that
  starts and files nothing. The Deployment names the Secret in every render with `optional: true`,
  so the Secret NOT existing is the normal state, the Pod starts without it, and the app's boot
  guard is what refuses the half-made selection.
- **`close_sink` is structural, never an `isinstance` against an adapter class.** That is what
  lets the composition root close an HTTP connection pool it does not know exists, and what keeps
  `QueueSink` and every test stub out of it.

### Gates (run from `apps/report-intake`)

`uv run pytest -q` **495 passed** (438 → 495; +57) · `uv run ruff check` clean ·
`uv run ruff format --check` 83 files · `uv run pyright` **0 errors, 0 warnings**.
`python3 .github/scripts/verify_chart_wiring.py` from the repo root: **78/78** (75 → 78; the
three added assert the two render-time refusals and that the Linear key comes from an optional
Secret with no literal). `helm lint` clean.

### Deviations

- **The plan's frozen environment surface grew by four names.** Unavoidable: an adapter that
  talks to a third party needs credentials, and `Settings` is the sole authority on this
  service's environment. Recorded in plan §2.4 rather than only in the test.
- **The chart was edited, which this pass's brief did not name.** Also unavoidable: the
  chart-vs-`Settings` equality is asserted from both sides, so four new fields with no chart
  lines is a red gate, and rendering a credential into a ConfigMap would have been the wrong way
  to make it green.
- **`docs/complexity-baseline.md` refreshed in full.** Its `file:line` marks had drifted from
  earlier passes (whole rows missing for the `identity` package, `caps.py` lines stale) and
  `create_app` had reached 24 before this pass. Regenerated with the command the file documents;
  no headline number moved for `linear_sink.py` itself.

---

## 2026-08-27 — second follow-up pass: a drain path for the queue

`QueueSink` marks a row `queued` and stops there. Nothing in this service could then name those
rows: `cli.py` ran uvicorn and nothing else, spec §1 removed `GET /v1/reports/{ref}`, and plan
§13's verification step — "confirm `queue list` shows it, file it via MCP" — described a command
that did not exist. A queued report was findable by grepping pod logs or opening the database, so
the sink this item shipped had no way to be emptied. Same unit of work, same adapter, so it lands
in this ledger rather than a new one.

### What is new

- **`src/report_intake/queue_cli.py`** — the three commands, their rendering, and their exit
  codes. `queue list` (the rows awaiting triage, newest received first, `--limit`), `queue show
  <ref>` (the ticket body an agent pastes into Linear), `queue mark-filed <ref> --ticket-id
  --ticket-url` (the row is somebody's now). No SQL: it calls `ReportStore` and `render_ticket`.
- **`src/report_intake/cli.py`** — an argparse subcommand tree on the existing console script.
  **argparse, not typer**: this app's runtime dependencies are fastapi / httpx / pydantic /
  pydantic-settings / tortoise / uvicorn, and neither aigateway nor scoreboard pulls typer either,
  so a CLI framework would be a new dependency in a deployed image for one parser.
- **`reports/store.py`** — `awaiting_triage(limit=…)`, `read_for_triage(ref)`,
  `mark_filed(ref, …)`, plus the `TriageReport` row they answer with. Every one keeps the module's
  existing contract: bounded by `STORAGE_TIMEOUT_S`, and any ORM failure leaves as
  `StorageUnavailable`.
- **`delivery/render.py`** — `_one_line` is now public as `one_line(value, *, limit=…)`. The only
  change to that module, and additive: `render_ticket`'s signature, plan §2's frozen contract, is
  untouched.
- **Tests** — `test_queue_console.py` (23, driving the real `cli.main(["queue", …])` against a
  migrated database), `test_triage_read_containment.py` (2), plus 11 store tests and 2 entrypoint
  tests appended to the existing files. 495 → 531.

### Decisions worth carrying forward

- **`report-intake` with no arguments still runs uvicorn, and that is a contract rather than a
  default.** It is the container's `ENTRYPOINT`, so a subcommand made mandatory at the top level
  is every pod in the fleet failing to start. `add_subparsers` is left optional and the top-level
  parser carries `run=_serve`; `required=True` appears only under `queue`, where a bare invocation
  has no sensible fallback. Two tests hold it: one drives `main()` with `sys.argv` set to the bare
  command (the console-script wrapper's actual path), and one asserts an unrecognised argument is
  argparse's exit 2 rather than a web server started inside a `kubectl exec` session.
- **This is a command, and a containment test is what keeps it one.** Spec §1 removed
  `GET /v1/reports/{ref}` on its merits — `POST /v1/reports` is unauthenticated, so a by-ref read
  makes a guessable `ref` worth guessing — and three new store reads are exactly how that endpoint
  comes back under another name. `test_triage_read_containment.py` asserts the three are called
  from `reports/store.py` and `queue_cli.py` only, and separately that no `routes/` module so much
  as mentions one. The store method is `read_for_triage` rather than `read` precisely so that scan
  can be exact instead of a guess about which `.read(` was meant.
- **`mark_filed` is a separate store method from `record_delivery`, because of one column.**
  `record_delivery` increments `attempts`, which is the retry backoff's only input and reads as
  "how hard did THIS SERVICE try". A person filing a ticket by hand is not the sink having been
  called, so a flag on the existing method would make that column lie to whoever reads it next.
  Asserted from both sides — the store test and the console test.
- **Whether a mark is allowed is the console's decision; the store writes.** The same division
  `claim_due` already keeps, where the backoff producing `due_before` is retry policy and the
  store is not where policy lives. The console refuses only one case: a row already `delivered`
  under a *different* ticket id. The ticket columns are the ticket's address, so overwriting one
  erases the only pointer this service holds to an issue that exists, and two ids on one report
  means one bug was filed twice — visible, not tidied away. Re-running with the SAME id is
  idempotent, because an agent repeating itself is not a second ticket.
- **Every table cell goes through `render.one_line`, and that is the same defence `render.py`
  already makes.** `trace_id` is client-controlled and §2.4 caps it nowhere, so a newline inside
  one ends its row and prints the rest as a second one — a report forged into the listing an agent
  triages from. The test seeds that payload straight into the store, past `bind()`, deliberately:
  the console must not depend on intake having stripped anything. ANSI escapes need no handling
  here because `bind()` control-strips the payload at intake and keeps only tab and newline, both
  of which the flattener collapses — stated in the module docstring so the next reader does not
  add a redundant pass.
- **`show` prints the body VERBATIM, and it is the one place nothing is reshaped.** It is what
  gets pasted into Linear, so it has to be what the sink would have been handed, byte for byte —
  asserted against `render_ticket(...).body` directly. The header block above it is labels whose
  values are one line by construction (`ref` server-minted, `state` one of four literals, `title`
  already collapsed by `render._title`, and a ticket reference only reaches the columns through a
  check that refuses whitespace), so "the body is everything after the first blank line" holds.
- **`--ticket-id` / `--ticket-url` are bounded at the CLI, before the database is opened.** For
  `ReportDocument.reply_to`'s reason: every ORM failure leaves the store as `StorageUnavailable`,
  so a value past the column width would be answered as a database outage — telling an operator to
  retry something that will never work.
- **stdout is the table; stderr is the commentary; the exit codes are distinguishable.** `0` fine,
  `1` refused (a fact about the data), `2` argparse's usage error, `3` storage would not answer.
  `1` and `3` are separate on purpose: a script retrying a transient outage must not also retry a
  mistyped `ref`. An unmigrated database — the ordinary state of a freshly deployed pod, since
  this service never migrates itself — is `3` and an empty stderr-free stdout, never an empty
  queue. stdout is flushed before each stderr note, because the two buffer differently the moment
  either is redirected and `queue list > file` otherwise printed the footer above its table.
- **`list` shows `queued` and nothing else**, which is `_due`'s reading from the other side.
  `pending` still belongs to the retry queue, `delivered` is done, and `failed` is an alert
  `retry.py` already logs at error rather than a backlog somebody scrolls. Ordered on `created_at`
  — the server's clock — because `occurred_at` is the client's claim and a reporter that could
  choose it could pin itself to the top of an operator's screen.
- **A row whose payload no longer validates still appears, with its payload-derived cells marked
  `?`.** It is still awaiting triage, and the one report this service can no longer read is the
  one a human most needs to see. `queue show` refuses it with the reason rather than crashing.
  The `_document` helper is deliberately NOT shared with `retry.py`'s namesake: that one logs at
  error and marks the row terminally `failed`, and a listing with a side effect is not a listing.

### Gates (run from `apps/report-intake`)

`uv run pytest -q` **531 passed** (495 → 531; +36) · `uv run ruff check` clean ·
`uv run ruff format --check` 86 files · `uv run pyright` **0 errors, 0 warnings**.

### Deviations

- **`delivery/render.py` grew a public name.** `_one_line` → `one_line(value, *, limit=…)`,
  because the console renders the same client-controlled values into a terminal table and the
  identical trick has the identical cause. Additive: `render_ticket` — the contract plan §2 froze
  — is unchanged, and the `limit` parameter exists only because a table column is narrower than a
  bullet, not because the rule differs.
- **One existing test was edited.** `test_the_entrypoint_serves_the_app_on_the_configured_address`
  called `cli.main()` with no argv, which now reaches argparse's `sys.argv` fallback — under
  pytest that is the test session's own arguments. It now pins `sys.argv` to `["report-intake"]`,
  which makes it a STRONGER assertion than before: it exercises the real console-script path
  rather than a signature that used to ignore argv entirely.
- **`docs/complexity-baseline.md` refreshed.** No headline number moved (C901 7, PLR0915 24,
  PLR0912 6, PLR0911 3) and `create_app` is untouched, but `store.py`'s `file:line` marks shifted
  and the two new modules enter the tables — `cli.py:_parser` at PLR0915 16 is the largest thing
  this pass added, eight under the threshold.
- **Nothing else was touched.** No `Settings` field, so plan §2.4's environment surface is still
  23 names and the chart is unchanged; `test_chart_environment.py` passes untouched. No Linear, no
  `CLAUDE.md`. `.github/scripts/verify_chart_wiring.py` could not be run in this session's
  environment (no PyYAML on the interpreter it resolves to) — it is unaffected either way, and the
  chart-vs-`Settings` equality it mirrors is asserted from the app's own suite.
- **Two stray lines were removed from this ledger.** The previous pass left `</content>` and
  `</invoke>` — leaked tool markup — between its own section and the `LinearSink` one. Deleted;
  no prose changed.

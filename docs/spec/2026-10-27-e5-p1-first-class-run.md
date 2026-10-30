---
status: approved   # owner approved 2026-10-30 (§9)
issue: OME-1785    # one sub-issue per PR is filed under it
parent: OME-1294   # E5 · Improve managing runs in SF Client
date: 2026-10-27
base: origin/main 482460344
---

# E5 P1: a first-class Run (id, owner, state, history)

## 1. Purpose

An `sf.evaluate` call over N Candidates has no id the Engine knows, no owner, no state, and no
index. Once the cell that launched it is gone, the run cannot be found, followed or listed.

P1 makes each evaluation a **Run record owned by the Engine**, with an id, an owner, per-Candidate
outcomes, a derived state and a 30-day retention period. The Client gains `sf.runs` to list,
reopen, wait on and cancel Runs from any notebook or machine.

P1 changes no execution behaviour. The Client still drives the fan-out, a run still stops when
nobody listens, and results still flow to the Client as today. **History never blocks a run:** if
anything about the Run record fails, the evaluation runs exactly as it does today. P2 (detach,
`OME-1611` + `OME-1617`) builds on this record.

**One code path.** The Client is identical against a local Engine (`serve --local`) and a hosted
one. The Engine differs only where it already differs today: in which adapter implements a port.

## 2. As-is (verified at 482460344)

Paths are relative to `apps/screamingface-engine/src/screamingface_engine/` unless they start
with `packages/`.

- **There is no run above the Candidate.** Each Candidate is a *topic*: a random id minted by
  unauthenticated `POST /token` (`auth/token.py:9-15`, `rest/routes.py:670-685`). Nothing groups
  the N topics of one evaluation.
- **The Engine keeps no database.** Run state lives in memory and in NATS: the queue `url4-runq`
  and the events `url4-events`, which have a 24 h max age (`runner_queue.py:3-10`,
  `config.py:270-278`). Local mode uses an in-process runner and `InMemoryEventStream`
  (`local.py:446-507`, `adapters/memory.py:34`).
- **Streams are ensured in code by both halves.** `url4-events` is created or updated at startup
  by the App and the runner pool, each from the same rendered values
  (`deploy/helm/values.schema.json:102-104`).
- **Identity is verified but never stored.** Envoy sets `X-User-Email` from the Cloudflare Access
  assertion (`job_env.py:46-70`, `deploy/helm/templates/securitypolicy.yaml`). It is read at
  start only to forward to aigateway (`rest/routes.py:852`). The mount routes already split
  identity-required (hosted) from anonymous (local) with `require_identity`
  (`rest/mounts.py:116-129`, `local.py:416`).
- **Ports already absorb the local/cloud difference.** `EventStream` is backed by JetStream or by
  `InMemoryEventStream`. `JobRunner` is backed by the queue runner or the in-process runner.
- **Every run ends in exactly one terminal frame on `url4-events`**, published by `url4`'s
  `_terminate` (`packages/url4/src/url4/streaming/lifecycle.py:168-210`). The places the Engine
  observes that end:

  | Path | Where the end is observed |
  |---|---|
  | in-process runner | `_on_done` with `TerminalWatch` and `outcome_of` (`adapters/inprocess.py:154-169`, `run_evidence.py:102-137`) |
  | queue run, executed | the child process; then the worker supervisor after `_publish_if_needed` (`worker/supervisor.py:639-710`) |
  | queue run, never executed | the supervisor's `_publish_terminal` (`worker/supervisor.py:1209-1243`) |
  | cancelled while queued | the App's `_publish_tombstone` (`adapters/queue_runner.py:561-587`) |
  | out of deliveries | the App's `_publish_failure` (`adapters/max_deliveries.py:153-195`) |

- **The child knows the cost.** `executor.last_summary()` holds `cost_usd` and `error_code`
  (`runner/summary.py:27-39`). The child reaches its supervisor over a dedicated control pipe
  (`READY`, `ACK`; `child_protocol.py:1-32`), never over stdout.
- **Client:**
  - `CandidateResult.run_id` *is* the topic (`packages/screamingface/src/screamingface/report.py:288`).
    The topic is a bearer secret, and it is already public (`OME-966`).
  - A client-local evaluation uuid exists only when a result store is configured
    (`_results/evaluation.py:14-23`). It never reaches the Engine or `Report`.
  - After a 503 admission refusal, the Client re-sends the same start on the same topic for up to
    its admission budget, 900 s by default (`_engine/transport.py:1071-1100`,
    `_engine/admission.py:25`, `OME-1066`).
  - A user abort (Ctrl-C) stops every active topic through `cancel_active` (`_engine/transport.py`).
  - `sf.reports` lists only locally saved results (`reports.py:1-48`).

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **The Engine owns the Run record. The Client is an interface to it.** | A Client-local index cannot be reopened from another machine. A "local = disk, cloud = server" split would be two code paths. |
| D2 | **Storage is one Tortoise ORM adapter behind a `RunRegistry` port.** Local: a SQLite file in the Engine data dir, the default under `serve --local`. Hosted: a new database, `engine`, on the existing `charts/db` Postgres server, with its own role and Secret, given as `URL4_CLOUD_DATABASE_URL`. A hosted App with no URL runs with **Runs off**: it logs a warning at start and `/runs*` answer 404, so the Client falls back (D7). A hosted App given a SQLite URL refuses to start. | The same pattern aigateway uses (`apps/aigateway/src/aigateway/db.py:9-43`): one code path, plain SQL for the queries, no new pod or volume. SQLite in a pod would be wiped on every restart. Runs off lets the code ship to an environment before its database exists. *Rejected:* JetStream KV plus SQLite (two adapters that can drift apart); aigateway's database (crosses the app boundary). |
| D3 | **Every database write goes through the App. Runners and url4 hold no database connection.** | The owner condition (§9): one writer is easy to reason about, and runners stay free to run anywhere, for example on AWS Lambda. |
| D4 | **Outcomes travel on a `CandidateOutcomeStream` port.** It has a JetStream adapter (stream `url4-candidate-outcomes`) and an in-memory adapter (`InMemoryCandidateOutcomeStream`), like `EventStream` and `InMemoryEventStream`. Every producer publishes to it, and one App consumer writes them. | One write path in both modes: no "local writes directly" branch, and no runner holds database access. |
| D5 | **`Run.id` is `run_` + a random UUID in hex, minted by the Engine. It is not a secret.** Access is checked by owner, and a foreign or unknown id answers 404. Runs list by `created_at`, newest first, with the id breaking ties. | Ordering comes from a timestamp column, not the id, so the id needs no clock or counter and any number of App replicas can mint it. Safe to paste anywhere (`OME-966`). |
| D6 | **The owner is the verified `X-User-Email` hosted, or `local` in local mode.** It is resolved through the same `require_identity` switch as the mounts, and stored as `sha256` of the email trimmed, NFC-normalised and case-folded. A hosted `/runs*` call without identity gets 401. | It reuses the identity the edge already verifies. Local mode is loopback and single-user. |
| D7 | **Registration is best-effort.** If `POST /runs` fails in any way (any non-2xx answer, such as 401 for no identity, 404 for an older Engine or with Runs off, or a 5xx while the database is down; or a transport error), `evaluate` runs exactly as today, with `Report.run_id = None` and one notice. | History never breaks automation or a lagging local Engine. |
| D8 | **Every `evaluate` registers a Run**: Recipe, raw-URL4 and replay alike, whatever `save_results` is set to. The Client's local manifest is keyed by `Run.id`. | A Run is the record of every evaluation, not only the saved ones. |
| D9 | **`Run.report()` reads the Client's local store only.** On a machine without those results it raises an error that names the run and says the results are not on this machine. | Results stay where they are today, so Garage and its lifecycle are unchanged. Opening a report on another machine is P2's question. |
| D10 | **`CandidateResult.run_id` is deprecated for `attempt_id`** (same value), with a `DeprecationWarning` for two minor releases. The `run_id=` constructor keyword still works, with the warning, and the SDK's own readers use `attempt_id`. `Report.run_id` is the Run. `Event.run_id` (`events.py:27`) and the event envelope's `run_id` (`_engine/contract.py:534`) name an event's topic and are out of scope. | One name, "run id", for two different things would be confusing. Renaming outright breaks notebooks. |
| D11 | **`sf.runs` is a new namespace. `sf.reports` is unchanged.** | Different source and object: Engine records of Runs in any state, versus locally saved results. |
| D12 | **Cancel is run-wide and sticky.** `DELETE /runs/{id}` applies while any Candidate is not terminal (`pending` included): it sets the cancel flag, stops every live topic, moves `pending` Candidates to `stopped`, and refuses later starts under the run with 409 `run_canceled`. When every Candidate is terminal it changes nothing and answers 204. | A cancel from another notebook must also stop Candidates the original Client has not started yet, and must never rewrite a run that has finished. |

## 4. Contract

### 4.1 Engine HTTP

All routes resolve the owner (D6) and answer RFC 9457 `Problem`s, as the existing routes do.

| Route | Request | Response |
|---|---|---|
| `POST /runs` | `{client_key, benchmark, case_count, candidates: [name, …], client_version}` | 201 `RunRecord`, or 200 with the existing record for a repeated `(owner, client_key)` |
| `GET /runs` | `?state=&since=&limit=50&cursor=` | 200 `{runs: [RunRecord], next_cursor}`, newest first |
| `GET /runs/{id}` | — | 200 `RunRecord` · 404 `run_not_found` |
| `DELETE /runs/{id}` | — | 202, or 204 when every Candidate is terminal · 404 `run_not_found` |
| `GET /?q=` (existing start) | new headers `X-SF-Run: <run id>`, `X-SF-Run-Candidate: <index>` | as today · 404 `run_not_found` · 409 `run_canceled` · 409 `candidate_already_started` |

- **`client_key`** is a fresh uuid the Client mints for every `evaluate`, saved or not. When a
  result store exists, its evaluation uuid is this same value. It makes `POST /runs` idempotent,
  so the Client sends it as a replay-safe request (`_REPLAY_SAFE`, as `client.py:474` does): a
  retry after a lost response returns the same Run.
- **`X-SF-Run-Candidate`** is the Candidate's zero-based index in the run's `candidates` list, so
  any Candidate name, ASCII or not, binds safely.
- **404s.** Only `POST /runs` falls back silently (D7). On every other route, a 404 whose Problem
  type is `run_not_found` means the id is unknown or foreign. Any other 404 (an older Engine, or
  Runs off) means this Engine does not serve Runs.
- **`RunRecord`** is `{id, state, created_at, finished_at, benchmark, case_count, candidates:
  [{name, state, attempt_id?, started_at?, finished_at?, cost_usd?, error_code?}]}`. It never
  carries the owner.

### 4.2 Ports (Engine core)

```python
class RunRegistry(Protocol):            # implemented once, with Tortoise
    async def create(self, owner: OwnerKey, spec: RunSpec) -> RunRecord: ...
    async def get(self, owner: OwnerKey, run_id: str) -> RunRecord | None: ...
    async def list(self, owner: OwnerKey, query: RunQuery) -> RunPage: ...
    async def bind(self, owner: OwnerKey, run_id: str, candidate: int, topic: str) -> None: ...
    async def mark_scheduled(self, topic: str) -> None: ...
    async def settle(self, topic: str, outcome: CandidateOutcome) -> None: ...
    async def cancel(self, owner: OwnerKey, run_id: str) -> RunRecord | None: ...
    async def reconcile(self) -> int: ...                                    # R6
    async def expire(self, older_than: datetime) -> int: ...                 # R7

class CandidateOutcomeStream(Protocol): # JetStream `url4-candidate-outcomes` | in-memory
    survives_restart: bool                                                   # R6
    async def ensure_stream(self) -> None: ...                               # R11
    async def publish(self, topic: str, outcome: CandidateOutcome) -> None: ...
    def consume(self) -> AsyncIterator[Delivery[CandidateOutcome]]: ...      # ack() after commit
```

- **The core imports ports only.** Adapters live under `adapters/` and are wired in `app.py` and
  `local.py`, next to the runner they pair with.
- **Writes use compare-and-set:** `UPDATE … SET revision = revision + 1 WHERE id = ? AND
  revision = ?`, identical on SQLite and Postgres.
- **Runner-side code imports `CandidateOutcomeStream` only**, never `RunRegistry`.

### 4.3 Rules

- **R1. Create before spend.** The Client calls `POST /runs` after preflight and before the
  first `POST /token`.
- **R2. Bind at start.** The start route binds `topic → (run, candidate)` before scheduling. The
  run's owner must be the caller, otherwise 404. A start under a canceled run is refused with 409
  `run_canceled` before anything is scheduled.
  - A Candidate binds to one topic per run, and a topic binds to exactly one Candidate of one Run
    (a unique index on topic). So `settle(topic, …)` always has one target.
  - A bind leaves the Candidate `pending`. It becomes `scheduled` (`mark_scheduled`) only once
    scheduling succeeds, so a start that is refused, or that the Client gives up on, leaves it
    `pending` and the R5 grace applies.
  - Binding the same `(run, candidate, topic)` again succeeds and changes nothing, so the
    Client's re-sent start after a 503 still schedules.
  - A different topic for a bound Candidate, or a topic bound elsewhere, gets 409
    `candidate_already_started`.
  - A bind that fails on the database is logged, and the start proceeds unbound (§8).
- **R3. Outcomes.** A `CandidateOutcome` is `{status, error_code?, cost_usd?}`; cost is exact
  only, as on the wire. It is built everywhere by one classifier: a `SettlementWatch` (which
  extends `TerminalWatch`) and the existing `run_evidence.outcome_of`, which returns a
  `CandidateOutcome` carrying the summary's cost.
  - **A producer publishes an outcome only when its own terminal frame is the one that landed on
    `url4-events`.** So the registry always agrees with the terminal frame the Client reads.
  - The producers, all publishing to `CandidateOutcomeStream`:
    - **in-process runner:** `_on_done`.
    - **queue run, executed:** the child sends `SETTLED {json}` on the control pipe, and its
      supervisor publishes it after `_publish_if_needed`. If the child died first, the supervisor
      publishes its own classification instead, with no cost. The encoder and decoder go in
      `child_protocol.py`, which stays stdlib-only, so cost travels as a decimal string.
    - **queue run, never executed:** `_publish_terminal`.
    - **App terminal writers:** `_publish_tombstone` and `_publish_failure`.
  - A topic with no binding is acked as a no-op at the consumer.
- **R4. One writer.** The App's consumer calls `settle` and acks only after the commit. A
  database outage delays outcomes but loses none: they are redelivered within the stream's 24 h
  `max_age`. The **first terminal outcome wins**, and a terminal Candidate never moves, so
  duplicate claims and redeliveries cannot contradict it. Reconcile (R6) only ever writes `lost`,
  and only once no outcome can still arrive.
- **The registry stores facts, not the Run's state.** Each Candidate's state, topic, times, cost
  and error code, and the Run's cancel flag, `created_at` and `last_activity_at`, which every
  bind, schedule, settle and cancel moves forward. The Run's state and `finished_at` are derived
  from them on every read (R5).
- **R5. State** is a pure function of the Candidate states, the run's cancel flag, its
  `last_activity_at` and the clock.
  - Candidate states: `pending` (bound or not, not yet scheduled), `scheduled`, `running`,
    `succeeded`, `failed`, `timed_out`, `stopped`, `lost`.
  - The grace is `run_pending_grace_s`, default 1800 s. It must exceed the Client's admission
    budget (900 s by default, configurable as `admission_budget_s`), so a Client waiting for
    admission never reads as `interrupted`.
  - **The first matching row wins**, in this order:
    1. `canceled`: the cancel flag is set and every Candidate is terminal.
    2. `running`: any Candidate is `scheduled` or `running`, or `pending` within the grace of
       `last_activity_at`.
    3. `interrupted`: any Candidate is `lost`, `stopped` without a cancel (reaped), or `pending`
       past the grace (the Client died).
    4. `complete`: every Candidate `succeeded`.
    5. `partial`: at least one `succeeded`, and every other Candidate is `failed` or `timed_out`.
    6. `errored`: every Candidate is `failed` or `timed_out`.
  - **Computed on read, never stored.** `GET /runs/{id}` and `GET /runs` derive the state from
    the stored facts at the moment of the read, so it is always exact, including the one change
    the clock drives (`pending` past the grace), and the two routes always agree. A Run's
    `finished_at` is its last Candidate's `finished_at` once the state is terminal, and absent
    otherwise.
  - **Filtering by state** happens in the App: `GET /runs?state=` loads the owner's Runs in the
    window (`since`, at most the 30-day retention), derives their states, filters, and pages.
    That is a few hundred or thousand rows per owner. A stored, indexed state column is a later
    migration if one owner ever holds far more, backfilled with the same pure function.
- **R6. Reconcile** runs at App start and hourly. **It only ever writes `lost`**; a terminal
  state and a cost come only from a real outcome.
  - **A stream that survives a restart** (JetStream). A Candidate still live
    `run_lost_after_s` (default 48 h) after it was bound settles as `lost`. P1 runs stop when
    nobody listens, so no real run comes near that, and it is longer than both
    `url4-candidate-outcomes` and `url4-runq` keep a message (24 h each), so no outcome can still
    arrive.
  - **A stream that does not survive a restart** (in memory). A Candidate bound before this
    process started settles as `lost` at once, because its outcome died with the old process. A
    Candidate bound since is left to its real outcome: the in-process runner always publishes
    from `_on_done`.
  - The port's `survives_restart` says which applies. It is a property of the adapter, not a
    mode branch. Reconcile asks the runner nothing.
  - A hosted App restart changes nothing for a Candidate still in the queue: it stays
    `scheduled` until its worker publishes.
- **R7. Retention** is the App's hourly sweep, also run at start, following the artifact
  sweeper's pattern (`app.py:156-170`). It deletes Runs whose `created_at` is older than
  `run_retention_s`, default 30 days. The same code runs on both databases.
- **R8. Cancel** follows D12. The Client also sends `DELETE /runs/{id}`, best-effort, when the
  user aborts an `evaluate` (Ctrl-C, `cancel_active`), so a deliberate stop reads `canceled`.
- **R9. Schema.**
  - Hosted: migrations run in a pre-install/pre-upgrade Helm hook Job, modelled on aigateway's
    (`apps/aigateway/charts/aigateway/templates/job-migrate.yaml`). The Job, and the App's
    database variable, render only when `database.existingSecret` is set, and the App's secret
    reference is `optional: true`. Without the Secret the chart renders and installs, and the App
    runs with Runs off (D2).
  - Local: `serve --local` applies pending migrations at start.
  - The App refuses to start on a schema older than its code.
- **R10. Create the database once per environment.** This is an owner action, because
  `charts/db`'s `POSTGRES_DB` init runs only on an empty volume. It is
  `CREATE ROLE engine LOGIN PASSWORD '…'; CREATE DATABASE engine OWNER engine;`, then the
  `engine-db` Secret, then `database.existingSecret` in the environment's values. The runbook goes
  in `apps/screamingface-engine/DEPLOYMENT.md`.
- **R11. The outcome stream is ensured in code, like `url4-events`.** Both the App and the runner
  pool call `ensure_stream()` at startup, from the same rendered `candidateOutcomes.*` values
  (max age 24 h, max bytes), declared in `values.schema.json` and rendered to both Deployments.
  A worker can therefore publish even if it starts before the App.

### 4.4 Client API

```python
report = sf.evaluate(candidates, benchmark="...")   # unchanged signature and return type
report.run_id                                       # "run_…" | None (D7)

sf.runs.list(*, state=None, since=None, limit=50) -> list[Run]
sf.runs.get(run_id) -> Run
# async twins: sf.runs.list_async, sf.runs.get_async

class Run:                       # a frozen snapshot; methods re-read the Engine
    id: str
    state: Literal["running", "complete", "partial", "errored", "canceled", "interrupted"]
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    candidates: tuple[CandidateRun, ...]   # name, state, cost_usd, error_code
    cost_usd: Decimal | None               # sum of the known costs
    def refresh(self) -> Run
    def progress(self) -> RunProgress      # Candidates done / total, and spend so far
    def wait(self, *, timeout: float | None = None) -> Run   # polls until terminal
    def report(self) -> Report             # local store only (D9)
    def cancel(self) -> None               # D12
```

- `sf.runs` is a plain submodule, shaped like `sf.reports`.
- `Run`, `CandidateRun` and `RunProgress` are exported from `screamingface`.
- An unknown or foreign id raises `KeyError`, like `sf.reports.get`. An Engine that does not
  serve Runs (an older Engine, or Runs off) raises `ExecutionError("runs_unavailable")`.
- `report()` on a Run that is still `running` raises `ExecutionError("run_not_finished")`. On any
  other non-`complete` state it follows the existing settlement rule:
  `ExecutionError("candidates_failed", partial_report=...)`.

## 5. Landings

Two landings, delivered as small stacked PRs (E1–E8 for P1a, C1–C4 for P1b) under `OME-1785`, each
with its own sub-issue. The plan (`docs/plan/2026-10-30-e5-p1-first-class-run.md`) has the split.

| Landing | Component | Change |
|---|---|---|
| P1a | `screamingface-engine` | Both ports and their adapters, the first migration, and the new dependencies at aigateway's pins (`tortoise-orm[asyncpg]==1.1.8`, `asyncpg==0.31.0`, dev `testcontainers[postgres]==4.15.0`). All R3 producers, the App consumer, the sweeps, `/runs` and start binding. Helm: the gated database Secret on the App Deployment only, the gated migrate Job, and the shared `candidateOutcomes.*` values. CI: a Postgres step on testcontainers, like aigateway's (`.github/workflows/aigateway-tests.yml:82-85`). |
| P1b | `client-sf` | `client_key` and `POST /runs` before spend, the binding headers, `Report.run_id`, cancel on abort. `sf.runs`, `Run`, `CandidateRun`, `RunProgress`. The manifest keyed by `Run.id`. `attempt_id` and the deprecation. The D7 fallback. |

P1b works against an Engine without `/runs` (D7), so the landings can ship in either order.

## 6. Tests (written first)

- **P1a, registry contract.** One suite, run on SQLite in every CI run and on Postgres on
  testcontainers:
  - create, get and list, with filters, cursor and newest-first order; Runs created in the same
    instant list in a stable order (by id), and a state filter still fills each page;
  - a repeated `client_key` returns the existing Run;
  - another owner's id is not found; owners differing only in case or surrounding space are one
    owner;
  - a bind leaves the Candidate `pending` until `mark_scheduled`; re-binding the same
    `(run, candidate, topic)` succeeds; a different topic, or a topic bound elsewhere, is refused;
  - settle is idempotent, the first terminal wins, and compare-and-set holds under concurrent
    writes;
  - cancel is sticky; it moves `pending` Candidates to `stopped` and the run reads `canceled`,
    including a run that read `interrupted` with `pending` Candidates; when every Candidate is
    terminal it changes nothing;
  - every R5 row in order, on an injected clock, including overlaps (one `succeeded` plus one
    `lost` is `interrupted`); a read returns the state of that moment, so `pending` turns
    `interrupted` once the grace passes with no write; a late bind after `interrupted` reads
    `running` again;
  - reconcile writes only `lost`: with a surviving stream, a Candidate still live
    `run_lost_after_s` after its bind, and nothing younger; with a non-surviving stream, a
    pre-restart bind at once, and never a bind made since;
  - expire deletes exactly the Runs created before the cutoff.
- **P1a, outcomes.** One case per R3 producer, against the in-memory stream:
  - the in-process runner on success, failure, timeout and cancel;
  - a queue child's `SETTLED` line, with its cost;
  - a child killed before reporting, which falls back to the supervisor's classification;
  - a spawn failure and an expired message;
  - a tombstone followed by the worker's later claim, which publishes nothing more;
  - max deliveries racing a final success: only the writer whose terminal frame landed
    publishes, and the registry matches the frame;
  - a duplicate claim.

  The consumer: while the registry is failing nothing is acked; once it recovers, the
  redelivery settles in full. A repeat after success is a no-op.
- **P1a, routes.**
  - Hosted with no identity gives 401; local mode gives owner `local`.
  - A hosted App without a database URL serves `/runs*` as 404; with a SQLite URL it refuses to
    start.
  - A foreign or unknown id gives 404 `run_not_found` on every route.
  - A start under a canceled run gives 409 before anything is scheduled.
  - The same start re-sent after a 503 schedules; a start whose bind fails on the database still
    schedules.
  - A non-ASCII Candidate name binds through its index.
  - A start without `X-SF-Run` behaves exactly as today.
- **P1a, chart.** Parsed-YAML tests, like `.github/scripts/verify_chart_wiring.py`:
  - without `database.existingSecret`, the chart renders with no migrate Job and no required
    Secret;
  - with it, the App Deployment and the migrate Job carry the Secret;
  - the App and the runner pool render the same `candidateOutcomes.*` values.
- **P1a, database-writes-in-the-App guards (§9).**
  - The layering gate fails if anything under `runner/` or `worker/`, or any shared leaf,
    imports `runs/` or the registry adapter, or if any module outside them imports the database
    stack (`tortoise`, `asyncpg`, `aiosqlite`). `url4` depends on `httpx` only.
  - The rendered runner Deployment carries no database URL or Secret.
- **P1b, Client.**
  - `POST /runs`, with a `client_key` even when `save_results=False`, comes before the first
    token; the binding headers are on every start; `Report.run_id` is set.
  - 401, 404, a 503 and a transport error each give exactly one notice and output identical to
    today's.
  - A user abort sends `DELETE /runs/{id}`.
  - `sf.runs.list/get` against a fake Engine; `KeyError` for `run_not_found`, `runs_unavailable`
    for any other 404.
  - `wait` on every terminal state.
  - A `cancel` from a second Client stops the first Client's remaining starts.
  - `report()` reads the local store; without one it raises the D9 error; while `running` it
    raises `run_not_finished`.
  - `CandidateResult.run_id` warns and equals `attempt_id`; no SDK path warns.
  - Raw-URL4 and replay calls are registered.
  - Generated notebooks stay output-free and deterministic.

## 7. Out of scope

- **P2:** detach, the Engine taking over the fan-out, the reaper exemption, overnight auth
  (`OME-1611`, `OME-1617`), and opening a report on another machine (result storage and
  retention).
- **Elsewhere:** case-level live progress (E3, `OME-1288`), budget caps (P4, `OME-695`),
  comparison (P5), and continuing an `interrupted` run.
- **Not covered:** removing the topic from public metadata (`OME-966`). Identity for Cloudflare
  service tokens: they get no record under D7. Mount runs. Pre-P1 local manifests stay readable
  through `sf.reports`.

## 8. Risks

- **A database outage at start loses that Candidate's history.** The start still runs, but
  unbound (R2): the cancel check is skipped, and the Candidate's outcome reaches the consumer as
  an unbound topic. The Run then reads `interrupted` and that cost is missing. This is accepted,
  because the alternative makes every evaluation depend on the history database.
- **A lost outcome message** (a NATS failure at publish, or an outage longer than 24 h) is caught
  by R6 48 h after the bind. Until then the Run reads `running`; afterwards the Candidate reads
  `lost` even if its work succeeded, and its cost is unknown.
- **The owner key is an unsalted hash.** `sha256` of a normalised email (D6) can be matched by
  anyone who can read the `engine` database and hashes a list of known emails. This is accepted:
  the table holds Run metadata only, never prompts or results, and a keyed HMAC would add a
  per-environment secret whose loss or rotation orphans every Run.
- **Two apps share one Postgres pod.** It is single-replica, on a 4 Gi volume
  (`apps/aigateway/charts/db/values.yaml`). Run rows are small. Moving the `engine` database to
  its own server later is a URL change.
- **dev and prod may not use `charts/db`.** It is aigateway's chart default; a platform-managed
  Postgres has not been ruled out. R10's statements are the same either way.
- **The queue runner's in-memory state still pins `replicaCount: 1`**
  (`adapters/queue_runner.py:231-246`). P1 neither fixes nor worsens that.

## 9. Owner decisions

- **2026-10-29, Irina (product) and Kevin (engineering), on `OME-1294`.** The Engine App may
  become stateful. This reverses the stateless-App property of `OME-513`
  (`docs/spec/2026-07-21-url4-cloud.md` §1.1 and §3) and the non-goal of `OME-1016`
  (`docs/spec/2026-08-26-run-resume-and-control.md` §5). **The condition: the runners, and the
  url4 SDK inside them, stay stateless.** D3, D4 and the §6 guards meet it.
- **2026-10-30, Tauquir (spec owner), on that condition.** It is a design constraint, not a
  security boundary: every database write goes through the App, so the system is easy to reason
  about and runners can run anywhere, for example on AWS Lambda. The §6 guards catch accidental
  drift (a direct import of the registry or the database stack); they do not try to defeat a
  deliberate workaround, which review catches.
- **2026-10-30, Tauquir (spec owner).** Keep side effects minimal: no change to Garage or its
  lifecycle (D9). The namespace is `sf.runs`. The outcome stream is `url4-candidate-outcomes`,
  behind a port with a JetStream adapter and an in-memory adapter, with no mode branch (D4).
  Delivery is small stacked PRs, one sub-issue each under `OME-1785`.

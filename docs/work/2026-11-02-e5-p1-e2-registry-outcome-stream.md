---
ticket: OME-1800
stack: screamingface-engine
status: done
started: 2026-11-02
finished: 2026-11-02
---

# e5-p1-e2-registry-outcome-stream — PR 2: the Run registry and the candidate outcome stream

## Intent

PR 2 of the E5 P1 Engine stack (`docs/plan/2026-10-30-e5-p1-first-class-run.md`, units E2 and
E3; spec `docs/spec/2026-10-27-e5-p1-first-class-run.md`), stacked on E1 (#1627), under
`OME-1785`. It adds the `RunRegistry` port with its Tortoise store (SQLite and Postgres), and the
`CandidateOutcomeStream` port with its JetStream and in-memory adapters, plus the one classifier
that builds a `CandidateOutcome`. Nothing is wired; the App does not use any of it yet.

## Planned changes

- `apps/screamingface-engine/pyproject.toml` and `uv.lock`: `tortoise-orm[asyncpg]==1.1.8`,
  `asyncpg==0.31.0`, `aiosqlite==0.22.1`; dev `testcontainers[postgres]==4.15.0`; the
  `needs_postgres` marker. All at aigateway's pins.
- `src/screamingface_engine/candidate_outcomes.py` (new, shared leaf): `CandidateOutcome`, its
  JSON codec, `OutcomeDelivery`, and the `CandidateOutcomeStream` port.
- `src/screamingface_engine/run_evidence.py`: `SettlementWatch` (extends `TerminalWatch`, keeps the
  error code) and `settlement_of`, which builds a `CandidateOutcome` from `outcome_of`'s verdict
  and the summary's cost. `outcome_of` and `_on_done` are unchanged.
- `src/screamingface_engine/adapters/memory.py`: `InMemoryCandidateOutcomeStream`.
- `src/screamingface_engine/adapters/candidate_outcomes_jetstream.py` (new, shared leaf): the
  stream `url4-candidate-outcomes` (work queue, 24 h max age), a durable pull consumer with
  explicit acks, ensured in code (spec R11).
- `src/screamingface_engine/runs/registry.py` (new): the `RunRegistry` port and its errors.
- `src/screamingface_engine/runs/models/` (new): `base.py`, `run.py`, `candidate.py`; one file per
  model, each with an abstract `Base*` (tortoise-dev).
- `src/screamingface_engine/runs/store.py` (new): `TortoiseRunStore`. Facts only; every write is a
  conditional `UPDATE` guarded on the state it expects; state and `finished_at` derived on read.
- `src/screamingface_engine/runs/db.py` (new): the Tortoise config, built like
  `apps/aigateway/src/aigateway/db.py`, and `migrate`/`init_db`/`close_db`.
- `src/screamingface_engine/runs/migrations/0001_initial.py` (new), generated with
  `tortoise makemigrations` (S1).
- `src/screamingface_engine/runs/records.py`: column size limits on `RunSpec`.
- `src/screamingface_engine/config.py`: `database_url`, `run_retention_s`, `run_pending_grace_s`
  (validated above the Client's 900 s admission budget) and `run_lost_after_s`.
- `.github/workflows/screamingface-engine-tests.yml`: the registry contract on Postgres
  (testcontainers, behind `URL4_CLOUD_TEST_PG=1`), and the outcome-stream contract in the
  real-NATS conformance job.
- this ledger, and the `docs/tasks` mirror at PR-open.

## Test plan

- Registry contract (spec §6), one suite on SQLite and, marked `needs_postgres`, on Postgres:
  create, get and list (filters, cursor, newest first, ties by id, a state filter fills a page);
  a repeated `client_key`; foreign ids; owners differing in case or space are one; bind leaves
  `pending`, re-bind is a no-op, a different topic or a topic bound elsewhere is refused, a bind
  under a canceled run is refused; settle is idempotent, the first terminal wins, concurrent
  settles leave one winner; cancel is sticky, stops `pending`, reads `canceled`, changes nothing
  once all is terminal; every R5 row through the store on an injected clock, `pending` turning
  `interrupted` with no write, a late bind reading `running` again; reconcile writes only `lost`
  on both stream kinds; expire deletes exactly the Runs created before the cutoff.
- The migration applies to an empty database and the autodetector proposes nothing after it.
- Outcome stream contract over both adapters (JetStream skipped without a broker): publish then
  consume; no ack means redelivery; an ack means none; `ensure_stream` is idempotent;
  `survives_restart` is `True` for JetStream and `False` in memory. Codec round trip, cost exact.
- `settlement_of` for success, failure, timeout and cancel, with and without a frame and a cost.
  The existing `outcome_of` tests stay green unedited.
- Config: defaults, and a grace at or below 900 s refused.

## Acceptance

- All new tests pass; every prior test stays green and unedited; `run_gates.py
  screamingface-engine` and `run_gates.py repo` green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `tests/unit/run_registry_support.py` (the store fixtures,
  built by the real migrations) and `runs/models/__init__.py`.
- **Commits:** one, `feat(engine): add the Run registry store and the candidate outcome stream`.
- **Gates:** `run_gates.py screamingface-engine` and `run_gates.py repo` all green (6,4xx tests,
  95.7% total coverage). 159 new tests. The JetStream and Postgres parameters were also run
  locally against a real `nats:2.10-alpine -js` and `postgres:16-alpine`: all pass. New modules
  are at 100% except `runs/store.py` (95%: two race-recovery branches) and the JetStream adapter
  (49% in the default lane; the conformance job covers it). No prior test edited.
- **Deviations:**
  - Layout follows aigateway (owner decision 2026-11-02): the store, models, `db.py` and
    migrations live in `runs/`; there is no `adapters/run_registry_tortoise`. E1 renamed
    `runs/model.py` to `runs/records.py` to match.
  - Compare-and-set is on state, not a `revision` column (owner decision 2026-11-02): every
    write is one `UPDATE … WHERE` guarded on the state it expects. Spec §4.2 updated.
  - `outcome_of` keeps its tuple (the evidence line and its tests use it); the new
    `settlement_of` builds the `CandidateOutcome` from it, so there is still one classifier. A
    run with no terminal frame settles `failed` with `no_terminal_frame`.
  - `aiosqlite==0.22.1` is pinned explicitly, as aigateway does; Tortoise needs it for SQLite.
  - The test fixture clears Tortoise's `EXECUTOR_CACHE` per test: it is keyed by connection
    name, so one process switching SQLite to Postgres reused SQLite's placeholders. The App opens
    one database for its life, so production is unaffected.
  - `RunSpec` now enforces the column widths (E1 left them to E2).
  - Left for PR 3 (E4): `mark_scheduled` reports whether it applied, so a start that lost to a
    cancel aborts; the writer restarts its consumer after an error; the App and the pool apply
    changed stream limits at startup (`ensure_stream` creates and checks, never rewrites).
  - Locally, the full suite hangs when a NATS broker is reachable on `localhost:4222`
    (pre-existing broker tests; CI's main job has no broker). Not investigated in this unit.
  - Review of #1634 (owner decision 2026-11-05, spec D6 and §9): the owner key is the email
    trimmed and lowercased, as aigateway's account key. Two prior tests in `test_run_records.py` changed with it, pinned in
    `.claude/test-change-approvals/OME-1800.json`.
  - Every write locks its Run row first; a record is derived from one joined statement; `cancel`
    checks and sets under that lock (spec §4.2).
  - `CandidateOutcome` carries the producer's `finished_at` and refuses what the registry cannot
    store; a frame's unstorable code becomes `error_code_unstorable` (spec R3). A cost below the
    column's precision rounds up, never to 0.
  - `create` refuses a repeated `client_key` that names another evaluation
    (`ClientKeyConflict`); `list` refuses a cursor that names no Run (`InvalidCursor`). Their
    409 and 422 answers are mapped with the routes in PR 4.
  - `expire` deletes the Candidates first, so its count is the Runs it deleted on both databases.
  - The outcome codec treats `RecursionError` as malformed; `ensure_stream` also checks `discard`
    and `subjects`; `consume` applies this code's consumer config to an existing durable; the
    in-memory adapter refuses an empty topic and is bounded by age and count.
  - Settings refuse non-finite windows and a `run_lost_after_s` within the streams' retention.
  - `tortoise-orm` is held by hand in Dependabot for the Engine and the SDK, with a twin pin test
    in each (`test_tortoise_pin_conformance.py`).

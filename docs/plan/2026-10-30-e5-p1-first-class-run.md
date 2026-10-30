# E5 P1 plan: a first-class Run

Status: APPROVED by the owner 2026-10-30.

Spec (approved 2026-10-30): `docs/spec/2026-10-27-e5-p1-first-class-run.md`. Issue `OME-1785`,
under epic `OME-1294`.

## Shape

Two independent stacks of small PRs: **E1–E8** in `screamingface-engine` and **C1–C4** in
`screamingface`. The Client stack does not wait for the Engine stack: every Client PR is safe
against an Engine without `/runs` (spec D7).

- **Stacked.** Each PR branches from the one below it and targets it. When the base squash-merges,
  the next is rebased onto `origin/main` (`git rebase --onto origin/main <old-base-branch>`) and
  retargeted to `main`.
- **Each PR is safe to merge and deploy alone.** E1–E3 add code the App does not use. From E4 on,
  a hosted environment without the database runs with Runs off, exactly as today.
- **Linear:** each PR gets its own sub-issue under `OME-1785`, filed when that PR opens, with the
  owner's confirmation, so each branch carries its own `OME-N`.
- **Per PR:** RED first, the full stack gates, `run_gates.py repo`, a self-review, and its own
  ledger in `docs/work/` with the outcome filled before the PR opens. Tortoise work follows the
  `tortoise-dev` companion skill (built-in Tortoise migrations, never Aerich).

## Engine stack: `screamingface-engine`

Gates: `uv run .claude/scripts/run_gates.py screamingface-engine`. Paths are under
`apps/screamingface-engine/src/screamingface_engine/`.

**Module layout.** The layering gate (`.claude/scripts/check_layering.py`) keeps every database
write in the App (spec D3, §9), so the new code is split along it:

- `candidate_outcomes.py`, a **shared leaf**: `CandidateOutcome` and the `CandidateOutcomeStream`
  port. Importable by the App, the worker and the run half.
- `run_evidence.py` (existing; it imports only `url4.streaming`), a **shared leaf**: the one
  classifier, `SettlementWatch` and `outcome_of`.
- `runs/`, **control plane only**: the `RunRegistry` port and its types, the pure state function,
  the consumer and the sweeps.
- `adapters/run_registry_tortoise.py` (control plane), `adapters/candidate_outcomes_jetstream.py`
  (shared leaf, beside `adapters.jetstream`), and the in-memory adapter in `adapters/memory.py`.

### E1. Layering rule, Run types and state

Not wired. No dependency change.

- `check_layering.py`:
  - `runs` and `adapters.run_registry_tortoise` join the control plane, which bars the run mode
    and every shared leaf from them; a new rule bars the worker too.
  - No module outside the registry may import the database stack (`tortoise`, `asyncpg`,
    `aiosqlite`), exempt modules included. This is what keeps a process without the registry
    from opening a connection; the `URL4_CLOUD_DATABASE_URL` field in `config.py` (E2) is
    harmless on its own.
  - The rules catch accidental drift, a direct import; they are a design guard, not a security
    boundary (spec §9).
  - `candidate_outcomes`, `run_evidence` and `adapters.candidate_outcomes_jetstream` are unlisted,
    so they are shared leaves by the gate's default.
- New `runs/model.py`: `RunSpec`, `RunRecord`, `RunQuery`, `RunPage`, `OwnerKey`, the Candidate
  states. They keep only the domain rules (at least one Candidate, unique names stored stripped,
  `limit` bounds, a known `state`, an aware `since`); request types are checked by the route
  schemas (E8).
- New `runs/state.py`: R5 as a pure function with an injected clock.
- New `runs/ids.py`: the `run_` id, a random UUID in hex (spec D5), and its anchored pattern.

Tests:
- A fixture module under `worker/`, `runner/` or a shared leaf importing `runs` or the registry
  adapter fails the gate; the database stack imported anywhere outside `runs/` and the registry
  adapter fails, `local.py` included; the same imports from `app` (registry) and `runs/` (the
  stack) pass.
- Every R5 row in its stated order, including overlaps (one `succeeded` plus one `lost` is
  `interrupted`; `failed` plus a reaped `stopped` is `interrupted`; cancel flag with every
  Candidate terminal is `canceled`) and both sides of the `run_pending_grace_s` window.
- Ids have the `run_` + 32-hex form and are distinct; the pattern refuses anything else.

### E2. Registry port and Tortoise adapter

Not wired.

- The registry stores facts only (spec §4.3). The Run table: owner, `client_key` (unique per
  owner), benchmark, case count, client version, the cancel flag, `created_at` (indexed with the
  id for newest-first paging) and `last_activity_at`, which every write moves forward. The
  Candidate table: index, name, topic (unique), state, bind and finish times, cost and error
  code. A read derives the Run's state and `finished_at` with R5.
- `bind` leaves the Candidate `pending`; `mark_scheduled` moves it to `scheduled`. `cancel` moves
  `pending` Candidates to `stopped` and applies only while any Candidate is non-terminal.
- New `runs/registry.py` (the port), `adapters/run_registry_tortoise.py`,
  `runs/migrations/0001_initial.py`, and `runs/db.py`, with the config built like
  `apps/aigateway/src/aigateway/db.py:9-43`.
- `pyproject.toml`: `tortoise-orm[asyncpg]==1.1.8`, `asyncpg==0.31.0`, the dev dependency
  `testcontainers[postgres]==4.15.0` and the `needs_postgres` marker, all at aigateway's pins.
- `config.py`: `URL4_CLOUD_DATABASE_URL` (defaults to SQLite in the data dir only under
  `serve --local`), `run_retention_s` (30 days), `run_pending_grace_s` (1800 s; validated to exceed
  the Client's default admission budget) and `run_lost_after_s` (48 h).
- `.github/workflows/screamingface-engine-tests.yml`: a Postgres step on testcontainers, like
  aigateway's (`aigateway-tests.yml:82-85`), behind the Engine's own opt-in variable.

Tests: the spec §6 registry contract suite, on SQLite and, marked `needs_postgres`, on Postgres.

### E3. Candidate outcome stream

Not wired.

- `candidate_outcomes.py`: the port (`survives_restart`, `ensure_stream`, `publish`, `consume`)
  and `CandidateOutcome`.
- `run_evidence.py`: `SettlementWatch` (extending `TerminalWatch`, `:102-135`), and `outcome_of`
  (`:137`) returning a `CandidateOutcome` with the summary's cost. `_on_done` keeps its behaviour.
- `adapters/candidate_outcomes_jetstream.py`: the stream `url4-candidate-outcomes`, ensured in
  code like `url4-events` (spec R11).
- `InMemoryCandidateOutcomeStream` in `adapters/memory.py`.

Tests:
- One contract suite over both adapters: publish then consume; no ack means redelivery; an ack
  means none; `ensure_stream` is idempotent.
- `outcome_of` for success, failure, timeout and cancel, with and without a summary. The existing
  `outcome_of` tests stay green unedited.
- `survives_restart` is `True` for JetStream and `False` in memory.

### E4. Wire the registry and its one writer

The first PR that changes a deployment.

- New `runs/consumer.py`: consume, `settle`, and ack only after the commit. An unbound topic is
  acked as a no-op. It starts and stops in the App lifespan (`app.py`) and in `local.py`.
- Both the App and the runner pool call `ensure_stream()` for the outcome stream at startup.
- Startup (spec D2, R9):
  - `serve --local` applies pending migrations.
  - The App refuses to start on an older schema, or in hosted mode with a SQLite URL.
  - A hosted App with no URL runs with Runs off: a warning at start, no consumer, `/runs*`
    answer 404.
- Helm:
  - `templates/deployment.yaml`: the `database.existingSecret` Secret as
    `URL4_CLOUD_DATABASE_URL`, on the App only, rendered only when the value is set, with
    `optional: true`.
  - New `templates/job-migrate.yaml`, modelled on
    `apps/aigateway/charts/aigateway/templates/job-migrate.yaml`, rendered only when
    `database.existingSecret` is set.
  - `candidateOutcomes.maxAge` and `candidateOutcomes.maxBytes` in `values.yaml` and
    `values.schema.json`, rendered to both the App and the runner pool.
- `DEPLOYMENT.md`: the R10 runbook.

Tests:
- While the registry raises, nothing is acked. After it recovers, the redelivery settles in full.
  A repeat after success is a no-op.
- A hosted App with no database URL starts with Runs off and logs the warning; with a SQLite URL
  it refuses to start.
- A fresh SQLite migrates at local start. An un-migrated database stops the App with a message
  that names the migrate step.
- The spec §6 chart tests, and the rendered runner Deployment carries no database URL or Secret.

**Owner action to turn Runs on:** R10 in each environment. Until then the environment runs as
today.

### E5. App-side producers

- `adapters/inprocess.py` `_on_done` (`:154-169`), `adapters/queue_runner.py`
  `_publish_tombstone` (`:561-587`) and `adapters/max_deliveries.py` `_publish_failure`
  (`:153-195`) each publish one outcome, and only when their own terminal frame landed (spec R3).
- First step of the row: confirm each writer can tell whether its frame landed. If one cannot,
  stop and ask before changing how it writes.

Tests, one case per producer against the in-memory stream:
- in-process success, failure, timeout and cancel;
- a tombstone;
- max deliveries, and max deliveries losing to a final success (no outcome published).

### E6. Worker-side producers

- `child_protocol.py`: the `SETTLED {json}` encoder and decoder. It stays stdlib-only, and cost
  travels as a decimal string.
- The `runner/` child sends `SETTLED` from `executor.last_summary()` before it exits.
- `worker/supervisor.py`:
  - After `_publish_if_needed` (`:639-710`), it publishes the child's outcome when the child's
    terminal frame landed. If the child died first, it publishes its own classification, with no
    cost, when its own frame landed.
  - `_publish_terminal` (`:1209-1243`) publishes for a run that never executed.

Tests:
- The protocol round-trips, and malformed lines are rejected.
- A child's `SETTLED` line with cost.
- A child killed before reporting.
- A spawn failure and an expired message.
- A tombstone, then the worker's later claim, which publishes nothing more.
- Max deliveries racing a final success: the registry matches the landed terminal frame.
- A duplicate claim.

### E7. Sweeps: reconcile and retention

- New `runs/sweeps.py`, wired in `app.py` beside the artifact sweeper (`:156-170`) and in
  `local.py`, at start and hourly:
  - reconcile (spec R6), with the outcome stream's `survives_restart`;
  - expire (spec R7).

Tests:
- Reconcile never writes a terminal state or a cost.
- With a surviving stream, a Candidate still live `run_lost_after_s` after its bind reads
  `lost`, and a younger one is untouched, on an injected clock.
- A hosted restart with a still-queued Candidate: it stays `scheduled`, and the worker's outcome
  settles it with its cost.
- After a local restart, every in-flight Candidate reads `lost`.
- Expire deletes only Runs created before `run_retention_s`.

### E8. `/runs` routes, start binding and docs

- New `rest/runs.py`:
  - `POST /runs`, `GET /runs`, `GET /runs/{id}` and `DELETE /runs/{id}` (spec §4.1).
  - The owner is resolved through `require_identity` (`rest/mounts.py:116-129`).
  - An unknown or foreign id answers 404 `run_not_found`.
  - `DELETE` stops every live topic through the existing stop path.
- `rest/routes.py` start: reads `X-SF-Run` and `X-SF-Run-Candidate` (an index), binds before
  scheduling and calls `mark_scheduled` after (spec R2). A bind that fails on the database is
  logged, and the start proceeds unbound.
- `CHANGELOG.md`, and the `/runs` routes in `README.md`.

Tests: the spec §6 route tests, plus:
- `GET /runs` and `GET /runs/{id}` agree on state.
- A repeated `POST /runs` with the same `client_key` gives 200 and the same Run.
- A refused start leaves the Candidate `pending`.
- A start without the headers is unchanged. No existing start test is edited.

## Client stack: `screamingface`

Gates: `uv run .claude/scripts/run_gates.py screamingface`. Paths are under
`packages/screamingface/src/screamingface/`.

### C1. Runs wire client

Not wired.

- New `_engine/runs.py`, sync and async: `POST /runs`, `GET /runs`, `GET /runs/{id}` and
  `DELETE /runs/{id}`, decoded into frozen records. `POST /runs` carries `client_key` and is sent
  replay-safe (`_REPLAY_SAFE`).
- `POST /runs`: any non-2xx answer and any transport error maps to one internal "unavailable"
  result (D7).
- Reads and cancel: a 404 `run_not_found` maps to "unknown"; any other 404 to "runs not served";
  everything else raises as other Engine calls do.

Tests, on a fake transport:
- every route's success codes and 404;
- a lost `POST /runs` response is retried with the same `client_key`;
- a malformed body fails to decode;
- each D7 failure on `POST /runs`, including a 503, maps to "unavailable";
- on reads, `run_not_found` and a bare 404 map differently.

### C2. Register every evaluate

- `_evaluation/runner.py`, and the raw-URL4 and replay entry points (`_replay.py`): mint
  `client_key`, then `POST /runs` after preflight and before the first `POST /token`.
  `_results/evaluation.py` uses the same uuid when there is a result store, and keys the manifest
  by `Run.id`.
- `_engine/transport.py`: `X-SF-Run` and `X-SF-Run-Candidate` (the Candidate's index) on every
  start. A 409 `run_canceled` stops the remaining starts. `cancel_active` also sends
  `DELETE /runs/{id}`, best-effort.
- `report.py`: `Report.run_id`.

Tests:
- The call order is asserted on the fake transport.
- The headers are on every start, and `Report.run_id` is set.
- 401, 404, 503 and a transport error each give exactly one notice and a report identical to
  today's, compared field by field.
- `save_results=False` still sends a `client_key`.
- A user abort sends `DELETE /runs/{id}`; its failure changes nothing else.
- A cancel from a second Client stops the first Client's remaining starts.
- Raw-URL4 and replay calls register.

### C3. `sf.runs` and `Run`

- New `runs.py`, shaped like `reports.py`: `list` and `get`, with async twins.
- `Run`, `CandidateRun` and `RunProgress`, with `refresh`, `progress`, `wait`, `report` and
  `cancel` (spec §4.4), exported from `__init__.py`.
- `tests/public_surface_snapshot.json` gains the new names.

Tests:
- `list` and `get` against a fake Engine. An unknown id gives `KeyError`; an Engine that does
  not serve Runs gives `ExecutionError("runs_unavailable")`.
- `wait` on every terminal state, and on timeout.
- `report()` reads the local store; raises the D9 error without one; raises
  `ExecutionError("run_not_finished")` while `running`, and `ExecutionError("candidates_failed",
  ...)` on any other non-`complete` state.
- `cost_usd` sums the known costs only.

### C4. `attempt_id` and docs

- `report.py` (`:288`): `CandidateResult.attempt_id`. `run_id` becomes a property that warns with
  `DeprecationWarning` and returns `attempt_id`. The `run_id=` constructor keyword (`:350`) still
  works, with the warning. Saved-report JSON keeps its key.
- Every SDK reader of `CandidateResult.run_id` uses `attempt_id`: `_scoreboard/leaderboards.py:182`,
  `:348` (the `Idempotency-Key`) and `:809`; `_reproduction.py:102`, `:125`; `report.py:512`
  (`to_json`, which keeps the `run_id` key); `_inspect_log/payload.py:113`; `_ui/report_view.py:384`,
  `:843`; and `_results/store.py:96`, `:134` and `_evaluation/results.py:82`, `:168` where their
  `outcome` is a `CandidateResult`. The row ends with a search for `.run_id` that finds no
  `CandidateResult` reader left.
- `CHANGELOG.md`, a "Your runs" section in the SDK README, and docstrings. Notebooks are
  regenerated only if their output changes.

Tests:
- `run_id` warns and equals `attempt_id`; `CandidateResult(run_id=...)` warns and sets
  `attempt_id`.
- With `DeprecationWarning` as an error: leaderboard submit and edit, reproduction, log
  inspection, report export and the report view all pass.
- A report saved before the change loads with `attempt_id` set.
- The `check_notebooks` and `check_distribution` gates.

## Prior tests

No prior assertion is loosened. Expected edits, each listed in that PR's
`.claude/test-change-approvals/<OME-N>.json` for the append-only gate:

- C3: `tests/public_surface_snapshot.json` gains `runs`, `Run`, `CandidateRun`, `RunProgress`.
- C4: tests reading `CandidateResult.run_id` switch to `attempt_id`, or assert the warning.

If any other prior test needs a change, I stop and ask first.

## Owner actions

- R10 in each environment to turn Runs on, following the `DEPLOYMENT.md` runbook E4 adds.
- Confirm each sub-issue at its PR's open.

## Risks to watch while building

- `adapters/queue_runner.py` (872 lines), `worker/supervisor.py` (1,266) and `rest/routes.py`
  (969) are already large. New logic goes in new modules; these files gain only call sites.
- Rebasing a stack after each squash-merge: keep each PR's commits scoped to its own files so the
  `--onto` rebase stays mechanical.

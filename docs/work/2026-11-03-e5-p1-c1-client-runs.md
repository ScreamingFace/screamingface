---
ticket: OME-1815
stack: screamingface
status: in_progress
started: 2026-11-03
finished:
---

# e5-p1-c1-client-runs — PR 5: the Client half of a first-class Run

## Intent

PR 5 of the E5 P1 plan (`docs/plan/2026-10-30-e5-p1-first-class-run.md`, units C1–C4; spec
`docs/spec/2026-10-27-e5-p1-first-class-run.md`), from `origin/main`, under `OME-1785`. Every
`evaluate` registers a Run on the Engine before it spends, binds each start to its Candidate, and
cancels the Run on a user abort. `sf.runs` lists, reopens, waits on and cancels Runs.
`CandidateResult.run_id` becomes `attempt_id`. Against an Engine without `/runs` (an older one,
or Runs off) `evaluate` behaves exactly as today, with one notice (D7).

## Planned changes

Paths under `packages/screamingface/src/screamingface/`:

C1, the wire client:
- `_engine/runs.py` (new): `POST /runs`, `GET /runs`, `GET /runs/{id}`, `DELETE /runs/{id}`,
  sync and async, decoded into frozen records. `POST /runs` is replay-safe (`client_key`); any
  failure of it is one "unavailable" result. On reads and cancel, a 404 with code
  `run_not_found` is "unknown"; any other 404 is "Runs not served".

C2, register every evaluate (owner choice: in the transport):
- `_engine/transport.py`: `open_run` on both transports registers the Run and remembers each
  Candidate's binding; every start carries `X-SF-Run` and `X-SF-Run-Candidate`; a 409
  `run_canceled` stops the Run's remaining starts; an abort (`abort_evaluation`) runs
  `cancel_active` and sends `DELETE /runs/{id}`, best-effort, for the aborted evaluation's Run
  only, so another evaluation on the same Client keeps its Run. A 409 with a Run code is never taken for the start's own
  earlier attempt.
- `_core/ports.py`: the optional `_RunRegistration` port (a fake transport without it gets no
  Run).
- `_evaluation/runner.py`, `_evaluation/url4.py` (raw URL4 and replay): open the Run after
  preflight, before the first token; set `Report.run_id`. URL4 runs register as benchmark
  `"URL4 replay"` with 0 cases (owner choice).
- `_results/evaluation.py`: the manifest id is `Run.id`, or the `client_key` when unregistered.
- `report.py`: `Report.run_id`.
- `_runtime/server.py`: the local Engine's `database_url` in the data dir, when the bundled
  Engine has that setting.
- D7 notice: one `EvaluationWarning` (owner choice).

C3, `sf.runs`:
- `runs.py` (new): `list`, `get`, and their `_async` twins over the sync path; `Run`, `CandidateRun`,
  `RunProgress` with `refresh`, `progress`, `wait`, `report`, `cancel`; exported from
  `__init__.py`. `report()` off this machine raises `ExecutionError("results_not_local")`
  (owner choice).

C4, `attempt_id`:
- `report.py`: `CandidateResult.attempt_id`; `run_id` warns and returns it; `run_id=` still
  constructs, with the warning. Every SDK reader uses `attempt_id`.
- `CHANGELOG.md`, the SDK README "Your runs" section.

## Test plan

- C1: every route's success codes and 404s; a lost `POST /runs` response is re-sent with the same
  `client_key`; a malformed body fails to decode; each D7 failure maps to "unavailable"; on
  reads, `run_not_found` and a bare 404 map differently.
- C2: call order on a fake Engine (`POST /runs` before the first token); the headers on every
  start; `Report.run_id`; 401, 404, 503 and a transport error each give one notice and the same
  report; `save_results=False` still sends a `client_key`; an abort sends `DELETE /runs/{id}`,
  whose failure changes nothing; a `run_canceled` stops the remaining starts; raw URL4 and
  replay register.
- C3: `list`/`get` on a fake Engine; `KeyError` for an unknown id; `runs_unavailable` for a bare
  404; `wait` on every terminal state and on timeout; `report()` local, off-machine, running and
  not complete; `cost_usd` sums known costs only.
- C4: `run_id` warns and equals `attempt_id`; the constructor keyword warns; with
  `DeprecationWarning` as an error, the SDK paths that read it pass; an old saved report loads.

## Acceptance

- New tests green; targeted runs locally, CI runs the gates.
- Prior tests changed only as the plan lists (the public surface snapshot, `run_id` readers),
  each in `.claude/test-change-approvals/OME-1815.json`.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus `_engine/run_binding.py` (the per-Candidate Run bindings
  both transports share, so `transport.py` gains only call sites) and `_core/ports.py`
  (`_RunRegistration`, `_AsyncRunRegistration`). Tests: `test_runs_wire.py`,
  `test_run_registration.py`, `test_runs_api.py`, `test_attempt_id.py`,
  `test_runtime_engine_database.py` (new). `_replay.py` is unchanged: replay runs through
  `_evaluation/url4.py`, which registers. Spec §4.4 records the owner choices below; the plan's C2
  and Prior tests sections match what was built.
- **Commits:** one per unit on `e5-p1-c1-client-runs` (C1+C2, C3, C4, the R8 fix).
- **Gates:** targeted locally: ruff and pyright clean; the Client suite with the notebook extra
  passed (5281), coverage 97%. CI runs the full gates.
- **Prior tests (owner-approved, 2026-11-03), byte-pinned in
  `.claude/test-change-approvals/OME-1815.json`:** the public surface snapshot;
  `test_partial_submission_notice.py` and `test_analytics_integration.py` (`run_id` →
  `attempt_id` in a helper and a fake); `test_report.py` (`Report` now has `run_id`, `None` there);
  `_isolation_engine.py` (the fake Engine serves `POST /runs` and `DELETE /runs/{id}`).
- **Deviations:**
  - Owner choices: registration lives in the transport; the D7 notice is one
    `EvaluationWarning`; `Run.report()` off this machine raises
    `ExecutionError("results_not_local")`; raw-URL4 and replay register as `"URL4 replay"` with 0
    Cases.
  - `Run.wait(timeout=)` raises `TimeoutError`; `wait` on a finished snapshot returns it at once.
  - A Ctrl-C or task cancel of a one-Candidate or raw-URL4 evaluate also cancels its Run (R8):
    those paths never reach the sweep. Each Run is canceled once, within the 5 s stop bound.
  - The local Engine gets `database_url` only when its settings have the field, so this Client
    runs against an Engine from before or after E5 P1.
  - A passed `run_id=` wins over `attempt_id=`, so code that copies every field and then sets
    `run_id=` keeps its meaning.
  - The Client reads the Problem's `code` member (`run_not_found`, `run_canceled`), as the Engine
    writes it (PR 4).

---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: done   # planned | in_progress | done | blocked
started: 2026-09-28
finished: 2026-09-28
---

# engine-unclaimed-run-warning — warn the client about an unclaimed queued run; map broker publish failures to 503

Parent epic: **OME-1086** (Execute runs on a fixed worker pool pulling from a durable queue).
This unit fills the residual gap of **OME-1059** and **OME-948**. Both were closed as
superseded by OME-1086; their remaining intent is items 1 and 2 below.

## Intent

An admitted run that no worker claims stays `scheduled` with a silent socket for up to
~16 h 20 min (`capability_lifetime_s`). The client gets no signal. This unit:

1. Sends ONE generic `warn` notice to the attached client when a queued run has no frame
   after a configurable grace (`URL4_CLOUD_UNCLAIMED_RUN_WARN_S`, default 300 s). Warn only.
   The run is not failed.
2. Verifies how a non-capacity broker failure in `QueueJobRunner.schedule()` reaches the
   client, and maps it to a retryable RFC 9457 503 with `Retry-After` if it is a naked 500.
3. Checks for an alert-rule pattern in the repo charts. It adds rules only if a pattern exists.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/unclaimed.py` (new, policy only)
- `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py`
  (`accepted_ages()`; broker-failure translation in `schedule()`)
- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` (`RunQueueUnavailable`)
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` (503 mapping)
- `apps/screamingface-engine/src/screamingface_engine/config.py` (`unclaimed_run_warn_s`)
- `apps/screamingface-engine/src/screamingface_engine/app.py` (`_install_unclaimed_run_warner`)
- `apps/screamingface-engine/deploy/helm/{values.yaml,values.schema.json,templates/configmap.yaml}`
- `.claude/scripts/check_layering.py` (list `unclaimed` as control plane, like `reaper`)
- Tests: `tests/unit/test_unclaimed_run_warner.py`, `test_unclaimed_run_warner_wiring.py`,
  `test_queue_runner_accepted_ages.py`, `test_queue_schedule_broker_failure.py`,
  `test_chart_render_unclaimed_run_warn.py`

## Test plan

- Warner: warns once after grace; not before grace; never for a started or terminal run;
  no warn and no decision without a subscriber; an unreadable tail retries; state pruned.
- Wiring: installed only with a queue-aware runner and grace > 0; task starts and stops.
- Runner: `accepted_ages()` records only durably accepted runs.
- Broker failure: publish and admission-read broker errors become `RunQueueUnavailable`,
  the reservation is released; the route answers 503 problem+json with `Retry-After`.
- Chart: the ConfigMap renders `URL4_CLOUD_UNCLAIMED_RUN_WARN_S` from values.

## Acceptance

- A queued run with an attached WS and no frame after the grace gets exactly one WARN `Log`
  frame with generic text. A run that started never gets it.
- A broker failure in `schedule()` answers 503 + `Retry-After`, never a naked 500.
- `run_gates.py screamingface-engine` is green.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Source: `unclaimed.py` (new), `adapters/queue_runner.py`,
  `runner_queue.py`, `rest/routes.py`, `config.py`, `app.py`; chart `values.yaml`,
  `values.schema.json`, `templates/configmap.yaml`; `.claude/scripts/check_layering.py`.
  Tests (5 new files, 45 tests): `test_unclaimed_run_warner.py` (17),
  `test_unclaimed_run_warner_wiring.py` (11), `test_queue_runner_accepted_ages.py` (4),
  `test_queue_schedule_broker_failure.py` (9), `test_chart_render_unclaimed_run_warn.py` (4).
- **Commits:** `64b587d1` docs(engine): spec and plan · `c17a61ba` fix(engine): answer a
  retryable 503 when the run queue broker fails at schedule time · `178ed9a1` feat(engine):
  warn the attached client once when a queued run is not claimed · (this ledger commit).
- **Gates:** `run_gates.py screamingface-engine --base origin/main`: append-only ✓, ruff check
  ✓, ruff format ✓, pyright ✓, layering ✓, pytest 4103 passed / 19 skipped / **2 failed**,
  coverage 94.22% (≥ 80); `unclaimed.py` 100%. The 2 failures are
  `tests/integration/test_worker_spine.py` (`test_submit_claim_spawn_frames_terminal`,
  `test_a_warm_child_takes_the_run_and_is_replaced`). They fail the same way on pristine
  `origin/main` on this macOS host (checked in a temporary detached worktree): the warm child's
  `setrlimit` raises "current limit exceeds maximum limit". Not caused by this unit; CI (Linux)
  is the proof.
- **Item 2 finding:** confirmed BEFORE the fix — a `nats.errors.TimeoutError` from the publish
  gave `500 text/plain "Internal Server Error"`. Now 503 `application/problem+json`,
  `Retry-After: 5`, detail "the run queue is unavailable — retry shortly". Covers the admission
  depth read and the publish, for both ingresses (`GET /` and mount direct runs share
  `_schedule`).
- **Item 3 finding:** no chart in this repo ships alert rules (no `PrometheusRule`,
  `ServiceMonitor` or `PodMonitor` under `apps/*/deploy` or `apps/*/charts`). No rules added.
- **Deviations:**
  - The warner has its own process-wide task, not a call inside the reaper's loop (spec 3.3).
    Still no task per run.
  - `app.py` grows to ~615 lines (it was 551, already over the 450-line guide). The install
    function follows the `_install_orphan_reaper` pattern in the same file; moving the
    composition root is an unrelated refactor.
  - The pre-commit `ruff format` hook re-wrapped one unrelated line in `check_layering.py`
    (format only).
  - The chart render test was written after the chart edit; RED was proven by stashing the
    chart change (the test failed), then restoring it.

## Follow-ups

- **Queue alert rules (proposal; owner decides where they live — SigNoz or a chart
  `PrometheusRule`).** Metric names are from `metrics.py` / `worker/metrics.py`:
  1. `screamingface_engine_queue_oldest_unclaimed_age_s > 300` for 5 m → warning; `> 900` for
     5 m → critical. Same bound as the client notice, so an operator hears first.
  2. Zero free pool slots while work waits: `sum(screamingface_engine_worker_slots_busy) >=
     sum(screamingface_engine_worker_slots_total)` AND `screamingface_engine_queue_depth > 0`
     for 10 m → warning.
  3. No pool at all: `sum(screamingface_engine_worker_slots_total) == 0` (or the series is
     absent) AND `screamingface_engine_queue_depth > 0` for 2 m → critical — this is the case
     that kept runs silent for 16 h.
  4. Redeliveries rate `> 0` over 15 m → warning; any max-deliveries advisory → warning.
- Optional metric: a `unclaimed_warned_total` counter (the warner already counts
  `warned_total`) so an operator can see how often clients are told to wait.
- Linear bookkeeping from the audits (OME-1059, OME-948 closure comments; OME-1086 scope) is
  the owner's.

## Open owner questions

- Q1. Fail an unclaimed run after a bound shorter than 16 h (typed terminal error + tombstone)?
  This unit only warns.
- Q2. Where do queue alert rules live (SigNoz or the chart)?
- Q3. Is 300 s the wanted default for the client notice?

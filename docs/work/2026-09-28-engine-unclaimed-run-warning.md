---
ticket: unfiled   # slug-named ledger; set to OME-N when the issue is filed at PR-open
stack: screamingface-engine
status: in_progress   # planned | in_progress | done | blocked
started: 2026-09-28
finished:
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

- **Actual files:** <vs planned>
- **Commits:** <sha — message>
- **Gates:** <run_gates.py result line / counts>
- **Deviations:** <anything that differed from the plan, or "none">

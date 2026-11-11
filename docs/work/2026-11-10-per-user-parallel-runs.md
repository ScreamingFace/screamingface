---
ticket: OME-1880, OME-1881 (epic OME-1314)
stack: screamingface-engine
status: done         # planned | in_progress | done | blocked
started: 2026-11-10
finished: 2026-11-11
---

# per-user-parallel-runs — let one user run many more Engine runs at once

## Intent

The owner's goal (2026-11-10): put user experience over cost and let each user run many more
evaluations in parallel (target discussed: 50). This unit first maps how the per-user number is
set, where it is used and how it is enforced. The spec comes next, then the plan, then the code.
Related: runner-pool autoscaling (`OME-1870`, PR #1738) adds pods when queued runs can be claimed.

## Findings (research, 2026-11-10, at origin/main `5bdaa8569`)

One user's parallel work passes six limits, from outside to inside.

| # | Limit | Value (prod) | Where set | Scope |
|---|---|---|---|---|
| 1 | SDK fan-out per `sf.evaluate` call | 8 | `packages/screamingface/src/screamingface/_evaluation/runner.py:78` (`_MAX_CANDIDATES_IN_FLIGHT`), hard-coded | one call; no cap across calls |
| 2 | App admission: runs in flight per caller | 8 | `runner_queue.py:119` `DEFAULT_CALLER_INFLIGHT_CAP`; `config.py:404` `run_queue_caller_inflight_cap` (env `URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP`); not in the chart; not set in infra | per caller (`X-User-Email`), in memory, one App process |
| 3 | Queue: runs executing per bucket | 4 | chart `runnerPool.maxAckPending` (infra prod pins 4); default derives `replicas × workerSlots` (`deployment-runner.yaml:231`) | per bucket (16 buckets; users share a bucket by hash) |
| 4 | Pool: runs executing in the fleet | 8 | `replicas × workerSlots` = 2 × 4 | all users |
| 5 | Model calls inside runs | 4 per pod, split at spawn | `worker_io_capacity` 4 (`config.py:429`); `supervisor.py:1013-1028` divides by children, floor 1; judge calls separate: `CASE_GRADING_CONCURRENCY` 4 per run (`benchmark_aggregation.py:106`) | per pod / per run |
| 6 | Gateway: model calls per provider | openrouter 50 | `AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES` (aigateway `values-prod.yaml:49-52`); default 4 | all users, per aigw process; cache hits skip it |

Facts that matter for the design:

- **The real per-user execution limit in prod is 4, not 8.** Admission lets in 8; the bucket cap
  runs 4; the other 4 wait in the queue. A user who shares a bucket shares those 4 (chance
  `1 − (15/16)^k` with `k` other active users).
- **2 and 1 are coupled on purpose** (OME-1091 comments): "8 matches the Client's fan-out, so one
  ordinary Evaluation fits while a second concurrent one is refused".
- **Admission (2):** reserved in `schedule()` from `GET /?q=` (`queue_runner.py:680-728`);
  released on a terminal frame, a failed publish, or the 1 h lease (`runner_queue.py:127`).
  Refusal = 503 problem+json, `Retry-After` from the oldest reservation, clamped 30–300 s
  (`queue_runner.py:850-867`). The SDK re-sends for up to 900 s (`_engine/admission.py`), then
  fails with "run capacity stayed full". The counter is per process: sound only while the App
  has `replicaCount: 1` (`queue_runner.py:269-277`).
- **Queue (3):** a new `maxAckPending` does not change an existing durable consumer; the 16
  consumers must be deleted and made again while drained (`runner_queue.py:83-84,107-111`; seen
  on kind 2026-11-10). A higher value applies to every bucket, so it also raises what one
  bucket (one heavy user) can take from the shared pool.
- **Inner calls (5):** the per-pod model-call budget is fixed at spawn and does not rebalance
  (`FairShareGate` is local mode only). Pod total ≈ 4 to `4 + runs − 1`. Judge calls bypass it.
- **Gateway (6):** no per-user or per-profile limit exists (OME-920 not built). FIFO, so one
  user with many runs can hold most of the 50 slots. Queue wait up to 1800 s, then 503; the
  Engine retries once, then the Case fails.
- **In-process runner:** a global cap of 32 runs (`adapters/inprocess.py:116`), not per caller.

Tests that pin these values (append-only applies):

- SDK: `test_evaluate.py:42-43` (no `parallel` / `max_workers` argument);
  `test_admission_retry.py:124-127` (900 s budget). No test pins the 8.
- Engine admission: `test_queue_admission.py`, `test_queue_admission_release.py`,
  `test_runners_factory.py` use explicit caps; no test pins the default 8.
- Queue and pool: `test_chart_render_runner_pool.py:430-481`, `test_chart_render_bucket_count.py`,
  `test_queue_fairness.py`, `test_worker_claim.py:1507`.
- Gateway: `apps/aigateway/tests/unit/test_concurrency.py`, `test_provider_admission.py`.

## Impact analysis: 24 runs EXECUTING per user (2026-11-10)

Owner target changed to 24 parallel evals per user. Read as 24 runs executing at once.

Numbers to change (no code needed except the SDK):

- SDK fan-out 8 -> 24 (`runner.py:78`, hard-coded; code change).
- App per-caller cap 8 -> >= 24 (env `URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP`; the chart does not
  render it: add a value or `extraEnv`).
- `runnerPool.maxAckPending` 4 -> 24, plus delete and re-make the 16 durable consumers while the
  queue is drained.

Capacity (prod, OpenMined/infrastructure):

- One runner pod (4 slots): request 900m / 1540Mi, limit 10496Mi.
- `sf-fusion` quota `ns-ceiling` (requests 5 CPU / 8Gi, limits 48Gi, pods 20) fits 4 runner pods
  in total, INCLUDING the pods a rollout keeps for the drain (`quota.yaml:105-119`). 4 pods = 16
  slots for all users. One user at 24 needs 6 pods; U such users need 6U, x2 during a rollout.
- Tenant node pool: D8as_v7 (8 vCPU, 32 GiB), min 1, max 2 (`aks-platform/prod/main.tf:99-106`).
  Requests fit about 7 pods per node by CPU; real run memory (up to 2.5 GiB per run) fits about
  2-3 full pods per node (estimate). A bigger pool is new spend: owner approval first.

Gateway (aigw, one replica, 1000m / 512Mi limits; openrouter cap 50 per process, FIFO):

- Model calls per pod: `io_capacity // (children + spawning)`, floor 1, fixed at spawn: 4+2+1+1
  = 8 at a fresh pod, about 4-5 later. One 24-run user (6 pods) ~ 24-48 calls; judged benchmarks
  add up to 4 judge calls per run while grading. Cache hits skip the cap.
- One heavy user fits under 50; two or more queue in the gateway. The wait limit is 1800 s
  (`url4.toml:56` `timeout_s = 1800`; aigw takes `min(header, setting)`, `admission.py:41-57`),
  then 503, one Engine retry, then the Case fails. Expected effect: slower calls, not failures,
  until waits pass 30 min.
- Queued and in-flight calls hold their request bodies (and in-flight their responses) in the
  one 512Mi process: an OOM kill fails every in-flight call (risk, not measured).
- No per-user fairness in the gateway; > 1 replica needs code changes (process-local semaphore,
  caches, OAuth state). OpenRouter documents no concurrency cap (per-IP burst limits exist).
- `sf-aigw` quota (limits 4 CPU / 6Gi) allows a memory raise to 2Gi without an infra quota change.

Engine App and NATS:

- App: one replica, 512Mi limit; per run a WS session (1024-frame queue) + one NATS push
  consumer; reaper reads are O(armed topics). Cost per run not measured.
- Events stream `url4-events` 1 GiB drop-oldest, sized for 8 runs x 50 MB (`values.yaml:175-188`).
  At 48 runs ~21 MB each, at 100 ~10 MB: late attach / resume can miss early frames; runs do not
  fail. Fix: raise `events.maxBytes` (NATS PVC 10Gi x 3 in prod).
- Outcome stream 64 MiB refuse-newest (`values.yaml:207-211`): per-run size UNVERIFIED.

## Owner decisions (2026-11-10)

- Target: 24 runs per user. Fix the three hard blockers (App cap, bucket `max_ack_pending`, SDK
  fan-out). Quota and node pool belong to the infra team.
- The degrade risks are estimates: record them as a watch list, change nothing until a signal
  appears (spec "Watch list").
- Spec under epic `OME-1314`: `docs/spec/2026-11-10-per-user-parallel-runs.md`.

## Planned changes

Spec D1-D3 approved (Q1: default 24 in code; Q2: `GET /v1/limits`). Plan: `docs/plan/2026-11-10-per-user-parallel-runs.md`. Built by the `tiered-build` workflow.

## Test plan

To be decided in the spec.

## Acceptance

To be decided in the spec.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned. Engine: `runner_queue.py` (cap 24, `reconcile_consumers`,
  corrected comments), `config.py`, `worker/loop.py` (`_ConsumerReconciler`, one call in
  `Worker.run`), new `rest/limits.py` (`CallerLimits`, `GET /v1/limits`), `app.py`, `caller_inflight_cap`
  on `adapters/queue_runner.py` and `adapters/inprocess.py`, chart `values.yaml`, `values.schema.json`,
  `templates/configmap.yaml`, `README.md`, CHANGELOG, CI conformance lists; 6 new test files. SDK: new
  `_engine/limits.py`, `_evaluation/runner.py` (`load_caller_cap`, `cap` through `_settled_*` and the
  pool), `client.py` wiring, CHANGELOG; 2 new test files.
- **Build:** `tiered-build`. Run `wf_3249c84b-07e` lost its planner to Mac sleep (nothing built). Run
  `wf_08515758-828`: 2 waves, 6 tasks, green; it stopped at the gates on pyright errors in untouched
  `tests/unit/inspect/*` = inspect-ai in the engine venv (environment, not code; `uv sync --dev` fixed it).
  A false red byte-identity check (random jwtSecret) was repaired in the session script.
- **Design review (ACCEPT-WITH-FIXES, no structural finding), fixed in the main loop 2026-11-11:**
  (1) last "re-create to change max_ack_pending" claim in the `pull` docstring removed; (2) `cap` is
  required on `_settled_*` and two new tests prove the Engine cap reaches the pool through `evaluate`
  (6 Candidates, cap 3 => peak 3, sync and async); (3) one definition of the fallback 8 (`limits.py`
  takes it from the runner; `_evaluation` never imports `_engine`); (4) the cap is read BEFORE
  `open_run_*`, so no Run is registered while `/v1/limits` is slow (costs `# noqa: PLR0915` on
  `evaluate_sync/async`, with a reason); (5) `_cap_from` rewritten without a bare noqa; (6) new test:
  the TTL re-bind makes no consumer read or write; (7) `reconcile_consumers` gathers the 16 buckets
  and types `js` as `JetStreamContext`; (8) test docstrings no longer claim a "no sibling import" rule.
  Not changed: (9) no RED run for the chart test (accepted); (10) schema `""`/int form (as planned);
  (11) broad `except` in the SDK reader (spec D3 allows it).
- **Gates (final):** `run_gates.py screamingface-engine`, `screamingface`, `repo`: ALL GREEN. Default
  chart render byte-identical to `origin/main` (pinned jwtSecret). Real NATS 2.10: the CI conformance
  list = 57 passed, 0 skipped (includes `test_run_queue_reconcile_nats.py`).
- **Kind check (2026-11-11, kind `sf-prod`, image `local-pupr-final-1794374551`):** before, all 16
  `url4-runners-*` consumers read `max_ack_pending` 4. Deploy with `runnerPool.maxAckPending: 6`: after
  the runner rollout all 16 read 6, the worker logged `url4-runners-00 max_ack_pending 4 -> 6` (one line
  per consumer), and `GET /v1/limits` through the edge answered `{"caller_inflight_cap":24}`. Back to
  the normal values (derived 2 x 2 = 4): all 16 read 4 again (16 log lines `6 -> 4`), readyz 200.
  Side work: a first rebuild failed on a full Colima disk; the engine release was rolled back to
  revision 7 (no outage), host image copies and build cache were removed, then the build passed.
- **Commits / PRs (2026-11-11):** split at PR-open. Engine commit on `OME-1880-per-caller-run-cap-24`
  (sub-issue `OME-1880`); SDK commit on `OME-1881-sdk-fanout-from-engine-cap` (sub-issue `OME-1881`).
  Both rebased on origin/main `ecaabdf9c`.
- **Deviations:** the SDK fan-out cap read moved before `open_run_*` (plan said "before the fan-out";
  the review asked for before the Run exists).

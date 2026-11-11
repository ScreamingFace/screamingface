# Spec: let one user run 24 evaluations in parallel

- Date: 2026-11-10
- Epic: `OME-1314` (E23 · Scale current platform capacity to 30 concurrent users)
- Sub-issues: `OME-1880` (`screamingface-engine`), `OME-1881` (`client-sf`)
- Ledger: `docs/work/2026-11-10-per-user-parallel-runs.md` (research and impact analysis)
- Related: runner-pool autoscaling `OME-1870` (PR #1738); idle-pods-first `OME-1871`

## Problem

The owner wants one user to run 24 evaluations (Candidate runs) at the same time. Today one user
gets at most 4 runs executing and 8 runs in flight. Three limits in our code and chart cause this.
The namespace quota, the node pool and the autoscaling settings also limit it; the infra team owns
those (see "Infra handoff").

| # | Hard blocker | Today | Where |
|---|---|---|---|
| B1 | App admission: runs in flight per caller | 8 | `runner_queue.py:119` `DEFAULT_CALLER_INFLIGHT_CAP`; `config.py:404` `run_queue_caller_inflight_cap`; no chart value |
| B2 | Queue: runs executing per bucket (`max_ack_pending`) | 4 (prod pin) | chart `runnerPool.maxAckPending`; the value binds at consumer creation and a new value does not reach an existing consumer |
| B3 | SDK: runs sent at once per `sf.evaluate` | 8 | `packages/screamingface/src/screamingface/_evaluation/runner.py:78` `_MAX_CANDIDATES_IN_FLIGHT` |

## Facts this spec relies on

- F1. A WorkQueue consumer's `max_ack_pending` is editable in place on nats-server 2.10. Test on
  2026-11-10 (nats-server v2.10.29, nats-py): a consumer with cap 4 held 4 unacked messages;
  `add_consumer` with the same durable name and cap 24 succeeded; the 4 unacked messages stayed
  pending (no redelivery); the next fetch got the 2 remaining messages. The code comments that say
  "the consumer must be deleted and re-created" (`runner_queue.py:83-84`, `:107-111`) are wrong.
- F2. `pull_subscribe` on an existing durable binds without changing its config (kind walkthrough
  2026-11-10: consumers made with cap 4 kept 4 after the workers got cap 2).
- F3. The SDK re-sends a refused start (503 + `Retry-After`) for at most 900 s
  (`_engine/admission.py`), then fails the Candidate with "run capacity stayed full". An SDK that
  sends more runs than the Engine admits can therefore fail Candidates when earlier runs take
  longer than 15 min.
- F4. `test_evaluate.py:42-43` asserts that `evaluate` has no `parallel` or `max_workers` argument
  (a deliberate API decision).
- F5. Prod Engine image `url4.toml` sets `[aigateway] timeout_s = 1800`; the gateway uses
  `min(header, setting)`, so a model call can wait up to 1800 s in the gateway queue.

## Decisions

### D1. App admission cap: default 24, and a chart value (B1)

- `DEFAULT_CALLER_INFLIGHT_CAP` becomes 24. The Settings field and env var
  (`URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP`) stay as they are.
- New chart value `config.runQueueCallerInflightCap`, default empty. The App ConfigMap renders the
  env var only when the value is set. Empty means the code default. The default render stays
  byte-identical.
- The comments that tie the cap to the Client's fixed fan-out of 8 (`runner_queue.py:116-118`,
  `config.py:400-403`) change: the Client now reads the cap from the Engine (D3).
- Effect while prod still pins `maxAckPending: 4`: a user can have 24 runs admitted; 4 execute and
  20 wait in the Engine queue, not in the SDK. Admission, `Retry-After` and the 1 h lease do not
  change.

### D2. Workers keep the queue consumers' `max_ack_pending` in step (B2)

- New `RunQueue.reconcile_consumers()`. For each bucket consumer:
  - consumer not found: do nothing (the first pull creates it with the configured value);
  - `max_ack_pending` equals the configured value: do nothing;
  - otherwise: update the consumer in place. Send its CURRENT config with only `max_ack_pending`
    replaced, so no other field changes. Log old and new value.
- The worker calls it ONCE, at process start, before its claim loop. Not on the 300 s
  subscription re-bind. WHY: during a rollout the old pods drain for up to 16 h with the old value.
  They started before this change, so they never write. Only new pods write, once, and they all
  write the same value.
- A failed update logs a WARNING and the worker starts anyway, with the consumer's existing value.
  The run queue must not stop because a limit could not change.
- The App never writes a consumer (keeps the `OME-1870` invariant "the App never creates or binds
  a consumer").
- Lowering works the same way: NATS stops new deliveries until the running count drops below the
  new cap; running runs are not stopped.
- The wrong comments (F1) and the chart README / autoscaling-spec notes that say "delete and make
  again" change to "the next worker start applies it".
- The chart default for `runnerPool.maxAckPending` does not change (derived `replicas ×
  workerSlots`, OME-1142). Prod sets 24 in the infra values (handoff). With autoscaling on, the
  chart already requires a pinned value.
- Rollback note: a worker version without this code does not reconcile, so the consumers keep the
  last value written until a newer worker starts.

### D3. The SDK sizes its fan-out from the Engine (B3)

- New Engine route `GET /v1/limits`. Same authentication as the other `/v1` discovery routes
  (`/v1/operators`). Body: `{"caller_inflight_cap": <int>}`, the value admission enforces for this
  caller. Documented in OpenAPI.
- SDK: before it starts a multi-Candidate fan-out, it reads `GET /v1/limits` once per `evaluate`
  call. Fan-out = `min(number of Candidates, caller_inflight_cap)`, on the sync path (thread pool)
  and the async path (semaphore).
- Fallback: on 404 (an older Engine), a transport error, or a body without a positive integer, the
  SDK uses 8, today's value. This read never fails an evaluation.
- A single-Candidate evaluation does not read it (no fan-out).
- `evaluate()` gets no new argument (F4 stays true).
- WHY not a fixed 24 in the SDK: a new SDK against an Engine that still admits 8 would send 24,
  get 16 refusals and fail Candidates after 15 min (F3). Reading the Engine's value keeps the two
  in step for every Engine version and every per-environment setting.
- WHY a dedicated route and not a field on the Run record (`POST /v1/runs`): the Run record is
  also returned by run listings; a per-caller limit is not a property of a Run.

## Order of delivery

1. Engine PR (`screamingface-engine` sub-issue): D1, D2, the `/v1/limits` route of D3.
2. SDK PR (`client-sf` sub-issue): the client half of D3. It works against any Engine version
   (fallback 8), so it can merge any time after 1; it gives 24 only when the Engine answers 24.
3. Infra values (devops, OpenMined/infrastructure): `runnerPool.maxAckPending: 24`, autoscaling,
   quota and node pool. The next runner rollout applies the new consumer value (D2).

## Infra handoff (not in this repo)

- `kubernetes/apps/sf-url4-cloud/values/<env>.yaml`: `runnerPool.maxAckPending: 24`. Optional:
  `config.runQueueCallerInflightCap` only if an environment needs a value other than 24.
- Autoscaling (`OME-1870` prerequisites): KEDA add-on, NetworkPolicy, `maxReplicas`, quota for
  `2 × maxReplicas` runner pods, node pool max. Node pool size is new spend: owner approval first.
- Sizing guide: one user at 24 needs 6 runner pods (4 slots each); U such users need about 6U.

## Watch list (no change now; act only when the signal appears)

The owner decision (2026-11-10): these are estimated risks. Record them; change nothing until a
signal shows the problem.

| # | Risk | Signal to watch | Action when it appears |
|---|---|---|---|
| W1 | aigateway memory (one process, 512Mi limit) with many queued and in-flight calls | aigw container memory near its limit, or `OOMKilled` restarts | Raise `resources.limits.memory` in aigw prod values (the `sf-aigw` quota allows up to 6Gi) |
| W2 | aigateway OpenRouter cap 50 (FIFO, per process) with 2 or more heavy users | aigw 503 `provider_queue_timeout`; Case failures `aigateway_http_503`; long call latency | Raise `AIGW_PROVIDER_MAX_CONCURRENCY_OVERRIDES` openrouter; check the OpenRouter account limits first |
| W3 | Shared events stream 1 GiB, sized for 8 runs | `screamingface_engine_events_store_utilization_ratio` near 1; late attach / resume missing early frames | Raise `events.maxBytes` (NATS file store 10Gi per replica in prod) |
| W4 | Engine App memory (one replica, 512Mi) with many WebSocket sessions | App memory near its limit, or `OOMKilled` restarts | Raise the App memory limit |
| W5 | Scale-down removes busy pods; draining pods hold quota for up to 16 h | Runner pods in `Terminating` for hours; KEDA wants more pods than run | `OME-1871` (filed) |
| W6 | Two users in one bucket share its 24 | User reports of slow starts while the pool has free slots | Consider more buckets (cutover-sized change) |
| W7 | Outcome stream 64 MiB refuses new results when full | Outcome publish errors in the runner logs | Raise the outcome stream size |

## Non-goals

- Quota, node pool, autoscaling values, gateway and App resource limits (handoff and watch list).
- Per-user fairness in the pool or the gateway.
- Bucket count changes.
- More App replicas (the admission counter stays per process).
- A user-facing `evaluate()` argument for parallelism.

## Invariants

- Default chart render is byte-identical (D1 renders the new value only when set).
- The App never creates, binds or updates a queue consumer.
- Only a starting worker writes a consumer's `max_ack_pending`, and only that field.
- No running run is stopped or delivered twice by a cap change.
- The SDK never sends more runs at once than the Engine says it admits for the caller (or 8 when
  the Engine does not say).
- An unreadable `/v1/limits` never fails an evaluation.

## Test outline (RED first; tests are append-only)

Engine:
- The default caller cap is 24; the env var still overrides it.
- Chart: `config.runQueueCallerInflightCap` set → the ConfigMap has the env var; empty → the
  render equals the current default render.
- `GET /v1/limits` returns the enforced cap; it needs the same authentication as `/v1/operators`.
- `reconcile_consumers()`: raises a lower value; lowers a higher value; leaves an equal value
  alone (no write); skips a missing consumer; changes no field other than `max_ack_pending`;
  logs and continues on a broker error.
- The worker calls it once at start and not on the subscription re-bind.
- Integration (real NATS 2.10): runs in flight stay pending and are not redelivered when the cap
  is raised; the new cap admits more runs at once.

SDK:
- Fan-out follows `caller_inflight_cap` on the sync and async paths.
- Fallback 8 on 404, on a transport error, and on a bad body.
- A single Candidate makes no `/v1/limits` request.
- `evaluate()` still has no `parallel` / `max_workers` argument (existing test, unchanged).

## Owner answers (2026-11-10)

- Q1. The admission cap's code default is 24 (D1 as written).
- Q2. A dedicated `GET /v1/limits` route is accepted (D3 as written).

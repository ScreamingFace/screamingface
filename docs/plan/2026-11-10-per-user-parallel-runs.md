# Plan: let one user run 24 evaluations in parallel

- Spec: `docs/spec/2026-11-10-per-user-parallel-runs.md` (D1-D3; owner approved 2026-11-10)
- Ledger: `docs/work/2026-11-10-per-user-parallel-runs.md`
- Epic: `OME-1314`. Two sub-issues at PR-open: `screamingface-engine` (part A) and `client-sf`
  (part B). Build both in this worktree as two commits; split into two PRs at PR-open.
- Order inside the build: RED tests first, then code, then gates. Tests are append-only: never
  edit or delete an existing test. If an existing test fails because of a change below, STOP and
  report it (file, test name, failure); do not change the test.

## Part A — Engine (`apps/screamingface-engine`)

### A1. Caller cap default 24 (spec D1)

- `src/screamingface_engine/runner_queue.py:116-119`: `DEFAULT_CALLER_INFLIGHT_CAP = 24`. Replace
  the comment: the per-caller in-flight cap (OME-1091); 24 is the owner's per-user target
  (2026-11-10, OME-1314); the Client reads the enforced value from `GET /v1/limits` (spec D3), so
  the Client fan-out and this cap cannot drift.
- `src/screamingface_engine/config.py:400-403`: same comment change on
  `run_queue_caller_inflight_cap` (field, env name and `ge=1` unchanged).
- `src/screamingface_engine/runner_queue.py:83-84` and `:107-111`: the comments that say a
  `max_ack_pending` change needs the consumer deleted and re-created are wrong. New text: the value
  binds when the consumer is created; `pull_subscribe` on an existing durable does not change it;
  nats-server 2.10 edits it in place, and `RunQueue.reconcile_consumers()` (A2) applies it at
  worker start. Keep the V-5 part of `:107-111` (a deleted consumer can wedge a held subscription)
  — only the "required to change max_ack_pending" claim changes.

### A2. Chart value `config.runQueueCallerInflightCap` (spec D1)

- `deploy/helm/values.yaml`, in `config:` right after `runQueueBucketCount` (line ~154):
  ```yaml
  # The per-caller in-flight cap (OME-1091): how many runs one caller may have admitted at
  # once. Empty => the code default (24, OME-1314). Rendered to the App only; the Client reads
  # the enforced value from GET /v1/limits.
  runQueueCallerInflightCap: ""
  ```
- `deploy/helm/values.schema.json`: allow `""` or an integer `>= 1` for that key (follow how the
  schema declares other optional integers; if `config` is not in the schema, do nothing there).
- `deploy/helm/templates/configmap.yaml`, next to `URL4_CLOUD_RUN_QUEUE_BUCKET_COUNT` (line 56):
  ```yaml
  {{- if .Values.config.runQueueCallerInflightCap }}
  URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP: {{ .Values.config.runQueueCallerInflightCap | quote }}
  {{- end }}
  ```
  Empty value => nothing rendered => default render byte-identical to `origin/main`.
- `deploy/helm/README.md`: one line in the values / admission section naming the new value.

### A3. `RunQueue.reconcile_consumers()` (spec D2)

- File: `src/screamingface_engine/runner_queue.py`, method on `RunQueue`, placed after
  `_bound_subscription` (line ~1104).
- Signature: `async def reconcile_consumers(self) -> int` — returns how many consumers it updated.
- Behaviour, for each `subject in self.bucket_subjects()`:
  1. `info = await js.consumer_info(self._stream, _consumer_for(subject))`;
     `NotFoundError` => skip (the first pull creates it with `self._max_ack_pending`).
  2. `info.config.max_ack_pending == self._max_ack_pending` => skip (no write).
  3. Else `await js.add_consumer(self._stream, dataclasses.replace(info.config,
     max_ack_pending=self._max_ack_pending))`. Only that field changes; `durable_name`,
     `filter_subject`, `ack_wait`, `max_deliver` and everything else come from `info.config`.
     `logger.info("run queue consumer %s max_ack_pending %s -> %s", name, old, new)`.
  4. Any other exception for that bucket (`Exception`, not `BaseException`):
     `logger.warning(...)` naming the consumer and the exception type, then continue with the next
     bucket. Never raise.
- `js` comes from `await self._jetstream()` (same as `_consumer_infos`). If getting `js` itself
  fails, log a warning and return 0.
- Docstring: INVARIANT — called only by a starting worker (A4), never by the App and never on the
  subscription re-bind; only `max_ack_pending` changes; running runs stay pending (nats-server
  2.10 edits the field in place; spec F1).
- Exemplar for style: `RunQueue._consumer_infos` / `bucket_readings` (same file).

### A4. Call it once at worker start (spec D2)

- `src/screamingface_engine/worker/loop.py`:
  - New `@runtime_checkable class _ConsumerReconciler(Protocol)` with
    `async def reconcile_consumers(self) -> int: ...` (next to `_Queue`, line ~71). Do NOT add the
    method to `_Queue`: existing test fakes implement `_Queue` and must keep working.
  - In `WorkerLoop.run()` (line ~246), after the signal handlers and before the `TaskGroup`:
    ```python
    if isinstance(self._queue, _ConsumerReconciler):
        await self._queue.reconcile_consumers()
    ```
  - Nowhere else: not in `_claim_loop`, not in `pull`, not in `_bound_subscription`.
- Check `run_worker` (line ~608) builds the `WorkerLoop` with the real `RunQueue`, so the
  production path reaches the call.

### A5. `GET /v1/limits` (spec D3)

- Port: in the new `src/screamingface_engine/rest/limits.py` (the consumer defines the port; the
  `JobRunner` ABC lives in `packages/url4` — do NOT touch `packages/url4`):
  ```python
  @runtime_checkable
  class CallerLimits(Protocol):
      @property
      def caller_inflight_cap(self) -> int: ...
  ```
- Adapters:
  - `src/screamingface_engine/adapters/queue_runner.py`: a read-only `caller_inflight_cap`
    property returning the cap the adapter enforces (its constructor already receives
    `caller_inflight_cap`, `adapters/factory.py:81`).
  - `src/screamingface_engine/adapters/inprocess.py`: a read-only `caller_inflight_cap` property
    on the runner whose `__init__` takes `max_concurrent_runs` (line ~161-210), returning
    `self._max_concurrent`. WHY: in local mode one user owns the whole cap.
- `.claude/scripts/check_layering.py`: `rest` is already in `CONTROL_PLANE` (line ~99), so a new
  `rest/limits.py` needs no change; confirm the check passes.
- Route: new `src/screamingface_engine/rest/limits.py`, modelled on `rest/operators.py`:
  ```python
  router = APIRouter()

  @router.get("/v1/limits", tags=["Catalog"], summary="The caller's run limits")
  async def get_limits(request: Request) -> dict[str, int]:
      return {"caller_inflight_cap": _caller_inflight_cap(request)}
  ```
  `_caller_inflight_cap`: `request.app.state.job_runner` (set at `app.py:164`) if it satisfies
  `CallerLimits`; otherwise `request.app.state.settings.run_queue_caller_inflight_cap`.
  No route-level auth dependency (same as `/v1/operators`: the edge authenticates). No caching
  headers.
- Register the router in the `_ROUTERS` tuple in `src/screamingface_engine/app.py`.

### A6. Engine tests (new files only)

- `tests/unit/test_caller_inflight_default.py`: `Settings(jwt_secret=...)` default cap is 24;
  `URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP=7` overrides it; `runner_queue.DEFAULT_CALLER_INFLIGHT_CAP
  == 24`. Copy the Settings construction from an existing config test.
- `tests/unit/test_chart_render_caller_inflight_cap.py`: value `"30"` => the App ConfigMap has
  `URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP: "30"`; empty => the key is absent. Model on
  `tests/unit/test_chart_render_bucket_count.py` (helm render helper).
- `tests/unit/test_run_queue_reconcile_consumers.py` (fake JetStream with `consumer_info` /
  `add_consumer`; model the fake on `tests/unit/test_run_queue_unclaimed_depth.py`):
  raises 4 -> 24; lowers 24 -> 4; equal value => no `add_consumer` call; `NotFoundError` => skipped;
  the config sent keeps every other field of `info.config` (assert the dataclass equals the
  original with only `max_ack_pending` replaced); one bucket raising an exception => warning
  logged, the other buckets still reconciled, nothing raised; return value = number updated.
- `tests/unit/test_worker_reconcile_at_start.py`: `WorkerLoop.run()` with a fake queue that
  implements `reconcile_consumers` calls it exactly once before the first `pull`; a fake queue
  without the method still runs (no `AttributeError`). Reuse the WorkerLoop construction and drain
  trigger from the existing worker-loop unit tests.
- `tests/unit/test_rest_limits.py`: `GET /v1/limits` => 200 `{"caller_inflight_cap": N}` with the
  queue runner's cap; with a runner that is not `CallerLimits` => the Settings value. Model on
  `tests/unit/test_rest_operators.py`.
- `tests/integration/test_run_queue_reconcile_nats.py` (real NATS, skip when
  `URL4_CLOUD_TEST_NATS_URL` is unset — copy the skip/fixture pattern from
  `tests/integration/test_queue_unclaimed_depth_nats.py`): make a bucket consumer with cap 4,
  publish 6, fetch 4 without ack; a `RunQueue` with `max_ack_pending=24` runs
  `reconcile_consumers()` => returns 1, `consumer_info` shows 24, `num_ack_pending` still 4 (no
  redelivery), and a further fetch gets the 2 remaining messages. Second call returns 0.
- `.github/workflows/screamingface-engine-tests.yml`: add the new integration file to BOTH
  conformance lists (the run list and the skip-check list), with correct `\` continuations.

## Part B — Client SDK (`packages/screamingface`)

### B1. Read the cap from the Engine

- New `src/screamingface/_engine/limits.py`:
  - `DEFAULT_CALLER_INFLIGHT_CAP = 8` with a WHY comment: today's value; used when the Engine
    does not answer `GET /v1/limits` (an Engine older than OME-1314).
  - `def caller_inflight_cap_sync(http: httpx.Client) -> int` and
    `async def caller_inflight_cap_async(http: httpx.AsyncClient) -> int`: `GET /v1/limits`;
    return the body's `caller_inflight_cap` when it is an `int` (not `bool`) `>= 1`; otherwise —
    any non-200 status, `httpx.HTTPError`, non-JSON body, missing or bad field — return
    `DEFAULT_CALLER_INFLIGHT_CAP`. Never raise. Use the same request headers the SDK uses for
    `/v1/operators` (`engine_headers()` / the transport's client).
  - Exemplar: the `/v1/operators` fetch in `src/screamingface/_engine/catalog.py` (around line 40
    and its sync/async fetchers).
- Wire it like `load_operators`: `evaluate_sync` / `evaluate_async` in
  `src/screamingface/_evaluation/runner.py` get a new keyword `load_caller_cap: Callable[[], int]
  | None = None` (async: `Callable[[], Awaitable[int]]`). The public Client (`client.py`, where
  `load_operators=self._operator_catalog.load` is passed, lines ~352, ~369, ~867) passes a loader
  bound to the Engine http client at each of those call sites.
- Do NOT add an argument to the public `evaluate()` (`tests/test_evaluate.py:42-43`).

### B2. Use it for the fan-out

- `src/screamingface/_evaluation/runner.py`:
  - Keep `_MAX_CANDIDATES_IN_FLIGHT = 8` only as the fallback when `load_caller_cap is None`
    (rename is not needed; update its comment: "fallback; the Engine's `GET /v1/limits` sets the
    fan-out").
  - Read the cap ONCE per evaluate call, and only when there are 2 or more Candidates to run.
    One Candidate => no request.
  - Sync (`_run_candidates_sync`, line ~758): `max_workers=min(len(candidates), cap)`.
  - Async (`_run_candidates_async`, line ~896): `asyncio.Semaphore(cap)`.
  - Thread `cap` into those functions as a parameter; do not use a module global.

### B3. SDK tests (new files only)

- `tests/test_engine_limits.py`: sync and async readers: 200 with `{"caller_inflight_cap": 24}`
  => 24; 404 => 8; `httpx.ConnectError` => 8; non-JSON => 8; `{"caller_inflight_cap": 0}` /
  `true` / `"24"` / missing => 8. Use `httpx.MockTransport` (follow existing SDK transport tests).
- `tests/test_evaluate_fanout_cap.py`: with a fake transport, 30 Candidates and a loader returning
  24 => at most 24 runs in flight at once (sync and async; track the peak with a counter);
  loader returning 3 => peak 3; `load_caller_cap=None` => peak 8; one Candidate => the loader is
  never called. Model the fake transport on the existing runner tests that exercise
  `_run_candidates_sync`.
- Coverage gate for this stack is 95%: cover every branch of `limits.py`.

## Gates

- `uv run .claude/scripts/run_gates.py screamingface-engine`
- `uv run .claude/scripts/run_gates.py screamingface`
- `uv run .claude/scripts/run_gates.py repo`
- Default chart render byte-identical to `origin/main` (A2), and
  `.github/scripts/verify_chart_wiring.py` green (run Python through `uv`).
- Real NATS: `docker run -d --rm -p 4222:4222 nats:2.10-alpine -js`, then
  `URL4_CLOUD_TEST_NATS_URL=nats://127.0.0.1:4222 uv run pytest` on the engine conformance list
  (the CI workflow's list) — expect 0 skipped.

## Verification after the build (main loop, not the workflow)

- kind `sf-prod` (no model calls needed): deploy this branch's image with
  `runnerPool.maxAckPending: 6`; after the runner rollout, every `url4-runners-*` consumer reads
  6 (it read 4 before); `GET /v1/limits` through the edge answers `{"caller_inflight_cap": 24}`.
  Then put the cluster back to its normal values.

## Commits and PRs

- Commit 1 `feat(screamingface-engine): raise the per-caller run cap to 24 and keep queue consumer
  caps in step` (part A + spec/plan/ledger).
- Commit 2 `feat(screamingface): size the run fan-out from the Engine's per-caller cap` (part B).
- At PR-open (after the owner says yes): file the two sub-issues under `OME-1314`, add the
  `docs/tasks` mirrors, split into `OME-N-…` branches, `Refs:` in each body. The SDK PR does not
  depend on the Engine PR (fallback 8).
- If PR #1738 (autoscaling) merges first: its chart README paragraph and spec item 7 say
  "delete and make again"; change them to "the next worker start applies it" in this branch.

## Wisdom check

- Hexagonal: the route reads the limit from the component that enforces it (`CallerLimits` port,
  implemented by the runner adapters), not from a copy of the setting.
- No new public SDK argument; no change to admission, `Retry-After`, the lease, buckets or the
  depth ceiling.
- The reconcile writes only at worker start, so a rollout cannot flap the value.
- Watch-list items (spec W1-W7) are out of scope by owner decision.

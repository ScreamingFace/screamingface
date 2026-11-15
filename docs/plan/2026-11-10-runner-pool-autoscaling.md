# Plan — runner pool autoscaling on claimable queue demand

Spec: `docs/spec/2026-11-10-runner-pool-autoscaling.md`. Ledger:
`docs/work/2026-11-10-runner-pool-autoscaling.md`. Branch `runner-pool-autoscaling` (renamed
`OME-N-runner-pool-autoscaling` at PR-open). Stack `screamingface-engine` (`sdlc-python`).

## Frame

One PR, two halves that land together and default OFF:

1. App: measure claimable demand (spec D1), sample it on a cadence (D2), serve it (D3).
2. Chart: an opt-in KEDA ScaledObject that reads it (D4).

Out of scope: everything in the spec's Non-goals. Infra prerequisites go to the devops owner as a
hand-off list (spec, "Infrastructure prerequisites"), not code here.

Paths below are relative to `apps/screamingface-engine/`.

## Changes

### 1. `src/screamingface_engine/runner_demand.py` (new, CONTROL PLANE)

LAYERING: `runner_queue.py` is a shared leaf (the worker imports it), so it must not import this
module. `BucketReading` therefore lives in `runner_queue.py` (change 2) and this module imports
it. Add `"runner_demand"` to `CONTROL_PLANE` in `.claude/scripts/check_layering.py` with a WHY
comment in the style of `reaper` / `unclaimed`: left unlisted it would be a shared leaf a Runner
Job could import.

```python
from screamingface_engine.runner_queue import BucketReading

@dataclass(frozen=True, slots=True)
class RunnerDemand:
    demand: int
    running: int
    claimable: int
    queued: int
    unbound_buckets: int

def claimable_demand(readings: Sequence[BucketReading | None]) -> RunnerDemand: ...
    # None = consumer not bound yet -> unbound_buckets += 1, contributes 0.
    # headroom = queued if max_ack_pending <= 0 else max(0, max_ack_pending - running)

class DemandSource(Protocol):
    async def bucket_readings(self) -> list[BucketReading | None]: ...

class RunnerDemandSampler:
    def __init__(self, source: DemandSource, *, stale_s: float, clock: Callable[[], datetime]) -> None
    async def sample(self) -> None          # read, compute, store (demand, sampled_at); raise on error
    def snapshot(self) -> tuple[RunnerDemand, datetime] | None   # last good sample, any age
    def fresh(self) -> tuple[RunnerDemand, float] | None         # (demand, age_s) iff age <= stale_s
```

Pure function first, so the decision logic is tested without a broker. The sampler keeps the last
GOOD sample. A failed `sample()` raises, the periodic loop logs it, and the old sample ages out to
stale (spec D3 invariant).

### 2. `src/screamingface_engine/runner_queue.py`

Add the shared value type here, next to the queue that produces it:

```python
@dataclass(frozen=True, slots=True)
class BucketReading:
    running: int          # consumer num_ack_pending
    queued: int           # consumer num_pending
    max_ack_pending: int  # consumer config; <= 0 means "no cap" (JetStream -1)
```

`async def bucket_readings(self) -> list[BucketReading | None]` on `RunQueue`. Steps:

- Run `js.consumer_info(self._stream, _consumer_for(subject))` for each `self.bucket_subjects()`,
  concurrently with `asyncio.gather`.
- Map `nats.js.errors.NotFoundError` to `None`.
- Read `num_ack_pending`, `num_pending`, `config.max_ack_pending`. A server `None` becomes 0, and
  for `max_ack_pending` it becomes -1, meaning no cap.

Use the public `consumer_info` API, not `_api_request`. Do not bind or create consumers: that is
the worker's job, and the App must never create a consumer with its own `max_ack_pending`.

### 3. `src/screamingface_engine/adapters/queue_runner.py`

`async def bucket_readings(self)` delegates to `self._queue.bucket_readings()`. This makes
`QueueJobRunner` structurally a `DemandSource`. Admission state is not touched.

### 4. `src/screamingface_engine/config.py`

Next to `unclaimed_run_warn_s`, with WHY comments:

```python
runner_demand_sample_s: float = Field(default=15.0, ge=0.0)  # 0 = sampler off (was 5.0; owner 2026-11-10)
runner_demand_stale_s: float = Field(default=30.0, gt=0.0)
```

Add a model validator: if the sampler is on, `runner_demand_stale_s` must be at least
`2 x runner_demand_sample_s`. Otherwise one slow read flips the endpoint to 503.

### 5. `src/screamingface_engine/app.py`

`_install_runner_demand_sampler(app, job_runner, settings, clock)` copies
`_install_unclaimed_run_warner`:

- It is installed only when `isinstance(job_runner, DemandSource)` and `runner_demand_sample_s > 0`.
- It uses `_install_periodic(task_attr="runner_demand_task", tick_s=..., sweep=sampler.sample, ...)`.
- It sets `app.state.runner_demand` to the sampler, or to `None`.
- It logs "assumes a single replica", as the reaper and the warner do.

Call it from `create_app` next to the warner.

Also run one sample at startup, so the first reading does not wait a full tick. Add an optional
`sweep_on_start` parameter to `_install_periodic`, with default `False`, so existing callers are
unchanged.

### 6. `src/screamingface_engine/ops.py`

`GET /runner-demand` (`include_in_schema=False`, tag Ops):

| Case | Response |
|---|---|
| No sampler | 404, `{"status": "disabled"}` |
| No fresh sample | 503, `{"status": "stale", "age_s": <float or null>}` |
| Fresh sample | 200, with the spec D3 body |

The body holds integers and a timestamp only. Add a docstring INVARIANT: it never answers 0
without a reading.

### 7. `src/screamingface_engine/metrics.py`

Add `_RunnerDemandCollector(get_sampler)` and `register_runner_demand_metrics`, following the shape
of `_QueueCollector`. It yields the six gauges in spec D3 from `snapshot()`, and nothing before the
first sample. Register it in `create_app`.

### 8. Chart (`deploy/helm/`)

- **`values.yaml`**: add the `runnerPool.autoscaling` block from spec D4. Each key gets a WHY
  comment. Add a comment that `runnerPool.replicas` is ignored when the block is enabled.
- **`values.schema.json`**: add `autoscaling` under `runnerPool.properties`, with
  `additionalProperties: false`.
  - Integer minimums: `minReplicas >= 1`, `pollingIntervalS >= 1`, `podsPerStep >= 1`,
    `stepS >= 1`, `stabilizationS >= 0`.
  - `maxReplicas`: integer or null.
- **`templates/deployment-runner.yaml`**:
  - Wrap `replicas:` in `{{- if not .Values.runnerPool.autoscaling.enabled }}`.
  - Add `fail` guards next to the existing ones, for: maxReplicas unset, min > max, and
    `maxAckPending` unset while enabled. Each message names the values involved.
  - Render `URL4_CLOUD_RUN_QUEUE_MAX_ACK_PENDING` from the pinned value only. The existing
    `default (mul replicas workerSlots)` stays in place for the disabled path.
- **`templates/scaledobject-runner.yaml`** (new): rendered only when enabled, with the spec D4
  shape.
  - `scaleTargetRef.name` comes from the same helper the runner Deployment uses.
  - The URL is built from `screamingface-engine.fullname`, `.Release.Namespace` and
    `.Values.service.port`.
  - `targetValue` is `workerSlots`, quoted.
  - `minReplicaCount`, `maxReplicaCount` and `pollingInterval` come from values.
  - `advanced.horizontalPodAutoscalerConfig.behavior` holds the scaleUp and scaleDown windows and
    `Pods` policies.
- **`templates/NOTES.txt`**: when enabled, print "runner pool autoscaled min..max on /runner-demand".
- **`README.md`**: add a section "Autoscaling the runner pool". It covers the signal, the formula,
  the fail-static behavior, the scale-down cost (D5), and the infra prerequisites list.

### 9. CI

In `.github/workflows/screamingface-engine-tests.yml`, append the new integration test file to the
conformance job's file list. That job already runs a real `nats:2.10` and fails on skips.

## Test plan (RED first)

All new files. No existing test is edited, so no test-change approval is needed.

1. **`tests/unit/test_runner_demand.py`**, the pure function:
   - The spec scenario as a table, for n = 1, 4, 8: buckets A and B are `running=4, queued=4, cap=4`,
     bucket C is `running=0, queued=n, cap=4`. Demand is `8 + min(n, 4)`.
   - An empty queue gives 0.
   - Partial headroom: `running=2, queued=5, cap=4` gives claimable 2.
   - No cap (`-1`) makes all queued runs claimable.
   - An unbound bucket counts and contributes 0.
   - A bucket where `running > cap` (cap lowered while live) gives headroom 0, never negative.
2. **`tests/unit/test_runner_demand_sampler.py`**, the sampler:
   - Before any sample, `fresh()` returns None.
   - After a sample, it is fresh.
   - A failed sample keeps the old snapshot. That snapshot turns stale after `stale_s`. Use an
     injected clock.
   - A source error raises from `sample()`.
3. **`tests/unit/test_runner_demand_route.py`**: `/runner-demand` returns 404 when disabled, 503
   when there is no sample, 503 when the sample is stale, and 200 with the exact body when fresh.
   Assert that the body has no caller or topic keys.
4. **`tests/unit/test_runner_demand_metrics.py`**: no series before the first sample, then all six
   gauge names and values.
5. **`tests/unit/test_run_queue_bucket_readings.py`**: uses a fake JetStream with `consumer_info`.
   - Field mapping and `None` handling.
   - `NotFoundError` maps to None.
   - Other errors propagate.
   - There is no `pull_subscribe` or `add_consumer` call (the App never creates consumers).
6. **`tests/unit/test_app_runner_demand_wiring.py`**:
   - The sampler is installed for a queue runner when `sample_s > 0`.
   - It is not installed for an in-process runner, or when `sample_s = 0`.
   - The config validator rejects `stale_s < 2 x sample_s`.
   - `_install_periodic` default behavior is unchanged (no sweep at start).
7. **`tests/integration/test_runner_demand_nats.py`** (real NATS, conformance lane):
   - Create the queue stream and two bucket consumers with `max_ack_pending=4`.
   - Publish 6 runs to bucket A and 2 to bucket C.
   - Fetch 4 from A without acking.
   - Assert `bucket_readings()` and `claimable_demand()` give `running=4, claimable=2, demand=6`,
     where A's 2 held-back runs are excluded.
8. **`tests/unit/test_chart_render_runner_autoscaling.py`** (`helm template`, skip if no helm). It
   copies the `_render` helper of `test_chart_render_runner_pool.py`.
   - Default values render no ScaledObject, and the Deployment still has `replicas`.
   - The full default render equals a render with `autoscaling.enabled=false` set explicitly, which
     pins "disabled = unchanged".
   - Enabled (`min 2, max 5, maxAckPending 4`) renders exactly one ScaledObject with the right
     target name, URL, `valueLocation`, `targetValue == workerSlots`, min, max and behavior. The
     Deployment has no `replicas`.
   - The trigger URL host and port equal the rendered App Service name and port (parity).
   - The render refuses: no maxReplicas; `min 0`; `min > max`; enabled without `maxAckPending`.
     Each case asserts the error names the value.
   - With `workerSlots: 2`, `targetValue` is `"2"`.

Coverage: the new modules sit inside `screamingface_engine`, which has an 80% floor. The pure
function and the sampler aim for 100%.

## Gates

```
uv run .claude/scripts/run_gates.py screamingface-engine
```

These run ruff, ruff format, pyright, `check_layering.py`, and pytest with `-n auto --cov ...
--cov-fail-under=80`. Before PR-open, also run:

- `python3 .github/scripts/verify_chart_wiring.py`
- `helm lint apps/screamingface-engine/deploy/helm`

Check that `runner_demand.py` imports nothing from `adapters/` or `app.py`. The dependency points
the other way, through the `DemandSource` protocol. `check_layering.py` must pass with
`runner_demand` listed in `CONTROL_PLANE`, and `runner_queue.py` must not import it. That is
the one repo-script edit in this PR (`.claude/scripts/check_layering.py`). Its own tests
(`repo` stack) must stay green: `uv run .claude/scripts/run_gates.py repo`.

## Verification on kind (manual, recorded in the ledger Outcome)

`deploy/kind` already runs NATS and a 2 x 2 pool. Steps:

1. Install KEDA: `helm install keda kedacore/keda -n keda --create-namespace`, using a version the
   AKS add-on ships.
2. Deploy with these values: `autoscaling.enabled: true`, `minReplicas: 2`, `maxReplicas: 4`,
   `maxAckPending: 2`.
3. Use a stub aigateway, never a live provider. Check that a run takes minutes (a slow stub
   answer).
4. Submit 2 runs each as users A and B, which saturates 4 slots. Then submit runs as user C, in a
   different bucket.
5. Watch `kubectl get hpa,pods -w` and `curl .../runner-demand`. Expected:
   - demand goes to `4 + min(n, 2)`
   - a 3rd pod appears
   - C's runs are claimed
6. Let all runs finish. Expected: after the 300 s window, the pool returns to 2, and the idle pod
   exits in about 1 s.
7. Negative case: submit C's runs into A's bucket, or a capped bucket. Expected: no new pod.
8. Record the timings: queue to HPA desired, desired to pod ready, pod ready to claim.

## Rollout

1. This PR merges with the default OFF, so nothing changes in any environment.
2. Devops PR in OpenMined/infrastructure:
   - KEDA add-on
   - NetworkPolicy
   - quota sized for `2 x maxReplicas`
   - node pool max (with owner approval)
   - Argo CD `spec.replicas` handling
   - dev values `enabled: true`, `min 2`, `max 3`
3. Observe dev with a real backlog. Then move to staging, then prod.

## Wisdom check

- **Single App replica.** The App is the only reader. If the App is down, KEDA gets errors and the
  pool holds its size. No scale-down happens on missing data.
- **KEDA with `minReplicaCount > 0`** reuses the HPA's metric reads instead of its own polling
  (KEDA spec). This is fine: the HPA polls every 15 s.
- **Rollouts.** Runs on outgoing, draining pods are still unacked, so they count in `demand`.
  During a rollout the new ReplicaSet can scale one pod above need until they end. This is
  bounded by `maxReplicas` and the quota (spec D5).
- **Broker load.** 16 `CONSUMER.INFO` calls every 15 s is about 1 per second. That is negligible
  next to the workers' fetch loop.
- **Cold node.** When the node pool must grow, the first claim waits 3–5 min, plus the image pull.
  This PR does not fix that. Overprovisioning is a later problem.
- **`max_ack_pending` = -1** means unlimited, so all queued runs are claimable. Production pins 4.

## Owner decisions (2026-11-10)

1. Path and exposure: `GET /runner-demand` on the App port. **Accepted.**
2. Default windows: up immediately, 4 pods per 15 s; down after 300 s, 1 pod per 60 s. **Accepted.**
3. `pod-deletion-cost`: **follow-up PR.** See the spec section "Follow-up: choose an idle pod on
   scale-down". File it when this PR opens.

## Related, separate branch

`RunQueue.depth()` counts running runs as queued (spec "Side finding"). It is fixed on its own
branch `queue-depth-unclaimed`. If both touch `runner_queue.py`, whichever merges second rebases,
and reuses the other's consumer read if it fits.

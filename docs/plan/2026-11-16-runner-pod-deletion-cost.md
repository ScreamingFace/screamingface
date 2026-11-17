# Plan — the worker writes its busy slots as `pod-deletion-cost`

Spec: `docs/spec/2026-11-16-runner-pod-deletion-cost.md`. Ledger:
`docs/work/2026-11-16-runner-pod-deletion-cost.md`. Ticket `OME-1931` (epic `OME-1314`). Branch
`OME-1931-runner-pod-deletion-cost`. Stack `screamingface-engine` (`sdlc-python`).

## Frame

One PR, two halves that land together and default OFF:

1. Worker: a coalescing writer that PATCHes the pod's own annotation on a busy-count change (spec
   D1-D5).
2. Chart: an opt-in runner ServiceAccount, a mounted token, and the pod identity env (spec D6).

The two halves share one contract: the three env names of spec D5/D6. They have no shared file,
so they can be built in parallel. Docs are a third unit that depends on both.

Out of scope: everything in the spec's Non-goals, and all platform objects (spec D8).

Paths below are relative to `apps/screamingface-engine/`.

RULES for all changes:

- Tests are APPEND-ONLY: add new test files; do not edit or delete an existing test. If an
  existing test goes red, stop and report it; do not change the test.
- Follow the comment style of the files (WHY / INVARIANT / FEATURE notes).
- No new dependency. Use `httpx` and the standard library.
- The token must never be logged or put in an exception message that we build.

## Changes

### 1. `src/screamingface_engine/worker/deletion_cost.py` (new, WORKER MODE)

The port and the coalescing writer. No HTTP here.

```python
DELETION_COST_ANNOTATION = "controller.kubernetes.io/pod-deletion-cost"
MIN_WRITE_INTERVAL_S = 1.0
RETRY_INITIAL_S = 1.0
RETRY_MAX_S = 30.0

class PodCostWriter(Protocol):
    async def write(self, cost: int) -> None: ...   # raises on ANY failure
    async def aclose(self) -> None: ...

class DeletionCostPublisher:
    def __init__(
        self,
        writer: PodCostWriter,
        *,
        writes: Counter,                      # WorkerMetrics.deletion_cost_writes
        min_interval_s: float = MIN_WRITE_INTERVAL_S,
        retry_initial_s: float = RETRY_INITIAL_S,
        retry_max_s: float = RETRY_MAX_S,
    ) -> None: ...
    def notify(self, busy: int) -> None: ...  # sync; stores the number, sets the event; no I/O
    async def run(self) -> None: ...          # until cancelled; only CancelledError leaves it
    async def aclose(self) -> None: ...       # closes the writer; never raises
```

State: `_desired: int | None` (None until the first `notify`), `_written: int | None` (None until
the first good write), `_wake: asyncio.Event`, `_last_attempt: float | None` (loop time).

`run()` algorithm:

```
loop forever:
    await _wake.wait(); _wake.clear()
    backoff = retry_initial_s
    while _desired != _written:
        sleep until _last_attempt + min_interval_s (skip when _last_attempt is None)
        cost = _desired                      # read AFTER the sleep: the latest count wins
        if cost == _written: break
        _last_attempt = loop.time()
        try:
            await writer.write(cost)
        except Exception as exc:             # CancelledError is BaseException: it passes
            writes.labels("error").inc()
            log WARNING "pod-deletion-cost write failed with %r; retry in %.0fs"
            wait for (_wake is set) OR (backoff seconds), then _wake.clear()
            backoff = min(backoff * 2, retry_max_s)
            continue
        _written = cost
        writes.labels("ok").inc()
        backoff = retry_initial_s
```

Notes:

- `_desired != _written` with `_written is None` is true after the first `notify`, so the first
  `notify(0)` gives one write of 0 (spec D2, the start write).
- `notify` with the same number as `_desired` does not set the event.
- `aclose()` wraps `writer.aclose()` in `contextlib.suppress(Exception)`.

### 2. `src/screamingface_engine/worker/kube_pod.py` (new, WORKER MODE)

The `httpx` adapter of `PodCostWriter` and its builder.

```python
SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
WRITE_TIMEOUT_S = 5.0

class KubePodCostWriter:
    def __init__(self, *, client: httpx.AsyncClient, token_path: Path,
                 namespace: str, pod_name: str) -> None: ...
    async def write(self, cost: int) -> None: ...
    async def aclose(self) -> None: ...      # await client.aclose()

def build_pod_cost_writer(
    settings: Settings,
    environ: Mapping[str, str],
    *,
    service_account_dir: Path = SERVICE_ACCOUNT_DIR,
    client_factory: Callable[[str, Path], httpx.AsyncClient] = _default_client,
) -> KubePodCostWriter | None: ...
```

`write(cost)`:

- `token = token_path.read_text().strip()` on EACH call (WHY comment: the kubelet replaces the
  bound token before it expires; a cached token would stop working after about 1 h). The file is
  a few KB on tmpfs, so a sync read is accepted.
- `PATCH /api/v1/namespaces/{namespace}/pods/{pod_name}`, headers
  `Authorization: Bearer <token>` and `Content-Type: application/merge-patch+json`, body
  `json.dumps({"metadata": {"annotations": {DELETION_COST_ANNOTATION: str(cost)}}})` as bytes
  (`content=`).
- `response.raise_for_status()`.

`_default_client(base_url, ca_path)`:
`httpx.AsyncClient(base_url=base_url, verify=ssl.create_default_context(cafile=str(ca_path)),
timeout=WRITE_TIMEOUT_S)`.

`build_pod_cost_writer` returns `None`:

- with NO log when `settings.worker_deletion_cost_enabled` is false;
- with ONE `logger.warning` that names the first missing item, when the feature is on and one of
  these is missing: `settings.worker_pod_name`, `settings.worker_pod_namespace`,
  `environ["KUBERNETES_SERVICE_HOST"]`, the file `service_account_dir / "token"`, the file
  `service_account_dir / "ca.crt"`.

Base URL: `https://{host}:{port}` with `port = environ.get("KUBERNETES_SERVICE_PORT", "443")`. An
IPv6 host (it contains `:`) is put in brackets.

Exemplar for the injection style: `src/screamingface_engine/community_cache/__init__.py`
(`client_factory`) and `community_cache/aigateway.py`.

### 3. `src/screamingface_engine/worker/metrics.py`

Add one handle to `WorkerMetrics` and to `build_worker_metrics()`:

```python
deletion_cost_writes=Counter(
    "screamingface_engine_worker_deletion_cost_writes_total",
    "Writes of this pod's pod-deletion-cost annotation, labeled by outcome (ok, error).",
    ["outcome"],
    registry=registry,
),
```

Exemplar: `child_exit_codes` in the same file.

### 4. `src/screamingface_engine/config.py`

In the worker block, after `worker_metrics_port`:

```python
worker_deletion_cost_enabled: bool = False
worker_pod_name: str | None = None
worker_pod_namespace: str | None = None
```

With a FEATURE (OME-1931) comment: what the feature does, that the chart sets all three together,
and that a missing name is a fail-open case handled in `worker/kube_pod.py` (no validator; spec
D4).

### 5. `src/screamingface_engine/worker/loop.py`

- `Worker.__init__`: new keyword `deletion_cost: DeletionCostPublisher | None = None`, stored as
  `self._deletion_cost`.
- New method:

  ```python
  def _report_busy(self) -> None:
      busy = len(self._active)
      self._metrics.slots_busy.set(busy)
      # spec D2: no write after the drain signal; D3: notify is sync and cannot raise.
      if self._deletion_cost is not None and not self._draining.is_set():
          self._deletion_cost.notify(busy)
  ```

- Replace the two `self._metrics.slots_busy.set(len(self._active))` lines (in `_claim_loop` after
  the add loop, and in `_on_task_done`) with `self._report_busy()`. Keep the WHY comment about the
  order in `_claim_loop`.
- `run()`: after `self._pool.start()` and before the `try`, when `self._deletion_cost` is set:
  `self._deletion_cost.notify(len(self._active))` (the start write) and
  `cost_task = asyncio.create_task(self._deletion_cost.run())`. In the `finally`: cancel
  `cost_task`, `await` it with `contextlib.suppress(asyncio.CancelledError)`, then
  `await self._deletion_cost.aclose()`.
  INVARIANT comment: the task is NOT in the supervisors' TaskGroup, so a writer failure can never
  cancel a run (spec D3).
- `run_worker()`: build the publisher and pass it:

  ```python
  writer = build_pod_cost_writer(settings, os.environ)
  deletion_cost = (
      DeletionCostPublisher(writer, writes=metrics.deletion_cost_writes)
      if writer is not None else None
  )
  ```

  Build it inside `_main()` (the `httpx` client belongs to the running loop).

### 6. Chart: `deploy/helm/`

`values.yaml`, in `runnerPool:` after `autoscaling:` (comment style of the block: WHY /
INVARIANT):

```yaml
  deletionCost:
    enabled: false
  serviceAccount:
    create: true
    name: ""
    annotations: {}
```

Also change the two comments that name `OME-1871` as a future follow-up (the `scaleDown` block)
to name `runnerPool.deletionCost` and `OME-1931`.

`values.schema.json`: `runnerPool` has `additionalProperties: false`, so add `deletionCost`
(`{enabled: boolean}`, closed) and `serviceAccount` (`{create: boolean, name: string,
annotations: object}`, closed) with descriptions.

`templates/_helpers.tpl`: new helper `screamingface-engine.runnerServiceAccountName`:

- `deletionCost.enabled` false: the value of `screamingface-engine.serviceAccountName` (today's
  behavior);
- true: `default (printf "%s-runner" (include "screamingface-engine.fullname" .))
  .Values.runnerPool.serviceAccount.name`.

`templates/serviceaccount-runner.yaml` (new): rendered when `runnerPool.deletionCost.enabled` AND
`runnerPool.serviceAccount.create`. Name from the helper, labels as the runner Deployment
(`labelsBase` + `app.kubernetes.io/component: runner`), optional annotations,
`automountServiceAccountToken: false` on the object (WHY: only the runner pod opts in).

`templates/deployment-runner.yaml`:

- render guard, with the other guards: fail when `deletionCost.enabled` and
  `serviceAccount.create` is false and `serviceAccount.name` is empty;
- `automountServiceAccountToken`: `true` when enabled, else `false`; update the comment above it
  ("No token is mounted") to describe both cases;
- `serviceAccountName`: the new helper;
- env, only when enabled, after `URL4_CLOUD_WORKER_METRICS_PORT`:

  ```yaml
  - name: URL4_CLOUD_WORKER_DELETION_COST_ENABLED
    value: "true"
  - name: URL4_CLOUD_WORKER_POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: URL4_CLOUD_WORKER_POD_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
  ```

INVARIANT: with `deletionCost.enabled: false` the rendered runner Deployment is the same as on
`origin/main`, and no ServiceAccount document is added.

### 7. Docs

- `deploy/helm/README.md`: in "Autoscaling the runner pool", replace the **Scale-down** paragraph's
  "follow-up (OME-1871)" text and add a subsection "Idle pods first on scale-down
  (`pod-deletion-cost`)": what the worker writes and when, the values, the metric, the fail-open
  behavior, the accepted risk (spec D9), and the platform prerequisites (spec D8, 4 items, with a
  reference Role + RoleBinding YAML and the CiliumNetworkPolicy shape).
- `deploy/helm/templates/NOTES.txt`: only if it states that the runner mounts no token; then make
  the sentence conditional.

## Tests (new files only, `tests/unit/`)

1. `test_worker_deletion_cost_publisher.py` — a fake writer (records costs; can fail N times).
   Small intervals (0 to 0.02 s) by constructor. Cases: start write; one write per change; burst
   coalesces to the final value; same value gives no write; minimum interval is kept; failure is
   counted and retried; a newer value replaces a failed one; a writer that raises never makes
   `run()` raise; `notify` before `run()` is kept; `aclose` closes the writer and hides its error.
2. `test_kube_pod_cost_writer.py` — `httpx.MockTransport`. Cases: method, path, content type,
   exact body bytes, bearer token; the token file is read again on the second write; 403 and 500
   raise; the builder returns `None` silently when off; `None` + one warning for each missing
   prerequisite; base URL for IPv4 and IPv6; the token text is in no log record (`caplog`).
3. `test_worker_deletion_cost_wiring.py` — the fakes pattern of `test_worker_metrics.py`
   (`_FakeQueue`, `_FakeProcess`, `_HangingProcess`; copy them, do not import from a test file).
   Cases: `notify` gets the busy count after a claim batch and after a run ends; no `notify`
   after `_draining` is set; a publisher whose writer always fails does not change the run's
   terminal frame; `Worker` without a publisher behaves as before; settings defaults (three new
   fields); the env names map (`URL4_CLOUD_WORKER_POD_NAME` etc.).
4. `test_chart_render_runner_deletion_cost.py` — the `_render` pattern of
   `test_chart_render_runner_pool.py` (`helm template`, `skipif` without helm). Cases: default
   has no `-runner` ServiceAccount, `automountServiceAccountToken` false, none of the three env
   names; enabled has the ServiceAccount `<fullname>-runner` with automount false on the object,
   the pod's `serviceAccountName` and automount true, the three env entries with the two
   `fieldRef`s; `serviceAccount.name` override; `create: false` + name renders no ServiceAccount
   and uses the name; `create: false` + empty name fails the render; the App Deployment's
   ServiceAccount is unchanged in both cases; the schema refuses an unknown key under
   `deletionCost`.

## Gates

From the repo root: `uv run .claude/scripts/run_gates.py screamingface-engine` (append-only test
check, ruff, ruff format, pyright, layering, pytest with coverage). `helm` is installed locally,
so the chart tests run.

## After the build (not workflow tasks)

- Fill the ledger Outcome. Local commit. Kind walkthrough (spec, Acceptance). Then PR-open with
  `Refs: OME-1931`, and the answers to the ticket.

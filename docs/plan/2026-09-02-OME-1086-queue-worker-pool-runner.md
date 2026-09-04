# OME-1086 — implementation plan: queue-backed worker pool

Spec: `docs/spec/2026-09-02-OME-1086-queue-worker-pool-runner.md`. Read it first;
this plan does not restate the design, only how to land it.

Seven units. Each is one SDLC unit with its own ledger, worktree, branch, and PR.

## Execution order

```
OME-1087  port docstring          ─┐  independent, start any time
OME-1093  NATS durability (infra) ─┤  independent, HUMAN, start now — it gates the cutover
OME-1088  the run queue           ─┴─┐
                                     ├─> OME-1089  the worker      ─┐
                                     └─> OME-1090  status + cancel ─┤
                          OME-1088+1089 ─> OME-1091  admission     ─┤
                                                                    └─> OME-1092  cutover
                                              (also blocked by OME-1093)
```

| Unit | Landing | Actor | Blocked by |
| -- | -- | -- | -- |
| `OME-1087` | `packages/url4` | agentic | — |
| `OME-1088` | `apps/screamingface-engine` | agentic | — |
| `OME-1089` | `apps/screamingface-engine` | agentic | `OME-1088` |
| `OME-1090` | `apps/screamingface-engine` | agentic | `OME-1088` |
| `OME-1091` | `apps/screamingface-engine` | agentic | `OME-1088`, `OME-1089` |
| `OME-1092` | `apps/screamingface-engine` | agentic | `OME-1089`, `OME-1090`, `OME-1091`, `OME-1093` |
| `OME-1093` | infrastructure repo | **human** | — |

`OME-1093` is on the critical path and is the only human unit. Start it first, in
parallel with everything else, or the cutover waits on it.

## Conventions for every unit

Per `CLAUDE.md` and the `sdlc-python` skill:

1. `git fetch origin && git worktree add .claude/worktrees/OME-N-<desc> -b OME-N-<desc> origin/main` — branch from `origin/main`, never from the current checkout.
2. Create `docs/work/YYYY-MM-DD-OME-N-<desc>.md` from `docs/work/TEMPLATE.md` **before** touching code, and move the Linear issue to In Progress.
3. **RED first.** Write the failing test named in the unit's Steps, watch it fail, then implement.
4. Gates: `python3 .claude/scripts/run_gates.py` for the stack. For `apps/screamingface-engine` that is ruff check, ruff format --check, pyright, `check_layering.py`, and pytest with `--cov-fail-under=80`. For `packages/url4` the threshold is 95.
5. Conventional commit, body `Refs: OME-N`, no `Co-Authored-By`. PR, green CI, squash-merge. Never commit to `main`.
6. Fill the ledger Outcome before committing; close the Linear issue and the `docs/tasks/` mirror with the card's `close_template`.

---

## OME-1087 — Correct the JobRunner capacity contract

Smallest unit, no dependencies, and it removes the wrong belief `OME-1064` blamed.

### Steps

1. **RED:** `packages/url4/tests/unit/test_jobs_port.py` — assert `JobRunnerAtCapacity.__doc__` does not contain the cluster-backed carve-out, and that it does state the general rule. This test exists to stop a future revert restoring the false claim.
2. Rewrite the `JobRunnerAtCapacity` docstring: **any** substrate with a finite declared ceiling raises it; the caller maps it to retry-after. Delete the sentence "A cluster-backed runner lets the scheduler absorb the load and never raises."
3. Extend the `JobStatus` docstring to record that `scheduled` means "accepted, not yet started" — i.e. queued — so nobody adds a `queued` member later.
4. Grep for the same claim repeated elsewhere. `OME-1064` names `apps/screamingface-engine/src/screamingface_engine/rest/routes.py:200-202`; fix every copy in the same commit.

### Files

- `packages/url4/src/url4/streaming/interfaces/jobs.py` (modify)
- `packages/url4/tests/unit/test_jobs_port.py` (modify)
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` (comment only)

### Gates

`packages/url4`: ruff, format, pyright, pytest `--cov-fail-under=95`.
Touching `rest/routes.py` also runs the engine stack's gates.

---

## OME-1088 — The run queue

### Steps

1. **RED:** `tests/unit/test_run_queue_stream_config.py` — assert the queue stream is declared with `retention=WorkQueue`, `storage=file`, `num_replicas=3`, and a name that does **not** start with `url4-cloud_`.
2. **RED:** `tests/unit/test_run_queue_sweeper_exclusion.py` — assert `owns_stream()` refuses the queue name, and that a sweep with the queue present leaves it alive. **This is Trap 1 and the most important test in the epic**: without it, a sweep silently drops every queued run.
3. **RED:** `tests/unit/test_jetstream_consumer_config_split.py` — assert the event-stream consumer config still returns `AckPolicy.NONE` after the split, and the queue's returns `EXPLICIT` with `max_deliver=2`, `ack_wait`, and `max_ack_pending`.
4. **RED:** a duplicate publish of one topic yields exactly one message (`Nats-Msg-Id` dedupe).
5. Split `_consumer_config()` in `adapters/jetstream.py` into two named builders — one for broadcast replay readers, one for the work queue. Do **not** add a branch to the existing function; the event streams depend on its current behaviour and the split is what makes that dependency explicit.
6. Add `runner_queue.py`: stream declaration, `publish(message)` with `Nats-Msg-Id = topic`, `pull(batch, timeout)`, `depth()` and `oldest_age()` from `stream_info`, cached ~1-2s.
7. Add the message codec. It renders **through `job_env`** — the same functions `K8sJobRunner._env` uses. Assert in a test that a message round-trips to the identical env mapping the Job path produces, so the two encodings cannot diverge while both exist.
8. Add `owns_stream()`'s explicit queue exclusion, belt-and-braces beside the naming rule.
9. Settings: queue stream name, subject prefix, `duplicate_window`, `ack_wait`, `max_deliver`, `max_ack_pending`, depth ceiling, `max_age` storage backstop. Every one a `Settings` field with a default, because the chart renders exactly the set `Settings` declares.

### Files

- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/adapters/jetstream.py` (modify — the config split, `owns_stream`)
- `apps/screamingface-engine/src/screamingface_engine/config.py` (modify — new settings)
- `apps/screamingface-engine/tests/unit/test_run_queue_*.py` (new)
- `apps/screamingface-engine/tests/unit/test_jetstream_consumer_config_split.py` (new)
- `apps/screamingface-engine/tests/integration/test_run_queue_roundtrip.py` (new — real broker)

### Gates

Engine stack. Watch `check_layering.py`: `runner_queue.py` is imported by both the
serving half and the worker half, so it must import nothing from the run half.

---

## OME-1089 — The worker

### Steps

1. **RED:** `tests/unit/test_worker_claim.py` — a message whose topic already has a terminal frame is acked and **never** spawns a child.
2. **RED:** slot accounting never exceeds `worker_slots`, and the fetch batch equals free slots.
3. **RED:** child exit classification — exit 0 with a terminal frame published by the child (worker adds nothing); exit non-zero, signal, and 137 each produce a **named** terminal frame from the worker.
4. **RED:** a child hung past `deadline_s + STREAM_GRACE_S + margin` gets SIGTERM then SIGKILL, and a terminal frame is published.
5. **RED:** `in_progress()` heartbeats keep a long child's message unredelivered past `ack_wait`.
6. **RED:** `tests/unit/test_worker_child_memory_cap.py` — a child spawned with a per-run `RLIMIT_AS` that allocates past it dies **alone**; the worker and its siblings survive. This is the test that makes "subprocess isolation" true rather than aspirational.
7. **RED:** drain — on SIGTERM the worker stops pulling, in-flight children survive to `drain_grace_s`, then terminate with a `worker_draining` reason.
8. **RED:** a message whose capability has expired is acked with a `queue_expired` terminal frame and no child.
9. Implement `worker/` — the claim loop, the supervisor, the heartbeat task, the hard wall, and the drain handler. Use `asyncio.TaskGroup` for the supervisors so a failure cancels siblings deterministically, and `asyncio.create_subprocess_exec` for children. Every spawned task is owned; no fire-and-forget `create_task`.
10. Spawn children under `RLIMIT_AS` via a small exec wrapper, **not** `preexec_fn` — CPython documents `preexec_fn` as unsafe with threads, and this process runs an event loop plus the NATS client's own.
11. Add the `worker` mode to `cli.py`, beside `serve` and `run`, keeping the image one artifact with modes.
12. Extend `.claude/scripts/check_layering.py` with the worker half: it may import the serving half and `runner_queue`, and must import **nothing** from the run half. The worker spawns the run; it never imports it. That is what keeps the cold start down and the layering check meaningful.
13. Forward child stdout/stderr to the worker log with the topic bound. Add no logging of the expression — `runner/main.py` logs its length rather than its content on purpose (`OME-990`).

### Files

- `apps/screamingface-engine/src/screamingface_engine/worker/__init__.py`, `loop.py`, `supervisor.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/cli.py` (modify — the `worker` mode)
- `apps/screamingface-engine/src/screamingface_engine/config.py` (modify — `worker_slots`, `drain_grace_s`, `worker_io_capacity`, per-run memory budget)
- `.claude/scripts/check_layering.py` (modify — the worker half's rule)
- `apps/screamingface-engine/tests/unit/test_worker_*.py` (new)
- `apps/screamingface-engine/tests/integration/test_worker_spine.py` (new)

### Gates

Engine stack. The layering gate now has a third half to satisfy.

---

## OME-1090 — Status derivation and queue-aware cancellation

### Steps

1. **RED:** `tests/unit/test_queue_runner_status.py` — the spec's truth table, one test per row, including the capability-expiry boundary between `scheduled` and `not_found`.
2. **RED:** cancel-before-claim — `DELETE /` writes `Terminated(stopped)`; the worker then claims, skips, and acks exactly once.
3. **RED:** cancel-while-running — the control request reaches only the owning worker; the child is terminated; `Terminated(stopped)` appears once.
4. **RED:** `stop()` on an unknown topic stays idempotent and `DELETE /` still returns 204.
5. **RED:** `RunReaper` audience loss cancels a **queued** run. The Job path covered this by deleting a Job that might never have started; the queue path must not lose it.
6. **RED:** the queue-position notice reaches an attached socket and is superseded once `StartedEvent` arrives.
7. Add `QueueJobRunner(IdentityAwareJobRunner)`: `schedule()` publishes; `stop()` writes the tombstone and sends the control request; `status()`/`exists()` derive from the event stream plus capability validity.
8. Add the control subject: workers subscribe to `url4.runctl.*`; only the owner replies; the App treats no-reply within a short timeout as "not running here".
9. Push the queue-position notice through the WS bridge's existing `add_notifier` path. No protocol change and no stream write.
10. Subscribe the App to `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.*` and publish a named terminal failure for a run the queue gave up on.

### Files

- `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py` (new)
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py` (modify — select it)
- `apps/screamingface-engine/src/screamingface_engine/worker/loop.py` (modify — control subscription)
- `apps/screamingface-engine/src/screamingface_engine/app.py` (modify — advisory subscriber)
- `apps/screamingface-engine/src/screamingface_engine/ws/bridge.py` (modify — notice only if needed)
- `apps/screamingface-engine/tests/unit/test_queue_runner_*.py` (new)

### Gates

Engine stack.

---

## OME-1091 — Admission on queue depth, and fair scheduling

### Steps

1. **RED:** depth at ceiling raises `JobRunnerAtCapacity`, and the REST edge answers 503 with a `Retry-After` **derived from depth and throughput**, not the constant `1`.
2. **RED:** two admissions racing the last slot inside one refresh window cannot both pass — the reservation counter carried over from `OME-1065`.
3. **RED:** a per-caller in-flight cap refuses caller A's N+1 run while caller B is still admitted.
4. **RED:** round-robin pull interleaves two callers' runs instead of draining one caller first.
5. **RED:** the spawn-time io budget equals `worker_io_capacity / active_children` and appears in the child env as `URL4_CLOUD_IO_CONCURRENCY`.
6. Implement depth-based admission in `QueueJobRunner.schedule()`, reusing the cached-snapshot-plus-reservation shape `OME-1065` built. The counted resource changes; the race does not.
7. Implement per-caller subjects. Prefer a **stable hash** of the identity value as the bucket key, not the raw address — a subject name is readable by anything with broker access. (Spec open question 1.)
8. Implement round-robin pull across buckets in the worker.
9. Implement the spawn-time io budget in the supervisor.
10. Update `OME-908` with a comment stating precisely which half this closes and which half remains (dynamic rebalancing), so that issue does not read as fully delivered.

### Files

- `apps/screamingface-engine/src/screamingface_engine/adapters/queue_runner.py` (modify)
- `apps/screamingface-engine/src/screamingface_engine/runner_queue.py` (modify — buckets, round-robin)
- `apps/screamingface-engine/src/screamingface_engine/worker/supervisor.py` (modify — io budget)
- `apps/screamingface-engine/src/screamingface_engine/rest/routes.py` (modify — derived `Retry-After`)
- `apps/screamingface-engine/tests/unit/test_queue_admission.py`, `test_queue_fairness.py` (new)

### Gates

Engine stack.

---

## OME-1092 — Cut over the chart and retire the Job adapter

The cutover. **Blocked by `OME-1093`** — shipping this against a memory-backed
single-replica broker would be a regression dressed as an improvement.

### Steps

1. **RED (rendered-manifest tests, the `charts.yml` precedent):** the pool Deployment renders with the declared concurrency, the hardened securityContext, `envFrom` the existing runner-env ConfigMap, both checksum annotations, and `terminationGracePeriodSeconds > drain_grace_s`.
2. **RED:** **no** `batch/jobs` RBAC renders anywhere in the chart.
3. **RED:** a test asserting no import of the kubernetes client remains under `apps/screamingface-engine`.
4. Add `deploy/helm/templates/deployment-runner.yaml` and its values: `replicas`, `worker_slots`, resources, `drain_grace_s`, `preStop`, `maxUnavailable: 0`, and a PodDisruptionBudget.
5. Delete `templates/role.yaml` and `templates/rolebinding.yaml`, and the ServiceAccount's need for them.
6. Delete `adapters/k8s.py` entirely — `K8sJobRunner`, `_manifest`, `_env`, `_env_from`, `_QuotaSnapshot`, and the quota-admission block — plus its factory branch, the `kubernetes` dependency in `pyproject.toml` if nothing else uses it, and the settings only the Job path read (`job_ttl_s`, the k8s request timeout, the resource/nodeSelector/toleration plumbing).
7. **State in the commit body that queue-depth admission supersedes `OME-1065`.** A merged capacity feature is being deleted; the history must explain why, or the next reader will restore it.
8. Add the metrics and alerts the spec's Observability section names, with the oldest-unclaimed-age alert first — it is the one that would have fired on 2026-09-01.
9. Decide `worker_slots`' first deployed value against the node size `OME-1058` settles. Prefer starting narrow and widening after observation. (Spec open question 2.)

### Files

- `apps/screamingface-engine/deploy/helm/templates/deployment-runner.yaml`, `poddisruptionbudget.yaml` (new)
- `apps/screamingface-engine/deploy/helm/templates/role.yaml`, `rolebinding.yaml` (delete)
- `apps/screamingface-engine/deploy/helm/values.yaml`, `values.schema.json`, `values-cloud.yaml` (modify)
- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py` (delete)
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py` (modify)
- `apps/screamingface-engine/pyproject.toml` (modify — drop the kubernetes client)
- `apps/screamingface-engine/tests/unit/test_chart_render_runner_pool.py` (new)
- `apps/screamingface-engine/tests/unit/test_runners_k8s.py`, `test_cache_policy_threading.py`, `test_identity_header_propagation.py`, `test_adapters_extra_models.py`, `test_job_env_contract.py` (modify or delete — they target the deleted adapter; **port the ones that assert the env contract to the queue codec rather than deleting them**)

### Gates

Engine stack, plus `charts.yml`. Run `helm template` and read the output — the
`charts.yml` gate exists because `helm lint` reports success for a chart that
cannot render.

---

## OME-1093 — NATS durability and HA (human, infrastructure repo)

Lands in `OpenMined/infrastructure`, like `OME-1058`. Not this monorepo.

### Steps

1. Enable file-backed JetStream with a PersistentVolume. Size it as `pool concurrency × 50 MiB` (each run event stream's `max_bytes` reservation) plus the queue's own `max_bytes`, plus headroom. The kind rig's storage class is `standard`, not `local-path`.
2. Run 3 NATS replicas so JetStream metadata has a quorum.
3. Confirm `num_replicas: 3` on the work-queue stream specifically. The per-run event streams may stay R1 — they are transient and already lost on a broker restart today, which is out of scope.
4. Do not use `helm --wait` for this rollout, and expect the NATS reloader to fail on inotify in the kind rig.
5. **Failure-injection drill, which is the acceptance:** enqueue a run, `kubectl delete pod` the broker, and prove the run still executes. Without this evidence the prerequisite is unmet and `OME-1092` stays blocked.

### Acceptance

- An enqueued run survives a full broker restart and executes.
- `nats` runs 3 replicas with file storage; the work-queue stream reports `num_replicas: 3`.
- Storage headroom documented against the 50 MiB-per-run reservation.

---

## Cutover runbook

1. `OME-1093` merged and its drill evidence attached to the issue.
2. `OME-1087` … `OME-1091` merged; the queue path exercised in the integration spine.
3. Deploy `OME-1092` to the preview environment. Watch oldest-unclaimed age, slots busy, and redelivery count for a full evaluation.
4. Run a 9-candidate `draco-3pass` evaluation — the exact shape that failed on 2026-09-01 — and confirm every candidate completes, and that queue position is visible to the client throughout.
5. Deploy to production during a window with no long evaluation in flight; the deploy regression is real.

## Rollback

The owner chose one cutover, so **rollback is a chart revert plus a code revert**,
not a flag flip. Concretely: revert the `OME-1092` merge, which restores
`adapters/k8s.py`, the Job RBAC, and the quota admission, then redeploy. The
runner pool Deployment must be scaled to zero first, or queued runs will be
claimed by workers from the old image.

This is the cost of the no-coexistence decision, and it is why the preview soak in
step 3 of the runbook is not optional.

# OME-1086 — Execute runs on a fixed worker pool pulling from a durable queue

## Problem

Job-per-run makes the Pod count a variable the **client** chooses, against a quota
and a node the **operator** fixed.

`OME-1064` recorded the collision: a 9-candidate `draco-3pass` evaluation reported
24% progress, froze for 23 minutes with no error, and failed every candidate with
`websocket_disconnected`. Nothing crashed. The Engine pod never restarted and the
AI Gateway served 4,000–5,800 req/min with zero errors. The runs simply never got
Pods.

Five ceilings decided how many runs could exist, and none of them knew about the
others:

```
SDK        _MAX_CANDIDATES_IN_FLIGHT = 8    ← the CLIENT picks the fan-out
Engine     (K8s mode: no limit at all)      ← 32 exists only in the in-process adapter
Quota      requests.cpu: 2  → 8 runners     ← binds, at exactly the SDK's fan-out
Node       1 × D4as_v5 (4 vCPU), not autoscaled, shared with ~5 namespaces
Gateway    provider_max_concurrency = 4
```

Blast-radius mapping for this spec found a **sixth**: every run's JetStream event
stream reserves 50 MiB of `max_bytes` at creation, so the broker's store is itself
a concurrency ceiling (a 10Gi store caps out near 200 concurrent runs). Nobody had
counted it because nothing surfaces it.

Three sibling units make the collision legible without removing it:

- `OME-1065` (done) refuses a run when the namespace quota has no headroom.
- `OME-1059` (in progress) reports an unschedulable Job as a typed error.
- `OME-1058` sizes the node, which is necessary and still leaves the mismatch.

The cause is structural. While one Pod per run exists, the Pod count is elastic
against a fixed quota, and every layer either absorbs the load or breaks quietly.

## Decision

A **fixed pool of worker Pods** pulls runs from a **durable queue**. Pod count
becomes constant and declared. The queue becomes the elastic part.

```
Client ──POST /token──> App          (unchanged)
Client ──WS attach────> App          (unchanged; 428 if skipped)
Client ──GET /?q=…───> App
                        ├─ admission: queue depth vs ceiling → 503 + Retry-After
                        └─ publish ──> WorkQueue stream `url4-runq`
                                       (file storage, R3, Nats-Msg-Id = topic)
                                          │ durable pull consumer `url4-runners`
              Worker Pod (N slots) ── claim ──> fork `screamingface-engine run`
                                                  └─ publishes frames as today
App ── consumes `url4-cloud_<topic>` ──> WS ──> Client   (unchanged)
```

Owner decisions, 2026-09-02:

| Decision | Choice |
| -- | -- |
| Isolation | **Subprocess per run** inside the worker |
| Migration | **Replace `K8sJobRunner` outright** — no coexistence flag |
| NATS durability + HA | **In scope**, as a hard prerequisite (`OME-1093`) |
| Deployed fairness | **In scope** (`OME-1091`), as run-level + spawn-time budget |
| Retire the Job adapter and its RBAC | **In scope**, same plan (`OME-1092`) |
| Queue-depth autoscaling (KEDA) | **Out of scope** |

### Why a queue in NATS rather than a database or a new broker

NATS is already the run-event transport, already in the chart, already in the
mesh, and already has a client in this app (`adapters/jetstream.py`). The engine
owns no database, so a Postgres-backed queue would introduce a stateful
dependency to an app that has none. A second broker would add an operational
surface for no capability the existing one lacks.

The cost of this choice is that NATS becomes load-bearing for **accepting** work,
not only for streaming it. That cost is exactly `OME-1093`, and it is a
prerequisite rather than a hardening task — see the Traps section.

### Why subprocess per run rather than tasks in one process

Three reasons, in order of weight:

1. **The crash domain stays one run.** A run that exhausts memory kills its own
   child. In a task-per-run worker it kills every co-tenant run in the process.
2. **The run process contract does not change.** `runner/main.py` already *is*
   "one process, one run, read env, exit". The worker replaces
   `create_namespaced_job` with `fork/exec` and reuses `job_env` rendering
   verbatim. This is what keeps the change small enough to be reviewable.
3. **`check_layering.py` stays satisfiable.** That script keeps the serving-side
   and run-side import graphs disjoint, which is what holds a run's cold start
   down. Because the worker *spawns* the run rather than importing it, the worker
   joins the serving half and imports nothing from the run half.

The cost is ~1–2s of fork and import per run, and that `FairShareGate` cannot span
runs — see Fairness.

### What deliberately does not change

- **The client wire contract.** `POST /token`, the WebSocket attach frame, `GET /?q=…`,
  `DELETE /`, the frame stream, and the capability JWT are untouched. No SDK change
  is required by this epic.
- **The run process.** `runner/main.py`, `lifecycle.run`, `run_and_reclaim`, the
  per-run event stream, and the terminal-frame guarantee are untouched.
- **`job_env.py`'s rendering.** The queue message carries exactly the per-run
  values `K8sJobRunner._env` builds today, and the worker renders them to child
  env through the same functions. There must not be a second encoding.
- **The `JobRunner` port signatures.** A queue is just another substrate.
  `IdentityAwareJobRunner` is implemented by a new adapter; nothing widens.

### Rejected alternatives

- **Coexistence behind the factory flag.** Rejected by the owner in favour of one
  cutover. The consequence is that rollback is a code-and-chart revert rather than
  a flag flip, which is why the cutover runbook's preview soak is not optional.
- **Asyncio task per run.** Cheapest and it would make `FairShareGate` work
  deployed unchanged, but one run's OOM, leak, or CPU-bound grading loop degrades
  every co-tenant. Rejected on blast radius.
- **Single-slot worker pool** (one run per pod at a time, fixed pool). Total
  isolation and no fork cost, but pool size becomes the hard concurrency ceiling
  and idle pods hold reservations. Rejected as strictly less flexible than slots
  plus subprocesses.
- **Raising the quota.** Already rejected in `OME-1058`: more Pods would be
  created and would then fail on the node instead.

## Requirements

### Functional

1. Accept a run submission and return the capability token exactly as today.
2. Execute each accepted run **at most once to completion**, isolated, with the
   same environment contract the Job has today.
3. Stream the run's frames to the attached client exactly as today.
4. Report honest status: queued, running, or a terminal outcome.
5. Cancel a run whether it is queued or running.
6. Enforce the run's deadline, and refuse to execute a run whose client is gone.
7. Refuse admission with 503 + `Retry-After` when the system cannot take more,
   and make `Retry-After` mean something.

### Non-functional

| Dimension | Requirement | Source |
| -- | -- | -- |
| Pod footprint | **Constant and declared.** This is the point of the epic. | `OME-1058` |
| Durability | An accepted run must survive a broker restart. | forces `OME-1093` |
| Availability | 99.9% is sufficient. A lost *queued* run matters more than uptime. | — |
| Submission → start | < ~2s when a slot is free (today: a Pod cold start). | — |
| Run duration | Seconds to 16h (`job_deadline_s` = 57,600s). | `config.py:108` |
| Concurrency | 8–16 concurrent runs, matching the SDK's fan-out of 8. | `_MAX_CANDIDATES_IN_FLIGHT` |
| Queue volume | Negligible. A message is an expression plus metadata, a few KB. | — |

## Capacity envelope

Per-run quota charge today, including the `sf-fusion` LimitRange default:
**requests 200m/256Mi, limits 500m/1Gi**.

Eight concurrent runs therefore need 1600m of `requests.cpu`, which is what
saturates `requests.cpu: 2`.

A pool of 2 workers × 4 slots serves the same 8 concurrent runs and requests
roughly `2 × (4 × 200m + overhead)` ≈ 1800m and `2 × (4 × 256Mi + overhead)` ≈ 2.6Gi.

**This is not a capacity saving, and the spec must not imply one.** Eight
concurrent runs need the CPU that eight runs need. What changes:

- the footprint is **two Pods that always exist**, not zero-to-eight Pods that
  appear unpredictably, so the node can be sized against it exactly;
- admission has **one authority** (queue depth) instead of five that disagree;
- **no Pending Pod holds a quota reservation for 16 hours** — the failure ratchet
  `OME-1064` documented, where `activeDeadlineSeconds` of ~16h meant failed runs
  permanently ate capacity;
- there is **no per-run cold start**, because workers are warm.

`OME-1058`'s node sizing remains required. This epic removes the *disagreement*
between ceilings, not the ceilings.

## Design

### The run queue

A dedicated JetStream stream, separate from every per-run event stream.

| Property | Value | Why |
| -- | -- | -- |
| Stream name | `url4-runq` | **MUST NOT** begin with `url4-cloud_` — see Trap 1 |
| Subject | `url4-runq.<caller-bucket>` | per-caller subjects are the fairness seam |
| Retention | `WorkQueue` | a claimed-and-acked message is gone |
| Storage | `file` | a memory-backed queue loses accepted runs |
| Replicas | `3` | the queue must survive one broker loss |
| `max_age` | generous (24h) | **storage backstop only** — see below |
| Consumer | durable **pull**, `url4-runners` | many workers, one work queue |
| `AckPolicy` | `EXPLICIT` | the opposite of the event streams — see Trap 2 |
| `max_deliver` | `2` | one retry, then the max-deliveries advisory |
| `ack_wait` | 60s, heartbeated every 20s | a 16h run must not look abandoned |
| `max_ack_pending` | `replicas × worker_slots` | the broker itself stops over-handing |

**Message body** carries exactly the per-run values `K8sJobRunner._env` renders
today: topic, expression, `deadline_s`, stream grace, traceparent (validated),
profile, identity headers, cache policy, and the io budget. It is produced and
consumed through `job_env`, not a parallel encoding.

**`max_age` is a storage backstop, never a correctness mechanism.** JetStream
removes an aged-out unacked message with no advisory, so a run dropped that way
would never execute and never receive a terminal frame — reintroducing the exact
silence this epic removes, one layer down. Staleness is handled at claim time
instead (see Deadlines and expiry).

### The worker

A new mode of the existing CLI, so the image stays one artifact with modes — the
pattern the Dockerfile already documents for `serve` and `run`.

```
loop:
  free = worker_slots - len(active)
  if free == 0: await a slot
  msgs = await consumer.fetch(batch=free, timeout=...)
  for msg in msgs: spawn supervise(msg)

supervise(msg):
  if terminal_frame_exists(topic):        # dedupe / cancel / stale, one check
      await msg.ack(); return
  if capability_expired(topic):
      publish Terminated(failed, queue_expired); await msg.ack(); return
  child = fork `screamingface-engine run` with job_env(msg) as env
  heartbeat msg.in_progress() every 20s while child lives
  await child, bounded by deadline_s + STREAM_GRACE_S + margin
  classify exit; publish a named terminal frame if the child published none
  await msg.ack()
```

**Slot accounting is the worker's only shared mutable state.** It is `asyncio`
single-threaded, so the accounting is safe without a lock, but the fetch batch
must be computed from free slots — fetching more than the pool can hold is how a
pull consumer starves its siblings.

**Per-child memory cap is an invariant, not a refinement.** The Pod memory limit
covers every slot, so one child that allocates without bound triggers a **Pod**
OOM and kills its co-tenants — which would silently void the entire reason for
choosing subprocess isolation. Each child must therefore be spawned under its own
`RLIMIT_AS` set to the per-run memory budget, so an over-allocating run fails
alone. Set it in a tiny exec wrapper rather than `preexec_fn`, since CPython
documents `preexec_fn` as unsafe in the presence of threads and this process runs
an event loop plus whatever the NATS client starts.

**Child stdout/stderr** are forwarded to the worker's log with the topic bound.
The worker adds no logging of its own about the expression: `runner/main.py`
already logs its length rather than its content, because an expression may carry
prompts (`OME-990`), and the worker must not undo that.

### Delivery semantics and idempotency

At-least-once delivery, exactly-once *completion*, by three layers:

1. **Publish dedupe.** `Nats-Msg-Id: <topic>` plus a `duplicate_window` that must
   exceed the client's whole retry horizon — default **120s**, which covers the
   SDK's retry budget over a derived `Retry-After`. The broker collapses a
   resubmission itself, which preserves the meaning of `JobAlreadyExists` with no
   lookup table. Set it too short and a client's legitimate retry becomes a second
   execution of the same run.
2. **The run's own event stream is the completion record.** `lifecycle.run`
   publishes `StartedEvent` first and a terminal frame on **every** exit path,
   including cancellation and deadline. A terminal frame present at claim time
   means the run is finished, cancelled, or expired — ack and never execute.
3. **Max-deliveries advisory.** When a message exhausts `max_deliver`, the App
   subscribes to
   `$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.url4-runq.url4-runners` and
   publishes a named terminal failure to the run's event stream. A run the queue
   gives up on ends in a stated error rather than silence.

**Accepted duplicate-work window.** A worker that dies *mid-run* leaves a run with
a `StartedEvent` and no terminal frame. On redelivery the successor cannot tell
"80% done and orphaned" from "never started", so it re-executes from scratch and
the caller's model spend is partly repeated. This is bounded by `max_deliver: 2`
to at most one repeat, and materially absorbed in production by the gateway's
global response cache, which is enabled by default there and will serve the
repeated calls as hits. The alternative — `max_deliver: 1` — trades that cost for
a lost run with nobody left alive to report it, which is the failure class this
epic exists to delete.

### Status derivation

`status(topic)` becomes a pure function of evidence that already exists. No claim
table, no KV bucket, no new store:

| Evidence on the run's event stream | Status |
| -- | -- |
| terminal frame present | its outcome (`succeeded` / `failed` / `timed_out` / `stopped`) |
| `StartedEvent`, no terminal frame | `running` |
| neither, capability unexpired | `scheduled` |
| neither, capability expired | `not_found` |

This is stateless, so it is correct across App replicas — which a process-local
counter would not be. It also retires `OME-1059`'s defect structurally rather than
by patch: `_map_status` today maps both "Pending, starting soon" and "Pod refused"
to `scheduled`, and in this model `scheduled` can only mean "accepted, not yet
started".

`JobStatus` needs **no new member**. `scheduled` already means queued, and
`OME-1087` records that in the port docstring so a later reader does not add one.

### Cancellation

- **Queued, unclaimed.** `DELETE /` publishes `Terminated(stopped)` to the run's
  event stream immediately. The worker later claims, sees the terminal frame,
  acks, and never executes. No deletion of a message by sequence is needed, and
  the App never has to know the message's sequence.
- **Running.** Core NATS request/reply on `url4.runctl.<topic>`. Every worker
  subscribes to `url4.runctl.*`; only the owner replies, and it SIGTERMs its
  child, which publishes its own `Terminated(stopped)` exactly as it does today.
  The App treats no-reply within a short timeout as "not running here" and falls
  back to the tombstone above.
- **`RunReaper` needs no change.** It already calls `job_runner.stop(topic)` on
  audience loss. `OME-1090` must add a test that this reaches a **queued** run,
  because the Job path handled that case by deleting a Job that might never have
  started.

### Deadlines and expiry

Three bounds, each owned by exactly one component:

| Bound | Owner | Value |
| -- | -- | -- |
| Run deadline | the child, in-process | `asyncio.timeout(deadline_s)` in `lifecycle.run`, unchanged |
| Hard wall | the worker | `deadline_s + STREAM_GRACE_S + margin`: SIGTERM, then SIGKILL |
| Queue staleness | the worker, at claim | capability expired → `queue_expired` terminal frame, ack |

The worker's hard wall replaces `activeDeadlineSeconds`. This is a real
improvement: a Pending Pod can no longer hold a quota reservation for 16 hours,
because there is no Pending Pod.

### Admission and backpressure

- Refuse on **queue depth** against a configured ceiling, raising the existing
  `JobRunnerAtCapacity`. The 503 + `Retry-After` mapping at `rest/routes.py:203-208`
  is already wired and does not change.
- Depth and oldest-message age come from `stream_info` (`state.messages`,
  `state.first_ts`), cached ~1–2s — the same cache-plus-reservation shape
  `OME-1065` built for the quota snapshot. **Keep the reservation counter.** The
  resource being counted changes; the read-modify-write race between two
  admissions inside one refresh window does not.
- **Derive `Retry-After` from a drain estimate** (oldest age and depth against
  observed pool throughput) rather than the hard-coded `1` in place today. A
  client told to retry in 1 second when the true wait is minutes retries into a
  wall. This is the seam `OME-1066` consumes.
- `max_ack_pending` gives a second, broker-enforced bound: the queue will not
  hand out more than the pool can hold even if admission is wrong.

### Fairness

`FairShareGate` (`runner/fair_share.py:83`) is already written, already
work-conserving, and already the implementation `OME-908` asked for — but it is an
**in-process asyncio gate**, wired only in local mode (`local.py:170`), because
deployed runs are separate processes. Subprocess isolation keeps that true.

The deployed half of `OME-908` therefore lands as two narrower mechanisms:

1. **Run-level fairness** — per-caller queue subjects with round-robin pull, plus
   a per-caller in-flight cap at admission. One caller's 9-candidate evaluation
   can no longer occupy every slot. This is what `OME-908`'s title asks for:
   *fair-schedule concurrent Engine runs so one large benchmark run doesn't
   starve others*.
2. **Fetch-level budget** — the worker computes
   `worker_io_capacity / max(1, active_children)` and passes it through the
   existing `URL4_CLOUD_IO_CONCURRENCY` at spawn. Strictly better than today's
   static `runner_io_concurrency = 4`, but **fixed at spawn**: it does not
   rebalance when a sibling exits.

**Declared follow-up, not this epic:** dynamic rebalancing, via a control socket
from each child to a parent-held `FairShareGate`. The seam is the env variable —
a child that learns its budget over a socket instead of at spawn changes nothing
above it.

### Deployment topology

A second `Deployment` in the engine chart, `screamingface-engine-runner`:

- `replicas × worker_slots` is the declared concurrency; both are chart values.
- Resources are `worker_slots × per-run charge` plus overhead — the number the
  operator sizes the node against.
- The same hardened context the Job manifest applies today: non-root 1000,
  read-only rootfs, all capabilities dropped, `RuntimeDefault` seccomp,
  `/tmp` `emptyDir`, `automountServiceAccountToken: false`, `enableServiceLinks: false`.
- `envFrom` the **existing** runner-env ConfigMap, unchanged. It already carries
  `AIGATEWAY_BASE_URL`, `URL4_CLOUD_NATS_URL`, and the artifact-store settings,
  and the invariant that Helm owns those names still holds.
- `checksum/config` and `checksum/secret` annotations, matching the App
  Deployment. A ConfigMap change alone must roll the pool, or it keeps stale env.
- `terminationGracePeriodSeconds` > `drain_grace_s`; `preStop` stops pulling;
  `maxUnavailable: 0` plus a PodDisruptionBudget as the named mitigations for the
  deploy regression below.

**RBAC shrinks.** The `Role` and `RoleBinding` granting
`create/get/list/watch/delete` on `batch/jobs` are deleted. The control plane
stops being able to create Pods at all — a real least-privilege win that falls out
of the design rather than being bolted on.

### Observability

The queue makes the system's health a number for the first time.

**Metrics:** queue depth; oldest-unclaimed age; slots busy and total; claim
latency; run duration; redelivery count; child exit codes (137 = OOM); worker
restarts; max-deliveries advisories.

**Alerts:** oldest-unclaimed age above threshold for a sustained window — the
canonical consumer-lag alert, and the one that would have fired on 2026-09-01;
any redelivery; any max-deliveries advisory; slots saturated while depth rises.

## Traps this design must close

These were found while mapping the blast radius. Each is silent if missed, and
each carries a named test obligation.

**Trap 1 — the orphan sweeper would delete the queue.** `_sweep_orphans`
(`adapters/jetstream.py:199`) enumerates every stream and deletes those
`owns_stream()` accepts, which is a `url4-cloud_` prefix test. A work-queue stream
inside that prefix would be reclaimed, silently dropping every queued run. The
queue is named outside the prefix **and** excluded explicitly in `owns_stream()`,
belt and braces, because a future rename of the prefix must not re-open this.
*Obligation:* a test that a sweep with the queue present leaves it alive.

**Trap 2 — `AckPolicy.NONE` is load-bearing and wrong for a queue.**
`_consumer_config()` always returns `AckPolicy.NONE`, and that is correct for the
event streams: they are no-callback broadcast replay readers, and under `EXPLICIT`
every frame would be redelivered after `AckWait`, delivery would stop once
`max_ack_pending` filled, and runs past roughly 1000 frames would truncate
silently. The queue needs the exact opposite. **Split the function** so the two
configurations are separately expressible, rather than adding a branch to the one
the event streams depend on. *Obligation:* a regression test that the event-stream
config still returns `NONE`.

**Trap 3 — storage is a concurrency ceiling.** Each run event stream reserves
50 MiB of `max_bytes` at creation. File-backed storage must be sized as
`pool concurrency × 50 MiB` plus the queue's own `max_bytes`, plus headroom.
*Obligation:* the sizing is written into `OME-1093`'s acceptance, with the
kind-rig note that the storage class is `standard`, not `local-path`.

## Accepted regressions

**A run no longer survives a control-plane deploy.** Today a Job is an independent
object; an App rollout cannot touch a running evaluation. Tomorrow a worker
rollout drains: it stops pulling, keeps children alive up to `drain_grace_s` while
still heartbeating, then SIGTERMs them so each publishes `Terminated(stopped)`
with a `worker_draining` reason. With a 16-hour `job_deadline_s`, a deploy will
interrupt long evaluations. `maxUnavailable: 0`, a PodDisruptionBudget, and deploy
scheduling reduce the exposure; none eliminate it. The failure is at least
**named** rather than silent, and `OME-1066`'s 503 handling gives the SDK a path
to resubmit.

**A worker pool creates no capacity.** Stated in full under Capacity envelope.
`OME-1058` is still required.

## Test strategy

Ranked by likelihood × impact. The top three are the ones that can lose or
duplicate a caller's work silently, which is this epic's whole subject.

| # | Risk | Impact | Technique |
| -- | -- | -- | -- |
| 1 | Queue deleted or drained by the sweeper | Every queued run lost, silently | Trap-1 regression test; sweep integration test with the queue present |
| 2 | Wrong ack policy on the queue, or the event streams broken by the split | Runs redelivered forever, or frames truncated past ~1000 | Config assertions on both consumer shapes; a >1000-frame run |
| 3 | Duplicate execution beyond the accepted window | Caller billed twice | Completion-record check tests: terminal present → never spawn; crash mid-run → exactly one repeat |
| 4 | A run ends with no terminal frame | The 23-minute silence returns | Child SIGKILL / exit 137 / hung past hard wall → named terminal frame; max-deliveries advisory → named terminal frame |
| 5 | Per-child memory cap missing | One run OOMs the Pod, killing co-tenants | Spawn a child that allocates past its budget; assert only that child dies |
| 6 | Cancellation misses a queued run | Orphaned run executes for a departed client | Cancel-before-claim; `RunReaper` audience loss on a queued run |
| 7 | Status lies | Client and operator both misled | The status truth table, one test per row, including the expiry boundary |
| 8 | Admission wrong under concurrency | Over-admission, or a wall of 503s | Two admissions racing the last slot; `Retry-After` derived, not constant |
| 9 | Drain kills work it did not need to | Long evaluations lost on every deploy | Drain: stop pulling, in-flight survives to grace, then named termination |
| 10 | One caller starves another | The `OME-908` complaint, undelivered | Round-robin interleaving; per-caller cap |

**Levels.** Unit tests carry the truth tables, config assertions, and classification
logic with a faked broker — the existing `tests/unit/_fakes.py` pattern. Integration
tests carry publish → pull → ack against a real broker and the full spine
(submit → claim → spawn → frames → terminal), following
`tests/integration/test_e2e_compose_flow.py` and `test_local_spine.py`.

**Failure injection is mandatory, not optional.** The bugs in this design live in
timing windows: worker death mid-run, broker restart with a queued run, SIGTERM
during drain, a child that ignores SIGTERM. Each needs a test that actually kills
the thing. `OME-1093`'s acceptance is itself a failure-injection drill — an
enqueued run must survive `kubectl delete pod` of the broker and still execute.

**No sleep-based synchronisation.** Wait on events and conditions with deadlines.
A worker-pool suite built on `asyncio.sleep(0.1)` will be flaky, and a flaky suite
here is worse than none, because it trains people to ignore exactly the signals
this epic added.

**Gaps and assumptions.** This strategy assumes the integration suite can run a
real NATS broker, which it already does. It does not cover load testing the pool
at its declared concurrency — worth doing once `OME-1093` lands, and not a merge
gate. It also does not attempt to prove the absence of duplicate execution outside
the stated `max_deliver: 2` window; that window is a documented trade-off, not a
defect to test away.

## Out of scope

- **Queue-depth autoscaling (KEDA).** Owner decision. The pool is a fixed replica
  count; autoscaling interacts with `OME-1058`'s node ceiling and deserves its own
  unit.
- **Dynamic io rebalancing** via a parent-held gate and a control socket. The env
  variable is the seam; see Fairness.
- **A structured `QueuedEvent`** in the url4 streaming protocol. Queue position
  reaches the client through the WS bridge's existing notifier path, so no protocol
  change is needed. Worth revisiting only if the SDK wants to render it richly.
- **Node sizing** — `OME-1058`.
- **SDK 503 retry** — `OME-1066`.
- **SDK per-run cancellation on disconnect** — `OME-1067`.
- **Making the per-run event streams durable.** They are transient by design and
  are already lost on a broker restart today. Only the queue must survive.

## Open questions

None blocking. Two to settle during implementation, both local to a unit:

1. The per-caller bucket key for queue subjects — the identity header value
   directly, or a hash of it. A raw email address in a subject name is readable by
   anything with broker access, so `OME-1091` should prefer a stable hash.
2. Whether `worker_slots` should default to 4 (matching `runner_io_concurrency`
   and the gateway's per-provider width) or to 1 for the first deployment, with
   the pool widened after a period of observation. `OME-1092` decides against the
   node size `OME-1058` settles.

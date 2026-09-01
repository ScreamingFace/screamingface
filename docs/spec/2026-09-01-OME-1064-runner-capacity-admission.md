# OME-1064 — Runner Job capacity: admission, detection, and backpressure

Status: proposed · Date: 2026-09-01 · Epic: OME-1064

## 1. The incident this specifies against

On 2026-09-01 an `sf.evaluate(list(solos.values()), benchmark="draco-3pass", progress=True)`
run of 9 candidates was submitted at 11:23:50 UTC. It reported 24% progress (220 of 900
cases), then froze — no error, no warning, the model-call counter static. After ~23 minutes
the SDK failed every candidate with `websocket_disconnected ... after 1369.6s`. Six of nine
candidates completed **0 of 100 cases**. One candidate had completed **100 of 100** and was
failed anyway.

Nothing crashed. The Engine pod never restarted (`restart_count=0`, up since 2026-08-29).
The AI Gateway served 4,000–5,800 req/min with zero errors throughout. The runs never got
Pods.

Only one Runner Pod started in the whole window. It had been submitted at 11:23:50 and sat
Pending for ~19 minutes, then emitted 42,448 frames in ~207s — which is why progress arrived
in bursts and then stopped.

Cluster events in `sf-fusion`:

```
FailedScheduling  0/3 nodes are available: 1 Insufficient cpu, 2 node(s) had untolerated taint(s)
NotTriggerScaleUp pod didn't trigger scale-up: 1 node(s) had untolerated taint(s)
FailedCreate      Error creating: pods "url4-..." is forbidden: exceeded quota: ns-ceiling
```

## 2. Root cause

### 2.1 Five capacity ceilings, none aware of each other

| Layer | Ceiling | Source |
|---|---|---|
| SDK | `_MAX_CANDIDATES_IN_FLIGHT = 8` | `packages/screamingface/src/screamingface/_evaluation/runner.py:43` |
| Engine (K8s mode) | **none** | `adapters/k8s.py:182-206` |
| Engine (local mode) | `DEFAULT_MAX_CONCURRENT_RUNS = 32` | `adapters/inprocess.py:47` |
| Namespace quota | `requests.cpu: 2` → 8 runners | infra `kubernetes/apps/sf-fusion/base/quota.yaml` |
| Node | 1 × `D4as_v5`, not autoscaled | infra `terraform/stacks/azure/aks-platform/dev/main.tf` |
| Gateway | `provider_max_concurrency = 4` | `apps/aigateway/src/aigateway/config.py:111` |

The **client** decides the fan-out. Nothing below it can refuse. Each layer either absorbs
the load or fails silently. This is the structural defect; every symptom below follows from
it.

### 2.2 The binding constraint is `requests.cpu`

The `sf-fusion` LimitRange defaults resource-less containers to `{cpu: 500m, memory: 512Mi}`.
The Runner Job declares `requests: {cpu: 200m, memory: 256Mi}` and `limits: {memory: 1Gi}`
with **no CPU limit** (`apps/screamingface-engine/deploy/helm/values.yaml:365-370`), so the
LimitRange supplies `limits.cpu: 500m`. Each Runner Pod charges the quota
**requests 200m/256Mi, limits 500m/1Gi**.

Against measured standing usage (310m/528Mi requests; 2.5 CPU/2.6Gi limits):

| Dimension | Ceiling | Headroom | Runners that fit |
|---|---|---|---|
| `limits.cpu` | 8 | 5500m | 11 |
| `limits.memory` | 12Gi | ~9.4Gi | 9 |
| `requests.memory` | 3Gi | 2544Mi | 9 |
| **`requests.cpu`** | **2** | **1690m** | **8** |

`requests.cpu` binds at exactly 8 — precisely `_MAX_CANDIDATES_IN_FLIGHT`. One evaluation
saturates the namespace exactly, leaving nothing for a concurrent evaluation or for the
Engine's own rollout surge pod. Engine logs show unrelated `ifeval` runs scheduled at 11:29,
11:30:58 and 11:42:38, overlapping this run.

The 2026-08-25 quota resize raised the *limits* ceilings and deliberately left requests
unchanged. The intent (keep scheduling pressure visible) was sound; the effect was to move
the bottleneck onto `requests.cpu` at exactly the client's fan-out.

### 2.3 The false invariant

`packages/url4/src/url4/streaming/interfaces/jobs.py:24-34`:

> `JobRunnerAtCapacity` — *"Only substrates that own a finite local resource raise it — an
> in-process runner shares one event loop across every run it accepts, so admission is its own
> job. **A cluster-backed runner lets the scheduler absorb the load and never raises.**"*

`rest/routes.py:200-202` restates it. A namespace carrying a ResourceQuota **is** a substrate
that owns a finite local resource. A quota does not absorb load; it refuses Pod creation.

The consequence is that the entire backpressure path — `JobRunnerAtCapacity` → 503 +
`Retry-After` (`rest/routes.py:198-208`) — exists, is wired, and is switched off for the one
runner that needs it.

### 2.4 Why the failure was silent

Three independent gaps, each sufficient to hide the condition:

1. **`schedule()` cannot see the refusal.** `create_namespaced_job` returns 201; the quota
   rejection is raised later against the Job *controller*. `FailedCreate` from quota does not
   count against `backoffLimit: 0`, so the Job retries creation indefinitely instead of
   failing. Observed retries: 11:42:39, :40, :42, :46, :54, 11:43:10, :42, 11:44:42, 11:45:42,
   11:46:42.
2. **`_map_status` cannot represent it.** A Job whose Pod is Pending-unschedulable and a Job
   whose Pod was refused both have `active = 0` and no terminal condition, so both map to
   `"scheduled"` — identical to a healthy Job one second from starting
   (`adapters/k8s.py:96-104`).
3. **Nothing watches the producer.** The bridge heartbeats every 15s regardless
   (`ws_heartbeat_s = 15.0`); the SDK's receive timeout is 120s and never fires; `RunReaper`
   fires only on *audience* loss (`orphan_grace_s = 120`), never producer silence.

Five streams carried zero frames for their entire life while heartbeating normally:

```
duration_s=1356.9  frames=0  heartbeats=90
duration_s=1636.3  frames=0  heartbeats=109
duration_s=2449.4  frames=0  heartbeats=163
duration_s=2510.1  frames=0  heartbeats=167
duration_s=2686.1  frames=0  heartbeats=179
```

### 2.5 Why one failure destroyed nine candidates

`transport.py:240-249` (`_sweep_after_disconnect`) calls `cancel_active()` when the 90s
reconnect budget expires. `cancel_active()` (`:262-281`) iterates `self._active_tokens` —
*every* capability the client instance owns — and stops all of them. One lost socket therefore
failed all nine candidates, including the one that had completed 100/100.

### 2.6 Secondary hazard

`activeDeadlineSeconds = job_deadline_s + 60 + 30 ≈ 16h` with the default
`job_deadline_s = 57600`. A Pending Pod holds its quota reservation for up to 16 hours, so
un-startable runs ratchet capacity away from healthy ones.

## 3. Requirements

### Functional

- **F1** A run that cannot obtain a Pod must reach the client as a **typed, named error**
  within a bounded time, never as silence and never as `websocket_disconnected`.
- **F2** The Engine must refuse a run it cannot place, using the existing 503 + `Retry-After`
  contract, rather than creating a Job that will never produce a Pod.
- **F3** The SDK must treat that refusal as **backpressure** — wait and retry — not as a
  candidate failure.
- **F4** A stream failure must fail **only its own run**. Runs that are healthy, or already
  terminal, must survive a sibling's disconnect.
- **F5** The status port must be able to represent "will never start" distinctly from
  "waiting to start".

### Non-functional

- **N1** No behaviour change for a run that fits: same 202, same Job, same latency.
- **N2** Capacity must have exactly **one** source of truth. A second copy of the ceiling in
  Engine configuration is a defect, not a feature.
- **N3** Admission must degrade safely: if capacity cannot be determined, fall back to
  today's behaviour plus F1 detection. Detection is the floor; admission is the optimisation.
- **N4** Correct under >1 Engine replica. A process-local counter alone does not satisfy this.
- **N5** A healthy run that is merely slow to schedule must not be failed early — every grace
  is configurable and defaults above normal scheduling latency.

### Explicitly out of scope

- **Fairness between runs.** Ordering the queue is `OME-908`, which is not implementable
  until F2 creates a queue. After this spec lands, admission order is FIFO.
- **Cluster sizing.** `OME-1058`.
- **Gateway per-provider concurrency.** Not the constraint in this incident; re-measure after
  F2.

## 4. Design

### 4.1 Detection (F1, F5) — `OME-1059`

Extend the status mapping so an un-startable Job is representable: a Pod in `Pending` whose
condition carries `reason=Unschedulable`, or a Job carrying a `FailedCreate` event, is not
`"scheduled"`. Add a distinct `JobStatus` member rather than collapsing the difference at the
port.

Add a **producer-side watchdog**: when a topic has been attached and has published zero
frames after a configurable grace (proposal `URL4_CLOUD_RUN_START_GRACE_S`, default ~120s),
query the runner status and publish a typed `ai.url4.error` naming the real cause
(`run_unschedulable`, carrying the Kubernetes reason text), then terminate the run.

This mirrors the `stream_reclaimed` treatment added in `OME-1019`: an indistinguishable
silent state replaced by a typed error the SDK can surface.

**Detection is the correctness floor and ships first.** It is independent of infrastructure,
and it alone converts 23 minutes of silence into a named error in ~30s.

### 4.2 Admission (F2, N2, N3, N4) — `OME-1065`

`K8sJobRunner` becomes capacity-aware by reading the **namespace ResourceQuota**:

1. Read `status.used` vs `status.hard`, cached ~2s.
2. Before creating a Job, test whether one more Runner Pod fits on every constrained
   dimension — `requests.cpu`, `requests.memory`, `limits.cpu`, `limits.memory`, `pods`. The
   Pod's charge is its own spec **plus LimitRange defaults**; omitting the LimitRange makes
   the arithmetic wrong by 500m per Pod (§2.2).
3. If it does not fit, raise `JobRunnerAtCapacity`, which `rest/routes.py:198-208` already
   maps to 503 + `Retry-After`.
4. Maintain a local in-flight reservation counter over the cached reading, so several
   `schedule()` calls between two refreshes cannot jointly overshoot.

**Why the quota and not a configured number.** The quota is already the operator's declared
capacity. Reading it satisfies N2 (one source of truth — a config value would be a second copy
that drifts), gives self-tuning when infrastructure resizes the ceiling with no redeploy, and
satisfies N4, because every replica reads the same authoritative object. The reservation
counter is a race guard over a shared reading, not a private ceiling.

Requires `get`/`watch` on `resourcequotas` in the Engine's Role — the deployed Role has none
today.

**Rejected alternative.** An Engine-local counter with a configured maximum is simpler, but
duplicates the ceiling, drifts from the cluster silently, and is wrong with more than one
replica. Rejected on N2 and N4.

### 4.3 Backpressure at the client (F3) — `OME-1066`

Today `transport.py:872` sets `permanent=response.status_code < 500`, so a 503 raises
immediately; `Retry-After` is never parsed and the `_ATTACH_RETRY_DELAYS` ladder covers only
428. Treat 503 as retryable, honour `Retry-After` (falling back to the existing full-jitter
`_reconnect_delay`), bound the total wait, and surface *queued* state through `progress=True`.

**`OME-1065` and `OME-1066` must ship together.** Admission alone converts a silent hang into
a fast failure — more legible, but the user still cannot run 9 candidates. Together they
convert it into a wait, which is the actual fix. After both, `_MAX_CANDIDATES_IN_FLIGHT = 8`
stops being a capacity decision taken by the client.

### 4.4 Blast radius (F4) — `OME-1067`

Separate the two cases currently sharing `cancel_active()`:

- one stream lost past its reconnect budget → cancel that run only;
- client shutdown / explicit abort → keep today's sweep-everything semantics.

A run already in a terminal state must never be cancelled retroactively.

Independent of the capacity work; reduces the blast radius of *any* stream failure.

### 4.5 Infrastructure (`OME-1058`)

`requests.cpu` and node capacity must move **together**. Raising the quota alone converts
`FailedCreate` into `FailedScheduling` — both were already present in this one incident, which
is the evidence that the node is co-binding. The user pool is not autoscaled, so nothing can
grow; enabling autoscaling is the prerequisite for either sizing option. Detail and options in
`OME-1058`.

## 5. Sequencing

| # | Issue | Landing | Depends on |
|---|---|---|---|
| 1 | `OME-1059` detection | engine | — |
| 2 | `OME-1067` blast radius | SDK | — |
| 3 | `OME-1065` admission | engine | — |
| 4 | `OME-1066` client backpressure | SDK | `OME-1065` |
| 5 | `OME-1058` capacity | infra | owner decision |
| 6 | `OME-908` fairness | engine | `OME-1065` |

Steps 1–2 fix the reported experience and carry no infrastructure dependency. Steps 3–5 fix
the outcome. Step 6 becomes tractable only after step 3.

## 6. Acceptance for the epic

- A run refused by quota surfaces a typed error naming capacity, within the start grace —
  not `websocket_disconnected`, not silence.
- With the namespace at its ceiling, submission returns 503 + `Retry-After`; the SDK waits and
  the run subsequently completes.
- A 9-candidate `draco-3pass` evaluation concurrent with another evaluation completes, or
  reports precisely which candidates were queued and why.
- One stream failure fails exactly one candidate.
- No behaviour change when capacity is available.

## 7. Long-term direction (not specified here)

Job-per-run makes Pod count elastic against a fixed quota — that is the collision at the heart
of this incident. A fixed worker pool consuming runs from NATS inverts it: constant Pod count,
elastic queue. That removes the failure class rather than bounding it, and makes fairness a
property of the queue rather than a scheduler to be written. Recorded as direction; not
proposed for this epic.

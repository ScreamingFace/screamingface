# OME-1065 — Refuse a run when the namespace ResourceQuota has no headroom

## Problem

`K8sJobRunner.schedule()` creates a Job unconditionally. The `sf-fusion` namespace
carries a `ResourceQuota` (`ns-ceiling`). A quota does not absorb load. It refuses
Pod creation asynchronously, after `create_namespaced_job` has already returned
201. On 2026-09-01 this produced 23 minutes of silent non-execution (OME-1064).

The port documents this as deliberate:

> "A cluster-backed runner lets the scheduler absorb the load and never raises."
> — `packages/url4/src/url4/streaming/interfaces/jobs.py:31-34`

That sentence is false in this deployment. A namespace with a ResourceQuota is a
substrate that owns a finite local resource. The 503 + `Retry-After` backpressure
path already exists and is fully wired (`rest/routes.py:198-208`). Only the K8s
adapter never raises `JobRunnerAtCapacity`.

## Decision

`K8sJobRunner` gains capacity awareness sourced from the namespace ResourceQuota
itself:

1. Read the ResourceQuota's `status.used` vs `status.hard`, cached ~2 seconds.
2. Before creating a Job, compute whether one more Runner Pod fits on every
   constrained dimension: `requests.cpu`, `requests.memory`, `limits.cpu`,
   `limits.memory`, `pods`.
3. The Pod's charge is its own spec plus any LimitRange defaults. The runner sets
   no `limits.cpu`, so the namespace LimitRange supplies it. The arithmetic is
   wrong by 500m per Pod if this is not accounted for.
4. If one more Pod does not fit, raise `JobRunnerAtCapacity`. The REST edge turns
   this into 503 + `Retry-After`.
5. Hold a local in-flight reservation counter alongside the cached quota reading.
   This closes the read-modify-write race when several `schedule()` calls run
   between two quota refreshes.

### Why read the quota rather than configure a number

The quota is already the operator's declared capacity. Reading it keeps one source
of truth. A configured limit would be a second copy that silently drifts from the
cluster. It self-tunes when infrastructure resizes the ceiling with no redeploy.
It stays correct across multiple Engine replicas — a process-local counter would
not.

### Degradation

If the quota or the LimitRange cannot be read (absent, RBAC denied, API error),
fall back to today's behaviour: create the Job and let OME-1059's detection catch
an un-startable run. Admission is an optimisation over detection, never a
replacement for it. A failed read backs off 30 seconds so a permanently denied
read does not hammer the API server.

## Design

### The quota snapshot

`_QuotaSnapshot` holds `used`, `hard`, and `charge` as exact integers:

- cpu in millicores (`"200m"` → 200, `"2"` → 2000)
- memory in bytes (`"256Mi"` → 268435456)
- pods as a count

Integer arithmetic keeps the ceiling comparison exact. A float comparison at the
ceiling (`0.4 + 8*0.2 > 2.0`) would refuse the run that exactly fills the quota.

`used` and `hard` are merged across the namespace's quotas: max used, min hard per
dimension. `charge` is the quota charge of one Runner Pod: its own `resources`
spec plus LimitRange defaults, merged across LimitRanges (max per resource —
conservative when two LimitRanges disagree).

### The admission gate

`_schedule_blocking` runs on a `to_thread` worker. A `threading.Lock` makes the
refresh + check + reserve atomic:

```
with lock:
    refresh quota if stale
    if snapshot exists and not fits(snapshot, reserved):
        raise JobRunnerAtCapacity(reserved, max_runs_that_fit(snapshot))
    reserved += 1
create the Job
on ApiException:
    with lock: reserved -= 1
    map 409 to JobAlreadyExists, else re-raise
```

`fits` checks every charged dimension the quota constrains:

```
used + (reserved + 1) * charge <= hard
```

The reservation counter covers the window between refreshes. It resets to zero at
each successful refresh, because the quota's `used` then reflects everything older
than the window. A create failure releases the reservation immediately.

### The client seam

`CoreV1QuotaClient` is a narrow structural Protocol, in the same style as the
existing `BatchV1JobsClient`:

- `list_namespaced_resource_quota(namespace, *, _request_timeout=...)`
- `list_namespaced_limit_range(namespace, *, _request_timeout=...)`

`build_job_runner` wires a `CoreV1Api` alongside the `BatchV1Api`, sharing the
process's single cached `ApiClient`. `core_client=None` disables admission
(direct constructions in tests keep today's behaviour).

### RBAC

The Engine's Role gains `get`/`list`/`watch` on `resourcequotas` and
`get`/`list` on `limitranges` (core API group). The chart change is part of this
issue.

## Out of scope

- Fairness between runs (OME-908). This issue only decides whether there is room,
  not whose run gets it.
- Cluster capacity sizing (OME-1058).
- Client-side retry on 503 (OME-1066, the sibling SDK issue, which must ship with
  this one).

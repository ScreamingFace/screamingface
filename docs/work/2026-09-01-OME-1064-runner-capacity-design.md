---
ticket: OME-1064
stack: repo
status: done
started: 2026-09-01
finished: 2026-09-01
---

# OME-1064 — Runner Job capacity: incident diagnosis, spec, plan, and decomposition

## Intent

Diagnose the 2026-09-01 `draco-3pass` stall to root cause, then turn the diagnosis into SDLC
artifacts and a filed decomposition. This unit produces **documents and work items only** — no
production code. Implementation of each child unit is gated on owner approval.

## What was done

### Investigation

1. Read the deployment architecture of `apps/screamingface-engine` + `apps/aigateway`.
2. Queried SigNoz for the incident window (2026-09-01 11:23–12:10 UTC): Kubernetes events in
   `sf-fusion`, Engine `ws.bridge` stream records, gateway request rates, pod restart counts.
3. Cloned `OpenMined/infrastructure` (shallow) and read the real cluster configuration —
   `kubernetes/apps/sf-fusion/base/quota.yaml`, `terraform/stacks/azure/aks-platform/dev/main.tf`,
   `terraform/modules/azure/aks/main.tf`, `docs/ledger.md`.
4. Recomputed the quota arithmetic with the namespace LimitRange applied.

### Findings

Root cause is **five capacity ceilings that do not know about each other**, with the client
choosing the fan-out and nothing below it able to refuse. Full detail in the spec.

The binding constraint is **`requests.cpu: 2`**, which fits exactly 8 Runner Pods — precisely
`_MAX_CANDIDATES_IN_FLIGHT = 8`. One evaluation saturates the namespace; anything concurrent
is refused, and the refusal is invisible because `create_namespaced_job` returns 201 while the
quota rejection lands asynchronously on the Job controller.

`packages/url4/src/url4/streaming/interfaces/jobs.py:24-34` documents the assumption that made
this possible: *"a cluster-backed runner lets the scheduler absorb the load and never raises."*
A namespace with a ResourceQuota does not absorb load. The 503 + `Retry-After` backpressure
path already exists and is switched off for the only runner that needs it.

## Corrections made during this unit

Three of my own earlier conclusions were wrong and were retracted:

1. **Caching / gateway provider-concurrency starvation.** Proposed first; rejected by the owner
   from direct prior experience (fully-cached runs had completed end to end). Re-investigated
   from SigNoz rather than argued.
2. **"Add the missing toleration" to Runner Pods.** Wrong — the taints are deliberate isolation
   boundaries (system addon pool; PR-preview isolation enforced by
   `sf-preview/templates/admission.yaml`). Retracted in `OME-1058`.
3. **"The `limits.*` ceilings bind."** Wrong — recomputing with the LimitRange shows
   `requests.cpu` binds first, at exactly 8 runners. `OME-1058` was rewritten and retitled; its
   recommendation changed materially, because raising the quota alone converts `FailedCreate`
   into `FailedScheduling`.

The third correction also invalidated the trigger recorded in the infrastructure ledger, which
gates a second user node on >85% node **memory** while both real signals in this incident were
**CPU**.

## Artifacts produced

- `docs/spec/2026-09-01-OME-1064-runner-capacity-admission.md`
- `docs/plan/2026-09-01-OME-1064-runner-capacity-admission.md`
- `docs/tasks/2026-09-01-OME-{1058,1059,1064,1065,1066,1067}-*.md`

## Work items

| Issue | Title | Landing |
|---|---|---|
| `OME-1064` | Make Runner Job capacity explicit and enforced end to end (epic) | engine + SDK |
| `OME-1059` | Surface unschedulable Runner Jobs as a typed run error | engine |
| `OME-1067` | Cancel only the affected run when a stream disconnects | SDK |
| `OME-1065` | Refuse a run when the namespace ResourceQuota has no headroom | engine |
| `OME-1066` | Retry run submission on 503 Retry-After | SDK |
| `OME-1058` | Size sf-fusion capacity for concurrent evaluations | infra |

Relations set: `OME-1066` blocked-by `OME-1065`; `OME-908` blocked-by `OME-1065`; `OME-1064`
related to `OME-908`. `OME-1058` and `OME-1059` reparented under `OME-1064`.

`OME-908` received a comment correcting its stated starvation locus: it names the gateway
per-provider FIFO, but the gateway served 4,000–5,800 req/min with zero errors during the
incident. A run that cannot get a Pod never reaches the gateway. That issue is also **not
implementable today** — fair scheduling orders a queue, and nothing currently queues.

## Outcome

- **Actual files:** as listed above; no source files touched.
- **Commits:** see PR.
- **Gates:** none applicable — documentation-only unit, no code paths changed.
- **Deviations:** the epic was filed as `OME-1064`; the spec and plan filenames were written
  against that number after filing, so the placeholder `OME-1060` used while drafting does not
  appear in any committed artifact.
- **Owner-verify:** the capacity option in `OME-1058` is an owner decision (spend). The
  recommendation there is autoscaling plus `OME-1065`, deferring a second node until there is
  CPU-based evidence.

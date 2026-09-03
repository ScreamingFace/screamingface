---
ticket: OME-1065
stack: screamingface-engine
status: in_progress
started: 2026-09-01
finished:
---

# OME-1065 — Refuse a run when the namespace ResourceQuota has no headroom

## Intent

`K8sJobRunner.schedule()` creates a Job unconditionally. The `sf-fusion` namespace
carries a `ResourceQuota` (`ns-ceiling`) that refuses Pod creation asynchronously,
after `create_namespaced_job` has already returned 201. On 2026-09-01 this produced
23 minutes of silent non-execution (OME-1064). This unit makes the K8s adapter
raise the existing `JobRunnerAtCapacity` — which the REST edge already maps to
503 + `Retry-After` — when one more Runner Pod does not fit the namespace quota.

## Planned changes

- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py` — quota
  admission in `K8sJobRunner`: `CoreV1QuotaClient` protocol, quota snapshot,
  LimitRange-aware Pod charge, ~2s cached refresh, reservation counter, admission
  gate in `_schedule_blocking`.
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py` —
  `build_job_runner` wires a `CoreV1Api` client alongside the batch client.
- `apps/screamingface-engine/deploy/helm/templates/role.yaml` — RBAC: `get`/`list`/
  `watch` on `resourcequotas`, `get`/`list` on `limitranges`.
- `apps/screamingface-engine/tests/unit/_k8s_fakes.py` — shared fake core client.
- `apps/screamingface-engine/tests/unit/test_runners_k8s.py` — admission tests.
- `apps/screamingface-engine/tests/unit/test_runners_factory.py` + 3 other factory
  callers — pass the fake core client factory.

## Test plan

- Quota at ceiling → `JobRunnerAtCapacity`, no Job created.
- A submission that fits → Job created exactly as today.
- LimitRange default accounted: Pod spec omits `limits.cpu`, quota `limits.cpu`
  binds → refused.
- Concurrent `schedule()` calls cannot jointly overshoot the ceiling.
- Quota unreadable → schedules proceed, no exception leaks.
- No quota in namespace → schedules proceed.
- Create failure releases the reservation.
- Factory threads the core client.

## Acceptance

- With the namespace quota at its ceiling, a run submission returns 503 with
  `Retry-After`, not 202.
- A submission that fits still returns 202, and the Job is created exactly as today.
- Quota accounting includes LimitRange-defaulted values, verified against a Pod
  spec that omits `limits.cpu`.
- Concurrent `schedule()` calls cannot jointly overshoot the ceiling.
- Quota unreadable → schedules proceed, no exception leaks into the request path.
- RBAC: the Engine's Role gains `get`/`watch` on `resourcequotas` (plus
  `limitranges` for the charge computation).
- Unit coverage via the existing fake `BatchV1JobsClient` seam.

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned — `adapters/k8s.py`, `adapters/factory.py`,
  `deploy/helm/templates/role.yaml`, `tests/unit/_k8s_fakes.py`,
  `tests/unit/test_runners_k8s.py`, `tests/unit/test_runners_factory.py`,
  `tests/unit/test_aigateway_base_url_forwarding.py`,
  `tests/unit/test_runner_job_lifecycle_settings.py`,
  `tests/unit/test_tavily_key_forwarding.py` + the four docs artifacts.
- **Commits:** <sha> — feat(engine): refuse a run when the namespace quota has no headroom (OME-1065)
- **Gates:** ruff check ✓ · ruff format ✓ · pyright 0 errors ✓ · layering OK ✓ ·
  pytest 2282 passed, 5 skipped, 91.65% coverage (≥80) ✓
- **Deviations:** the spec adds `limitranges` RBAC (get/list) beyond the ticket's
  `resourcequotas` line — the LimitRange read is required for the defaulted-charge
  accounting the acceptance criteria demand.

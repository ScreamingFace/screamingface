# OME-1065 — Plan: quota-aware admission in K8sJobRunner

## Steps

1. **`adapters/k8s.py` — the client seam and snapshot types.**
   Add `CoreV1QuotaClient` Protocol plus the structural Protocols for the
   returned objects (`_QuotaView`, `_QuotaList`, `_LimitRangeView`,
   `_LimitRangeList`, `_LimitRangeItem`, `_LimitRangeSpec`), in the same style as
   the existing `_JobView` family. Add `_QuotaSnapshot` dataclass
   (`used`/`hard`/`charge` as `dict[str, int]`).

2. **`adapters/k8s.py` — quantity parsing and charge computation.**
   `_quantity(dimension, value)` parses a k8s quantity to an exact int
   (millicores for cpu, natural unit otherwise) via
   `kubernetes.utils.quantity.parse_quantity`. `_limitrange_defaults` merges
   LimitRange defaults (max per resource). `_pod_charge` computes the charge of
   one Runner Pod from `self._resources` plus the defaults.

3. **`adapters/k8s.py` — the admission gate.**
   Constructor gains `core_client: CoreV1QuotaClient | None = None` and
   `quota_cache_ttl_s: float = 2.0`. Add `_quota_snapshot`, `_quota_cache_time`,
   `_reserved`, `_admission_lock`. `_schedule_blocking` calls `_reserve_or_raise`
   before the create and `_release_reservation` on `ApiException`. Add
   `_refresh_quota_if_stale`, `_fits`, `_max_runs_that_fit`. Import
   `JobRunnerAtCapacity`.

4. **`adapters/factory.py` — wire the core client.**
   Add `_in_cluster_core_client()` (shares the cached `ApiClient`). Add
   `core_client_factory` parameter to `build_job_runner`, pass
   `core_client=core_client_factory()`.

5. **`deploy/helm/templates/role.yaml` — RBAC.**
   Add `resourcequotas` (get/list/watch) and `limitranges` (get/list) rules.

6. **Tests.**
   `_k8s_fakes.py`: add `FakeQuotaStatus`, `FakeQuota`, `FakeLimitRangeItem`,
   `FakeLimitRangeSpec`, `FakeLimitRange`, `FakeQuotaList`, `FakeLimitRangeList`,
   `FakeCoreV1`. `test_runners_k8s.py`: admission tests (ceiling, fits,
   LimitRange default, concurrency, unreadable, no quota, create-failure
   release). `test_runners_factory.py` + the 3 other factory callers: pass
   `core_client_factory` returning the fake.

## Files

- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py`
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py`
- `apps/screamingface-engine/deploy/helm/templates/role.yaml`
- `apps/screamingface-engine/tests/unit/_k8s_fakes.py`
- `apps/screamingface-engine/tests/unit/test_runners_k8s.py`
- `apps/screamingface-engine/tests/unit/test_runners_factory.py`
- `apps/screamingface-engine/tests/unit/test_aigateway_base_url_forwarding.py`
- `apps/screamingface-engine/tests/unit/test_runner_job_lifecycle_settings.py`
- `apps/screamingface-engine/tests/unit/test_tavily_key_forwarding.py`

## Gates

- `uv run ruff check`
- `uv run ruff format --check`
- `uv run pyright`
- `python3 ../../.claude/scripts/check_layering.py`
- `uv run pytest --cov=screamingface_engine --cov=url4.streaming --cov-fail-under=80 -q`

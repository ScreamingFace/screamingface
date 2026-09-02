---
ticket: OME-1092
stack: screamingface-engine
status: in_progress
started: 2026-09-02
finished:
---

# OME-1092 — Cut over the chart to the worker pool and retire the Job adapter and its RBAC

## Intent

The cutover, blocked by OME-1093. Adds the runner pool Deployment with its drain
configuration and disruption budget, and deletes `adapters/k8s.py`, the
`batch/jobs` Role and RoleBinding, and the settings only the Job path read. The
control plane loses the ability to create Pods, which is a least-privilege win
falling out of the design. The commit body must state that queue-depth admission
supersedes OME-1065, or the next reader will restore the deleted quota code.

## Planned changes

- `apps/screamingface-engine/deploy/helm/templates/deployment-runner.yaml`,
  `poddisruptionbudget.yaml` (new).
- `apps/screamingface-engine/deploy/helm/templates/role.yaml`,
  `rolebinding.yaml` (delete).
- `apps/screamingface-engine/deploy/helm/values.yaml`,
  `values.schema.json`, `values-cloud.yaml` (modify).
- `apps/screamingface-engine/src/screamingface_engine/adapters/k8s.py` (delete).
- `apps/screamingface-engine/src/screamingface_engine/adapters/factory.py`
  (modify).
- `apps/screamingface-engine/pyproject.toml` (modify — drop the kubernetes
  client if nothing else uses it).
- Tests: `tests/unit/test_chart_render_runner_pool.py` (new); port the
  env-contract tests from the deleted adapter to the queue codec.

## Test plan

- RED (rendered-manifest tests): the pool Deployment renders with the declared
  concurrency, the hardened securityContext, `envFrom` the existing runner-env
  ConfigMap, both checksum annotations, and
  `terminationGracePeriodSeconds > drain_grace_s`.
- RED: no `batch/jobs` RBAC renders anywhere in the chart.
- RED: a test asserting no import of the kubernetes client remains under
  `apps/screamingface-engine`.

## Acceptance

- The chart renders a runner pool; the Job adapter and its RBAC are gone.
- Queue-depth admission supersedes OME-1065, stated in the commit body.
- Engine stack gates green (cov >= 80), plus `charts.yml` (helm template).

## Outcome (fill at the end — required before COMMIT)

- **Actual files:** as planned, plus: `templates/NOTES.txt`, `templates/garage.yaml`,
  `templates/secret-tavily.yaml`, `templates/secret-artifact-storage.yaml`,
  `templates/_helpers.tpl`, `templates/configmap-runner-env.yaml` comment updates;
  `deploy/helm/README.md` rewritten for the pool; engine `README.md`, `Dockerfile`,
  `docs/execution-flow-diagrams.md`, `docs/request-workflow.md` de-Jobbed;
  `.github/scripts/verify_chart_wiring.py` now looks up both Deployments by name and reads
  the pool's image instead of `URL4_CLOUD_RUNNER_IMAGE`; `.claude/scripts/check_layering.py`
  dropped `adapters.k8s`; aigateway chart comments re-pointed at the pool's labels.
  New tests: `test_chart_render_runner_pool.py`, `test_no_kubernetes_client.py`,
  `test_worker_metrics.py`, `test_queue_metrics.py`. Deleted: `adapters/k8s.py`,
  `_k8s_fakes.py`, `test_runners_k8s.py`, `test_runner_job_lifecycle_settings.py`,
  `test_runner_job_env_isolation.py`, `test_tavily_key_forwarding.py`,
  `test_aigateway_base_url_forwarding.py`. Ported to the queue codec: `test_job_env_contract.py`,
  `test_run_queue_codec.py`, and the env-contract tests in `test_cache_policy_threading.py`,
  `test_identity_header_propagation.py`, `test_adapters_extra_models.py`.
- **Commits:** <sha — message>
- **Gates:** ruff check/format clean · pyright 0 errors · check_layering OK ·
  `helm lint` 0 failed · `helm template` renders · verify_chart_wiring 110/110 ·
  pytest 2304 passed, 8 skipped, coverage 90.84% (floor 80).
- **Deviations:** the runner pool runs the BENCHMARK image (the worker forks each run as a
  child from its own image, so the pool must carry the private grading assets) — the design
  did not name the image; the old `URL4_CLOUD_RUNNER_IMAGE` env var is gone and the verifier
  reads the pool Deployment's image instead. Worker metrics are served on a dedicated port
  (`runnerPool.metricsPort`, `prometheus_client.start_http_server`) because the worker is a
  separate process with no /metrics of its own. Alert rules live in a separate repo (none in
  this one); the metrics they consume are wired here, oldest-unclaimed-age first.

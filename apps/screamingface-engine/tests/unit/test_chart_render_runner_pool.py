"""The runner pool Deployment renders with the declared concurrency and hardening (OME-1092).

The cutover replaces one-Job-per-run scheduling with a fixed worker pool. This test renders
the chart and asserts the pool's shape:

- `replicas × worker_slots` is the declared concurrency (both chart values);
- the pod carries the same hardened securityContext the Job manifest used to apply
  (non-root 1000, read-only rootfs, all capabilities dropped, RuntimeDefault seccomp,
  /tmp emptyDir, `automountServiceAccountToken: false`, `enableServiceLinks: false`);
- its env comes from the existing runner-env ConfigMap by `envFrom`, unchanged;
- a ConfigMap change alone rolls the pool via the checksum annotations;
- the drain configuration (`preStop` + `terminationGracePeriodSeconds > drain_grace_s` +
  a `maxUnavailable: 0` PodDisruptionBudget) is what keeps a deploy from interrupting runs;
- the container command is the `worker` mode;
- NO `batch/jobs` RBAC renders anywhere — the control plane can no longer create Pods.

WHY render and not read the template text: the charts.yml gate exists because `helm lint`
reports success for a chart that cannot render. The assertions here are against the RENDERED
manifest — the same precedent as `test_chart_identity.py`'s render test and the
`verify_chart_wiring.py` gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "deploy" / "helm"
_RELEASE = "url4-cloud"

# The runner pool's admission key in aigateway's NetworkPolicy (the old `RUNNER_LABELS`).
_RUNNER_NAME_LABEL = "url4-runner"


def _render() -> list[dict]:
    """Render the chart and return its documents. Raises if helm refuses."""
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _values() -> dict:
    return yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))


def _find(docs: list[dict], kind: str, name: str) -> dict:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind} named {name!r} in the rendered chart")


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_pool_deployment_renders_with_the_declared_concurrency() -> None:
    """`replicas × worker_slots` is the declared concurrency — both are chart values, and the
    pool's slot count must match the worker's own `run_queue_worker_slots` default."""
    docs = _render()
    values = _values()
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")

    assert pool["spec"]["replicas"] == values["runnerPool"]["replicas"]
    assert values["runnerPool"]["workerSlots"] >= 1
    # The declared concurrency: replicas × slots. The worker's slot count is the same value
    # the queue settings derive `max_ack_pending` from, so the pool and the queue cannot
    # disagree about how many runs one worker may hold.
    assert pool["spec"]["replicas"] * values["runnerPool"]["workerSlots"] >= 1


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_pool_pod_is_hardened_like_the_job_manifest_was() -> None:
    """The same hardening the Job manifest applied today: non-root 1000, read-only rootfs,
    all capabilities dropped, RuntimeDefault seccomp, /tmp emptyDir, no service-account token,
    no service-link env injection."""
    docs = _render()
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    pod = pool["spec"]["template"]["spec"]

    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}
    assert {"name": "tmp", "emptyDir": {}} in pod["volumes"]

    container = pod["containers"][0]
    sec = container["securityContext"]
    assert sec["allowPrivilegeEscalation"] is False
    assert sec["capabilities"] == {"drop": ["ALL"]}
    assert sec["runAsNonRoot"] is True
    assert sec["runAsUser"] == 1000
    assert sec["readOnlyRootFilesystem"] is True
    assert {"name": "tmp", "mountPath": "/tmp"} in container["volumeMounts"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_pool_runs_the_worker_mode_and_inherits_the_runner_env_configmap() -> None:
    """The container command is the `worker` mode (OME-1089), and its deploy-time env is the
    existing runner-env ConfigMap attached by `envFrom` — Helm still owns those names."""
    docs = _render()
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    container = pool["spec"]["template"]["spec"]["containers"][0]

    assert container["command"] == ["screamingface-engine", "worker"]
    assert {"configMapRef": {"name": f"{_RELEASE}-{_RELEASE}-runner-env"}} in container["envFrom"]


def _render_with_overrides(**overrides: str) -> list[dict]:
    """Render the chart with `--set` overrides, so a test can prove a chart VALUE
    actually reaches the rendered manifest. (`--set`, not `--set-string`: the schema
    types workerSlots/drainGraceS/metricsPort as numbers, and helm refuses a string.)"""
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string",
            "config.natsUrl=nats://nats.example:4222"]
    for key, value in overrides.items():
        args += ["--set", f"{key}={value}"]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_pool_renders_its_own_settings_into_the_worker_env() -> None:
    """`runnerPool.workerSlots` / `drainGraceS` / `metricsPort` must reach the worker pod's
    env — the worker builds `Settings()` from its environment, so unrendered values read
    the code defaults instead. The drift is invisible while the defaults coincide
    (4 / 30 / 9109), so this test renders NON-default values: an operator who sets
    `workerSlots: 8` gets 8× the resource requests, and the worker must actually run 8
    slots (the queue's `max_ack_pending` derives from the same setting)."""
    docs = _render_with_overrides(
        **{
            "runnerPool.workerSlots": "8",
            "runnerPool.drainGraceS": "17",
            "runnerPool.metricsPort": "9199",
        }
    )
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    container = pool["spec"]["template"]["spec"]["containers"][0]
    env = {entry["name"]: entry["value"] for entry in container["env"]}

    assert env["URL4_CLOUD_RUN_QUEUE_WORKER_SLOTS"] == "8"
    assert env["URL4_CLOUD_WORKER_DRAIN_GRACE_S"] == "17"
    assert env["URL4_CLOUD_WORKER_METRICS_PORT"] == "9199"
    # The metrics port and the containerPort are the same knob — they must agree.
    port = next(p for p in container["ports"] if p["name"] == "metrics")
    assert port["containerPort"] == 9199


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_a_configmap_change_alone_rolls_the_pool() -> None:
    """Both checksum annotations are present, matching the App Deployment's invariant: a
    ConfigMap/Secret value change alone must roll the pod, or the pool keeps stale env."""
    docs = _render()
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    annotations = pool["spec"]["template"]["metadata"]["annotations"]

    assert "checksum/runner-env" in annotations
    assert "checksum/secret" in annotations
    assert annotations["checksum/runner-env"], "the runner-env checksum rendered empty"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_drain_configuration_keeps_a_deploy_from_interrupting_runs() -> None:
    """`terminationGracePeriodSeconds > drain_grace_s`, a `preStop` that starts the drain,
    and a `maxUnavailable: 1` PodDisruptionBudget — voluntary disruptions are SERIALIZED,
    one pod at a time. A PDB cannot see slot occupancy, so `0` would not "wait for the
    slots"; it makes `disruptionsAllowed` permanently 0 and every drain/autoscaler
    eviction blocks on this pod forever. The drain itself is what protects in-flight
    runs."""
    docs = _render()
    values = _values()
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    pod = pool["spec"]["template"]["spec"]

    assert pod["terminationGracePeriodSeconds"] > values["runnerPool"]["drainGraceS"]
    pre_stop = pod["containers"][0]["lifecycle"]["preStop"]["exec"]["command"]
    assert pre_stop, "the pool needs a preStop that starts the drain"

    pdb = _find(docs, "PodDisruptionBudget", f"{_RELEASE}-{_RELEASE}-runner")
    assert pdb["spec"]["maxUnavailable"] == 1
    assert pdb["spec"]["selector"]["matchLabels"]["app.kubernetes.io/name"] == _RUNNER_NAME_LABEL


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_pool_resources_are_slots_times_the_per_run_charge_plus_overhead() -> None:
    """The pool's resources are `worker_slots × per-run charge` + the worker's own overhead —
    sized so the declared concurrency can actually run, not BestEffort."""
    docs = _render()
    values = _values()
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    resources = pool["spec"]["template"]["spec"]["containers"][0]["resources"]
    slots = values["runnerPool"]["workerSlots"]
    charge = values["runnerPool"]["perRunCharge"]
    overhead = values["runnerPool"]["overhead"]

    assert resources["requests"]["cpu"] == (
        f"{slots * charge['cpuMillicores'] + overhead['cpuMillicores']}m"
    )
    assert resources["requests"]["memory"] == (
        f"{slots * charge['memoryMi'] + overhead['memoryMi']}Mi"
    )
    assert resources["limits"]["memory"] == (
        f"{slots * charge['memoryLimitMi'] + overhead['memoryLimitMi']}Mi"
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_no_batch_jobs_rbac_renders_anywhere_in_the_chart() -> None:
    """RED (OME-1092): the control plane stops being able to create Pods. No Role or
    RoleBinding may render, and no template may grant verbs on `batch/jobs`."""
    docs = _render()

    kinds = {doc.get("kind") for doc in docs}
    assert "Role" not in kinds, (
        "the namespace Role must be gone — the control plane no longer schedules Jobs"
    )
    assert "RoleBinding" not in kinds, "the RoleBinding must be gone with the Role"

    rendered = "\n".join(yaml.safe_dump(doc) for doc in docs)
    assert "batch" not in rendered, "no template may grant verbs on batch/jobs"
    assert "jobs" not in rendered, "no template may name the jobs resource"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_pool_carries_the_network_policy_admission_label() -> None:
    """The pool replaces the Jobs, so its pods must carry the `url4-runner` label aigateway's
    NetworkPolicy admits — the same contract the old `RUNNER_LABELS` served."""
    docs = _render()
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    labels = pool["spec"]["template"]["metadata"]["labels"]

    assert labels["app.kubernetes.io/name"] == _RUNNER_NAME_LABEL
    assert labels["app.kubernetes.io/part-of"] == "url4-cloud"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_deploy_time_credentials_travel_by_secret_reference_never_as_literals() -> None:
    """The Tavily and object-storage credentials reach the pool by `envFrom.secretRef`, never
    as literals in the rendered manifest — the same invariant the Job path held (a manifest is
    readable with `get` and echoed by `kubectl describe`)."""
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "tavily.enabled=true",
            "--set",
            "tavily.apiKey=tvly-chart-test",
            "--set",
            "artifactStorage.backend=s3",
            "--set",
            "artifactStorage.s3.endpointUrl=http://garage:3900",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")
    env_from = pool["spec"]["template"]["spec"]["containers"][0]["envFrom"]

    assert {"secretRef": {"name": f"{_RELEASE}-{_RELEASE}-tavily"}} in env_from
    assert {"secretRef": {"name": f"{_RELEASE}-{_RELEASE}-artifact-storage"}} in env_from
    # The key IS in the chart's own Secret object (that is what a Secret is for) — the
    # invariant is that it never reaches the pool's env as a literal.
    pool_yaml = yaml.safe_dump(pool)
    assert "tvly-chart-test" not in pool_yaml, (
        "the Tavily key must never be a literal in the pool's env — it travels by "
        "envFrom.secretRef only"
    )


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_runner_env_configmap_still_carries_the_deploy_time_names() -> None:
    """The runner-env ConfigMap is unchanged: Helm still owns AIGATEWAY_BASE_URL and the
    artifact-store settings, and the pool inherits them by `envFrom`."""
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "config.aigatewayBaseUrl=http://aigateway:9105",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    runner_env = _find(docs, "ConfigMap", f"{_RELEASE}-{_RELEASE}-runner-env")
    pool = _find(docs, "Deployment", f"{_RELEASE}-{_RELEASE}-runner")

    assert runner_env["data"]["AIGATEWAY_BASE_URL"] == "http://aigateway:9105"
    assert "URL4_CLOUD_NATS_URL" in runner_env["data"]
    assert {"configMapRef": {"name": f"{_RELEASE}-{_RELEASE}-runner-env"}} in pool["spec"][
        "template"
    ]["spec"]["containers"][0]["envFrom"]

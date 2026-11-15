"""The opt-in KEDA ScaledObject for the runner pool (runner-pool autoscaling spec D4).

With `runnerPool.autoscaling.enabled` true, the chart renders one ScaledObject that scales the
runner Deployment on the App's `GET /runner-demand` (the claimable queue demand), the Deployment
renders no `spec.replicas`, and the queue's per-caller `max_ack_pending` must be pinned. Disabled
= unchanged: the render is byte-identical to the render before this block existed.

WHY render and not read the template text: `helm lint` reports success for a chart that cannot
render, so the assertions here are against the RENDERED manifest. The same precedent as
`test_chart_render_runner_pool.py`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "deploy" / "helm"
_RELEASE = "url4-cloud"
_NAMESPACE = "sf-test"
_POOL = f"{_RELEASE}-{_RELEASE}-runner"
_APP_SERVICE = _POOL.removesuffix("-runner")
_ENABLED = {
    "runnerPool.autoscaling.enabled": "true",
    "runnerPool.autoscaling.minReplicas": "2",
    "runnerPool.autoscaling.maxReplicas": "5",
    "runnerPool.maxAckPending": "4",
    # The chart refuses autoscaling with a drain shorter than the run deadline (spec D5).
    "runnerPool.drainGraceS": "57600",
    "runnerPool.terminationGracePeriodSeconds": "57625",
}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _helm(**overrides: str) -> subprocess.CompletedProcess[str]:
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--namespace",
        _NAMESPACE,
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    for key, value in overrides.items():
        args += ["--set", f"{key}={value}"]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(**overrides: str) -> list[dict[str, Any]]:
    result = _helm(**overrides)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _refusal(**overrides: str) -> str:
    result = _helm(**overrides)
    assert result.returncode != 0, "the render must refuse these values"
    return result.stderr


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind} named {name!r} in the rendered chart")


def _of_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [doc for doc in docs if doc.get("kind") == kind]


def _env(pool: dict[str, Any]) -> dict[str, str]:
    return {
        e["name"]: e["value"]
        for e in pool["spec"]["template"]["spec"]["containers"][0]["env"]
        if "value" in e
    }


def test_the_default_render_has_no_scaled_object_and_keeps_replicas() -> None:
    docs = _render()

    assert _of_kind(docs, "ScaledObject") == []
    assert _find(docs, "Deployment", _POOL)["spec"]["replicas"] == 1


def test_disabled_is_byte_identical_to_the_default() -> None:
    # WHY pin auth.jwtSecret: when it is empty, the chart makes a random JWT secret on each
    # render, and that also changes the checksum/secret annotation. A pinned value makes the
    # render deterministic, so the two renders can be compared byte for byte.
    pinned = {"auth.jwtSecret": "fixed-test-secret"}
    a = _helm(**pinned)
    b = _helm(**pinned, **{"runnerPool.autoscaling.enabled": "false"})

    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    assert a.stdout == b.stdout


def test_enabled_renders_one_scaled_object_on_the_runner_deployment() -> None:
    docs = _render(**_ENABLED)

    (so,) = _of_kind(docs, "ScaledObject")
    assert so["apiVersion"] == "keda.sh/v1alpha1"
    assert so["metadata"]["name"] == _POOL
    assert so["spec"]["scaleTargetRef"] == {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "name": _POOL,
    }
    assert so["spec"]["minReplicaCount"] == 2
    assert so["spec"]["maxReplicaCount"] == 5
    assert so["spec"]["pollingInterval"] == 15
    assert "fallback" not in so["spec"]

    (trigger,) = so["spec"]["triggers"]
    assert trigger["type"] == "metrics-api"
    assert trigger["metricType"] == "AverageValue"
    assert trigger["metadata"] == {
        "format": "json",
        "url": f"http://{_APP_SERVICE}.{_NAMESPACE}.svc.cluster.local:9108/runner-demand",
        "valueLocation": "demand",
        "targetValue": "4",
    }


def test_enabled_behavior_carries_the_scaling_windows() -> None:
    docs = _render(**_ENABLED)

    (so,) = _of_kind(docs, "ScaledObject")
    assert so["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"] == {
        "scaleUp": {
            "stabilizationWindowSeconds": 0,
            "tolerance": "0",
            "policies": [{"type": "Pods", "value": 4, "periodSeconds": 15}],
        },
        "scaleDown": {
            "stabilizationWindowSeconds": 300,
            "policies": [{"type": "Pods", "value": 1, "periodSeconds": 60}],
        },
    }


def test_enabled_the_deployment_has_no_replicas_and_the_pinned_ack_cap() -> None:
    docs = _render(**_ENABLED)

    pool = _find(docs, "Deployment", _POOL)
    assert "replicas" not in pool["spec"]
    assert _env(pool)["URL4_CLOUD_RUN_QUEUE_MAX_ACK_PENDING"] == "4"


def test_the_trigger_url_follows_the_rendered_app_service() -> None:
    docs = _render(**_ENABLED, **{"service.port": "9200"})

    svc = _find(docs, "Service", _APP_SERVICE)
    port = svc["spec"]["ports"][0]["port"]
    assert port == 9200
    (so,) = _of_kind(docs, "ScaledObject")
    url = so["spec"]["triggers"][0]["metadata"]["url"]
    assert (
        url
        == f"http://{svc['metadata']['name']}.{_NAMESPACE}.svc.cluster.local:{port}/runner-demand"
    )


def test_enabled_without_max_replicas_is_refused() -> None:
    stderr = _refusal(**{"runnerPool.autoscaling.enabled": "true", "runnerPool.maxAckPending": "4"})

    assert "runnerPool.autoscaling.maxReplicas" in stderr


def test_a_zero_min_replicas_is_refused() -> None:
    stderr = _refusal(**{**_ENABLED, "runnerPool.autoscaling.minReplicas": "0"})

    assert "minReplicas" in stderr


def test_min_above_max_is_refused() -> None:
    stderr = _refusal(**{**_ENABLED, "runnerPool.autoscaling.minReplicas": "6"})

    assert "runnerPool.autoscaling.minReplicas (6)" in stderr
    assert "runnerPool.autoscaling.maxReplicas (5)" in stderr


def test_enabled_without_a_pinned_max_ack_pending_is_refused() -> None:
    stderr = _refusal(**{k: v for k, v in _ENABLED.items() if k != "runnerPool.maxAckPending"})

    assert "runnerPool.maxAckPending" in stderr


def test_the_target_value_is_the_worker_slot_count() -> None:
    docs = _render(**_ENABLED, **{"runnerPool.workerSlots": "2"})

    (so,) = _of_kind(docs, "ScaledObject")
    assert so["spec"]["triggers"][0]["metadata"]["targetValue"] == "2"


def test_every_document_declares_its_identity_when_enabled() -> None:
    for doc in _render(**_ENABLED):
        assert doc.get("apiVersion") and doc.get("kind")

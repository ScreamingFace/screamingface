"""OME-1931 spec D6: the runner pod mounts no ServiceAccount token unless deletionCost is enabled,
also when the value is removed (null), and the feature renders the same with autoscaling on or off.
Assertions are on the PARSED render.

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
_FULL = f"{_RELEASE}-{_RELEASE}"
_RUNNER = f"{_FULL}-runner"
_NEW_ENV = (
    "URL4_CLOUD_WORKER_DELETION_COST_ENABLED",
    "URL4_CLOUD_WORKER_POD_NAME",
    "URL4_CLOUD_WORKER_POD_NAMESPACE",
)
_ON = {"runnerPool.deletionCost.enabled": "true"}
_AUTOSCALING_ON = {
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


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == kind and doc.get("metadata", {}).get("name") == name:
            return doc
    raise AssertionError(f"no {kind} named {name!r} in the rendered chart")


def _of_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [doc for doc in docs if doc.get("kind") == kind]


def _pod(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return _find(docs, "Deployment", _RUNNER)["spec"]["template"]["spec"]


def _env_names(pod: dict[str, Any]) -> set[str]:
    return {e["name"] for c in pod["containers"] for e in (c.get("env") or [])}


def test_a_removed_enabled_value_mounts_no_token() -> None:
    docs = _render(**{"runnerPool.deletionCost.enabled": "null"})
    pod = _pod(docs)

    assert pod["automountServiceAccountToken"] is False
    assert pod["serviceAccountName"] == _FULL
    assert not any(d["metadata"]["name"] == _RUNNER for d in _of_kind(docs, "ServiceAccount"))
    assert _env_names(pod).isdisjoint(_NEW_ENV)


def test_the_default_render_has_a_boolean_false() -> None:
    pod = _pod(_render())

    assert pod["automountServiceAccountToken"] is False


@pytest.mark.parametrize(
    "extra",
    [{}, _AUTOSCALING_ON],
    ids=["autoscaling-off", "autoscaling-on"],
)
def test_the_feature_renders_the_same_with_autoscaling_on_and_off(extra: dict[str, str]) -> None:
    docs = _render(**_ON, **extra)
    pod = _pod(docs)

    assert pod["automountServiceAccountToken"] is True
    assert pod["serviceAccountName"] == _RUNNER
    assert _find(docs, "ServiceAccount", _RUNNER)
    assert set(_NEW_ENV) <= _env_names(pod)

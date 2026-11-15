"""The runner-pool ScaledObject scales up exactly; autoscaling refuses a drain shorter than a run.

Scale-up: the HPA holds the replica count while the usage ratio stays inside its tolerance band
(cluster default 10 %), so 3 pods of 4 slots at demand 13 never get a 4th pod. The chart renders
`behavior.scaleUp.tolerance` (default "0") so a scale-up follows `ceil(demand / workerSlots)`
(autoscaling spec D4). Drain: a scale-down may remove a busy pod, so with autoscaling on
`runnerPool.drainGraceS` must cover the longest run, `config.jobDeadlineS` (spec D5). The
assertions are against the RENDERED manifest, as in `test_chart_render_runner_autoscaling.py`.
"""

from __future__ import annotations

import math
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
_ENABLED = {
    "runnerPool.autoscaling.enabled": "true",
    "runnerPool.autoscaling.minReplicas": "2",
    "runnerPool.autoscaling.maxReplicas": "5",
    "runnerPool.maxAckPending": "4",
    "runnerPool.drainGraceS": "57600",
    "runnerPool.terminationGracePeriodSeconds": "57625",
}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _helm(flag: str = "--set", **overrides: str) -> subprocess.CompletedProcess[str]:
    # WHY a flag: `--set` sends `0.05` to the schema as a string, and the schema types
    # `scaleUp.tolerance` as a number; `--set-json` sends the number a values file would.
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
        args += [flag, f"{key}={value}"]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(**overrides: str) -> list[dict[str, Any]]:
    result = _helm(**overrides)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _refusal(**overrides: str) -> str:
    result = _helm(**overrides)
    assert result.returncode != 0, "the render must refuse these values"
    return result.stderr


def _of_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [doc for doc in docs if doc.get("kind") == kind]


def _hpa_desired(current: int, total: float, target: float, tolerance: float) -> int:
    """The Kubernetes HPA rule for an AverageValue external metric
    (`GetExternalPerPodMetricReplicas` in `pkg/controller/podautoscaler`): the usage ratio is
    `total / (current × target)`. Inside the tolerance band around 1 the HPA holds `current`;
    outside it, it scales to `ceil(total / target)`."""
    ratio = total / (current * target)
    if abs(1.0 - ratio) <= tolerance:
        return current
    return math.ceil(total / target)


def test_the_scale_up_tolerance_renders_as_zero_by_default() -> None:
    docs = _render(**_ENABLED)

    (so,) = _of_kind(docs, "ScaledObject")
    behavior = so["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]
    assert behavior["scaleUp"]["tolerance"] == "0"
    assert "tolerance" not in behavior["scaleDown"]


def test_a_tolerance_override_renders_as_a_quantity_string() -> None:
    result = _helm("--set-json", **_ENABLED, **{"runnerPool.autoscaling.scaleUp.tolerance": "0.05"})

    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    (so,) = _of_kind(docs, "ScaledObject")
    behavior = so["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]
    assert behavior["scaleUp"]["tolerance"] == "0.05"


def test_a_negative_tolerance_is_refused() -> None:
    result = _helm("--set-json", **_ENABLED, **{"runnerPool.autoscaling.scaleUp.tolerance": "-0.1"})

    assert result.returncode != 0, "the render must refuse a negative tolerance"
    assert "tolerance" in result.stderr
    assert "minimum" in result.stderr


def test_three_pods_of_four_slots_at_demand_13_scale_to_four() -> None:
    docs = _render(**_ENABLED, **{"runnerPool.workerSlots": "4"})

    (so,) = _of_kind(docs, "ScaledObject")
    target = float(so["spec"]["triggers"][0]["metadata"]["targetValue"])
    tolerance = float(
        so["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]["scaleUp"]["tolerance"]
    )
    assert _hpa_desired(3, 13, target, tolerance) == 4
    # The reviewer's case: the cluster default 10 % tolerance holds 3 pods (13/12 = 1.083).
    assert _hpa_desired(3, 13, target, 0.1) == 3
    assert _hpa_desired(8, 35, target, tolerance) == 9
    assert _hpa_desired(8, 35, target, 0.1) == 8
    assert _hpa_desired(9, 39, target, tolerance) == 10
    assert _hpa_desired(9, 39, target, 0.1) == 9


def test_enabled_with_a_drain_shorter_than_the_run_deadline_is_refused() -> None:
    stderr = _refusal(
        **{
            **_ENABLED,
            "runnerPool.drainGraceS": "30",
            "runnerPool.terminationGracePeriodSeconds": "60",
        }
    )

    assert "runnerPool.drainGraceS (30)" in stderr
    assert "config.jobDeadlineS (57600)" in stderr


def test_a_drain_equal_to_the_run_deadline_is_accepted() -> None:
    docs = _render(**_ENABLED)

    assert _of_kind(docs, "ScaledObject")


def test_a_shorter_run_deadline_allows_a_shorter_drain() -> None:
    docs = _render(
        **{
            **_ENABLED,
            "config.jobDeadlineS": "600",
            "runnerPool.drainGraceS": "600",
            "runnerPool.terminationGracePeriodSeconds": "625",
        }
    )

    assert _of_kind(docs, "ScaledObject")


def test_disabled_ignores_the_drain_rule() -> None:
    docs = _render()

    assert _of_kind(docs, "ScaledObject") == []

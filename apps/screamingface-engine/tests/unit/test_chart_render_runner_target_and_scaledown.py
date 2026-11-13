"""The runner-pool ScaledObject takes a per-pod target and an optional scale-down switch.

KEDA 2.17 (the AKS add-on) drops `behavior.scaleUp.tolerance`, so the HPA keeps its default 10 %
band. The band stalls a pool that has more claimable runs than slots: 3 pods of 4 slots at demand
13 hold at 3. `runnerPool.autoscaling.targetPerPod` lowers the per-pod target (3.6 for 4 slots),
so the usage ratio always leaves the band and the pool scales up (spec D8). `scaleDown.enabled:
false` renders `selectPolicy: Disabled`, so the pool never shrinks by itself until OME-1871.

The assertions are against the RENDERED manifest, as in
`test_chart_render_runner_scaleup_tolerance_and_drain.py`.
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
    # WHY a flag: `--set` sends `3.6` to the schema as a string, and the schema types
    # `targetPerPod` and `scaleDown.enabled` as number and boolean; `--set-json` sends the
    # value a values file would.
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


def _render(flag: str = "--set", **overrides: str) -> list[dict[str, Any]]:
    result = _helm(flag, **overrides)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


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


def _behavior(docs: list[dict[str, Any]]) -> dict[str, Any]:
    (so,) = _of_kind(docs, "ScaledObject")
    return so["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]


def _target(docs: list[dict[str, Any]]) -> str:
    (so,) = _of_kind(docs, "ScaledObject")
    return so["spec"]["triggers"][0]["metadata"]["targetValue"]


def test_the_default_enabled_render_targets_the_slot_count_and_scales_down() -> None:
    docs = _render(**_ENABLED, **{"runnerPool.workerSlots": "4"})

    assert _target(docs) == "4"
    assert "selectPolicy" not in _behavior(docs)["scaleDown"]


def test_a_per_pod_target_override_renders_as_a_quantity_string() -> None:
    docs = _render("--set-json", **_ENABLED, **{"runnerPool.autoscaling.targetPerPod": "3.6"})

    assert _target(docs) == "3.6"


def test_the_keda_217_target_never_stalls_the_pool() -> None:
    # KEDA 2.17 drops the tolerance, so the HPA runs with the default 10 % band.
    docs = _render(
        "--set-json",
        **_ENABLED,
        **{"runnerPool.workerSlots": "4", "runnerPool.autoscaling.targetPerPod": "3.6"},
    )
    target = float(_target(docs))

    assert _hpa_desired(3, 13, target, 0.1) == 4
    for pods in range(1, 21):
        assert _hpa_desired(pods, 4 * pods + 1, target, 0.1) > pods


def test_the_stall_that_the_lower_target_fixes_is_real() -> None:
    # The slot target with the default 10 % band holds 3 pods at demand 13 (13/12 = 1.083).
    assert _hpa_desired(3, 13, 4.0, 0.1) == 3


def test_a_per_pod_target_above_the_slot_count_is_refused() -> None:
    result = _helm(
        "--set-json",
        **_ENABLED,
        **{"runnerPool.workerSlots": "4", "runnerPool.autoscaling.targetPerPod": "4.5"},
    )

    assert result.returncode != 0, "the render must refuse a target above workerSlots"
    assert "runnerPool.autoscaling.targetPerPod (4.5)" in result.stderr
    assert "runnerPool.workerSlots (4)" in result.stderr


def test_a_per_pod_target_equal_to_the_slot_count_renders() -> None:
    docs = _render(
        "--set-json",
        **_ENABLED,
        **{"runnerPool.workerSlots": "4", "runnerPool.autoscaling.targetPerPod": "4"},
    )

    assert _target(docs) == "4"


def test_a_zero_per_pod_target_is_refused_by_the_schema() -> None:
    result = _helm("--set-json", **_ENABLED, **{"runnerPool.autoscaling.targetPerPod": "0"})

    assert result.returncode != 0, "the render must refuse a zero target"
    assert "targetPerPod" in result.stderr


def test_scale_down_disabled_renders_select_policy_disabled() -> None:
    docs = _render(
        "--set-json", **_ENABLED, **{"runnerPool.autoscaling.scaleDown.enabled": "false"}
    )

    assert _behavior(docs)["scaleDown"]["selectPolicy"] == "Disabled"


def test_scale_down_disabled_leaves_scale_up_unchanged() -> None:
    default = _behavior(_render(**_ENABLED))
    disabled = _behavior(
        _render("--set-json", **_ENABLED, **{"runnerPool.autoscaling.scaleDown.enabled": "false"})
    )

    assert disabled["scaleUp"] == default["scaleUp"]


def test_autoscaling_disabled_renders_no_scaled_object() -> None:
    docs = _render()

    assert _of_kind(docs, "ScaledObject") == []

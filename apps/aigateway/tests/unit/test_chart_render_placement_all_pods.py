"""Every pod the chart renders carries the chart's node placement (OME-1314).

WHY this file exists: `nodeSelector` and `tolerations` are set once in values, and each
template must read them. A template that forgets them still renders, every gate passes, and
the pod lands on the wrong pool. The migrate Job and the bundled Garage were such templates.
This test renders every workload the chart can produce with placement set and asserts each
pod template carries it, so a future workload that forgets it is caught.

WHY `affinity` is excluded: an affinity names pod labels. The gateway's affinity selects
gateway pods, which the migrate Job and Garage do not carry, so copying it would be wrong.

WHY the render is generic over kinds: a hand-picked list of pods would miss the next
workload. The test iterates the rendered documents and fails if the expected set is absent,
so it cannot pass on an empty render.

AIDEV-NOTE: needs `helm` on PATH. The skipif guard matches the sibling chart tests. GitHub's
`ubuntu-latest` ships helm, so these run on the merge gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "charts" / "aigateway"

_POOL = {"openmined.org/pool": "tenant"}
_TOLERATIONS = [{"key": "workload", "operator": "Equal", "value": "tenant", "effect": "NoSchedule"}]
_PLACED: dict[str, Any] = {"nodeSelector": _POOL, "tolerations": _TOLERATIONS}
_AFFINITY = {
    "nodeAffinity": {
        "requiredDuringSchedulingIgnoredDuringExecution": {
            "nodeSelectorTerms": [{"matchExpressions": [{"key": "x", "operator": "Exists"}]}]
        }
    }
}
_WORKLOAD_KINDS = {"Deployment", "StatefulSet", "Job", "DaemonSet"}
_EXPECTED = {
    ("Deployment", "aigw-aigateway"),
    ("Job", "aigw-aigateway-migrate"),
    ("StatefulSet", "aigw-aigateway-garage"),
}


def _render(tmp_path: Path, values: dict[str, Any]) -> list[dict[str, Any]]:
    base: dict[str, Any] = {
        "database": {"existingSecret": "db-secret"},
        "auth": {"existingSecret": "auth-secret"},
        "snapshot": {"enabled": True, "garage": {"enabled": True}},
        "migration": {"enabled": True},
    }
    base.update(values)
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump(base))
    result = subprocess.run(
        ["helm", "template", "aigw", str(_CHART), "--values", str(values_file)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _pod_specs(docs: list[dict[str, Any]]) -> list[tuple[str, str, dict[str, Any]]]:
    found = []
    for doc in docs:
        kind = doc["kind"]
        if kind == "CronJob":
            pod = doc["spec"]["jobTemplate"]["spec"]["template"]
        elif kind in _WORKLOAD_KINDS:
            pod = doc["spec"]["template"]
        else:
            continue
        found.append((kind, doc["metadata"]["name"], pod["spec"]))
    return found


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_every_pod_template_carries_the_chart_placement(tmp_path: Path) -> None:
    pods = _pod_specs(_render(tmp_path, {**_PLACED, "affinity": _AFFINITY}))
    assert _EXPECTED <= {(kind, name) for kind, name, _ in pods}, (
        "an expected workload did not render"
    )
    for kind, name, spec in pods:
        assert spec.get("nodeSelector") == _POOL, f"{kind}/{name} has no nodeSelector"
        assert spec.get("tolerations") == _TOLERATIONS, f"{kind}/{name} has no tolerations"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_rendered_workloads_include_gateway_migrate_and_garage(tmp_path: Path) -> None:
    pods = _pod_specs(_render(tmp_path, {**_PLACED, "affinity": _AFFINITY}))
    found = {(kind, name) for kind, name, _ in pods}
    assert _EXPECTED <= found


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_garage_and_migrate_carry_no_affinity_but_the_gateway_does(tmp_path: Path) -> None:
    docs = _render(tmp_path, {**_PLACED, "affinity": _AFFINITY})
    pods = {(kind, name): spec for kind, name, spec in _pod_specs(docs)}
    assert "affinity" in pods[("Deployment", "aigw-aigateway")]
    assert "affinity" not in pods[("Job", "aigw-aigateway-migrate")]
    assert "affinity" not in pods[("StatefulSet", "aigw-aigateway-garage")]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_default_values_add_no_placement(tmp_path: Path) -> None:
    pods = _pod_specs(_render(tmp_path, {}))
    assert _EXPECTED <= {(kind, name) for kind, name, _ in pods}
    for kind, name, spec in pods:
        assert "nodeSelector" not in spec, f"{kind}/{name} gained a nodeSelector by default"
        assert "tolerations" not in spec, f"{kind}/{name} gained tolerations by default"

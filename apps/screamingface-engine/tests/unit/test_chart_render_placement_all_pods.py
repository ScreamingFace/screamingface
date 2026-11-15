"""Every pod this chart's own templates render runs on the chart's node placement (OME-1314).

The optional NATS subchart takes its placement from `nats.*` values and is not checked here.

The App, the runner pool, both bundled Garage StatefulSets and the migrate Job must carry the same
`nodeSelector` and `tolerations`. WHY: a pod that misses them stays Pending on a tainted pool, or
lands on a node the operator did not choose. `affinity` is NOT copied to Garage or the migrate Job:
its labels name the App, and those pods carry other labels.

The assertions are against the RENDERED manifest, as in `test_chart_render_garage_selector.py`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm"
_RELEASE = "url4-cloud"
_FULLNAME = f"{_RELEASE}-{_RELEASE}"
_PLACEMENT = {"openmined.org/pool": "tenant"}
_TOLERATIONS = [{"key": "workload", "operator": "Equal", "value": "tenant", "effect": "NoSchedule"}]
_AFFINITY = {
    "podAntiAffinity": {
        "preferredDuringSchedulingIgnoredDuringExecution": [
            {
                "weight": 1,
                "podAffinityTerm": {
                    "topologyKey": "kubernetes.io/hostname",
                    "labelSelector": {"matchLabels": {"app.kubernetes.io/name": _RELEASE}},
                },
            }
        ]
    }
}
# WHY these gates: `garage.enabled` renders the results Garage, the s3 artifact backend with no
# blob endpoint renders the blob Garage, and `database.existingSecret` renders the migrate Job.
_WORKLOADS_ON = {
    "garage": {"enabled": True},
    "artifactStorage": {"backend": "s3"},
    "database": {"existingSecret": "db-creds"},
}
_EXPECTED_WORKLOADS = {
    f"Deployment/{_FULLNAME}",
    f"Deployment/{_FULLNAME}-runner",
    f"StatefulSet/{_FULLNAME}-garage",
    f"StatefulSet/{_FULLNAME}-garage-blobs",
    f"Job/{_FULLNAME}-migrate",
}
_POD_KINDS = {"Deployment", "StatefulSet", "Job", "CronJob", "DaemonSet"}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="needs the helm CLI")


def _write_values(tmp_path: Path, values: dict[str, Any]) -> Path:
    path = tmp_path / "values.yaml"
    path.write_text(yaml.safe_dump(values), encoding="utf-8")
    return path


def _render(values: Path | None = None) -> list[dict[str, Any]]:
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    if values is not None:
        args += ["-f", str(values)]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _pod_templates(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every pod template in the render, keyed `Kind/name`. Walks each kind that embeds a pod,
    so a workload added later is found without a change here."""
    pods: dict[str, dict[str, Any]] = {}
    for doc in docs:
        kind = doc["kind"]
        if kind not in _POD_KINDS:
            continue
        if kind == "CronJob":
            template = doc["spec"]["jobTemplate"]["spec"]["template"]
        else:
            template = doc["spec"]["template"]
        pods[f"{kind}/{doc['metadata']['name']}"] = template
    return pods


def test_every_rendered_pod_carries_the_chart_placement(tmp_path: Path) -> None:
    values = _write_values(
        tmp_path, {**_WORKLOADS_ON, "nodeSelector": _PLACEMENT, "tolerations": _TOLERATIONS}
    )
    pods = _pod_templates(_render(values))
    # INVARIANT: the set is not empty and holds every workload this test is about, so a render
    # that lost a workload cannot pass by checking nothing.
    assert _EXPECTED_WORKLOADS <= set(pods), sorted(pods)
    for name, template in pods.items():
        spec = template["spec"]
        assert spec.get("nodeSelector") == _PLACEMENT, name
        assert spec.get("tolerations") == _TOLERATIONS, name


def test_garage_and_migrate_pods_carry_no_affinity(tmp_path: Path) -> None:
    values = _write_values(
        tmp_path, {**_WORKLOADS_ON, "nodeSelector": _PLACEMENT, "affinity": _AFFINITY}
    )
    pods = _pod_templates(_render(values))
    # The top-level affinity is set: the App and the runner pool must receive it.
    assert pods[f"Deployment/{_FULLNAME}"]["spec"].get("affinity") == _AFFINITY
    assert pods[f"Deployment/{_FULLNAME}-runner"]["spec"].get("affinity") == _AFFINITY
    for name in (
        f"StatefulSet/{_FULLNAME}-garage",
        f"StatefulSet/{_FULLNAME}-garage-blobs",
        f"Job/{_FULLNAME}-migrate",
    ):
        assert "affinity" not in pods[name]["spec"], name


def test_default_values_place_no_pod(tmp_path: Path) -> None:
    # Plain chart defaults: nothing is placed.
    for name, template in _pod_templates(_render()).items():
        assert "nodeSelector" not in template["spec"], name
        assert "tolerations" not in template["spec"], name
    # Garage and the migrate Job switched on, placement still at its defaults.
    values = _write_values(tmp_path, _WORKLOADS_ON)
    pods = _pod_templates(_render(values))
    assert _EXPECTED_WORKLOADS <= set(pods), sorted(pods)
    for name, template in pods.items():
        assert "nodeSelector" not in template["spec"], name
        assert "tolerations" not in template["spec"], name

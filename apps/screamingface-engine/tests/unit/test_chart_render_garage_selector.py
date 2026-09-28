"""The App Service never selects the bundled Garage's pods (kind suite finding).

Garage pods used to carry the App's own selector labels (plus a component label), so the App
Service's name+instance selector matched them too — App traffic, and a port-forward to the App,
could land on Garage.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="needs the helm CLI")


def _render() -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "url4-cloud",
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "garage.enabled=true",
            "--set",
            "artifactStorage.backend=s3",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _matches(selector: dict[str, str], labels: dict[str, str]) -> bool:
    return all(labels.get(key) == value for key, value in selector.items())


def test_the_app_service_does_not_select_garage_pods() -> None:
    docs = _render()
    garage = next(
        d for d in docs if d["kind"] == "StatefulSet" and "garage" in d["metadata"]["name"]
    )
    garage_pod_labels = garage["spec"]["template"]["metadata"]["labels"]
    services = [d for d in docs if d["kind"] == "Service"]
    garage_services = [s for s in services if "garage" in s["metadata"]["name"]]
    app_services = [s for s in services if s not in garage_services]
    assert app_services and garage_services
    for service in app_services:
        assert not _matches(service["spec"]["selector"], garage_pod_labels), service["metadata"]
    for service in garage_services:
        assert _matches(service["spec"]["selector"], garage_pod_labels)
    assert _matches(garage["spec"]["selector"]["matchLabels"], garage_pod_labels)


def test_the_garage_selector_is_the_app_identity_plus_the_garage_component() -> None:
    """INVARIANT: the Garage StatefulSet's selector is main's — the chart's name+instance plus
    `component: garage`. WHY: a StatefulSet selector is immutable, so a new one fails the sync
    on every environment that bundles Garage (dev, staging and prod all do), and the platform's
    NetworkPolicies admit App↔Garage traffic by exactly these labels."""
    docs = _render()
    app = next(
        d for d in docs if d["kind"] == "Deployment" and "runner" not in d["metadata"]["name"]
    )
    garage = next(
        d for d in docs if d["kind"] == "StatefulSet" and "garage" in d["metadata"]["name"]
    )
    identity = app["spec"]["selector"]["matchLabels"]
    expected = {**identity, "app.kubernetes.io/component": "garage"}
    assert garage["spec"]["selector"]["matchLabels"] == expected
    assert _matches(expected, garage["spec"]["template"]["metadata"]["labels"])


def test_the_app_service_selects_only_the_control_plane_pods() -> None:
    """WHY the Service and not the Garage selector carries the split: a Service selector is
    mutable, and the App pods already carry `component: control-plane`, so old and new App pods
    both stay selected during the rollout."""
    docs = _render()
    app = next(
        d for d in docs if d["kind"] == "Deployment" and "runner" not in d["metadata"]["name"]
    )
    service = next(
        d for d in docs if d["kind"] == "Service" and "garage" not in d["metadata"]["name"]
    )
    selector = service["spec"]["selector"]
    assert selector.get("app.kubernetes.io/component") == "control-plane"
    assert _matches(selector, app["spec"]["template"]["metadata"]["labels"])

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

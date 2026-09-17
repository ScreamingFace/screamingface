"""The chart probes the endpoints that answer the question each probe asks (OME-942).

Both probes used to target `/healthz`, so `/livez` and `/readyz` were dead surfaces and the
readiness probe could not fail whatever the state of a pod's NATS connection. That is read off
the chart and the endpoint; no incident is claimed here, and none was investigated.

WHY these assertions run against a RENDERED manifest and not `helm lint`: lint reads the
templates without executing them and reports success for a chart that cannot render at all.
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

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render() -> list[dict[str, Any]]:
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


def _app_container(docs: list[dict[str, Any]]) -> dict[str, Any]:
    for doc in docs:
        name = str(doc.get("metadata", {}).get("name", ""))
        if doc.get("kind") == "Deployment" and not name.endswith("-runner"):
            return doc["spec"]["template"]["spec"]["containers"][0]
    raise AssertionError("no App Deployment in the rendered chart")


def test_the_chart_probes_readyz_for_readiness() -> None:
    assert _app_container(_render())["readinessProbe"]["httpGet"]["path"] == "/readyz"


def test_the_chart_probes_livez_for_liveness() -> None:
    assert _app_container(_render())["livenessProbe"]["httpGet"]["path"] == "/livez"


def test_the_two_probes_are_not_the_same_endpoint() -> None:
    """INVARIANT: pointing liveness and readiness at ONE endpoint is what made the readiness
    probe dead config in the first place. They fail differently — liveness restarts the pod,
    readiness only takes it out of rotation — so a broker-aware liveness probe would turn a
    NATS outage into a restart loop across every replica."""
    container = _app_container(_render())

    assert (
        container["livenessProbe"]["httpGet"]["path"]
        != container["readinessProbe"]["httpGet"]["path"]
    )


def test_the_probes_still_target_the_named_http_port() -> None:
    """The endpoints moved; the port they are served on did not."""
    container = _app_container(_render())

    assert container["livenessProbe"]["httpGet"]["port"] == "http"
    assert container["readinessProbe"]["httpGet"]["port"] == "http"

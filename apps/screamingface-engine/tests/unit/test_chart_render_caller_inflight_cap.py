"""The chart renders the per-caller in-flight cap to the App only (OME-1314).

FEATURE (OME-1314): `config.runQueueCallerInflightCap` is the per-caller in-flight cap
(OME-1091) as a chart value. It is rendered to the App ConfigMap only: the App is the process
that admits runs, and the Client reads the enforced value from `GET /v1/limits`. The runner
pool never admits, so it must not receive the variable.

The value is empty by default. An empty value renders no variable, so the App falls back to
the code default (24, OME-1314) and the default render stays byte-identical to origin/main.
A zero cap is refused by the schema, because a cap of zero admits no run at all.

This file keeps its own small render helper; it needs only the App ConfigMap.
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
_KEY = "URL4_CLOUD_RUN_QUEUE_CALLER_INFLIGHT_CAP"


def _render_result(*set_values: str) -> subprocess.CompletedProcess[str]:
    args = [
        "helm",
        "template",
        _RELEASE,
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    for value in set_values:
        args += ["--set", value]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(*set_values: str) -> list[dict[str, Any]]:
    result = _render_result(*set_values)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _app_configmap(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """The App's own ConfigMap — the one that is NOT the runner-env ConfigMap."""
    for doc in docs:
        name = str(doc.get("metadata", {}).get("name", ""))
        if doc.get("kind") == "ConfigMap" and not name.endswith("-runner-env"):
            return doc
    raise AssertionError("no App ConfigMap in the rendered chart")


def _runner_env_configmap(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """The ConfigMap that carries the runner pool's environment."""
    for doc in docs:
        name = str(doc.get("metadata", {}).get("name", ""))
        if doc.get("kind") == "ConfigMap" and name.endswith("-runner-env"):
            return doc
    raise AssertionError("no runner-env ConfigMap in the rendered chart")


def _runner_env(docs: list[dict[str, Any]]) -> dict[str, str]:
    """The runner pool container's explicit `env`, flattened to name -> value."""
    for doc in docs:
        name = str(doc.get("metadata", {}).get("name", ""))
        if doc.get("kind") == "Deployment" and name.endswith("-runner"):
            container = doc["spec"]["template"]["spec"]["containers"][0]
            return {entry["name"]: entry["value"] for entry in container.get("env", [])}
    raise AssertionError("no runner-pool Deployment in the rendered chart")


def _values() -> dict[str, Any]:
    return yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))


def test_the_chart_declares_an_empty_cap() -> None:
    """Empty means the code default. The key must exist so the template can test it."""
    assert _values()["config"]["runQueueCallerInflightCap"] == ""


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_an_empty_cap_renders_no_env_var() -> None:
    """INVARIANT: the default render carries no cap variable, so the App uses the code
    default and the render stays byte-identical to the chart before this value existed."""
    assert _KEY not in _app_configmap(_render())["data"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_a_set_cap_reaches_the_app() -> None:
    docs = _render("config.runQueueCallerInflightCap=30")
    assert _app_configmap(docs)["data"][_KEY] == "30"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_cap_is_app_only() -> None:
    """INVARIANT: the runner pool never admits runs, so the cap is not rendered to it.
    Pinned with a NON-default value, so a template that rendered the variable to both halves
    could not pass by rendering nothing."""
    docs = _render("config.runQueueCallerInflightCap=30")
    assert _KEY not in _runner_env(docs)
    assert _KEY not in _runner_env_configmap(docs).get("data", {})


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_a_zero_cap_is_refused() -> None:
    """A cap of zero admits no run, so the schema refuses it before any template runs."""
    assert _render_result("config.runQueueCallerInflightCap=0").returncode != 0

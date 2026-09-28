"""The chart renders the queue's replica count to BOTH halves (OME-1092).

`Settings.run_queue_replicas` (OME-1088) is read by the App's composition root and the
worker's alike, because both declare the SAME singleton queue stream and `ensure_stream`
refuses a declaration whose properties diverge from an existing one. A chart that rendered the
value to only one half would leave the other on the code default — a startup failure for
whichever half declares second, and one that only appears on a clustered broker.

WHY the default is 1: this chart bundles a SINGLE-NODE NATS subchart, and a single-node broker
refuses `replicas > 1` outright with `ServerError 10074`. A default the chart's own bundled
broker cannot accept is the wrong default — it made every run fail on a kind cluster while the
worker's claim loop retried forever. Raising it for a clustered deployment is a values change
with no code change (owner decision, 2026-09-03; durability work is OME-1093).
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
_KEY = "URL4_CLOUD_RUN_QUEUE_REPLICAS"


def _render(*set_values: str) -> list[dict[str, Any]]:
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
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _app_configmap(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """The App's own ConfigMap — the one that is NOT the runner-env ConfigMap."""
    for doc in docs:
        name = str(doc.get("metadata", {}).get("name", ""))
        if doc.get("kind") == "ConfigMap" and not name.endswith("-runner-env"):
            return doc
    raise AssertionError("no App ConfigMap in the rendered chart")


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


def test_the_chart_defaults_the_replica_count_to_one() -> None:
    """The bundled NATS subchart is single-node, so the default install must be able to
    declare its own queue."""
    assert _values()["config"]["runQueueReplicas"] == 1


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_app_receives_the_replica_count() -> None:
    assert _app_configmap(_render())["data"][_KEY] == "1"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_worker_receives_the_replica_count() -> None:
    assert _runner_env(_render())[_KEY] == "1"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_both_halves_follow_a_configured_replica_count() -> None:
    """INVARIANT: the two halves declare ONE stream, so they must never be rendered a
    different count. Pinned with a NON-default value — rendering only one half still passes a
    test written against the default."""
    docs = _render("config.runQueueReplicas=3")
    assert _app_configmap(docs)["data"][_KEY] == "3"
    assert _runner_env(docs)[_KEY] == "3"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_schema_refuses_a_replica_count_below_one() -> None:
    """A stream has at least one replica. `values.schema.json` rejects it before any template
    runs, which is a better error than the broker's."""
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "config.runQueueReplicas=0",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "a zero replica count must not render"

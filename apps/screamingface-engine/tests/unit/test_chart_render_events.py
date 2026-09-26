"""The chart renders the shared events stream's limits to BOTH halves (uniform executor,
PRD 01 §4).

`Settings.events_max_bytes` (and its siblings) are read by the App's composition root and
the worker's alike, because both declare the SAME singleton events stream and
`ensure_events_stream` refuses a declaration whose properties diverge from an existing one.
A chart that rendered a value to only one half would leave the other on the code default —
a startup failure for whichever half declares second, exactly like `runQueueReplicas`
(`test_chart_render_queue_replicas.py`).
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
_VALUES_KEYS = (
    "events.maxBytes",
    "events.maxMsgsPerSubject",
    "events.maxAgeS",
    "events.replicas",
)


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


def test_the_chart_defaults_match_the_prd() -> None:
    events = _values()["events"]
    assert events["maxBytes"] == 8 * 1024**3
    assert events["maxMsgsPerSubject"] == 20_000
    assert events["maxAgeS"] == 86_400
    assert events["replicas"] == 1


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_app_receives_the_default_events_config() -> None:
    data = _app_configmap(_render())["data"]
    assert data["URL4_CLOUD_EVENTS_MAX_BYTES"] == str(8 * 1024**3)
    assert data["URL4_CLOUD_EVENTS_MAX_MSGS_PER_SUBJECT"] == "20000"
    assert data["URL4_CLOUD_EVENTS_MAX_AGE_S"] == "86400"
    assert data["URL4_CLOUD_EVENTS_REPLICAS"] == "1"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_worker_receives_the_default_events_config() -> None:
    env = _runner_env(_render())
    assert env["URL4_CLOUD_EVENTS_MAX_BYTES"] == str(8 * 1024**3)
    assert env["URL4_CLOUD_EVENTS_MAX_MSGS_PER_SUBJECT"] == "20000"
    assert env["URL4_CLOUD_EVENTS_MAX_AGE_S"] == "86400"
    assert env["URL4_CLOUD_EVENTS_REPLICAS"] == "1"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_overriding_max_bytes_changes_both_halves() -> None:
    """INVARIANT: the two halves declare ONE stream, so a configured limit must never be
    rendered a different value to each. Pinned with a NON-default value, and one large enough
    to expose the float64-scientific-notation hazard (`deployment-node.yaml`'s equivalent
    fix): rendering only one half, or the wrong format, still passes a test written against
    the default."""
    docs = _render("events.maxBytes=17179869184")  # 16 GiB
    assert _app_configmap(docs)["data"]["URL4_CLOUD_EVENTS_MAX_BYTES"] == "17179869184"
    assert _runner_env(docs)["URL4_CLOUD_EVENTS_MAX_BYTES"] == "17179869184"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_overriding_every_events_value_changes_both_halves() -> None:
    docs = _render(
        "events.maxMsgsPerSubject=5000",
        "events.maxAgeS=3600",
        "events.replicas=1",
    )
    app_data = _app_configmap(docs)["data"]
    worker_env = _runner_env(docs)
    assert app_data["URL4_CLOUD_EVENTS_MAX_MSGS_PER_SUBJECT"] == "5000"
    assert worker_env["URL4_CLOUD_EVENTS_MAX_MSGS_PER_SUBJECT"] == "5000"
    assert app_data["URL4_CLOUD_EVENTS_MAX_AGE_S"] == "3600"
    assert worker_env["URL4_CLOUD_EVENTS_MAX_AGE_S"] == "3600"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_schema_refuses_a_zero_max_bytes() -> None:
    """The store has at least one byte. `values.schema.json` rejects it before any template
    runs, which is a better error than the broker's own (erd.md §5 EV-D9)."""
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "events.maxBytes=0",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "a zero maxBytes must not render"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_schema_rejects_an_unknown_events_key() -> None:
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "events.bogus=1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "an unknown events.* key must not render"


def test_the_readme_documents_the_alert_and_the_purge_command() -> None:
    readme = (_CHART / "README.md").read_text(encoding="utf-8")
    assert "screamingface_engine_events_store_utilization_ratio > 0.8" in readme
    assert "purge-legacy-streams" in readme
    for key in _VALUES_KEYS:
        assert key in readme

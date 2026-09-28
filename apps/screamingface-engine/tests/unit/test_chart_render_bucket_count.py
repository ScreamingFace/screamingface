"""The chart renders the queue's bucket count to BOTH halves (OME-1092).

`Settings.run_queue_bucket_count` (OME-1091) is the ONE queue property that must agree
between the App and the worker: the App publishes into `bucket_subject()` and the worker
polls `bucket_subjects()`. The chart rendered it to NEITHER, so the two agreed only by both
falling back to the same code default — an operator who raised it on the App (env is the only
path) published runs into buckets no worker ever polls.

WHY that is worse than the replica-count drift this file is modelled on: a divergent replica
count FAILS, loudly, at `ensure_stream`. A divergent bucket count succeeds at every step —
the run is accepted with a 202, sits in a bucket nobody visits, and expires silently at
`run_queue_max_age_s`. One value rendered to both halves is what makes the disagreement
unexpressible.

Self-contained helpers rather than imports from the sibling chart-render module: the
append-only rule means each cycle brings its own, so a later edit here cannot break a prior
file.
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
_KEY = "URL4_CLOUD_RUN_QUEUE_BUCKET_COUNT"


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


def test_the_chart_declares_a_bucket_count() -> None:
    """The value must exist for either half to be rendered from it."""
    assert _values()["config"]["runQueueBucketCount"] >= 1


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_app_receives_the_bucket_count() -> None:
    assert _app_configmap(_render())["data"][_KEY]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_worker_receives_the_bucket_count() -> None:
    assert _runner_env(_render())[_KEY]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_both_halves_follow_a_configured_bucket_count() -> None:
    """INVARIANT: the publisher and the poller must never be rendered a different count.
    Pinned with a NON-default value — rendering only one half still passes a test written
    against the default, which is exactly how this stayed invisible."""
    docs = _render("config.runQueueBucketCount=8")
    assert _app_configmap(docs)["data"][_KEY] == "8"
    assert _runner_env(docs)[_KEY] == "8"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_schema_refuses_a_bucket_count_below_one() -> None:
    """Zero is the modulus of `bucket_subject`'s hash, so it is a `ZeroDivisionError` on
    every `schedule()`. `Settings` refuses it too; the schema refuses it before any template
    runs, which is the earlier and cheaper of the two."""
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "config.runQueueBucketCount=0",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "a zero bucket count must not render"

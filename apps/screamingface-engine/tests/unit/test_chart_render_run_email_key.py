"""The chart gives the App, and only the App, the key that seals each Run's owner email
(OME-1837, E5 P2 spec R16).

WHY render rather than read the template text: see `test_chart_render_tracing.py`.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm"
_RELEASE = "url4-cloud"
_NATS = "config.natsUrl=nats://nats.example:4222"
_RUNS_ON = "database.existingSecret=engine-db"
_KEY_VAR = "URL4_CLOUD_RUN_EMAIL_KEY"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*settings: str) -> list[dict[str, Any]]:
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _deployment(docs: list[dict[str, Any]], component: str) -> dict[str, Any]:
    for doc in docs:
        if doc["kind"] != "Deployment":
            continue
        if (component == "runner") == doc["metadata"]["name"].endswith("-runner"):
            return doc
    raise AssertionError(f"no {component} Deployment rendered")


def _env(deployment: dict[str, Any]) -> dict[str, Any]:
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return {entry["name"]: entry for entry in container.get("env", [])}


def _secrets(docs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {doc["metadata"]["name"]: doc for doc in docs if doc["kind"] == "Secret"}


def test_with_runs_on_the_chart_generates_a_32_byte_key_for_the_app() -> None:
    docs = _render(_RUNS_ON)

    ref = _env(_deployment(docs, "app"))[_KEY_VAR]["valueFrom"]["secretKeyRef"]
    secret = _secrets(docs)[ref["name"]]
    assert ref["key"] == _KEY_VAR
    assert len(base64.b64decode(secret["stringData"][_KEY_VAR], validate=True)) == 32


def test_an_operators_own_secret_is_used_and_none_is_generated() -> None:
    docs = _render(
        _RUNS_ON, "database.emailKey.existingSecret=my-key", "database.emailKey.existingSecretKey=k"
    )

    ref = _env(_deployment(docs, "app"))[_KEY_VAR]["valueFrom"]["secretKeyRef"]
    assert (ref["name"], ref["key"]) == ("my-key", "k")
    assert not any(name.endswith("-run-email-key") for name in _secrets(docs))


def test_with_runs_off_there_is_no_key() -> None:
    docs = _render()

    assert _KEY_VAR not in _env(_deployment(docs, "app"))
    assert not any(name.endswith("-run-email-key") for name in _secrets(docs))


def test_the_runner_pool_never_sees_the_key() -> None:
    """INVARIANT (spec R16): only the App opens an owner's email; a runner gets it in its start."""
    runner = _deployment(_render(_RUNS_ON), "runner")

    assert _KEY_VAR not in _env(runner)
    assert "run-email-key" not in yaml.safe_dump(runner)


def test_a_key_name_set_without_a_secret_still_reads_the_generated_one() -> None:
    """Review round 4: the chart's own Secret always holds `URL4_CLOUD_RUN_EMAIL_KEY`, so the
    App reads that name from it whatever `existingSecretKey` says."""
    docs = _render(_RUNS_ON, "database.emailKey.existingSecretKey=run-key")

    ref = _env(_deployment(docs, "app"))[_KEY_VAR]["valueFrom"]["secretKeyRef"]
    assert ref["key"] == _KEY_VAR
    assert _KEY_VAR in _secrets(docs)[ref["name"]]["stringData"]


def test_the_generated_key_outlives_an_uninstall_and_the_app_rolls_when_it_changes() -> None:
    """Review round 4: losing the key strands every Run in flight (spec R16), so `helm
    uninstall` keeps the Secret, and the App's pods carry its checksum, so a changed key rolls
    them all together instead of leaving pods on two keys."""
    docs = _render(_RUNS_ON)
    app = _deployment(docs, "app")
    ref = _env(app)[_KEY_VAR]["valueFrom"]["secretKeyRef"]
    secret = _secrets(docs)[ref["name"]]

    assert secret["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
    assert "checksum/run-email-key" in app["spec"]["template"]["metadata"]["annotations"]

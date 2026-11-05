"""The chart turns Runs on with a database Secret, and ships the outcome stream's limits
(OME-1785, E5 P1 spec D2, R9, R11).

WHY render rather than read the template text: see `test_chart_render_tracing.py`.
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
_NATS = "config.natsUrl=nats://nats.example:4222"
_SECRET = "database.existingSecret=engine-db"
_DATABASE_VAR = "URL4_CLOUD_DATABASE_URL"

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
        name = doc["metadata"]["name"]
        if (component == "runner") == name.endswith("-runner"):
            return doc
    raise AssertionError(f"no {component} Deployment rendered")


def _container(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]["containers"][0]


def _env(container: dict[str, Any]) -> dict[str, Any]:
    return {entry["name"]: entry for entry in container.get("env", [])}


def _jobs(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [doc for doc in docs if doc["kind"] == "Job"]


def test_without_a_secret_there_is_no_database_and_no_migrate_job() -> None:
    """Spec D2: the chart installs before the database exists, and the App runs with Runs off."""
    docs = _render()

    assert _DATABASE_VAR not in _env(_container(_deployment(docs, "app")))
    assert _jobs(docs) == []


def test_the_secret_reaches_the_app_as_a_required_reference() -> None:
    """WHY required: the migrate Job's reference is, so a named Secret that does not exist
    fails the release in both places instead of silently leaving Runs off."""
    entry = _env(_container(_deployment(_render(_SECRET), "app")))[_DATABASE_VAR]

    ref = entry["valueFrom"]["secretKeyRef"]
    assert (ref["name"], ref["key"]) == ("engine-db", "database-url")
    assert "optional" not in ref


def test_the_runner_pool_never_sees_the_database() -> None:
    """INVARIANT (spec D3): every database write is the App's, so the runners hold no URL."""
    runner = _deployment(_render(_SECRET), "runner")
    container = _container(runner)

    assert _DATABASE_VAR not in _env(container)
    assert "engine-db" not in yaml.safe_dump(runner)


def test_the_migrate_job_runs_before_install_and_upgrade() -> None:
    (job,) = _jobs(_render(_SECRET))

    hooks = job["metadata"]["annotations"]["helm.sh/hook"]
    assert hooks == "pre-install,pre-upgrade"
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == [
        "python",
        "-m",
        "tortoise",
        "-c",
        "screamingface_engine.runs.db.TORTOISE_CONFIG",
        "migrate",
    ]
    ref = _env(container)[_DATABASE_VAR]["valueFrom"]["secretKeyRef"]
    assert (ref["name"], ref["key"]) == ("engine-db", "database-url")


def test_a_custom_secret_key_is_used_everywhere() -> None:
    docs = _render(_SECRET, "database.existingSecretKey=dsn")

    app_ref = _env(_container(_deployment(docs, "app")))[_DATABASE_VAR]["valueFrom"]
    (job,) = _jobs(docs)
    job_ref = _env(job["spec"]["template"]["spec"]["containers"][0])[_DATABASE_VAR]["valueFrom"]
    assert app_ref["secretKeyRef"]["key"] == job_ref["secretKeyRef"]["key"] == "dsn"


def test_the_outcome_stream_limits_reach_both_halves() -> None:
    """Spec R11: the App and the runner pool each apply their own values at startup, so both
    must render from the same ones."""
    docs = _render("candidateOutcomes.maxAgeS=7200", "candidateOutcomes.maxBytes=1048576")

    configmap = next(
        doc
        for doc in docs
        if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == (f"{_RELEASE}-{_RELEASE}")
    )
    runner = _env(_container(_deployment(docs, "runner")))
    for name, value in (
        ("URL4_CLOUD_CANDIDATE_OUTCOMES_MAX_AGE_S", "7200"),
        ("URL4_CLOUD_CANDIDATE_OUTCOMES_MAX_BYTES", "1048576"),
    ):
        assert configmap["data"][name] == value
        assert runner[name]["value"] == value


def test_an_outcome_max_age_the_lost_cutoff_cannot_outlast_is_refused() -> None:
    """WHY: the App and the runner pool would refuse to start on it (`run_lost_after_s`, 48 h)."""
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    args += ["--set", "candidateOutcomes.maxAgeS=172800"]

    result = subprocess.run(args, capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert "maxAgeS" in result.stderr


def test_the_migrate_job_names_its_component_once() -> None:
    """WHY the raw text: a YAML parser keeps the last of two equal keys, but a strict one, such
    as the GitOps controller's, refuses the manifest."""
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS, "--set", _SECRET]
    rendered = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    (job_text,) = [doc for doc in rendered.split("\n---") if "\nkind: Job\n" in doc]
    labels = job_text.split("\n  labels:\n", 1)[1].split("\n  annotations:", 1)[0]

    assert labels.count("app.kubernetes.io/component:") == 1
    assert "app.kubernetes.io/component: migrate" in labels

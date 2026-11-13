"""E5 P2 spec D9a and §8: the chart gives the App and the runner pool one run-results store.

FEATURE: a detached Run (OME-1837). With Runs on, every result of a driver-started run and each
Run's context live in a bucket of their own, kept for the Run's 30 days.

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
_FULLNAME = "url4-cloud-url4-cloud"
_NATS = "config.natsUrl=nats://nats.example:4222"
_RUNS_ON = "database.existingSecret=engine-db"
_ACCESS, _SECRET = "URL4_CLOUD_RUN_RESULTS_S3_ACCESS_KEY", "URL4_CLOUD_RUN_RESULTS_S3_SECRET_KEY"
_STORE_KEYS = (
    "URL4_CLOUD_RUN_RESULTS_STORE",
    "URL4_CLOUD_RUN_RESULTS_S3_ENDPOINT_URL",
    "URL4_CLOUD_RUN_RESULTS_S3_BUCKET",
    "URL4_CLOUD_RUN_RESULTS_S3_REGION",
)

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _helm(*settings: str) -> subprocess.CompletedProcess[str]:
    args = ["helm", "template", _RELEASE, str(_CHART), "--set-string", _NATS]
    for setting in settings:
        args += ["--set", setting]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _render(*settings: str) -> list[dict[str, Any]]:
    result = _helm(*settings)
    assert result.returncode == 0, result.stderr
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _named(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any] | None:
    return next(
        (doc for doc in docs if doc["kind"] == kind and doc["metadata"]["name"] == name), None
    )


def _config(docs: list[dict[str, Any]], suffix: str) -> dict[str, str]:
    for doc in docs:
        if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == f"{_FULLNAME}{suffix}":
            return doc["data"]
    raise AssertionError(f"no ConfigMap {_FULLNAME}{suffix}")


def _container_env(docs: list[dict[str, Any]], runner: bool) -> dict[str, Any]:
    for doc in docs:
        if doc["kind"] == "Deployment" and doc["metadata"]["name"].endswith("-runner") == runner:
            container = doc["spec"]["template"]["spec"]["containers"][0]
            return {entry["name"]: entry for entry in container.get("env", [])}
    raise AssertionError("no such Deployment")


def _secret_of(env: dict[str, Any], key: str) -> str:
    return env[key]["valueFrom"]["secretKeyRef"]["name"]


def test_with_runs_off_there_is_no_store() -> None:
    docs = _render()

    assert not any(key in _config(docs, "") for key in _STORE_KEYS)
    assert _named(docs, "StatefulSet", f"{_FULLNAME}-garage-run-results") is None
    assert _named(docs, "Secret", f"{_FULLNAME}-run-results-storage") is None
    assert _ACCESS not in _container_env(docs, runner=False)


def test_with_runs_on_both_halves_read_one_store_on_the_bundled_garage() -> None:
    """INVARIANT (D9a): the runners write where the App reads."""
    docs = _render(_RUNS_ON)
    app, pool = _config(docs, ""), _config(docs, "-runner-env")

    assert {key: app[key] for key in _STORE_KEYS} == {key: pool[key] for key in _STORE_KEYS}
    assert app["URL4_CLOUD_RUN_RESULTS_STORE"] == "s3"
    assert app["URL4_CLOUD_RUN_RESULTS_S3_ENDPOINT_URL"] == (
        f"http://{_FULLNAME}-garage-run-results:3900"
    )
    garage = _named(docs, "StatefulSet", f"{_FULLNAME}-garage-run-results")
    assert garage is not None
    labels = garage["spec"]["template"]["metadata"]["labels"]
    assert labels["app.kubernetes.io/component"] == "garage-run-results"
    assert _named(docs, "Secret", f"{_FULLNAME}-run-results-storage") is not None


def test_the_garage_rpc_secret_reaches_no_engine_process() -> None:
    docs = _render(_RUNS_ON)

    for runner in (False, True):
        env = _container_env(docs, runner)
        assert _secret_of(env, _ACCESS) == f"{_FULLNAME}-run-results-storage"
        assert _secret_of(env, _SECRET) == f"{_FULLNAME}-run-results-storage"
        assert "GARAGE_RPC_SECRET" not in env


def test_the_runner_pool_may_have_a_write_only_key_of_its_own() -> None:
    """§8: a runner never reads a result back, so its key may only write."""
    docs = _render(
        _RUNS_ON,
        "runResults.storage.s3.endpointUrl=https://s3.example",
        "runResults.storage.s3.existingSecret=run-results-app",
        "runResults.storage.s3.poolExistingSecret=run-results-pool",
    )

    assert _secret_of(_container_env(docs, runner=False), _SECRET) == "run-results-app"
    assert _secret_of(_container_env(docs, runner=True), _SECRET) == "run-results-pool"
    assert _named(docs, "StatefulSet", f"{_FULLNAME}-garage-run-results") is None
    assert _named(docs, "Secret", f"{_FULLNAME}-run-results-storage") is None


def test_a_pool_key_of_its_own_on_the_bundled_garage_refuses_to_render() -> None:
    """The bundled Garage adopts one key pair, so a pool key of its own would get 403 on every
    write, failing every run at its probe."""
    result = _helm(_RUNS_ON, "runResults.storage.s3.poolExistingSecret=run-results-pool")

    assert result.returncode != 0
    assert "runResults.storage.s3.poolExistingSecret" in result.stderr


def test_runs_on_without_a_store_refuses_to_render() -> None:
    result = _helm(_RUNS_ON, "runResults.storage.backend=")

    assert result.returncode != 0
    assert "runResults.storage.backend" in result.stderr


def test_an_external_store_without_credentials_refuses_to_render() -> None:
    result = _helm(_RUNS_ON, "runResults.storage.s3.endpointUrl=https://s3.example")

    assert result.returncode != 0
    assert "runResults.storage.s3.existingSecret" in result.stderr


def test_the_runner_pool_gets_its_write_budget() -> None:
    docs = _render(_RUNS_ON, "runResults.writeBudgetS=90")

    assert _config(docs, "-runner-env")["URL4_CLOUD_RUN_RESULT_WRITE_BUDGET_S"] == "90"

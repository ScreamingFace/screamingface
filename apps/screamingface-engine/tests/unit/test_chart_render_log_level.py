"""The chart renders the app log level to BOTH halves (OME-942).

`logs.configure()` reads `URL4_CLOUD_LOG_LEVEL` and nothing in the chart ever set it, so no
deployed pod could be turned to DEBUG — the one control an operator reaches for during an
incident, declared in code and unreachable from a deployment.

WHY both halves: the App and the runner pool both run `screamingface_engine` code through
`cli.main`, which calls `configure_logging()` for every mode. A level rendered only to the App
would leave the worker pods — the ones carrying OME-1069's per-run log context, which is the
only view of a run that is not the CloudEvents stream — permanently at INFO.

WHY these assertions run against a RENDERED manifest and not `helm lint`: lint reads the
templates without executing them, so it reports success for a chart that cannot render at all.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from screamingface_engine.logs import DEFAULT_LEVEL, LEVEL_ENV

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "deploy" / "helm"
_RELEASE = "url4-cloud"


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


def _configmap(docs: list[dict[str, Any]], *, runner: bool) -> dict[str, str]:
    """The App's ConfigMap, or the runner pool's `-runner-env` one, as name -> value."""
    for doc in docs:
        name = str(doc.get("metadata", {}).get("name", ""))
        if doc.get("kind") != "ConfigMap":
            continue
        if name.endswith("-runner-env") is runner:
            return dict(doc["data"])
    raise AssertionError(f"no {'runner-env' if runner else 'App'} ConfigMap in the rendered chart")


def _values() -> dict[str, Any]:
    return yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))


def test_the_chart_declares_the_code_default_as_its_default() -> None:
    """INVARIANT: charting a knob must not silently change the level a deployment runs at.
    The chart's default is the code's `DEFAULT_LEVEL`, read from the module rather than
    restated, so a change to one that is not made in the other fails here."""
    assert _values()["config"]["logLevel"] == DEFAULT_LEVEL


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_app_receives_the_log_level() -> None:
    assert _configmap(_render(), runner=False)[LEVEL_ENV] == DEFAULT_LEVEL


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_runner_pool_receives_the_log_level() -> None:
    assert _configmap(_render(), runner=True)[LEVEL_ENV] == DEFAULT_LEVEL


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_turning_a_deployment_to_debug_reaches_both_halves() -> None:
    """STORY: as the operator debugging a dropped run stream, I set one value and BOTH the
    control plane and the worker that ran it start saying what they are doing.

    Pinned with a NON-default value deliberately: an assertion made against the default passes
    against a chart that renders the key to only one half, or hard-codes it."""
    docs = _render("config.logLevel=DEBUG")
    assert _configmap(docs, runner=False)[LEVEL_ENV] == "DEBUG"
    assert _configmap(docs, runner=True)[LEVEL_ENV] == "DEBUG"


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_the_schema_refuses_a_level_python_logging_does_not_know() -> None:
    """`logging` resolves an unknown level name to... nothing: `setLevel("VERBOSE")` raises at
    boot, inside the handler install, and the pod crashloops with a traceback that names the
    logging module rather than the values file. The schema rejects it before any template runs."""
    result = subprocess.run(
        [
            "helm",
            "template",
            _RELEASE,
            str(_CHART),
            "--set-string",
            "config.natsUrl=nats://nats.example:4222",
            "--set",
            "config.logLevel=VERBOSE",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "a level `logging` cannot resolve must not render"

"""The chart renders the unclaimed-run warning grace into the App's ConfigMap (under OME-1086).

`Settings.unclaimed_run_warn_s` is read only by the App (the warner runs in the control plane),
so only the App ConfigMap carries it — the runner pool never reads it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from screamingface_engine.config import Settings

_CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm"
_RELEASE = "url4-cloud"
_KEY = "URL4_CLOUD_UNCLAIMED_RUN_WARN_S"

needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _helm(*set_values: str) -> subprocess.CompletedProcess[str]:
    args = ["helm", "template", _RELEASE, str(_CHART)]
    args += ["--set-string", "config.natsUrl=nats://nats.example:4222"]
    for value in set_values:
        args += ["--set", value]
    return subprocess.run(args, capture_output=True, text=True)


def _app_configmap(*set_values: str) -> dict[str, Any]:
    result = _helm(*set_values)
    assert result.returncode == 0, result.stderr
    for doc in yaml.safe_load_all(result.stdout):
        name = str((doc or {}).get("metadata", {}).get("name", ""))
        if doc and doc.get("kind") == "ConfigMap" and not name.endswith("-runner-env"):
            return doc
    raise AssertionError("no App ConfigMap in the rendered chart")


def test_the_chart_default_matches_the_code_default() -> None:
    """One default, stated twice: a chart value that drifted from the code would silently
    decide every hosted deployment's bound."""
    values = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
    code_default = Settings.model_fields["unclaimed_run_warn_s"].default
    assert values["config"]["unclaimedRunWarnS"] == code_default


@needs_helm
def test_the_app_receives_the_default() -> None:
    assert _app_configmap()["data"][_KEY] == "300"


@needs_helm
def test_the_app_follows_a_configured_value() -> None:
    # Pinned with a NON-default value, so a template that hardcodes the default cannot pass.
    assert _app_configmap("config.unclaimedRunWarnS=900")["data"][_KEY] == "900"


@needs_helm
def test_the_schema_refuses_a_negative_value() -> None:
    assert _helm("config.unclaimedRunWarnS=-1").returncode != 0

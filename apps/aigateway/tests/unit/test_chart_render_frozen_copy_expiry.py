"""The chart sets the expiry time of a sealed frozen copy that no Score claims
(OME-1947, prd/copy-sweep.md S-37).

WHY this file exists: a chart that does not set the variable, or sets a name the code does not
read, is silently inert: every gate passes and the sweep expires with a default nobody chose.
This test renders the chart and feeds the rendered ConfigMap into `Settings`, so the chart and
the code must agree on the variable name.

AIDEV-NOTE: needs `helm` on PATH. The skipif guard matches the sibling chart tests. GitHub's
`ubuntu-latest` ships helm, so these run on the merge gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from aigateway.config import Settings

_APP_ROOT = Path(__file__).resolve().parents[2]
_CHART = _APP_ROOT / "charts" / "aigateway"
_PROD_VALUES = _CHART / "values-prod.yaml"
_VAR = "AIGW_FROZEN_COPY_UNCLAIMED_TTL_SECONDS"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _config_data(
    tmp_path: Path, values: dict[str, Any] | None = None, *, prod: bool = False
) -> dict[str, str]:
    base: dict[str, Any] = {
        "database": {"existingSecret": "db-secret"},
        "auth": {"existingSecret": "auth-secret"},
    }
    if values:
        base.update(values)
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump(base))
    args = ["helm", "template", "aigw", str(_CHART)]
    if prod:
        args += ["--values", str(_PROD_VALUES)]
    args += ["--values", str(values_file)]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    config = next(doc for doc in docs if doc["kind"] == "ConfigMap")
    deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert {"configMapRef": {"name": config["metadata"]["name"]}} in container["envFrom"]
    return config["data"]


def _settings_from(data: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.delenv(_VAR, raising=False)
    for key, value in data.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_the_chart_default_is_30_days_and_reaches_the_settings(tmp_path, monkeypatch):
    data = _config_data(tmp_path)
    assert data[_VAR] == "2592000"

    settings = _settings_from(data, monkeypatch)
    assert settings.frozen_copy_unclaimed_ttl_seconds == 2592000


def test_a_value_from_a_values_file_reaches_the_settings(tmp_path, monkeypatch):
    data = _config_data(tmp_path, {"config": {"frozenCopyUnclaimedTtlSeconds": 15552000}})
    assert data[_VAR] == "15552000"

    settings = _settings_from(data, monkeypatch)
    assert settings.frozen_copy_unclaimed_ttl_seconds == 15552000


def test_the_prod_values_keep_the_chart_default(tmp_path):
    assert _config_data(tmp_path, prod=True)[_VAR] == "2592000"


def test_the_value_is_a_key_of_config_and_not_of_the_sweep_block():
    values = yaml.safe_load((_CHART / "values.yaml").read_text())
    assert values["config"]["frozenCopyUnclaimedTtlSeconds"] == 2592000
    assert "frozenCopyUnclaimedTtlSeconds" not in values["config"]["frozenCopySweep"]

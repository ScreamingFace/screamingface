"""The chart sets the frozen copy retention sweep settings (OME-1947).

WHY this file exists: the gateway reads three variables for the sweep. A chart that does not
set them, or sets a variable the code does not read, is silently inert: every gate passes and
the sweep runs with defaults nobody chose. This test renders the chart and feeds the rendered
ConfigMap into `Settings`, so the chart and the code must agree on the variable names.

WHY there is no switch: the sweep has no enable flag, no date setting and no approval step.
The chart must not add one. See prd/copy-sweep.md section 4.1.

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
_VARS = (
    "AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS",
    "AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS",
    "AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES",
)

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
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)
    for key, value in data.items():
        monkeypatch.setenv(key, value)
    return Settings()


def test_the_chart_defaults_reach_the_settings(tmp_path, monkeypatch):
    data = _config_data(tmp_path)
    assert data["AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS"] == "3600"
    assert data["AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS"] == "86400"
    assert data["AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES"] == "100000"

    settings = _settings_from(data, monkeypatch)
    assert settings.frozen_copy_sweep_interval_seconds == 3600
    assert settings.frozen_copy_open_idle_seconds == 86400
    assert settings.frozen_copy_sweep_max_entries == 100000


def test_large_values_from_a_values_file_render_as_plain_integers(tmp_path, monkeypatch):
    # Helm deep-merges this partial `config` with the chart defaults.
    data = _config_data(
        tmp_path,
        {
            "config": {
                "frozenCopySweep": {
                    "intervalSeconds": 7200,
                    "openIdleSeconds": 172800,
                    "maxEntries": 1000000,
                }
            }
        },
    )
    assert data["AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES"] == "1000000"
    assert data["AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS"] == "172800"
    assert data["AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS"] == "7200"

    settings = _settings_from(data, monkeypatch)
    assert settings.frozen_copy_sweep_max_entries == 1000000
    assert settings.frozen_copy_open_idle_seconds == 172800
    assert settings.frozen_copy_sweep_interval_seconds == 7200


def test_the_prod_values_keep_the_chart_defaults(tmp_path):
    data = _config_data(tmp_path, prod=True)
    assert data["AIGW_FROZEN_COPY_SWEEP_INTERVAL_SECONDS"] == "3600"
    assert data["AIGW_FROZEN_COPY_OPEN_IDLE_SECONDS"] == "86400"
    assert data["AIGW_FROZEN_COPY_SWEEP_MAX_ENTRIES"] == "100000"


def test_the_chart_has_no_switch_and_no_date_for_the_sweep(tmp_path):
    data = _config_data(tmp_path)
    assert [k for k in data if "FROZEN_COPY" in k and ("ENABLED" in k or k.endswith("_FROM"))] == []

    values = yaml.safe_load((_CHART / "values.yaml").read_text())
    sweep_values = values["config"]["frozenCopySweep"]
    assert set(sweep_values) == {"intervalSeconds", "openIdleSeconds", "maxEntries"}

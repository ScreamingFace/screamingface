"""The chart sets the claim list of the frozen copy claim route (OME-1947, contracts K4).

WHY this file exists: a chart that does not set the variable, or that sets a name the code does
not read, keeps the claim route at 503 and every gate passes. This test renders the chart and
gives the rendered ConfigMap to `Settings`, so the chart and the code must agree on the name.

AIDEV-NOTE: needs `helm` on PATH. The skipif guard matches the sibling chart tests.
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
_VAR = "AIGW_FROZEN_COPY_CLAIM_EMAILS"
_SCOREBOARD_PEER: dict[str, Any] = {
    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "scoreboard"}},
    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "scoreboard"}},
}

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(tmp_path: Path, values: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    base: dict[str, Any] = {
        "database": {"existingSecret": "db-secret"},
        "auth": {"existingSecret": "auth-secret"},
    }
    if values:
        base.update(values)
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump(base))
    args = ["helm", "template", "aigw", str(_CHART), "--values", str(values_file)]
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _config_data(tmp_path: Path, values: dict[str, Any] | None = None) -> dict[str, str]:
    docs = _render(tmp_path, values)
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


def test_the_default_renders_the_key_with_an_empty_value(tmp_path, monkeypatch):
    data = _config_data(tmp_path)
    assert data[_VAR] == ""

    settings = _settings_from(data, monkeypatch)
    assert settings.frozen_copy_claim_emails == frozenset()


def test_a_list_renders_with_commas_and_reads_as_a_lower_case_set(tmp_path, monkeypatch):
    data = _config_data(
        tmp_path,
        {"config": {"frozenCopyClaimEmails": ["Scoreboard@OpenMined.org", "ops@example.test"]}},
    )
    assert data[_VAR] == "Scoreboard@OpenMined.org,ops@example.test"

    settings = _settings_from(data, monkeypatch)
    assert settings.frozen_copy_claim_emails == frozenset(
        {"scoreboard@openmined.org", "ops@example.test"}
    )


def test_the_claim_list_is_a_config_key_and_not_in_the_sweep_block():
    values = yaml.safe_load((_CHART / "values.yaml").read_text())
    assert values["config"]["frozenCopyClaimEmails"] == []
    assert "frozenCopyClaimEmails" not in values["config"]["frozenCopySweep"]


def test_a_scoreboard_allow_from_element_renders_as_one_from_element(tmp_path):
    docs = _render(tmp_path, {"networkPolicy": {"allowFrom": [_SCOREBOARD_PEER]}})
    policy = next(
        d
        for d in docs
        if d["kind"] == "NetworkPolicy" and d["metadata"]["name"] == "aigw-aigateway"
    )
    peers = policy["spec"]["ingress"][0]["from"]
    assert peers.count(_SCOREBOARD_PEER) == 1
    assert {"namespaceSelector": _SCOREBOARD_PEER["namespaceSelector"]} not in peers
    assert {"podSelector": _SCOREBOARD_PEER["podSelector"]} not in peers

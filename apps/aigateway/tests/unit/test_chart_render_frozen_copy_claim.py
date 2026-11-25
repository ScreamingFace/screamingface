"""The chart parts of the frozen copy claim route (OME-1947, contracts K4).

WHY this file exists: the claim route has no address list (owner decision 2026-11-25). The chart
must not render the removed variable, and `Settings` must not read it. The scoreboard reaches the
gateway through one `networkPolicy.allowFrom` element; this file renders that element.

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
_REMOVED_VAR = "AIGW_FROZEN_COPY_CLAIM_EMAILS"
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


def test_the_chart_renders_no_claim_address_key(tmp_path):
    data = _config_data(tmp_path)

    assert _REMOVED_VAR not in data


def test_the_values_have_no_claim_address_list():
    values = yaml.safe_load((_CHART / "values.yaml").read_text())

    assert "frozenCopyClaimEmails" not in values["config"]
    assert "frozenCopyClaimEmails" not in values["config"]["frozenCopySweep"]


def test_settings_has_no_claim_address_list(monkeypatch):
    # WHY set the old variable: a ConfigMap from an older release may still carry it.
    monkeypatch.setenv(_REMOVED_VAR, "scoreboard@openmined.org")

    settings = Settings()

    assert not hasattr(settings, "frozen_copy_claim_emails")
    assert "frozen_copy_claim_emails" not in Settings.model_fields


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

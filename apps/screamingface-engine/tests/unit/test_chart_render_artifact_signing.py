"""DEC-3 / DC-D3: the artifact-signing key follows the configuration, not the node tier.

The App signs a mount result's 303 (over 1 MiB) and verifies it, so the key reaches the App
whenever one is configured — and nothing is rendered or mounted when none is (MC-D9 then streams
such a result inline).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART = Path(__file__).resolve().parents[2] / "deploy" / "helm"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="needs the helm CLI")


def _render(*sets: str) -> list[dict[str, Any]]:
    args = [
        "helm",
        "template",
        "url4-cloud",
        str(_CHART),
        "--set-string",
        "config.natsUrl=nats://nats.example:4222",
    ]
    for value in sets:
        args += ["--set", value]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def _app(docs: list[dict[str, Any]]) -> dict[str, Any]:
    return next(
        d
        for d in docs
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "url4-cloud-url4-cloud"
    )


def _signing_secret_refs(deployment: dict[str, Any]) -> list[str]:
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    return [ref["secretRef"]["name"] for ref in container.get("envFrom", []) if "secretRef" in ref]


def test_signing_secret_renders_without_node_block() -> None:
    docs = _render("artifactSigning.signingKey=k" + "0" * 63)
    secret = next(
        d
        for d in docs
        if d["kind"] == "Secret" and d["metadata"]["name"].endswith("artifact-signing")
    )
    assert "URL4_CLOUD_ARTIFACT_SIGNING_KEY" in secret["stringData"]
    assert secret["metadata"]["name"] in _signing_secret_refs(_app(docs))


def test_an_existing_secret_reaches_the_app_and_nothing_is_rendered() -> None:
    docs = _render("artifactSigning.existingSecret=my-signing")
    assert not [
        d
        for d in docs
        if d["kind"] == "Secret" and d["metadata"]["name"].endswith("artifact-signing")
    ]
    assert "my-signing" in _signing_secret_refs(_app(docs))


def test_no_key_configured_renders_and_mounts_nothing() -> None:
    docs = _render()
    assert not [
        d
        for d in docs
        if d["kind"] == "Secret" and d["metadata"]["name"].endswith("artifact-signing")
    ]
    assert not [n for n in _signing_secret_refs(_app(docs)) if n.endswith("artifact-signing")]

"""The forwarder's STARTUP wiring: the mount set and digest derive from the world file (C2).

Separate from `test_forwarder.py` because this test drives the real lifespan (TestClient) and is
therefore synchronous; the forwarder behaviour tests are async and carry a module-level asyncio
mark. The derivation itself has no network hop, so the mount set is a fact about the declaration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from screamingface_engine import job_env
from screamingface_engine.app import _install_forwarder, create_app
from screamingface_engine.config import Settings

_REPO_CONFIG = Path(__file__).resolve().parents[2] / "url4.toml"


def test_install_forwarder_derives_the_mount_set_and_digest_at_startup() -> None:
    """AC12/erd §2: at startup the App learns its forwardable paths and the config digest."""
    settings = Settings(jwt_secret="s" * 32, node_base_url="http://node.test")
    app = create_app(settings)
    _install_forwarder(app, settings, env={job_env.RUNNER_CONFIG: str(_REPO_CONFIG)})

    with TestClient(app) as client:
        health = client.get("/healthz").json()
        unknown = client.get("/not/a/mount")

    expected = hashlib.sha256(_REPO_CONFIG.read_bytes()).hexdigest()
    assert health == {"status": "ok", "config_digest": expected}
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "endpoint_not_found"

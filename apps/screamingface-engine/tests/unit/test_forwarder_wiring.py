"""The forwarder's STARTUP wiring: the mount set and digest derive from the world file (C2).

Separate from `test_forwarder.py` because this test drives the real lifespan (TestClient) and is
therefore synchronous; the forwarder behaviour tests are async and carry a module-level asyncio
mark. The derivation itself has no network hop, so the mount set is a fact about the declaration.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.config import Settings
from screamingface_engine.rest.forwarder import install_forwarder

_REPO_CONFIG = Path(__file__).resolve().parents[2] / "url4.toml"


def test_install_forwarder_derives_the_mount_set_and_digest_at_startup(
    node_tier_settings: Callable[..., Settings],
) -> None:
    """AC12/erd §2: at startup the App learns its forwardable paths and the config digest."""
    # FX-38: a node tier needs a store both tiers share — the shared fixture supplies it.
    settings = node_tier_settings()
    app = create_app(settings)
    install_forwarder(app, settings, env={job_env.RUNNER_CONFIG: str(_REPO_CONFIG)})

    with TestClient(app) as client:
        health = client.get("/healthz").json()
        unknown = client.get("/not/a/mount")

    expected = hashlib.sha256(_REPO_CONFIG.read_bytes()).hexdigest()
    assert health == {"status": "ok", "config_digest": expected}
    # FX-31: an unknown path does not match the node route, so the ENGINE answers it.
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Not Found"}

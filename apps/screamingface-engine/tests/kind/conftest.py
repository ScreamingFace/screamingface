"""Session fixtures for the uniform executor kind suite (test-plan §5).

Every test under `tests/kind/` needs a live cluster at kind context `kind-sf-uniform`
(`deploy/kind/up.sh`). The reachability probe and the `kubectl`/port-forward plumbing live in
`_cluster.py`, imported here as plain functions; this module only wraps the ones that need
teardown as fixtures. Test modules call `_cluster.kind_reachable()` once at import time to build
their own `pytestmark = [..., pytest.mark.skipif(...)]`, the same shape
`tests/integration/test_worker_spine.py` uses for its NATS-reachability skip — so an unreachable
cluster skips each test individually instead of erroring the whole module.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx
import pytest
from _cluster import (
    APP_PORT,
    APP_SERVICE,
    NATS_PORT,
    NATS_SERVICE,
    KubectlRunner,
    port_forward,
    run_kubectl,
)


@pytest.fixture(scope="session")
def app_base_url() -> Iterator[str]:
    """Port-forwards the App Service (`sf-uniform-url4-cloud`, port 9108) and yields its
    `http://127.0.0.1:<port>` base URL once `/healthz` answers."""
    with port_forward(APP_SERVICE, APP_PORT) as local_port:
        base_url = f"http://127.0.0.1:{local_port}"
        deadline = time.monotonic() + 30
        healthy = False
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{base_url}/healthz", timeout=2.0)
                if response.status_code == 200:
                    healthy = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        if not healthy:
            raise RuntimeError("the App did not become healthy through the port-forward")
        yield base_url


@pytest.fixture(scope="session")
def nats_local_port() -> Iterator[int]:
    """Port-forwards the bundled NATS Service's client port (4222) — used only by K6 to list
    JetStream streams over a real `nats-py` connection."""
    with port_forward(NATS_SERVICE, NATS_PORT) as local_port:
        yield local_port


@pytest.fixture(scope="session")
def kubectl_cmd() -> KubectlRunner:
    return run_kubectl

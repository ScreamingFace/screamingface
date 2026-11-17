"""OME-1931 spec D3/D4: the Kubernetes adapter fails open when the API client cannot be built, and
one write is limited to 5 s for the whole request. No network: httpx.MockTransport and an injected
client_factory.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import ssl
from pathlib import Path

import httpx
import pytest

from screamingface_engine.config import Settings
from screamingface_engine.worker.kube_pod import (
    WRITE_TIMEOUT_S,
    KubePodCostWriter,
    build_pod_cost_writer,
)

_TOKEN = "test-token-not-real"
_LOGGER = "screamingface_engine.worker.kube_pod"


def _sa_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sa"
    d.mkdir(exist_ok=True)
    (d / "token").write_text(_TOKEN + "\n")
    (d / "ca.crt").write_text("not-a-real-ca\n")
    return d


def _on(**overrides: object) -> Settings:
    return Settings(
        **{
            "worker_deletion_cost_enabled": True,
            "worker_pod_name": "url4-cloud-runner-abc",
            "worker_pod_namespace": "sf-fusion",
            **overrides,
        }
    )


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.WARNING]


@pytest.mark.parametrize(
    "exc",
    [ssl.SSLError("bad CA"), PermissionError("denied"), ValueError("garbled")],
    ids=["ssl", "permission", "value"],
)
def test_a_client_build_error_gives_none_and_one_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, exc: Exception
) -> None:
    def _boom(base_url: str, ca_path: Path) -> httpx.AsyncClient:
        raise exc

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        writer = build_pod_cost_writer(
            _on(),
            {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
            service_account_dir=_sa_dir(tmp_path),
            client_factory=_boom,
        )

    assert writer is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "runs without it" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_a_slow_api_server_times_out_the_whole_request(tmp_path: Path) -> None:
    async def _slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(
        base_url="https://kube.test:443", transport=httpx.MockTransport(_slow)
    )
    writer = KubePodCostWriter(
        client=client,
        token_path=_sa_dir(tmp_path) / "token",
        namespace="sf-fusion",
        pod_name="url4-cloud-runner-abc",
        timeout_s=0.05,
    )
    try:
        loop = asyncio.get_running_loop()
        started = loop.time()
        with pytest.raises(TimeoutError):
            await writer.write(1)
        elapsed = loop.time() - started
        assert elapsed < 0.5
    finally:
        await writer.aclose()


def test_the_default_whole_request_limit_is_5_s() -> None:
    assert WRITE_TIMEOUT_S == 5.0
    default = inspect.signature(KubePodCostWriter.__init__).parameters["timeout_s"].default
    assert default == WRITE_TIMEOUT_S


def test_both_ids_missing_names_the_pod_name_first(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[tuple[str, Path]] = []

    def _factory(base_url: str, ca_path: Path) -> httpx.AsyncClient:
        calls.append((base_url, ca_path))
        return httpx.AsyncClient(base_url=base_url)

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        writer = build_pod_cost_writer(
            _on(worker_pod_name=None, worker_pod_namespace=None),
            {"KUBERNETES_SERVICE_HOST": "10.0.0.1"},
            service_account_dir=_sa_dir(tmp_path),
            client_factory=_factory,
        )

    assert writer is None
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "URL4_CLOUD_WORKER_POD_NAME" in message
    assert "NAMESPACE" not in message
    assert calls == []

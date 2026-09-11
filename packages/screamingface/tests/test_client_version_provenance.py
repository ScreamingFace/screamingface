"""Engine HTTP identity uses the installed Client version on every transport path."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

import screamingface as sf
from screamingface import _version
from screamingface._engine.transport import AsyncUrl4CloudTransport, Url4CloudTransport


def _installed_version(monkeypatch: pytest.MonkeyPatch, version: str | None) -> str:
    def lookup(name: str) -> str:
        assert name == "screamingface"
        if version is None:
            raise PackageNotFoundError(name)
        return version

    monkeypatch.setattr(_version, "distribution_version", lookup)
    return version or _version.SOURCE_TREE_VERSION


@pytest.mark.parametrize("version", ["9.8.7+local", None])
@pytest.mark.parametrize("factory", [sf.Client, Url4CloudTransport])
def test_sync_engine_request_identifies_client_and_preserves_request_headers(
    monkeypatch: pytest.MonkeyPatch,
    version: str | None,
    factory: type[sf.Client] | type[Url4CloudTransport],
) -> None:
    expected = _installed_version(monkeypatch, version)
    client = factory(engine_url="http://127.0.0.1:9108")
    try:
        request = client._http.build_request(
            "GET", "/", params={"q": "test"}, headers={"URL4-Capability": "capability"}
        )
        assert request.headers["User-Agent"] == f"screamingface/{expected}"
        assert request.headers["URL4-Capability"] == "capability"
        assert request.url.params["q"] == "test"
        assert request.content == b""
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["9.8.7+local", None])
@pytest.mark.parametrize("factory", [sf.AsyncClient, AsyncUrl4CloudTransport])
async def test_async_engine_request_identifies_client_and_preserves_request_headers(
    monkeypatch: pytest.MonkeyPatch,
    version: str | None,
    factory: type[sf.AsyncClient] | type[AsyncUrl4CloudTransport],
) -> None:
    expected = _installed_version(monkeypatch, version)
    client = factory(engine_url="http://127.0.0.1:9108")
    try:
        request = client._http.build_request(
            "GET", "/", params={"q": "test"}, headers={"URL4-Capability": "capability"}
        )
        assert request.headers["User-Agent"] == f"screamingface/{expected}"
        assert request.headers["URL4-Capability"] == "capability"
        assert request.url.params["q"] == "test"
        assert request.content == b""
    finally:
        if isinstance(client, sf.AsyncClient):
            await client.aclose()
        else:
            await client.close()

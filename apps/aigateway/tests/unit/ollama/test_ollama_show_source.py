"""OME-1537 review (HupBaHa 2026-10-20, findings 1-2; owner decision 2026-10-21).

``/api/show`` probes run ONLY in the async Ollama ``model_discovery_source`` through the
``ModelCatalog``: ``register_models()`` returns probe-free seeds, the kill switch
(``AIGW_DISCOVERY_ENABLED=false``) means zero probes, the whole probe round has one
deadline (a slow-drip host cannot hold it open), at most ``OLLAMA_SHOW_CONCURRENCY``
probes are in flight, and a failed round keeps the last-good snapshot.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import pytest

from aigateway.core.model_capabilities import model_row
from aigateway.core.model_catalog import ModelCatalog
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryLimits,
    DiscoveryPostClient,
    HttpxDiscoveryClient,
    RawResponse,
)
from aigateway.plugins.ollama_provider import discovery as ollama_discovery
from aigateway.plugins.ollama_provider import plugin as ollama_plugin
from aigateway.plugins.ollama_provider.discovery import (
    DEFAULT_OLLAMA_HOST,
    OLLAMA_SHOW_CONCURRENCY,
    clear_ollama_discovery_cache,
    ollama_model_discovery_source,
)
from aigateway.plugins.ollama_provider.plugin import OllamaProviderPlugin

from ._show_client import ShowClient

_NAMES = ["qwen2.5vl:3b", "qwen3:14b"]
_CAPS = {"qwen2.5vl:3b": ["completion", "vision"], "qwen3:14b": ["completion", "tools"]}


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_ollama_discovery_cache()
    yield
    clear_ollama_discovery_cache()


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    names = list(_NAMES)
    monkeypatch.setattr(ollama_plugin, "resolve_ollama_host", lambda: DEFAULT_OLLAMA_HOST)
    monkeypatch.setattr(ollama_plugin, "discover_ollama_models", lambda _host: list(names))
    return names


class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def now(self) -> float:
        return self.value


def _modalities(entries) -> dict[str, list[str]]:
    plugin = OllamaProviderPlugin()
    return {row["id"]: row["input_modalities"] for row in (model_row(plugin, e) for e in entries)}


# --- register_models: seeds only, no /api/show ---------------------------------


def test_register_models_never_probes_show(
    installed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_args, **_kwargs):
        raise AssertionError("register_models must not open a connection")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    monkeypatch.setattr(ollama_discovery, "_fetch_ollama_input_modalities", no_network)

    entries = OllamaProviderPlugin().register_models()

    assert [e.model_name for e in entries] == [f"ollama/{n}" for n in _NAMES]
    assert all(e.input_modalities is None for e in entries)


# --- the async source ------------------------------------------------------------


def test_the_plugin_declares_a_host_scoped_listing_source(installed: list[str]) -> None:
    source = OllamaProviderPlugin().model_discovery_source()
    assert source is not None
    assert source == ollama_model_discovery_source(DEFAULT_OLLAMA_HOST)
    assert DEFAULT_OLLAMA_HOST in source.key


@pytest.mark.asyncio
async def test_live_listing_carries_show_evidence(installed: list[str]) -> None:
    client = ShowClient(_CAPS)
    entries = await OllamaProviderPlugin().discover_live_models(client=client)
    assert entries is not None
    assert _modalities(entries) == {
        "ollama/qwen2.5vl:3b": ["text", "image"],
        "ollama/qwen3:14b": ["text"],
    }
    assert sorted(client.asked) == sorted(_NAMES)


@pytest.mark.asyncio
async def test_a_get_only_transport_is_a_failed_attempt(installed: list[str]) -> None:
    class _GetOnly:
        async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
            raise AssertionError("unreachable")

    assert not isinstance(_GetOnly(), DiscoveryPostClient)
    with pytest.raises(DiscoveryError) as exc:
        await OllamaProviderPlugin().discover_live_models(client=_GetOnly())
    assert exc.value.reason == "unsupported_transport"


@pytest.mark.asyncio
async def test_no_installed_models_lists_nothing_without_probing(
    installed: list[str],
) -> None:
    installed.clear()
    client = ShowClient(_CAPS)
    assert await OllamaProviderPlugin().discover_live_models(client=client) == ()
    assert client.asked == []


@pytest.mark.asyncio
async def test_probes_are_bounded_in_concurrency(
    installed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    installed[:] = [f"m{i}:1b" for i in range(OLLAMA_SHOW_CONCURRENCY * 3)]
    client = ShowClient({}, delay_s=0.02)
    entries = await OllamaProviderPlugin().discover_live_models(client=client)
    assert entries is not None and len(entries) == len(installed)
    assert client.peak_in_flight == OLLAMA_SHOW_CONCURRENCY


@pytest.mark.asyncio
async def test_the_whole_round_has_one_deadline(
    installed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each probe alone is well inside its own per-request budget; together they are
    # not. Only an aggregate deadline bounds the round.
    monkeypatch.setattr(ollama_discovery, "OLLAMA_SHOW_DEADLINE_S", 0.2)
    installed[:] = [f"m{i}:1b" for i in range(OLLAMA_SHOW_CONCURRENCY * 10)]
    client = ShowClient({}, delay_s=0.1)

    started = time.monotonic()
    with pytest.raises(DiscoveryError) as exc:
        await OllamaProviderPlugin().discover_live_models(client=client)
    elapsed = time.monotonic() - started

    assert exc.value.reason == "timeout"
    assert elapsed < 1.5
    assert len(client.asked) < len(installed)


@pytest.mark.asyncio
async def test_a_slow_drip_show_body_hits_the_deadline(installed: list[str]) -> None:
    async def drip() -> AsyncIterator[bytes]:
        yield b'{"capabilities": ["vision"], "license": "'
        while True:
            yield b" "
            await asyncio.sleep(0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, content=drip(), headers={"content-type": "application/json"})

    client = HttpxDiscoveryClient(transport=httpx.MockTransport(handler))
    started = time.monotonic()
    with pytest.raises(DiscoveryError) as exc:
        await OllamaProviderPlugin().discover_live_models(
            client=client, limits=DiscoveryLimits(timeout_s=0.25)
        )
    assert exc.value.reason == "timeout"
    assert time.monotonic() - started < 3.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (404, '{"error": "nope"}', "bad_status"),
        (200, "not json", "malformed_json"),
        (200, "[1, 2]", "malformed_json"),
        (200, "[" * 100_000 + "]" * 100_000, "malformed_json"),
    ],
)
async def test_a_bad_show_answer_fails_the_round(
    installed: list[str], status: int, body: str, reason: str
) -> None:
    class _Bad(ShowClient):
        async def post(self, url, *, json_body, timeout_s, max_bytes) -> RawResponse:
            return RawResponse(status=status, content_type="application/json", body=body)

    with pytest.raises(DiscoveryError) as exc:
        await OllamaProviderPlugin().discover_live_models(client=_Bad({}))
    assert exc.value.reason == reason


@pytest.mark.asyncio
async def test_the_show_body_is_byte_capped(installed: list[str]) -> None:
    caps: list[int] = []

    class _Recording(ShowClient):
        async def post(self, url, *, json_body, timeout_s, max_bytes) -> RawResponse:
            caps.append(max_bytes)
            return await super().post(
                url, json_body=json_body, timeout_s=timeout_s, max_bytes=max_bytes
            )

    await OllamaProviderPlugin().discover_live_models(client=_Recording(_CAPS))
    assert caps and set(caps) == {ollama_discovery.SHOW_MAX_BYTES}


@pytest.mark.asyncio
async def test_a_recent_answer_is_not_asked_again(installed: list[str]) -> None:
    client = ShowClient(_CAPS)
    plugin = OllamaProviderPlugin()
    await plugin.discover_live_models(client=client)
    await plugin.discover_live_models(client=client)
    assert sorted(client.asked) == sorted(_NAMES)


# --- through the ModelCatalog: last-good ---------------------------------------


@pytest.mark.asyncio
async def test_a_failed_round_keeps_the_last_good_snapshot(installed: list[str]) -> None:
    clock = _Clock()
    catalog = ModelCatalog(clock=clock)
    plugin = OllamaProviderPlugin()
    source = plugin.model_discovery_source()
    assert source is not None

    good = await catalog.entries_for(plugin, client=ShowClient(_CAPS), limits=None)
    assert good is not None
    clear_ollama_discovery_cache()
    clock.value += source.ttl_s + 1.0

    failing = ShowClient(_CAPS, fail=True)
    stale = await catalog.entries_for(plugin, client=failing, limits=None)

    assert failing.asked, "the refresh was attempted"
    assert stale is not None
    assert _modalities(stale)["ollama/qwen2.5vl:3b"] == ["text", "image"]


# --- the kill switch: zero /api/show ----------------------------------------------


@pytest.fixture
def _discovery_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_DISCOVERY_ENABLED", "false")


def test_kill_switch_means_zero_show_probes(
    _discovery_off: None,
    installed: list[str],
    monkeypatch: pytest.MonkeyPatch,
    authenticated_client,
) -> None:
    probes: list[str] = []

    async def record_post(self, url: str, **_kwargs) -> RawResponse:
        probes.append(url)
        raise AssertionError("no /api/show under the kill switch")

    monkeypatch.setattr(HttpxDiscoveryClient, "post", record_post)
    monkeypatch.setattr(
        ollama_discovery,
        "_fetch_ollama_input_modalities",
        lambda *a, **k: probes.append("sync") or None,
    )

    assert authenticated_client.app.state.model_catalog is None
    response = authenticated_client.get("/v1/models")

    assert response.status_code == 200
    rows = {r["id"]: r["input_modalities"] for r in response.json()["data"]}
    assert rows["ollama/qwen2.5vl:3b"] == ["text"]
    assert probes == []

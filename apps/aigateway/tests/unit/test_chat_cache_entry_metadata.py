"""The chat-route slice of the cache-entry-metadata feature (PRD tasks C1-C4).

FEATURE: every cached response carries a standard metadata block (cost, latency,
tokens) written beside it and read back on a hit.

STORY: as an operator I re-run a priced OpenRouter call and the second, identical
request is served from the shared cache while reporting the cost the first call
actually paid.

INVARIANT (PRD §2.3, locked order): the block is built from the ``AccountingSession``
BEFORE ``RequestCacheWrite`` is constructed, and the store still runs BEFORE
``attach_success_metadata``. ``response_size_bytes`` therefore measures the provider
response only.

INVARIANT (I3): cost is an output, so the stored block never changes the cache key.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aigateway.core.request_cache import RequestCacheWrite
from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata
from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import CachedEntry, TortoiseRequestCacheStore
from aigateway.core.usage_accounting import active_collector
from aigateway.plugins.openrouter_provider import plugin as openrouter_plugin_module
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings
from aigateway.plugins.taxonomy.session import attach_hit_metadata as real_attach_hit_metadata

_CHAT_PATH = "/v1/chat/completions"
_MODEL = "openrouter/anthropic/claude-fable-5"
_KEY = "sk-or-v1-test"
_RAW_COST = Decimal("0.012345")
_DIRECT_COST_SOURCE = "openrouter.usage.cost"
_DIRECT_COST_UNIT = "openrouter_credits"
_WriteStatus = Literal["stored", "race_lost", "not_stored"]


# --- arrangement ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _api_key_validation_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # This module is outside the frozen legacy allowlist, so it opts in to a VALID
    # readiness result: key validation is not what these tests exercise.
    from aigateway.core.api_key_validation import (
        ApiKeyValidationResult,
        ApiKeyValidationStage,
        ApiKeyValidationState,
    )
    from aigateway.core.api_key_validation_service import ApiKeyValidationService

    async def _valid(_self: Any, _plugin: Any, _provider: str, _api_key: str):
        return ApiKeyValidationResult(
            state=ApiKeyValidationState.VALID, stage=ApiKeyValidationStage.READINESS
        )

    monkeypatch.setattr(ApiKeyValidationService, "validate", _valid)


@pytest.fixture
def chat_client(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> TestClient:
    monkeypatch.setattr(
        openrouter_plugin_module.PLUGIN, "settings", OpenRouterPluginSettings(enabled=True)
    )
    monkeypatch.setenv("AIGW_REQUEST_CACHE_ENABLED", "true")
    response = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    )
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['token']}"})
    return client


class _MetadataStore:
    """An in-memory store honouring the landed ``CachedEntry`` read contract.

    ``get`` returns ``CachedEntry | None``, so the metadata block travels with the row
    exactly as the real Tortoise store returns it.
    """

    def __init__(self) -> None:
        self.rows: dict[str, CachedEntry] = {}
        self.set_calls: list[RequestCacheWrite] = []
        self.get_calls: list[str] = []

    def cache_available(self) -> bool:
        return True

    async def get(self, key_hash: str) -> CachedEntry | None:
        self.get_calls.append(key_hash)
        return self.rows.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> _WriteStatus:
        self.set_calls.append(entry)
        if entry.key_hash in self.rows:
            return "race_lost"
        self.rows[entry.key_hash] = CachedEntry(response=entry.response, metadata=entry.metadata)
        return "stored"


class _RecordingStore:
    """The REAL Tortoise store, with its calls recorded.

    Used by the two tests whose whole subject is that a block survives the trip to storage and
    back: the row genuinely round-trips through SQL, so ``metadata_json`` is actually serialized,
    written, re-read and parsed. Wrapping rather than faking keeps that path under test while
    still exposing what was written, which is what the assertions compare against.

    The in-memory ``_MetadataStore`` above stays for the tests that need two INDEPENDENT misses
    of the same request (the key-stability and size-cap pairs) — against one real database the
    second of those would hit instead of writing, which is a different test.
    """

    def __init__(self) -> None:
        self._inner = TortoiseRequestCacheStore()
        self.set_calls: list[RequestCacheWrite] = []
        self.get_calls: list[str] = []

    def cache_available(self) -> bool:
        return self._inner.cache_available()

    async def get(self, key_hash: str) -> CachedEntry | None:
        self.get_calls.append(key_hash)
        return await self._inner.get(key_hash)

    async def set_if_absent(self, entry: RequestCacheWrite) -> _WriteStatus:
        self.set_calls.append(entry)
        return await self._inner.set_if_absent(entry)


def _install(client: TestClient, store: _MetadataStore) -> _MetadataStore:
    cast(Any, client.app).state.request_cache_store = store
    return store


def _install_real(client: TestClient) -> _RecordingStore:
    store = _RecordingStore()
    cast(Any, client.app).state.request_cache_store = store
    return store


async def _overwrite_stored_block(key_hash: str, metadata: CacheEntryMetadata) -> None:
    """Rewrite one row's block directly in the database.

    Run on the app's own loop via ``client.portal`` — the TestClient holds the Tortoise
    connections there, so reaching them from the test thread would bind to the wrong loop.
    """
    await RequestCacheEntry.filter(key_hash=key_hash).update(metadata_json=metadata.serialize())


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


def _provider_body(*, cost: object | None = None) -> dict[str, Any]:
    """The provider-compatible final response the fake dispatch answers with."""
    usage: dict[str, Any] = {
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "total_tokens": 125,
    }
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "or-final-1",
        "object": "chat.completion",
        "model": "anthropic/claude-fable-5",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ANSWER"},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


class _Dispatch:
    """A fake ``litellm.acompletion`` that reports one observed send to the collector.

    ``raw_usage`` is what the RAW provider JSON carried, and it is where a real provider
    decimal arrives from (the hooks parse the wire body with ``parse_float=Decimal``).
    ``None`` means the raw body held no usage block, so the mapper falls back to the
    converted final response.
    """

    def __init__(self, *, raw_usage: dict[str, Any] | None, final_body: dict[str, Any]) -> None:
        self.calls = 0
        self._raw_usage = raw_usage
        self._final_body = final_body

    async def __call__(self, **_kwargs: Any) -> Any:
        self.calls += 1
        collector = active_collector()
        assert collector is not None, "the dispatch ran outside the bound collector"
        marker = object()
        collector.on_send_admitted(marker)
        raw_evidence = (
            None
            if self._raw_usage is None
            else {"id": "or-raw-1", "model": "claude-fable-5", "usage": self._raw_usage}
        )
        collector.on_response_completed(marker, status=200, raw_evidence=raw_evidence)
        return dict(self._final_body)


def _post(client: TestClient, body: dict[str, Any] | None = None) -> Any:
    return client.post(_CHAT_PATH, json=body if body is not None else _body())


def _priced_dispatch() -> _Dispatch:
    # The cost lives ONLY in the raw provider JSON. The final body must stay
    # provider-compatible JSON, so it carries no Decimal.
    return _Dispatch(
        raw_usage={
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "cost": _RAW_COST,
        },
        final_body=_provider_body(),
    )


def _unpriced_dispatch() -> _Dispatch:
    return _Dispatch(
        raw_usage={"prompt_tokens": 100, "completion_tokens": 25},
        final_body=_provider_body(),
    )


def _aigw(response: Any) -> dict[str, Any]:
    body = response.json()
    assert "_aigw" in body, f"accounted response carried no _aigw: {body}"
    return body["_aigw"]


# --- #1 the block never changes the cache key (I3) -----------------------------


def test_a_stored_metadata_block_never_changes_the_cache_key(
    credential_blobs: Any, chat_client: TestClient
) -> None:
    """I3: cost is an output. A priced and an unpriced run of the SAME request must
    produce the same key, or the corpus would silently partition by price."""
    _create_connection(chat_client)

    priced_store = _install(chat_client, _MetadataStore())
    with patch("litellm.acompletion", _priced_dispatch()):
        priced = _post(chat_client)
    assert priced.status_code == 200, priced.text

    unpriced_store = _install(chat_client, _MetadataStore())
    with patch("litellm.acompletion", _unpriced_dispatch()):
        unpriced = _post(chat_client)
    assert unpriced.status_code == 200, unpriced.text

    (priced_write,) = priced_store.set_calls
    (unpriced_write,) = unpriced_store.set_calls
    assert priced_write.key_hash == unpriced_write.key_hash
    assert priced_write.prompt_hash == unpriced_write.prompt_hash
    # Non-vacuous: the two runs really did store different metadata.
    assert priced_write.metadata is not None
    assert unpriced_write.metadata is not None
    assert priced_write.metadata.direct_cost["status"] == "reported"
    assert unpriced_write.metadata.direct_cost["status"] == "unavailable"


# --- #6 a raw provider cost is stored exactly ----------------------------------


def test_a_miss_stores_the_exact_raw_provider_decimal_and_unit(
    credential_blobs: Any, chat_client: TestClient
) -> None:
    _create_connection(chat_client)
    store = _install(chat_client, _MetadataStore())
    with patch("litellm.acompletion", _priced_dispatch()):
        response = _post(chat_client)
    assert response.status_code == 200, response.text
    assert response.headers["X-AIGW-Cache"] == "miss"

    (write,) = store.set_calls
    assert write.metadata is not None
    assert write.metadata.metadata_status == "complete"
    assert write.metadata.direct_cost == {
        "status": "reported",
        "amount": "0.012345",
        "unit": _DIRECT_COST_UNIT,
        "source": _DIRECT_COST_SOURCE,
    }
    assert write.metadata.usage["input"]["total"] == 100
    assert write.metadata.usage["output"]["total"] == 25
    assert write.metadata.usage["source"] == "provider_raw_response"


def test_a_cost_that_arrives_only_through_the_converted_response_is_never_certified(
    credential_blobs: Any, chat_client: TestClient
) -> None:
    """§2.4: only the write-time raw JSON can prove provenance. A converted float is
    not raw evidence, so it is stored as unknown — never as a reported price."""
    _create_connection(chat_client)
    store = _install(chat_client, _MetadataStore())
    dispatch = _Dispatch(raw_usage=None, final_body=_provider_body(cost=0.012345))
    with patch("litellm.acompletion", dispatch):
        response = _post(chat_client)
    assert response.status_code == 200, response.text

    (write,) = store.set_calls
    assert write.metadata is not None
    assert write.metadata.direct_cost["status"] == "unavailable"
    assert write.metadata.direct_cost["amount"] is None
    # Tokens still arrive from the converted response; only money stays unknown.
    assert write.metadata.usage["input"]["total"] == 100


# --- #7 the size cap measures the provider response only (I5, E2) --------------


def test_response_size_bytes_is_unchanged_by_the_metadata_block(
    credential_blobs: Any, chat_client: TestClient
) -> None:
    _create_connection(chat_client)
    priced_store = _install(chat_client, _MetadataStore())
    with patch("litellm.acompletion", _priced_dispatch()):
        _post(chat_client)

    unpriced_store = _install(chat_client, _MetadataStore())
    with patch("litellm.acompletion", _unpriced_dispatch()):
        _post(chat_client)

    (priced_write,) = priced_store.set_calls
    (unpriced_write,) = unpriced_store.set_calls
    assert priced_write.metadata is not None, "the priced run stored no block"
    assert unpriced_write.metadata is not None, "the unpriced run stored no block"
    expected = len(
        json.dumps(
            priced_write.response, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    )
    assert priced_write.response_size_bytes == expected
    # Same body, different metadata: the measurement is the response alone.
    assert priced_write.response_size_bytes == unpriced_write.response_size_bytes
    assert "_aigw" not in json.dumps(priced_write.response)


# --- #8 the stored block reaches the hit path ---------------------------------


def test_the_stored_block_travels_from_get_to_attach_hit_metadata(
    credential_blobs: Any, chat_client: TestClient
) -> None:
    """The read-path plumbing (A6/ERD §5.5). Without it nothing downstream works."""
    _create_connection(chat_client)
    store = _install_real(chat_client)
    with patch("litellm.acompletion", _priced_dispatch()):
        first = _post(chat_client)
    assert first.status_code == 200, first.text
    (stored_write,) = store.set_calls
    assert stored_write.metadata is not None

    # Replace the row's block with a distinctive one, so the assertion cannot pass on
    # a value the write path happened to produce.
    distinctive = CacheEntryMetadata(
        metadata_status="complete",
        observed_at=stored_write.metadata.observed_at,
        response_model=stored_write.metadata.response_model,
        usage=stored_write.metadata.usage,
        direct_cost={
            "status": "reported",
            "amount": "9.999999",
            "unit": _DIRECT_COST_UNIT,
            "source": _DIRECT_COST_SOURCE,
        },
        provider_latency_ms=321,
    )
    portal = chat_client.portal
    assert portal is not None  # entered: the TestClient's lifespan portal is live
    portal.call(_overwrite_stored_block, stored_write.key_hash, distinctive)

    captured: dict[str, Any] = {}

    def _spy(cached: dict[str, Any], session: Any, *, plugin: Any, entry_metadata: Any = None):
        captured["entry_metadata"] = entry_metadata
        return real_attach_hit_metadata(
            cached, session, plugin=plugin, entry_metadata=entry_metadata
        )

    with patch("aigateway.routes.chat.attach_hit_metadata", _spy):
        hit = _post(chat_client)

    assert hit.status_code == 200, hit.text
    assert hit.headers["X-AIGW-Cache"] == "hit"
    # Parsed back out of the row, so equality — not identity — is what proves the
    # block made the whole round trip through `metadata_json`.
    assert captured["entry_metadata"] == distinctive
    reference = _aigw(hit)["usage_accounting"]["cache"]["reference"]
    assert reference["direct_cost"] == distinctive.direct_cost
    assert reference["latency"]["provider_latency_ms"] == 321


# --- #28 the e2e spine --------------------------------------------------------


def test_e2e_a_miss_stores_priced_metadata_and_the_next_identical_request_hits_with_it(
    credential_blobs: Any, chat_client: TestClient
) -> None:
    """S1 -> S3: one spine test through the real chat route.

    Request 1 misses, dispatches once and stores the block. Request 2 is identical and
    must hit: no second dispatch, no current-request spend, and the stored cost reported
    verbatim as historical evidence.
    """
    _create_connection(chat_client)
    store = _install_real(chat_client)
    dispatch = _priced_dispatch()
    with patch("litellm.acompletion", dispatch):
        first = _post(chat_client)
        assert first.status_code == 200, first.text
        assert first.headers["X-AIGW-Cache"] == "miss"

        (write,) = store.set_calls
        assert write.metadata is not None
        assert write.metadata.metadata_status == "complete"
        assert write.metadata.direct_cost["status"] == "reported"
        assert write.metadata.direct_cost["amount"] == "0.012345"
        assert write.metadata.direct_cost["unit"] == _DIRECT_COST_UNIT
        assert dispatch.calls == 1

        hit = _post(chat_client)

    assert hit.status_code == 200, hit.text
    assert hit.headers["X-AIGW-Cache"] == "hit"
    assert dispatch.calls == 1, "the hit dispatched the provider again"
    assert len(store.set_calls) == 1, "the hit wrote a second row"

    metadata = _aigw(hit)
    reference = metadata["usage_accounting"]["cache"]["reference"]
    assert reference["direct_cost"] == write.metadata.direct_cost
    assert reference["usage"]["source"] == "cached_converted_response"
    assert reference["latency"]["provider_latency_ms"] == write.metadata.provider_latency_ms
    assert reference["incurred_in_current_request"] is False

    # A hit performs no provider work and incurs no current-request cost.
    assert metadata["usage_accounting"]["attempts"] == []
    economics = metadata["request_economics"]
    assert economics["observed_new_attempts"] == 0
    assert economics["known_direct_cost_subtotals"] == []
    assert economics["direct_cost_status"] == "not_applicable"


def _create_connection(client: TestClient) -> None:
    """Create the OpenRouter api-key connection the credential target needs."""
    response = client.post(
        "/v1/oauth/connections/api-key",
        json={"provider": "openrouter", "label": "work-openrouter", "api_key": _KEY},
    )
    assert response.status_code == 201, response.text

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import fields as dataclass_fields

import pytest
import pytest_asyncio
from tortoise import Tortoise

from aigateway.core.request_cache.models import RequestCacheEntry
from aigateway.core.request_cache.store import RequestCacheWrite, TortoiseRequestCacheStore
from aigateway.db import build_tortoise_config

_KEY = "a" * 64
_RESPONSE = {
    "id": "cmpl-1",
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "cached"},
        }
    ],
}


class _Available:
    def cache_available(self) -> bool:
        return True


@pytest_asyncio.fixture
async def store(tmp_path) -> AsyncIterator[TortoiseRequestCacheStore]:
    await Tortoise.close_connections()
    await Tortoise.init(
        config=build_tortoise_config(f"sqlite://{tmp_path / 'single-cache.sqlite3'}"),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield TortoiseRequestCacheStore(availability=_Available())
    finally:
        await Tortoise.close_connections()


def test_request_cache_contract_has_one_lane() -> None:
    assert {field.name for field in dataclass_fields(RequestCacheWrite)} == {
        "key_hash",
        "prompt_hash",
        "provider",
        "model",
        "response",
        "response_size_bytes",
        "metadata",
    }

    model_fields = set(RequestCacheEntry._meta.fields_map)
    assert {"account_id", "profile_name", "key_version", "response_ciphertext"}.isdisjoint(
        model_fields
    )
    assert {"response_json", "expires_at"} <= model_fields


@pytest.mark.asyncio
async def test_request_cache_round_trip_uses_plain_json(store: TortoiseRequestCacheStore) -> None:
    write = RequestCacheWrite(
        key_hash=_KEY,
        prompt_hash="p" * 64,
        provider="anthropic",
        model="anthropic/claude-haiku-4-5",
        response=_RESPONSE,
        response_size_bytes=128,
    )

    assert await store.set_if_absent(write) == "stored"
    entry = await store.get(_KEY)
    assert entry is not None
    assert entry.response == _RESPONSE

    row = await RequestCacheEntry.get(key_hash=_KEY)
    assert row.response_json == json.dumps(_RESPONSE, separators=(",", ":"), ensure_ascii=False)
    assert row.expires_at is None

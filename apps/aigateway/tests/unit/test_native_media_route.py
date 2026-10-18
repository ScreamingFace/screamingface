"""Content-part refusals reach the HTTP caller as the typed 422 (OME-1541).

FEATURE: image and file input across the gateway (OME-1529).
STORY: as a caller sending a part my provider cannot carry, I get a 422 naming the provider
and the part type — not a 500, not a remapped 502, and never a 200 that ignored the part.

INVARIANT: the refusal is raised in `prepare_chat_body`, before credential injection and
dispatch, so a refused request never reaches the provider. (The global-cache stage runs
earlier; these providers use `CacheBypass`.) Unit tests elsewhere call `prepare_chat_body`
directly; these pin the same contract through the real route.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from aigateway.core.credential_names import credential_name_for, profile_id_for
from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileDefaults, ProfileState
from aigateway.plugins.codex_provider.auth import credential_service_for

_MODEL = "codex/gpt-5.4-mini"
_DISPATCH = "aigateway.plugins.codex_provider.plugin.CodexProviderPlugin.chat_completion"
_PNG_URI = "data:image/png;base64,iVBORw0KGgo="


async def _seed_codex(credential_blobs, client) -> None:
    account_id = client.get("/v1/auth/me").json()["id"]
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, "default")),
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "id_token": "id",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "codex", "default"),
            account_id=account_id,
            provider="codex",
            name="default",
            state=ProfileState.AUTHENTICATED,
            defaults=ProfileDefaults(),
        )
    )


def _capture(store: dict[str, Any]):
    async def _fake_chat_completion(_self, body):
        store.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    return _fake_chat_completion


def _post(client, content: list[Any]):
    return client.post(
        "/v1/chat/completions",
        json={"model": _MODEL, "messages": [{"role": "user", "content": content}]},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("part", "part_type"),
    [
        (
            {"type": "image_url", "image_url": {"url": "data:audio/wav;base64,UklGRg=="}},
            "image_url",
        ),
        ({"type": "image_url", "image_url": {"url": _PNG_URI, "detail": []}}, "image_url"),
        ({"type": "input_audio", "input_audio": {"data": "x", "format": "wav"}}, "input_audio"),
        ({}, "untyped"),
    ],
)
async def test_route_answers_typed_422_and_never_dispatches(
    credential_blobs, authenticated_client, part: dict[str, Any], part_type: str
) -> None:
    await _seed_codex(credential_blobs, authenticated_client)
    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, ["what is this?", part])

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_content_part"
    assert detail["provider"] == "codex"
    assert detail["part_type"] == part_type
    assert captured == {}


@pytest.mark.asyncio
async def test_route_dispatches_a_supported_image_unchanged(
    credential_blobs, authenticated_client
) -> None:
    # WHY: the mirror of the refusal — an accepted image must reach dispatch intact, so the
    # gate cannot pass by refusing everything.
    await _seed_codex(credential_blobs, authenticated_client)
    image = {"type": "image_url", "image_url": {"url": _PNG_URI, "detail": "high"}}
    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, ["what is this?", image])

    assert resp.status_code == 200, resp.text
    assert captured["messages"][-1]["content"] == ["what is this?", image]

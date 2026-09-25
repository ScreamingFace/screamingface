"""The parameter contract refuses the CALLER's values — never a stored Profile default.

FEATURE: one effective parameter contract. The provider rule set that drives the
``/v1/models`` summary and the ``/v1/model-parameters`` detail decides what may be
dispatched, and since OME-1323 (D2) every value it judges is one the caller sent.

STORY: as a caller I am told exactly which of MY fields a model does not enable, before
anything is prepared, cached, authorized or dispatched — and I am never shown a rejection
for a field I did not send, even when my Profile still stores an invalid historical value.

INVARIANT: caller parameters are classified against the provider's enabled rules, schemas
and resolved auth mode BEFORE provider preparation, cache planning, credential access and
dispatch. A Profile's historical defaults are not merged, so they are never classified,
never refused and never dispatched (the cutover itself is pinned by
``test_chat_saved_defaults_are_not_merged.py``).
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import (
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for
from aigateway.plugins.codex_provider.auth import (
    credential_service_for as codex_credential_service_for,
)

_ANTHROPIC_MODEL = "anthropic/claude-haiku-4-5"
_CODEX_MODEL = "codex/gpt-5.4-mini"


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _token_blob() -> str:
    return json.dumps(
        {
            "access_token": "tok",
            "refresh_token": "rt",
            "id_token": "id",
            "expires_at_ms": int(time.time() * 1000) + 3_600_000,
            "token_type": "Bearer",
        }
    )


def _seed_anthropic_credential(credential_blobs, account_id: str) -> None:
    credential_blobs.write(
        credential_service_for(credential_name_for(account_id, "default")),
        "default",
        _token_blob(),
    )


def _seed_codex_credential(credential_blobs, account_id: str) -> None:
    credential_blobs.write(
        codex_credential_service_for(credential_name_for(account_id, "default")),
        "default",
        _token_blob(),
    )


async def _seed_profile(
    credential_blobs, account_id: str, *, provider: str, defaults: ProfileDefaults
) -> None:
    idx = ProfileIndexStore(credential_store=credential_blobs.store)
    await idx.upsert(
        Profile(
            id=profile_id_for(account_id, provider, "default"),
            account_id=account_id,
            provider=provider,
            name="default",
            state=ProfileState.AUTHENTICATED,
            defaults=defaults,
        )
    )


def _capture(store: dict[str, Any]):
    async def _fake_chat_completion(_self, body):
        store.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    return _fake_chat_completion


_ANTHROPIC_PLUGIN = "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin"
_CODEX_PLUGIN = "aigateway.plugins.codex_provider.plugin.CodexProviderPlugin"
_ANTHROPIC_DISPATCH = f"{_ANTHROPIC_PLUGIN}.chat_completion"


# --- attribution ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_caller_fault_is_reported_alone_beside_an_invalid_historical_default(
    credential_blobs, authenticated_client
) -> None:
    # The Profile still carries an invalid historical `temperature`, and the caller sends an
    # unknown field. Stage C (D2) ignores the stored value entirely, so the error names ONLY
    # the caller's own field — `temperature`, which they never sent, is not in the request.
    account_id = _account_id(authenticated_client)
    _seed_anthropic_credential(credential_blobs, account_id)
    await _seed_profile(
        credential_blobs,
        account_id,
        provider="anthropic",
        defaults=ProfileDefaults(temperature=1.5),
    )

    captured: dict[str, Any] = {}
    with patch(_ANTHROPIC_DISPATCH, _capture(captured)):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": _ANTHROPIC_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "not_a_parameter": 1,
            },
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_parameters"
    assert detail["rejected"] == {"not_a_parameter": "unknown"}
    assert captured == {}


# --- ordering ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_refusal_precedes_provider_preparation_and_everything_after_it(
    credential_blobs, authenticated_client
) -> None:
    # prepare_chat_body is the EARLIEST of the four downstream steps the contract
    # must precede (chat.py: prepare < cache plan < credential injection <
    # dispatch), so a tripwire there establishes the whole ordering claim at once.
    # It is deliberately outside the route's dispatch try/except, so reaching it
    # would surface as an error rather than a sanitized 502. The refused value is the
    # caller's own: Codex enables no `temperature` (OME-634).
    account_id = _account_id(authenticated_client)
    _seed_codex_credential(credential_blobs, account_id)
    await _seed_profile(credential_blobs, account_id, provider="codex", defaults=ProfileDefaults())

    def _tripwire(_self, body):
        raise AssertionError("provider preparation ran before the parameter contract")

    with patch(f"{_CODEX_PLUGIN}.prepare_chat_body", _tripwire):
        resp = authenticated_client.post(
            "/v1/chat/completions",
            json={
                "model": _CODEX_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.5,
            },
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_parameters"
    assert resp.json()["detail"]["rejected"] == {"temperature": "unknown"}


@pytest.mark.asyncio
async def test_the_refusal_precedes_credential_access(
    credential_blobs, authenticated_client
) -> None:
    # No instrumentation: the profile is AUTHENTICATED but its credential blob is
    # deliberately never written. Reaching credential injection would raise
    # CredentialNotFoundError and render 401 auth_required, so observing the 400
    # is direct evidence that no credential was read. The refused value is the
    # caller's own `temperature`, which Codex does not enable.
    account_id = _account_id(authenticated_client)
    await _seed_profile(credential_blobs, account_id, provider="codex", defaults=ProfileDefaults())

    resp = authenticated_client.post(
        "/v1/chat/completions",
        json={
            "model": _CODEX_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.5,
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "unsupported_parameters"
    assert resp.json()["detail"]["rejected"] == {"temperature": "unknown"}

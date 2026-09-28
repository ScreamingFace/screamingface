"""OME-640: Anthropic refuses reasoning/max-token pairs the model cannot serve.

FEATURE: one effective parameter contract. ``reasoning_effort`` and ``max_tokens``
are each enabled and each schema-checked, but on a MANUAL-thinking model the
installed transform turns the effort into a thinking BUDGET, and Anthropic
requires that budget to be smaller than ``max_tokens``. The contract has to refuse
the pair it cannot honor instead of advertising both fields as independently safe.

STORY: as a caller I get an immediate, actionable 400 naming the two fields and
the rule that binds them, rather than an opaque provider error after the gateway
has already read my credential and dispatched.

INVARIANT: the constraint is MODEL-specific. Adaptive-thinking models get
``thinking={"type":"adaptive"}`` with no budget at all, so the constraint does not
exist for them and must never be applied to them.
INVARIANT: the constraint is AUTH-specific, and the auth split lives in the
credential layer — the OAuth strategy sends the interleaved-thinking beta header
and the api-key path sends no beta header at all. The seam therefore reads the
RESOLVED auth mode, never a caller-declared one.
INVARIANT: the exemption needs BOTH the beta header AND tools. Interleaved
thinking is defined as extended thinking WITH TOOL USE, so a tool-less OAuth
request is still bound by the ordinary rule.

AIDEV-NOTE: these tests drive the real route. The provider-local decision procedure
and the derived budget tables are exercised directly in
``test_anthropic_thinking_decision`` — a route test can reach only a handful of the
combinations that predicate has to get right.
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
    AuthType,
    Profile,
    ProfileDefaults,
    ProfileState,
    credential_name_for,
    profile_id_for,
)
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_PLUGIN = "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin"
_DISPATCH = f"{_PLUGIN}.chat_completion"

_MANUAL = "anthropic/claude-sonnet-4-5"
_HAIKU = "anthropic/claude-haiku-4-5"
_ADAPTIVE = (
    "anthropic/claude-opus-4-8",
    "anthropic/claude-opus-4-7",
    "anthropic/claude-sonnet-4-6",
)
_TOOLS = [
    {
        "type": "function",
        "function": {"name": "calc", "parameters": {"type": "object", "properties": {}}},
    }
]


# --- seeding ------------------------------------------------------------------


def _account_id(client) -> str:
    return client.get("/v1/auth/me").json()["id"]


def _service(account_id: str) -> str:
    return credential_service_for(credential_name_for(account_id, "default"))


async def _seed_profile(
    credential_blobs,
    account_id: str,
    *,
    auth_type: AuthType,
    defaults: ProfileDefaults | None = None,
) -> None:
    await ProfileIndexStore(credential_store=credential_blobs.store).upsert(
        Profile(
            id=profile_id_for(account_id, "anthropic", "default"),
            account_id=account_id,
            provider="anthropic",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type=auth_type,
            defaults=defaults or ProfileDefaults(),
        )
    )


async def _seed_oauth(credential_blobs, account_id: str, **kwargs) -> None:
    credential_blobs.write(
        _service(account_id),
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
    await _seed_profile(credential_blobs, account_id, auth_type="oauth", **kwargs)


async def _seed_api_key(credential_blobs, account_id: str, **kwargs) -> None:
    credential_blobs.write(
        _service(account_id),
        "default",
        json.dumps({"auth_type": "api_key", "api_key": "sk-ant-api03-raw"}),
    )
    await _seed_profile(credential_blobs, account_id, auth_type="api_key", **kwargs)


def _capture(store: dict[str, Any]):
    async def _fake_chat_completion(_self, body):
        store.update(body)
        return SimpleNamespace(
            model_dump=lambda: {"id": "x", "choices": [{"message": {"content": "ok"}}]}
        )

    return _fake_chat_completion


def _post(client, model: str, **extra: Any):
    return client.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hi"}], **extra},
    )


# --- the refusal --------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_manual_thinking_model_refuses_a_budget_exceeding_max_tokens(
    credential_blobs, authenticated_client
) -> None:
    # reasoning_effort="high" becomes thinking.budget_tokens=4096 on this model,
    # and Anthropic requires budget_tokens < max_tokens. Both fields validate
    # alone; the PAIR is what the provider cannot serve.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=128)

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "incompatible_parameters"
    assert detail["provider"] == "anthropic"
    assert detail["conflict"] == ["max_tokens", "reasoning_effort"]
    # The message must name the binding rule, not just say "invalid".
    assert "4096" in detail["message"]
    assert captured == {}


@pytest.mark.parametrize("model", _ADAPTIVE)
@pytest.mark.asyncio
async def test_an_adaptive_thinking_model_accepts_the_same_combination(
    credential_blobs, authenticated_client, model: str
) -> None:
    # The whole point of the model split: these three get
    # thinking={"type":"adaptive"} with NO budget, so there is nothing for
    # max_tokens to be smaller than. A provider-wide rule would break them.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, model, reasoning_effort="high", max_tokens=128)

    assert resp.status_code == 200
    assert captured["reasoning_effort"] == "high"
    assert captured["max_tokens"] == 128


# --- the interleaved-thinking exemption ---------------------------------------


@pytest.mark.asyncio
async def test_the_exemption_applies_on_oauth_with_tools(
    credential_blobs, authenticated_client
) -> None:
    # The OAuth strategy sends anthropic-beta: …interleaved-thinking-2025-05-14…,
    # under which budget_tokens may exceed max_tokens. With tools present the
    # feature is actually in effect, so the same body is legal.
    account_id = _account_id(authenticated_client)
    await _seed_oauth(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(
            authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=128, tools=_TOOLS
        )

    assert resp.status_code == 200
    assert captured["max_tokens"] == 128
    # Pins the premise the exemption rests on: this path really does carry the beta.
    assert "interleaved-thinking-2025-05-14" in captured["extra_headers"]["anthropic-beta"]


@pytest.mark.asyncio
async def test_the_exemption_needs_tools(credential_blobs, authenticated_client) -> None:
    # Interleaved thinking is extended thinking WITH TOOL USE. The beta header on
    # a tool-less request buys nothing, so the ordinary rule still binds.
    account_id = _account_id(authenticated_client)
    await _seed_oauth(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=128)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "incompatible_parameters"
    assert captured == {}


@pytest.mark.asyncio
async def test_the_exemption_is_oauth_only(credential_blobs, authenticated_client) -> None:
    # The api-key credential strategy sends Authorization and nothing else — no
    # beta header — so tools cannot buy the exemption on that path.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(
            authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=128, tools=_TOOLS
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "incompatible_parameters"
    assert captured == {}


@pytest.mark.asyncio
async def test_the_exemption_does_not_extend_to_haiku(
    credential_blobs, authenticated_client
) -> None:
    # AIDEV-NOTE: Haiku 4.5 is manual-thinking but is NOT in the interleaved set.
    # The published documentation groups it with Opus 4.5 as having "different
    # interleaved thinking behaviors" without saying what they are, so this takes
    # the fail-closed reading: an honest 400 on a pair that is invalid on the
    # api-key path regardless, rather than an opaque provider error.
    account_id = _account_id(authenticated_client)
    await _seed_oauth(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(
            authenticated_client, _HAIKU, reasoning_effort="high", max_tokens=128, tools=_TOOLS
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "incompatible_parameters"
    assert captured == {}


# --- the boundary and the non-triggers ----------------------------------------


@pytest.mark.asyncio
async def test_max_tokens_one_above_the_budget_dispatches(
    credential_blobs, authenticated_client
) -> None:
    # "budget_tokens must be LESS THAN max_tokens" — so budget+1 is the first
    # legal value, and the check must not be off by one in the strict direction.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=4097)

    assert resp.status_code == 200
    assert captured["max_tokens"] == 4097


@pytest.mark.asyncio
async def test_max_tokens_equal_to_the_budget_is_refused(
    credential_blobs, authenticated_client
) -> None:
    # INVARIANT: the boundary is EXCLUSIVE — Anthropic requires the budget to be
    # strictly smaller, so an exact tie is a refusal, not a pass.
    # AIDEV-NOTE: this is the dedicated home for the equal-values case. A profile
    # default in tests/unit/test_chat_x_profile.py used to land on it by accident
    # while testing something else entirely; that fixture moved off the boundary
    # and the boundary itself is asserted here.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    with patch(_DISPATCH, _capture({})):
        resp = _post(authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=4096)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "incompatible_parameters"


@pytest.mark.asyncio
async def test_a_tiny_max_tokens_without_reasoning_effort_dispatches(
    credential_blobs, authenticated_client
) -> None:
    # No thinking requested → no budget → nothing to conflict with. The seam must
    # not become a general max_tokens floor.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, _MANUAL, max_tokens=1)

    assert resp.status_code == 200
    assert captured["max_tokens"] == 1


@pytest.mark.asyncio
async def test_reasoning_effort_none_dispatches(credential_blobs, authenticated_client) -> None:
    # "none" is in the schema enum and maps to NO thinking at all; the plugin then
    # drops it in prepare_chat_body. It must not be treated as a budget request.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, _MANUAL, reasoning_effort="none", max_tokens=1)

    assert resp.status_code == 200
    assert captured["max_tokens"] == 1
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_an_absent_max_tokens_dispatches(credential_blobs, authenticated_client) -> None:
    # litellm raises max_tokens above the budget itself when the caller omitted
    # it, so the gateway must not invent a conflict where the transform fixes it.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    captured: dict[str, Any] = {}
    with patch(_DISPATCH, _capture(captured)):
        resp = _post(authenticated_client, _MANUAL, reasoning_effort="high")

    assert resp.status_code == 200
    assert "max_tokens" not in captured


# --- ordering: the refusal comes before everything downstream -----------------


@pytest.mark.asyncio
async def test_the_refusal_precedes_provider_preparation_and_everything_after_it(
    credential_blobs, authenticated_client
) -> None:
    # prepare_chat_body is the EARLIEST of the four downstream steps in
    # routes/chat.py (prepare < cache plan < credential injection < dispatch) and
    # sits outside the dispatch try/except, so tripping it proves the whole
    # "before provider preparation, cache planning, credential access and
    # dispatch" claim with one assertion.
    account_id = _account_id(authenticated_client)
    await _seed_api_key(credential_blobs, account_id)

    def _tripwire(_self, _body):
        raise AssertionError("prepare_chat_body ran on a refused parameter combination")

    with patch(f"{_PLUGIN}.prepare_chat_body", _tripwire):
        resp = _post(authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=128)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "incompatible_parameters"


@pytest.mark.asyncio
async def test_the_refusal_precedes_credential_access(
    credential_blobs, authenticated_client
) -> None:
    # Instrumentation-free ordering proof: the profile is AUTHENTICATED but no
    # credential blob was ever written, so reaching credential injection would
    # produce a 401. A 400 therefore means no credential was read.
    account_id = _account_id(authenticated_client)
    await _seed_profile(credential_blobs, account_id, auth_type="api_key")

    resp = _post(authenticated_client, _MANUAL, reasoning_effort="high", max_tokens=128)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "incompatible_parameters"

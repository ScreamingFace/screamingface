"""Live Codex model list, per ChatGPT account, behind the OME-972 cache (OME-1634).

FEATURE: Codex through the gateway (ChatGPT-account OAuth) — the models a signed-in account
can actually use, read from the Codex backend instead of a static list that went dead.
STORY: as a caller refused a Codex model, I am told which models my account can use; as a
caller listing models, I see the live Codex models once the gateway has read them.

INVARIANT: fail closed, all-or-nothing — a malformed or empty catalog never replaces the last
good list. The list is only ever read with a credential a dispatch handed over.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from litellm.llms.custom_llm import CustomLLMError

from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
from aigateway.plugins.codex_provider import live_models
from aigateway.plugins.codex_provider.live_models import (
    CODEX_MODELS_URL,
    CodexModelDirectory,
    parse_listed_slugs,
)
from aigateway.plugins.codex_provider.plugin import CodexProviderPlugin

_LISTED = {
    "models": [
        {"slug": "gpt-6-astra", "visibility": "list", "supported_in_api": True},
        {"slug": "gpt-5.6-sol", "visibility": "list"},
        {"slug": "codex-auto-review", "visibility": "hide"},
        {"slug": "gpt-6-astra", "visibility": "list"},
    ]
}


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t


class _FakeClient:
    def __init__(self, responses: list[RawResponse | Exception]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        del timeout_s, max_bytes
        self.calls.append(url)
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _ok(payload: Any) -> RawResponse:
    return RawResponse(status=200, content_type="application/json", body=json.dumps(payload))


def _directory(
    responses: list[RawResponse | Exception],
) -> tuple[CodexModelDirectory, _FakeClient, list[dict[str, str]], _Clock]:
    client = _FakeClient(responses)
    headers_seen: list[dict[str, str]] = []
    clock = _Clock()

    def factory(headers: dict[str, str]) -> _FakeClient:
        headers_seen.append(headers)
        return client

    return CodexModelDirectory(clock=clock, client_factory=factory), client, headers_seen, clock


def _jwt(auth_claims: dict[str, Any] | None) -> str:
    def seg(obj: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    payload: dict[str, Any] = {"sub": "u"}
    if auth_claims is not None:
        payload["https://api.openai.com/auth"] = auth_claims
    return f"{seg({'alg': 'none'})}.{seg(payload)}.sig"


_PLUS = _jwt({"chatgpt_plan_type": "plus", "chatgpt_account_id": "acct-1"})


# --- parser -----------------------------------------------------------------------------


def test_parser_keeps_listed_slugs_in_order_without_duplicates() -> None:
    assert parse_listed_slugs(_LISTED) == ("gpt-6-astra", "gpt-5.6-sol")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"models": "x"},
        {"models": ["x"]},
        {"models": [{"slug": 7, "visibility": "list"}]},
        {"models": [{"slug": "a", "visibility": None}]},
        {"models": [{"slug": "", "visibility": "list"}]},
    ],
)
def test_parser_refuses_malformed_catalogs(payload: Any) -> None:
    with pytest.raises(DiscoveryError) as caught:
        parse_listed_slugs(payload)
    assert caught.value.reason == "malformed_json"


def test_parser_refuses_a_catalog_with_nothing_listed() -> None:
    with pytest.raises(DiscoveryError) as caught:
        parse_listed_slugs({"models": [{"slug": "a", "visibility": "hide"}]})
    assert caught.value.reason == "model_catalog_empty"


def test_parser_refuses_an_oversized_catalog() -> None:
    rows = [{"slug": f"m{i}", "visibility": "list"} for i in range(201)]
    with pytest.raises(DiscoveryError) as caught:
        parse_listed_slugs({"models": rows})
    assert caught.value.reason == "model_catalog_too_large"


# --- directory --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_account_id_means_no_dial() -> None:
    directory, client, _headers, _clock = _directory([])
    assert await directory.slugs_for(_jwt({"chatgpt_plan_type": "plus"})) is None
    assert await directory.slugs_for(None) is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_dial_carries_the_callers_credential_to_the_fixed_url() -> None:
    directory, client, headers, _clock = _directory([_ok(_LISTED)])
    assert await directory.slugs_for(_PLUS) == ("gpt-6-astra", "gpt-5.6-sol")
    assert client.calls == [CODEX_MODELS_URL]
    assert headers[0]["Authorization"] == f"Bearer {_PLUS}"
    assert headers[0]["ChatGPT-Account-Id"] == "acct-1"
    assert headers[0]["originator"] == "codex_cli_rs"


@pytest.mark.asyncio
async def test_explicit_account_id_wins_over_the_token_claim() -> None:
    directory, _client, headers, _clock = _directory([_ok(_LISTED)])
    await directory.slugs_for(_PLUS, account_id="acct-header")
    assert headers[0]["ChatGPT-Account-Id"] == "acct-header"


@pytest.mark.asyncio
async def test_list_is_cached_per_account_within_ttl() -> None:
    other = _jwt({"chatgpt_account_id": "acct-2"})
    directory, client, _headers, clock = _directory(
        [_ok(_LISTED), _ok({"models": [{"slug": "gpt-x", "visibility": "list"}]})]
    )
    await directory.slugs_for(_PLUS)
    clock.t += 10
    assert await directory.slugs_for(_PLUS) == ("gpt-6-astra", "gpt-5.6-sol")
    assert await directory.slugs_for(other) == ("gpt-x",)
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_failure_keeps_the_last_good_list() -> None:
    directory, _client, _headers, clock = _directory(
        [_ok(_LISTED), RawResponse(status=500, content_type="text/plain", body="x")]
    )
    await directory.slugs_for(_PLUS)
    clock.t += 301
    assert await directory.slugs_for(_PLUS) == ("gpt-6-astra", "gpt-5.6-sol")
    assert directory.latest() == ("gpt-6-astra", "gpt-5.6-sol")


@pytest.mark.asyncio
async def test_cold_failure_is_unknown_not_an_error() -> None:
    directory, _client, _headers, _clock = _directory([DiscoveryError("unreachable")])
    assert await directory.slugs_for(_PLUS) is None
    assert directory.latest() is None


@pytest.mark.asyncio
async def test_latest_follows_the_most_recent_refresh_and_expires() -> None:
    other = _jwt({"chatgpt_account_id": "acct-2"})
    directory, _client, _headers, clock = _directory(
        [_ok(_LISTED), _ok({"models": [{"slug": "gpt-x", "visibility": "list"}]})]
    )
    assert directory.latest() is None
    await directory.slugs_for(_PLUS)
    await directory.slugs_for(other)
    assert directory.latest() == ("gpt-x",)
    # INVARIANT: the same trust window the cache serves stale values in (ttl + stale).
    clock.t += 3901
    assert directory.latest() is None


# --- plugin listing port ----------------------------------------------------------------


def _plugin() -> CodexProviderPlugin:
    return CodexProviderPlugin.__new__(CodexProviderPlugin)


def test_plugin_declares_a_listing_source() -> None:
    source = _plugin().model_discovery_source()
    assert source is not None
    assert source.key == "codex:models:list"


@pytest.mark.asyncio
async def test_listing_serves_the_latest_known_list_as_gateway_rows() -> None:
    directory, _client, _headers, _clock = _directory([_ok(_LISTED)])
    await directory.slugs_for(_PLUS)
    with patch.object(live_models, "DIRECTORY", directory):
        entries = await _plugin().discover_live_models(client=_FakeClient([]))
    assert entries is not None
    assert [e.model_name for e in entries] == ["codex/gpt-6-astra", "codex/gpt-5.6-sol"]
    assert [e.litellm_params["model"] for e in entries] == [
        "codex/gpt-6-astra",
        "codex/gpt-5.6-sol",
    ]


@pytest.mark.asyncio
async def test_listing_without_a_known_list_fails_so_seeds_serve() -> None:
    directory, _client, _headers, _clock = _directory([])
    unused = _FakeClient([])
    with patch.object(live_models, "DIRECTORY", directory), pytest.raises(DiscoveryError) as caught:
        await _plugin().discover_live_models(client=unused)
    assert caught.value.reason == "no_snapshot"
    # INVARIANT: the credential-free injected client is never dialed for Codex.
    assert unused.calls == []


# --- refusal carries the account's list -------------------------------------------------

_HANDLER = "aigateway.plugins.codex_provider.plugin.get_litellm_codex_handler"
_REFUSAL = (
    "Codex upstream request failed with status 400: "
    '{"detail":"The \'gpt-5.4\' model is not supported when using Codex with a ChatGPT account."}'
)


class _Raising:
    async def acompletion(self, **_kwargs: Any) -> Any:
        raise CustomLLMError(status_code=400, message=_REFUSAL)


def _detail(err: HTTPException) -> dict[str, Any]:
    assert isinstance(err.detail, dict)
    return cast("dict[str, Any]", err.detail)


async def _refused(directory: CodexModelDirectory, api_key: str) -> HTTPException:
    body = {"model": "codex/gpt-5.4", "messages": [{"role": "user", "content": "hi"}]}
    body["api_key"] = api_key
    with (
        patch(_HANDLER, return_value=_Raising()),
        patch.object(live_models, "DIRECTORY", directory),
        pytest.raises(HTTPException) as caught,
    ):
        await _plugin().chat_completion(body)
    return caught.value


@pytest.mark.asyncio
async def test_refusal_lists_the_models_the_account_can_use() -> None:
    directory, _client, _headers, _clock = _directory([_ok(_LISTED)])
    err = await _refused(directory, _PLUS)
    assert err.status_code == 403
    detail = _detail(err)
    assert detail["code"] == "codex_model_unsupported"
    assert detail["plan"] == "plus"
    assert detail["available_models"] == ["codex/gpt-6-astra", "codex/gpt-5.6-sol"]


@pytest.mark.asyncio
async def test_refusal_reads_the_account_id_from_the_dispatch_headers() -> None:
    directory, _client, headers, _clock = _directory([_ok(_LISTED)])
    body = {
        "model": "codex/gpt-5.4",
        "messages": [{"role": "user", "content": "hi"}],
        "api_key": _jwt({"chatgpt_plan_type": "plus"}),
        "extra_headers": {"ChatGPT-Account-Id": "acct-hdr"},
    }
    with (
        patch(_HANDLER, return_value=_Raising()),
        patch.object(live_models, "DIRECTORY", directory),
        pytest.raises(HTTPException),
    ):
        await _plugin().chat_completion(body)
    assert headers[0]["ChatGPT-Account-Id"] == "acct-hdr"


@pytest.mark.asyncio
async def test_refusal_without_a_known_list_omits_available_models() -> None:
    directory, _client, _headers, _clock = _directory([DiscoveryError("timeout")])
    err = await _refused(directory, _PLUS)
    assert err.status_code == 403
    detail = _detail(err)
    assert detail["code"] == "codex_model_unsupported"
    assert "available_models" not in detail


# --- AIGW_DISCOVERY_ENABLED=false silences the Codex list read too (review finding) ------


@pytest.mark.asyncio
async def test_disabled_directory_never_dials_and_reports_unknown() -> None:
    directory, client, headers, _clock = _directory([_ok(_LISTED)])
    directory.set_enabled(enabled=False)
    assert await directory.slugs_for(_PLUS) is None
    # INVARIANT: zero discovery egress of ANY kind — not even a client is built.
    assert headers == []
    assert client.calls == []


@pytest.mark.asyncio
async def test_refusal_with_discovery_disabled_sends_no_request() -> None:
    directory, client, headers, _clock = _directory([_ok(_LISTED)])
    with patch.object(live_models, "DIRECTORY", directory):
        _plugin().configure_discovery(enabled=False)
    err = await _refused(directory, _PLUS)
    assert err.status_code == 403
    detail = _detail(err)
    assert detail["code"] == "codex_model_unsupported"
    assert "available_models" not in detail
    assert headers == []
    assert client.calls == []


@pytest.mark.asyncio
async def test_reenabling_discovery_restores_the_refusal_list() -> None:
    directory, client, _headers, _clock = _directory([_ok(_LISTED)])
    with patch.object(live_models, "DIRECTORY", directory):
        _plugin().configure_discovery(enabled=False)
        _plugin().configure_discovery(enabled=True)
    err = await _refused(directory, _PLUS)
    assert _detail(err)["available_models"] == ["codex/gpt-6-astra", "codex/gpt-5.6-sol"]
    assert client.calls == [CODEX_MODELS_URL]


@pytest.mark.parametrize(("flag", "expected"), [("false", False), ("true", True)])
def test_create_app_hands_the_discovery_switch_to_the_codex_directory(
    monkeypatch: pytest.MonkeyPatch, flag: str, expected: bool
) -> None:
    from aigateway.config import Settings
    from aigateway.main import create_app

    directory, _client, _headers, _clock = _directory([])
    monkeypatch.setenv("AIGW_DISCOVERY_ENABLED", flag)
    with patch.object(live_models, "DIRECTORY", directory):
        create_app(Settings())
    assert directory.enabled is expected

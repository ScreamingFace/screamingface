"""Media admission at the chat route boundary, before cache and credentials (OME-1542, review 2).

# FEATURE: image and file input across the gateway (OME-1529).
# INVARIANT: every media refusal — a malformed `data:` URI on any provider, media in Anthropic's
# top-level `system` — is the typed 422 raised BEFORE the cache stage and BEFORE credential
# resolution, whatever the caller's credential state (unconnected, OAuth, API key). A
# profile/auth error can therefore never preempt the media 422, and a refused body never reaches
# the cache.
# INVARIANT: a valid mixed-case `HTTPS://` image is admitted for Codex at ingress AND accepted by
# the provider's own parser after credential resolution — never admitted only to fail later.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from aigateway.routes import chat as chat_route

_PNG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
_MALFORMED = ["data:", "data:not-a-media-uri", "data:image/png;base64,%%%"]
_GUARDED_MODELS = [
    "anthropic/claude-haiku-4-5",
    "ollama/qwen2.5vl:3b",
    "openai/gpt-4o-mini",
    "openrouter/google/gemini-2.5-flash",
    "gemini-cli/gemini-2.5-flash",
    "codex/gpt-5",
]


class _Seams:
    def __init__(self) -> None:
        self.cache: list[str] = []
        self.credentials: list[str] = []


def _credential_outcome(state: str) -> Any:
    async def resolve(_access: Any, *, provider: str, **_kwargs: Any) -> Any:
        if state == "unconnected":
            raise HTTPException(status_code=404, detail="provider not connected")
        return object(), state

    return resolve


@pytest.fixture(params=["unconnected", "oauth", "api_key"])
def seams(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> _Seams:
    """Records any call into the cache stage or credential resolution, for each credential state."""
    seen = _Seams()
    resolve = _credential_outcome(request.param)

    async def cache_probe(_request: Any, *, body: dict[str, Any], **_kwargs: Any) -> Any:
        seen.cache.append(body["model"])
        raise HTTPException(status_code=418, detail="reached the cache stage")

    async def credential_probe(access: Any, **kwargs: Any) -> Any:
        seen.credentials.append(kwargs["provider"])
        return await resolve(access, **kwargs)

    monkeypatch.setattr(chat_route, "look_up_global_cache", cache_probe)
    monkeypatch.setattr(chat_route, "_resolve_credential_target", credential_probe)
    return seen


def _assert_refused_early(resp: Any, seams: _Seams, reason: str) -> None:
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "unsupported_content_part"
    assert detail["reason"] == reason
    assert seams.cache == []
    assert seams.credentials == []


# --- finding 3: Anthropic top-level `system` media -------------------------------------------


@pytest.mark.parametrize(
    "system_part",
    [
        _PNG,
        {"type": "file", "file": {"file_data": "data:application/pdf;base64,JVBERi0xLjQK"}},
    ],
    ids=["image", "file"],
)
@pytest.mark.parametrize("stream", [False, True], ids=["sync", "stream"])
def test_anthropic_top_level_system_media_is_refused_before_cache_and_credentials(
    authenticated_client, seams: _Seams, system_part: dict[str, Any], stream: bool
) -> None:
    body: dict[str, Any] = {
        "model": "anthropic/claude-haiku-4-5",
        "system": ["be brief", system_part],
        "messages": [{"role": "user", "content": "hi"}],
    }
    if stream:
        body["stream"] = True

    resp = authenticated_client.post("/v1/chat/completions", json=body)

    _assert_refused_early(resp, seams, "media in a system message")
    assert resp.json()["detail"]["provider"] == "anthropic"


def test_anthropic_system_message_media_is_refused_before_cache_and_credentials(
    authenticated_client, seams: _Seams
) -> None:
    body = {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [
            {"role": "system", "content": ["be brief", _PNG]},
            {"role": "user", "content": "hi"},
        ],
    }

    resp = authenticated_client.post("/v1/chat/completions", json=body)

    _assert_refused_early(resp, seams, "media in a system message")


def test_anthropic_text_system_still_reaches_the_cache(authenticated_client, seams: _Seams) -> None:
    body = {
        "model": "anthropic/claude-haiku-4-5",
        "system": [{"type": "text", "text": "be brief"}],
        "messages": [{"role": "user", "content": ["look", _PNG]}],
    }

    resp = authenticated_client.post("/v1/chat/completions", json=body)

    assert resp.status_code == 418, resp.text
    assert seams.cache == ["anthropic/claude-haiku-4-5"]


def test_only_the_anthropic_plugin_refuses_top_level_system_media(authenticated_client) -> None:
    # The hook is a provider's own admission rule; the core default admits everything.
    from aigateway.core.plugin_base import ProviderPluginBase

    registry = authenticated_client.app.state.providers
    overriding = sorted(
        plugin.custom_llm_provider
        for plugin in registry.all()
        if type(plugin).refuse_inadmissible_media
        is not ProviderPluginBase.refuse_inadmissible_media
    )
    assert overriding == ["anthropic"]


# --- finding 4: malformed `data:` URIs --------------------------------------------------------


@pytest.mark.parametrize("model", _GUARDED_MODELS)
@pytest.mark.parametrize("value", _MALFORMED)
@pytest.mark.parametrize("kind", ["image", "file"])
def test_a_malformed_data_uri_is_refused_before_cache_and_credentials(
    authenticated_client, seams: _Seams, model: str, value: str, kind: str
) -> None:
    part = (
        {"type": "image_url", "image_url": {"url": value}}
        if kind == "image"
        else {"type": "file", "file": {"file_data": value}}
    )
    body = {"model": model, "messages": [{"role": "user", "content": ["look", part]}]}

    resp = authenticated_client.post("/v1/chat/completions", json=body)

    _assert_refused_early(resp, seams, "not_data_uri")
    assert resp.json()["detail"]["part_type"] == ("image_url" if kind == "image" else "file")


# --- finding 5: Codex mixed-case https --------------------------------------------------------


class _ReachedSeal(Exception):
    pass


@pytest.mark.parametrize(
    "url", ["HTTPS://example.com/a.png", "Https://example.com/a.png", "hTTpS://example.com/a.png"]
)
def test_codex_carries_a_mixed_case_https_image_past_the_provider_parser(
    authenticated_client, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    sealed: list[dict[str, Any]] = []

    async def resolve(*_args: Any, **_kwargs: Any) -> Any:
        return object(), "oauth"

    async def seal(_access: Any, _target: Any, *, body: dict[str, Any], **_kwargs: Any) -> None:
        # Reached only after `prepare_chat_body` (Codex's `check_messages`) accepted the body.
        sealed.append(body)
        raise HTTPException(status_code=418, detail="reached authorization")

    monkeypatch.setattr(chat_route, "_resolve_credential_target", resolve)
    monkeypatch.setattr(chat_route, "_authorize_and_seal", seal)
    body = {
        "model": "codex/gpt-5",
        "messages": [
            {"role": "user", "content": ["look", {"type": "image_url", "image_url": {"url": url}}]}
        ],
    }

    resp = authenticated_client.post("/v1/chat/completions", json=body)

    assert resp.status_code == 418, resp.text
    assert len(sealed) == 1


@pytest.mark.parametrize("url", ["HTTP://example.com/a.png", "Http://127.0.0.1/a.png"])
def test_codex_refuses_a_mixed_case_plaintext_image_before_cache_and_credentials(
    authenticated_client, seams: _Seams, url: str
) -> None:
    body = {
        "model": "codex/gpt-5",
        "messages": [
            {"role": "user", "content": ["look", {"type": "image_url", "image_url": {"url": url}}]}
        ],
    }

    resp = authenticated_client.post("/v1/chat/completions", json=body)

    _assert_refused_early(resp, seams, "remote_url_not_https")

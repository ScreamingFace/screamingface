"""SCREAMINGFACE_ACCESS_TOKEN pre-seeds the Access store (e2e workbench U1, spec §6 option B)."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable

import httpx
import pytest

import screamingface as sf
from screamingface._access import auth as access_auth_module
from screamingface._access.auth import (
    _AccessTokenStore,
    _CloudflareAccessAuth,
    _seed_access_tokens,
)

_AUDIENCE = "a" * 64
_OTHER = "b" * 64
_ENGINE = "https://engine.example"
_SCOREBOARD = "https://scoreboard.example"


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _jwt(exp: float, aud: object) -> str:
    header = _b64u(json.dumps({"alg": "RS256"}).encode())
    payload = _b64u(json.dumps({"exp": exp, "aud": aud}).encode())
    return f"{header}.{payload}.sig"


def test_no_env_var_seeds_nothing() -> None:
    store = _AccessTokenStore()
    _seed_access_tokens(store, {}, monotonic_now=100.0, wall_now=1_800_000_000.0)
    assert store.usable(_AUDIENCE, 100.0) is None


@pytest.mark.parametrize("aud", [_AUDIENCE, [_AUDIENCE, _OTHER]])
def test_token_is_stored_under_every_audience_it_names(aud: str | list[str]) -> None:
    token = _jwt(1_800_000_900.0, aud)
    store = _AccessTokenStore()
    _seed_access_tokens(
        store, {"SCREAMINGFACE_ACCESS_TOKEN": token}, monotonic_now=100.0, wall_now=1_800_000_000.0
    )
    expected = [aud] if isinstance(aud, str) else aud
    for audience in expected:
        assert store.usable(audience, 100.0) == token


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        _jwt(1_800_000_010.0, _AUDIENCE),  # expires inside the 30 s skew
        _jwt(1_800_000_900.0, None),  # no aud
        _jwt(1_800_000_900.0, []),  # empty aud list
        _jwt(1_800_000_900.0, ["short"]),  # aud fails _VALID_AUDIENCE
    ],
)
def test_an_unusable_env_token_fails_loudly_without_echoing_it(token: str) -> None:
    with pytest.raises(sf.AuthenticationError) as caught:
        _seed_access_tokens(
            _AccessTokenStore(),
            {"SCREAMINGFACE_ACCESS_TOKEN": token},
            monotonic_now=100.0,
            wall_now=1_800_000_000.0,
        )
    assert caught.value.code == "access_env_token_invalid"
    assert caught.value.permanent is True
    assert token not in str(caught.value)
    assert caught.value.__cause__ is None


def test_client_uses_the_env_token_and_never_opens_a_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _jwt(time.time() + 900, _AUDIENCE)
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    browser_urls: list[str] = []
    seen: list[str | None] = []

    def auth(
        origin: str,
        *,
        token_store: _AccessTokenStore | None = None,
        discovery_error: Callable[[str], BaseException] | None = None,
    ) -> _CloudflareAccessAuth:
        return _CloudflareAccessAuth(
            origin,
            access_transport=httpx.MockTransport(lambda request: httpx.Response(500)),
            browser_presenter=browser_urls.append,
            token_store=token_store,
            discovery_error=discovery_error or access_auth_module._access_discovery_error,
        )

    def scoreboard(request: httpx.Request) -> httpx.Response:
        sent = request.headers.get("Cf-Access-Token")
        seen.append(sent)
        if sent is None:
            login = f"https://team.cloudflareaccess.com/cdn-cgi/access/login?kid={_AUDIENCE}"
            return httpx.Response(302, headers={"location": login})
        return httpx.Response(404)

    monkeypatch.setattr(access_auth_module, "_client_caller_auth", auth)
    with sf.Client(
        engine_url=_ENGINE,
        scoreboard_url=_SCOREBOARD,
        scoreboard_transport=httpx.MockTransport(scoreboard),
    ) as client:
        with pytest.raises(sf.LeaderboardError):
            client.leaderboards.get_score("00000000-0000-0000-0000-000000000001")

    assert seen == [None, token]
    assert browser_urls == []


@pytest.mark.asyncio
async def test_async_client_uses_the_env_token_and_never_opens_a_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _jwt(time.time() + 900, _AUDIENCE)
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    browser_urls: list[str] = []
    seen: list[str | None] = []

    def auth(
        origin: str,
        *,
        token_store: _AccessTokenStore | None = None,
        discovery_error: Callable[[str], BaseException] | None = None,
    ) -> _CloudflareAccessAuth:
        return _CloudflareAccessAuth(
            origin,
            access_transport=httpx.MockTransport(lambda request: httpx.Response(500)),
            browser_presenter=browser_urls.append,
            token_store=token_store,
            discovery_error=discovery_error or access_auth_module._access_discovery_error,
        )

    def scoreboard(request: httpx.Request) -> httpx.Response:
        sent = request.headers.get("Cf-Access-Token")
        seen.append(sent)
        if sent is None:
            login = f"https://team.cloudflareaccess.com/cdn-cgi/access/login?kid={_AUDIENCE}"
            return httpx.Response(302, headers={"location": login})
        return httpx.Response(404)

    monkeypatch.setattr(access_auth_module, "_client_caller_auth", auth)
    async with sf.AsyncClient(
        engine_url=_ENGINE,
        scoreboard_url=_SCOREBOARD,
        scoreboard_transport=httpx.MockTransport(scoreboard),
    ) as client:
        with pytest.raises(sf.LeaderboardError):
            await client.leaderboards.get_score("00000000-0000-0000-0000-000000000001")

    assert seen == [None, token]
    assert browser_urls == []


def test_a_malformed_env_token_fails_at_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", "not-a-jwt")
    with pytest.raises(sf.AuthenticationError) as caught:
        sf.Client(engine_url=_ENGINE, scoreboard_url=_SCOREBOARD)
    assert caught.value.code == "access_env_token_invalid"
    with pytest.raises(sf.AuthenticationError) as caught_async:
        sf.AsyncClient(engine_url=_ENGINE, scoreboard_url=_SCOREBOARD)
    assert caught_async.value.code == "access_env_token_invalid"


def test_a_token_for_another_audience_falls_back_to_the_browser_login() -> None:
    store = _AccessTokenStore()
    _seed_access_tokens(
        store,
        {"SCREAMINGFACE_ACCESS_TOKEN": _jwt(1_800_000_900.0, _OTHER)},
        monotonic_now=100.0,
        wall_now=1_800_000_000.0,
    )
    assert store.usable(_AUDIENCE, 100.0) is None

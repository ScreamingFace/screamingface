"""An Access token is only adopted for, or sent to, an HTTPS origin (PR #1438 review, blocker 2).

WHY: the origin's challenge only ASSERTS its Access audience; the assertion is trusted because it
comes from the configured HTTPS origin. Over plaintext anyone on the path can assert a matching
`kid` and harvest the bearer token from the retry, so a challenge from an http:// origin is a
permanent `access_requires_https` error instead. A local HTTP stack that never challenges keeps
working unchanged.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable

import httpx
import pytest

import screamingface as sf
from screamingface._access import auth as access_auth_module
from screamingface._access.auth import _AccessTokenStore, _CloudflareAccessAuth

_AUDIENCE = "a" * 64
_PLAIN_ENGINE = "http://engine.example"
_LOCAL_ENGINE = "http://127.0.0.1:8080"
_SCOREBOARD = "https://scoreboard.example"
_LOGIN = f"https://team.cloudflareaccess.com/cdn-cgi/access/login?kid={_AUDIENCE}"


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _token() -> str:
    header = _b64u(json.dumps({"alg": "RS256"}).encode())
    payload = _b64u(json.dumps({"exp": time.time() + 900, "aud": _AUDIENCE}).encode())
    return f"{header}.{payload}.{_b64u(b'signature')}"


def _challenge(request: httpx.Request) -> httpx.Response:
    return httpx.Response(302, headers={"location": _LOGIN})


def _models(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"object": "list", "data": []})


def _fake_auth_factory(
    browser_urls: list[str],
    discovery: Callable[[httpx.Request], httpx.Response] = lambda request: httpx.Response(500),
) -> Callable[..., _CloudflareAccessAuth]:
    def auth(
        origin: str,
        *,
        token_store: _AccessTokenStore | None = None,
        discovery_error: Callable[[str], BaseException] | None = None,
    ) -> _CloudflareAccessAuth:
        return _CloudflareAccessAuth(
            origin,
            access_transport=httpx.MockTransport(discovery),
            browser_presenter=browser_urls.append,
            token_store=token_store,
            discovery_error=discovery_error or access_auth_module._access_discovery_error,
        )

    return auth


def _recording(
    seen: list[str | None], respond: Callable[[httpx.Request], httpx.Response]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Cf-Access-Token"))
        return respond(request)

    return handler


def _assert_requires_https(error: sf.AuthenticationError, token: str) -> None:
    assert error.code == "access_requires_https"
    assert error.permanent is True
    assert token not in str(error)


def test_plain_http_engine_challenge_never_receives_the_env_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _token()
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    browser_urls: list[str] = []
    seen: list[str | None] = []
    monkeypatch.setattr(access_auth_module, "_client_caller_auth", _fake_auth_factory(browser_urls))

    with sf.Client(
        engine_url=_PLAIN_ENGINE,
        scoreboard_url=_SCOREBOARD,
        http_transport=httpx.MockTransport(_recording(seen, _challenge)),
    ) as client:
        with pytest.raises(sf.AuthenticationError) as caught:
            client.models.list()
        assert client._engine_auth.websocket_headers() == {}

    _assert_requires_https(caught.value, token)
    assert seen == [None]
    assert browser_urls == []


@pytest.mark.asyncio
async def test_async_plain_http_engine_challenge_never_receives_the_env_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _token()
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    browser_urls: list[str] = []
    seen: list[str | None] = []
    monkeypatch.setattr(access_auth_module, "_client_caller_auth", _fake_auth_factory(browser_urls))

    async with sf.AsyncClient(
        engine_url=_PLAIN_ENGINE,
        scoreboard_url=_SCOREBOARD,
        http_transport=httpx.MockTransport(_recording(seen, _challenge)),
    ) as client:
        with pytest.raises(sf.AuthenticationError) as caught:
            await client.models.list()
        assert await client._engine_auth.websocket_headers_async() == {}

    _assert_requires_https(caught.value, token)
    assert seen == [None]
    assert browser_urls == []


def test_websocket_reauthentication_on_plain_http_never_adopts_the_token() -> None:
    """The websocket path learns the audience through login()/reauthenticate() discovery."""

    token = _token()
    store = _AccessTokenStore()
    access_auth_module._seed_access_tokens(
        store,
        {"SCREAMINGFACE_ACCESS_TOKEN": token},
        monotonic_now=time.monotonic(),
        wall_now=time.time(),
    )
    browser_urls: list[str] = []
    auth = _fake_auth_factory(browser_urls, _challenge)(_PLAIN_ENGINE, token_store=store)
    try:
        for attempt in (auth.login, auth.reauthenticate):
            with pytest.raises(sf.AuthenticationError) as caught:
                attempt(timeout=1.0)
            _assert_requires_https(caught.value, token)
            assert auth.websocket_headers() == {}
        assert auth.authenticated is False
    finally:
        auth.close()
    assert browser_urls == []


@pytest.mark.asyncio
async def test_async_websocket_reauthentication_on_plain_http_never_adopts_the_token() -> None:
    token = _token()
    store = _AccessTokenStore()
    access_auth_module._seed_access_tokens(
        store,
        {"SCREAMINGFACE_ACCESS_TOKEN": token},
        monotonic_now=time.monotonic(),
        wall_now=time.time(),
    )
    browser_urls: list[str] = []
    auth = _fake_auth_factory(browser_urls, _challenge)(_PLAIN_ENGINE, token_store=store)
    try:
        for attempt in (auth.login_async, auth.reauthenticate_async):
            with pytest.raises(sf.AuthenticationError) as caught:
                await attempt(timeout=1.0)
            _assert_requires_https(caught.value, token)
            assert await auth.websocket_headers_async() == {}
    finally:
        auth.close()
    assert browser_urls == []


def test_local_http_stack_without_a_challenge_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _token()
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    browser_urls: list[str] = []
    seen: list[str | None] = []
    monkeypatch.setattr(access_auth_module, "_client_caller_auth", _fake_auth_factory(browser_urls))

    with sf.Client(
        engine_url=_LOCAL_ENGINE,
        scoreboard_url=_SCOREBOARD,
        http_transport=httpx.MockTransport(_recording(seen, _models)),
    ) as client:
        assert list(client.models.list()) == []
        assert client._engine_auth.websocket_headers() == {}

    assert seen == [None]
    assert browser_urls == []


@pytest.mark.asyncio
async def test_async_local_http_stack_without_a_challenge_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _token()
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    browser_urls: list[str] = []
    seen: list[str | None] = []
    monkeypatch.setattr(access_auth_module, "_client_caller_auth", _fake_auth_factory(browser_urls))

    async with sf.AsyncClient(
        engine_url=_LOCAL_ENGINE,
        scoreboard_url=_SCOREBOARD,
        http_transport=httpx.MockTransport(_recording(seen, _models)),
    ) as client:
        assert list(await client.models.list()) == []
        assert await client._engine_auth.websocket_headers_async() == {}

    assert seen == [None]
    assert browser_urls == []

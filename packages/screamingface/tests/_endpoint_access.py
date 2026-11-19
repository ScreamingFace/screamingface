"""Access fakes for the endpoint() tests (EB-2 to EB-7).

A hosted client that signs in with no browser and no network.

AIDEV-NOTE: the same fake as tests/test_access_env_token.py. SCREAMINGFACE_ACCESS_TOKEN puts the
token in the token store, and a mock transport answers the Access discovery request of login().
"""

from __future__ import annotations

import base64
import inspect
import json
import time
from collections.abc import Callable

import httpx
import pytest
from _chat_engine import Handler
from _chat_stream import AsyncHandler

import screamingface as sf
from screamingface._access import auth as access_auth_module
from screamingface._access.auth import _AccessTokenStore, _CloudflareAccessAuth

AUDIENCE = "a" * 64
HOSTED_URL = "https://engine.test"
TOKEN_HEADER = "Cf-Access-Token"


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def access_jwt() -> str:
    """A token for AUDIENCE that expires in 15 minutes; its signature is not checked."""

    header = _b64u(json.dumps({"alg": "RS256"}).encode())
    payload = _b64u(json.dumps({"exp": time.time() + 900, "aud": AUDIENCE}).encode())
    return f"{header}.{payload}.sig"


def challenge(_request: httpx.Request) -> httpx.Response:
    """The discovery answer of an Engine behind Access."""

    return httpx.Response(403, headers={"cf-access-aud": AUDIENCE})


def no_access(_request: httpx.Request) -> httpx.Response:
    """The discovery answer of an https Engine with no Access; login() refuses it."""

    return httpx.Response(200)


def fake_access(monkeypatch: pytest.MonkeyPatch, discovery: Handler = challenge) -> list[str]:
    """Each Client made after this call answers its Access discovery with `discovery`.

    The list collects the browser URLs of a sign-in; a test asserts that it stays empty.
    """

    browser_urls: list[str] = []

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

    monkeypatch.setattr(access_auth_module, "_client_caller_auth", auth)
    return browser_urls


def signed_in(monkeypatch: pytest.MonkeyPatch) -> tuple[str, list[str]]:
    """SCREAMINGFACE_ACCESS_TOKEN holds a usable token, and the sign-in opens no browser."""

    token = access_jwt()
    monkeypatch.setenv("SCREAMINGFACE_ACCESS_TOKEN", token)
    return token, fake_access(monkeypatch)


def hosted_client(handler: Handler, requests: list[httpx.Request]) -> sf.Client:
    """A Client whose Engine is HOSTED_URL; every request it receives lands in `requests`."""

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return sf.Client(
        engine_url=HOSTED_URL,
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(respond),
        save_results=False,
    )


def async_hosted_client(handler: AsyncHandler, requests: list[httpx.Request]) -> sf.AsyncClient:
    """An AsyncClient whose Engine is HOSTED_URL; every request it receives lands in `requests`."""

    async def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        answer = handler(request)
        if inspect.isawaitable(answer):
            return await answer
        return answer

    return sf.AsyncClient(
        engine_url=HOSTED_URL,
        scoreboard_url="http://scoreboard.test",
        http_transport=httpx.MockTransport(respond),
        save_results=False,
    )

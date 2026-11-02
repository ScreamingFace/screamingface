"""After a reactive Access challenge, the browser login returns to the challenged path (OME-1649).

WHY: staging and production protect the leaderboard with an Access application that covers only
`/v1/scores`; `/` is public. The edge transfers the application token only on a request that
Access gates, so a login whose `redirect_url` is the origin root never completes: the browser
lands on the public dashboard and the SDK polls until `access_login_timeout`. The challenged path
is inside the application by construction: Access just challenged it, and Access rules apply to
every HTTP method, so the browser's GET to that path runs through the same application.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from urllib.parse import SplitResult, parse_qs, unquote, urlsplit

import httpx
import pytest
from nacl.public import Box, PrivateKey, PublicKey

from screamingface._access.auth import _CloudflareAccessAuth
from screamingface._access.contract import _access_authorization_url
from screamingface._core.wire import _REPLAY_SAFE

_SCOREBOARD = "https://scoreboard.example"
_ENGINE = "https://engine.example"
_AUDIENCE = "b" * 64
_LOGIN = f"https://team.cloudflareaccess.com/cdn-cgi/access/login?kid={_AUDIENCE}"
_TRANSFER_STORE = "https://login.cloudflareaccess.org"
_TRANSFER_KEYS = {"token", "aud", "send_org_token", "edge_token_transfer"}


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _jwt(exp: float) -> str:
    header = _b64u(json.dumps({"alg": "RS256"}).encode())
    payload = _b64u(json.dumps({"exp": exp, "aud": _AUDIENCE}).encode())
    return f"{header}.{payload}.{_b64u(b'signature')}"


@dataclass
class _Clock:
    monotonic: float = 100.0
    wall: float = 1_800_000_000.0

    def now(self) -> float:
        return self.monotonic

    def wall_now(self) -> float:
        return self.wall

    def sleep(self, seconds: float) -> None:
        self.monotonic += seconds
        self.wall += seconds


@dataclass
class _PathScopedAccess:
    """Cloudflare's side: the transfer store, an Engine gated on its whole host, and a
    Scoreboard gated only under `/v1/scores` (the staging and production shape)."""

    clock: _Clock = field(default_factory=_Clock)
    server_key: PrivateKey = field(default_factory=PrivateKey.generate)
    browser_urls: list[str] = field(default_factory=list)
    seen_tokens: list[str | None] = field(default_factory=list)
    token: str = ""

    def __post_init__(self) -> None:
        self.token = _jwt(self.clock.wall + 900)

    def access(self, request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(f"{_TRANSFER_STORE}/transfer/"):
            return self._transfer(request)
        if request.url.host == "engine.example":
            return httpx.Response(302, headers={"location": _LOGIN})
        return httpx.Response(200)

    def origin(self, request: httpx.Request) -> httpx.Response:
        presented = request.headers.get("Cf-Access-Token")
        self.seen_tokens.append(presented)
        if request.url.path.startswith("/v1/scores") and presented != self.token:
            return httpx.Response(302, headers={"location": _LOGIN})
        return httpx.Response(201 if request.method == "POST" else 200)

    def auth(self, origin: str = _SCOREBOARD) -> _CloudflareAccessAuth:
        return _CloudflareAccessAuth(
            origin,
            access_transport=httpx.MockTransport(self.access),
            browser_presenter=self.browser_urls.append,
            clock=self.clock.now,
            wall_clock=self.clock.wall_now,
            sleep=self.clock.sleep,
        )

    def _transfer(self, request: httpx.Request) -> httpx.Response:
        public_text = unquote(request.url.path.rsplit("/", 1)[-1])
        peer = PublicKey(base64.urlsafe_b64decode(public_text))
        body = json.dumps({"app_token": self.token}).encode()
        encrypted = bytes(Box(self.server_key, peer).encrypt(body))
        service_key = base64.urlsafe_b64encode(bytes(self.server_key.public_key)).decode()
        return httpx.Response(
            200,
            headers={"service-public-key": service_key},
            content=base64.b64encode(encrypted),
        )


def _only_login(access: _PathScopedAccess) -> tuple[SplitResult, dict[str, list[str]]]:
    """The single browser URL's `redirect_url`, split, plus the outer transfer query."""

    assert len(access.browser_urls) == 1
    outer = urlsplit(access.browser_urls[0])
    assert (outer.scheme, outer.path) == ("https", "/cdn-cgi/access/cli")
    query = parse_qs(outer.query)
    return urlsplit(query["redirect_url"][0]), query


def _assert_returns_to(
    access: _PathScopedAccess,
    host: str,
    path: str,
) -> None:
    redirect, query = _only_login(access)
    # INVARIANT: the login starts and ends on the configured origin's host; only the path moves.
    assert urlsplit(access.browser_urls[0]).netloc == host
    assert (redirect.scheme, redirect.netloc, redirect.path) == ("https", host, path)
    redirect_query = parse_qs(redirect.query)
    # INVARIANT: the redirect carries the transfer parameters and nothing from the caller.
    assert set(redirect_query) == _TRANSFER_KEYS
    assert redirect_query["token"] == query["token"]
    assert redirect_query["aud"] == [_AUDIENCE]


def test_challenged_submit_logs_in_through_the_challenged_path() -> None:
    # STORY: as a researcher, `sf.leaderboards.submit()` publishes after one browser login.
    access = _PathScopedAccess()
    auth = access.auth()

    with httpx.Client(transport=httpx.MockTransport(access.origin), auth=auth) as client:
        response = client.post(
            f"{_SCOREBOARD}/v1/scores",
            json={"run_id": "run-1"},
            extensions={_REPLAY_SAFE: True},
        )

    assert response.status_code == 201
    assert access.seen_tokens == [None, access.token]
    _assert_returns_to(access, "scoreboard.example", "/v1/scores")
    auth.close()


@pytest.mark.asyncio
async def test_async_challenged_submit_logs_in_through_the_challenged_path() -> None:
    access = _PathScopedAccess()
    auth = access.auth()

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(access.origin),
        auth=auth,
    ) as client:
        response = await client.post(
            f"{_SCOREBOARD}/v1/scores",
            json={"run_id": "run-1"},
            extensions={_REPLAY_SAFE: True},
        )

    assert response.status_code == 201
    assert access.seen_tokens == [None, access.token]
    _assert_returns_to(access, "scoreboard.example", "/v1/scores")
    auth.close()


def test_challenged_path_keeps_its_wire_encoding_and_drops_the_caller_query() -> None:
    access = _PathScopedAccess()
    auth = access.auth()

    with httpx.Client(transport=httpx.MockTransport(access.origin), auth=auth) as client:
        response = client.get(
            f"{_SCOREBOARD}/v1/scores/score%201?view=full",
            extensions={_REPLAY_SAFE: True},
        )

    assert response.status_code == 200
    _assert_returns_to(access, "scoreboard.example", "/v1/scores/score%201")
    auth.close()


def test_authorization_url_uses_the_given_redirect_path_verbatim() -> None:
    url = _access_authorization_url(
        f"{_SCOREBOARD}/tenant",
        _AUDIENCE,
        "public-key==",
        redirect_path="/v1/scores/a%20b",
    )

    outer = urlsplit(url)
    redirect = urlsplit(parse_qs(outer.query)["redirect_url"][0])
    assert (outer.netloc, outer.path) == ("scoreboard.example", "/cdn-cgi/access/cli")
    assert (redirect.netloc, redirect.path) == ("scoreboard.example", "/v1/scores/a%20b")


def test_explicit_login_keeps_the_origin_path() -> None:
    # WHY: the Engine application covers its whole host, so a login started without a
    # challenge has no better path than the configured origin.
    access = _PathScopedAccess()
    auth = access.auth(_ENGINE)

    auth.login(timeout=10)

    assert auth.authenticated is True
    redirect, _query = _only_login(access)
    assert (redirect.netloc, redirect.path) == ("engine.example", "")
    auth.close()

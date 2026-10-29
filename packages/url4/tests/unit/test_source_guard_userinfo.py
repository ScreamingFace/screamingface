"""The url4 source guard refuses URLs with embedded credentials (userinfo).

No network: DNS answers come from an injected resolver, and the guarded transport's per-host
connection is replaced by an ``httpx.MockTransport`` that records everything put on the wire.

FEATURE: url4 source fetch destination guard (OME-1544) — credentialed URLs (OME-1552 acceptance).
STORY: as an operator, an expression that names ``https://user:pass@host/x`` — directly or through
a redirect — is refused before any DNS lookup or connection, so no ``Authorization`` is ever sent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io._source_policy import SourceGuard, check_url
from url4.io.http import HttpIOLayer
from url4.io.layer import FetchRequest

PUBLIC = "93.184.216.34"

Handler = Callable[[httpx.Request], httpx.Response]

CREDENTIALED = [
    "https://user:pass@example.com/x",  # username and password
    "https://user@example.com/x",  # username only
    "https://@example.com/x",  # empty userinfo (httpx drops it; the guard still refuses)
    "https://:@example.com/x",  # empty username and password
    "https://user:pass@93.184.216.34/x",  # on an allowed IP literal too
]

NOT_USERINFO = [
    "https://example.com/a%40b",
    "https://example.com/x?to=user%40example.org",
    "https://example.com/x#frag%40ment",
]


class _Net:
    def __init__(self) -> None:
        self.dns: dict[str, list[str]] = {"example.com": [PUBLIC], "other.example": [PUBLIC]}
        self.lookups: list[str] = []
        self.sent: list[httpx.Request] = []
        self.handler: Handler = lambda _r: httpx.Response(200, text="BODY")

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.lookups.append(host)
        return self.dns[host]

    def transport(self) -> httpx.AsyncBaseTransport:
        def record(request: httpx.Request) -> httpx.Response:
            self.sent.append(request)
            return self.handler(request)

        return httpx.MockTransport(record)


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> _Net:
    fake = _Net()
    monkeypatch.setattr(guarded_mod, "_inner_transport", fake.transport)
    return fake


def _io(net: _Net) -> HttpIOLayer:
    return HttpIOLayer(guard=SourceGuard(), resolver=net.resolve)


def _assert_refused(error: ResolutionError) -> None:
    assert error.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert error.permanent is True
    # The refusal never echoes the credentials it refused.
    assert "pass" not in str(error)
    assert "user:" not in str(error)
    assert "user@" not in str(error)


# --- the policy, without a transport ------------------------------------------------------


@pytest.mark.parametrize("url", CREDENTIALED)
def test_check_url_refuses_embedded_credentials(url: str) -> None:
    with pytest.raises(ResolutionError) as caught:
        check_url(url, SourceGuard())
    _assert_refused(caught.value)


@pytest.mark.parametrize("url", NOT_USERINFO)
def test_check_url_allows_a_percent_encoded_at_outside_the_authority(url: str) -> None:
    check_url(url, SourceGuard())


def test_credentials_are_refused_even_for_an_allowlisted_peer() -> None:
    with pytest.raises(ResolutionError) as caught:
        check_url(
            "https://user:pass@node.example/v1",
            SourceGuard(peer_hosts=frozenset({"node.example"})),
            peer=True,
        )
    _assert_refused(caught.value)


# --- the owned client: refused before any I/O ---------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("url", CREDENTIALED)
async def test_fetch_refuses_credentials_before_dns_or_connection(net: _Net, url: str) -> None:
    async with _io(net) as io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch(url, relative=False)
    _assert_refused(caught.value)
    assert net.lookups == []
    assert net.sent == []  # nothing on the wire, so no Authorization header either


@pytest.mark.asyncio
@pytest.mark.parametrize("url", CREDENTIALED)
async def test_fetch_ex_refuses_credentials_before_dns_or_connection(net: _Net, url: str) -> None:
    async with _io(net) as io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch_ex(FetchRequest(target=url, relative=False))
    _assert_refused(caught.value)
    assert net.lookups == []
    assert net.sent == []


@pytest.mark.asyncio
async def test_a_credentialed_url4_peer_is_refused_before_any_io(net: _Net) -> None:
    io = HttpIOLayer(guard=SourceGuard(peer_hosts=frozenset({"example.com"})), resolver=net.resolve)
    async with io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch("url4://user:pass@example.com/v1", relative=False)
    _assert_refused(caught.value)
    assert net.lookups == []
    assert net.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("url", NOT_USERINFO)
async def test_a_percent_encoded_at_in_path_or_query_is_fetched(net: _Net, url: str) -> None:
    async with _io(net) as io:
        assert await io.fetch(url, relative=False) == "BODY"
    (sent,) = net.sent
    assert sent.headers["host"] == "example.com"
    assert "authorization" not in sent.headers


# --- redirects: a credentialed Location is refused on its hop -----------------------------


def _redirect_to(location: str) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(200, text="LANDED")

    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "https://user:pass@other.example/landing",
        "https://user@other.example/landing",
        "https://user:pass@example.com/landing",  # same host, credentials added
        "//user:pass@other.example/landing",  # scheme-relative
    ],
)
async def test_a_redirect_to_a_credentialed_location_is_refused(net: _Net, location: str) -> None:
    net.handler = _redirect_to(location)
    async with _io(net) as io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch("https://example.com/", relative=False)
    _assert_refused(caught.value)
    assert [r.url.path for r in net.sent] == ["/"]  # only the first hop reached the wire
    assert net.lookups == ["example.com"]  # the credentialed hop was refused before DNS
    assert all("authorization" not in r.headers for r in net.sent)


@pytest.mark.asyncio
async def test_the_transport_alone_refuses_a_credentialed_request(net: _Net) -> None:
    # A request built outside HttpIOLayer (no pre-check): the transport still refuses it.
    transport = guarded_mod.GuardedTransport(SourceGuard(), resolver=net.resolve)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ResolutionError) as caught:
            await client.get("https://user:pass@example.com/x")
    _assert_refused(caught.value)
    assert net.lookups == []
    assert net.sent == []


# --- PR #1605 review 1: a malformed credentialed authority never reaches an error message ---

USER, SECRET = "alice", "s3cret"

MALFORMED_CREDENTIALED = [
    f"https://{USER}:{SECRET}@[::1",  # unclosed bracket, no path
    f"https://{USER}:{SECRET}@[::1/x",  # unclosed bracket before a path
    f"https://{USER}:{SECRET}@[not-an-ip]/x",  # bracketed non-address
    f"https://{USER}:{SECRET}@[::1]:bad/x",  # bracketed host, non-numeric port
    f"https://{USER}:{SECRET}@example.com:port/x",  # named host, non-numeric port
]


def _whole_chain(error: BaseException) -> list[BaseException]:
    """``error`` and every exception reachable through ``__cause__`` / ``__context__``."""
    seen: list[BaseException] = []
    pending: list[BaseException | None] = [error]
    while pending:
        current = pending.pop()
        if current is None or any(current is known for known in seen):
            continue
        seen.append(current)
        pending += [current.__cause__, current.__context__]
    return seen


def _assert_no_secret(error: BaseException) -> None:
    for link in _whole_chain(error):
        for text in (str(link), repr(link), *getattr(link, "__notes__", [])):
            assert SECRET not in text
            assert USER not in text


@pytest.mark.parametrize("url", MALFORMED_CREDENTIALED)
def test_check_url_refuses_a_malformed_credentialed_authority(url: str) -> None:
    with pytest.raises(ResolutionError) as caught:
        check_url(url, SourceGuard())
    _assert_refused(caught.value)
    _assert_no_secret(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", MALFORMED_CREDENTIALED)
async def test_fetch_refuses_a_malformed_credentialed_url_without_echoing_it(
    net: _Net, url: str
) -> None:
    async with _io(net) as io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch(url, relative=False)
    _assert_refused(caught.value)
    _assert_no_secret(caught.value)
    assert net.lookups == []
    assert net.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("url", MALFORMED_CREDENTIALED)
async def test_an_invalid_target_error_never_carries_its_userinfo(url: str) -> None:
    # An injected client skips the guard: httpx itself rejects the target, and the wrapped
    # error (message, repr and exception chain) must still not repeat the credentials.
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, text="BODY")

    io = HttpIOLayer(client=httpx.AsyncClient(transport=httpx.MockTransport(record)))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch(url, relative=False)
    _assert_no_secret(caught.value)
    assert sent == []


# --- PR #1605 review 2: an empty-userinfo Location is refused before httpx normalizes it ----


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "https://@other.example/landing",  # empty userinfo, absolute
        "//@other.example/landing",  # empty userinfo, scheme-relative
        "https://:@other.example/landing",  # empty username and password
    ],
)
async def test_a_redirect_to_an_empty_userinfo_location_is_refused(
    net: _Net, location: str
) -> None:
    net.handler = _redirect_to(location)
    async with _io(net) as io:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch("https://example.com/", relative=False)
    _assert_refused(caught.value)
    assert [r.url.path for r in net.sent] == ["/"]  # the second hop never reached the wire
    assert net.lookups == ["example.com"]  # other.example was never looked up

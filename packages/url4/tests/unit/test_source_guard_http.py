"""The destination guard on HttpIOLayer's OWNED client (spec F1b, OME-1544; fixes OME-1704).

No network: DNS answers come from an injected resolver, and the guarded transport's per-host
connection is replaced by an ``httpx.MockTransport`` that sees exactly what would go on the wire
(the pinned address, the ``Host`` header and the TLS ``sni_hostname``).

FEATURE: url4 source fetch destination guard (OME-1544).
STORY: as an operator, an expression that names a private, loopback or metadata address — in any
spelling, through DNS, or through a redirect — is refused before a connection is opened there.
"""

from __future__ import annotations

import asyncio
import functools
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import httpx
import pytest

import url4.io._guarded_transport as guarded_mod
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.http import HttpIOLayer, SourceGuard
from url4.io.layer import FetchRequest
from url4.peer._http import status_for

PUBLIC = "93.184.216.34"
PUBLIC_2 = "93.184.216.35"

Handler = Callable[[httpx.Request], httpx.Response]


class _Net:
    """The fake network: a resolver table plus what each pinned connection received."""

    def __init__(self) -> None:
        self.dns: dict[str, list[list[str]]] = {}
        self.lookups: list[str] = []
        self.sent: list[httpx.Request] = []
        self.handler: Handler = lambda _r: httpx.Response(200, text="BODY")

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.lookups.append(host)
        answers = self.dns[host]
        return answers.pop(0) if len(answers) > 1 else answers[0]

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


def _io(net: _Net, **guard: Any) -> HttpIOLayer:
    return HttpIOLayer(guard=SourceGuard(**guard), resolver=net.resolve)


async def _blocked(io: HttpIOLayer, url: str, code: str = ErrorCode.SOURCE_DESTINATION_BLOCKED):
    try:
        with pytest.raises(ResolutionError) as caught:
            await io.fetch(url, relative=False)
    finally:
        await io.aclose()
    assert caught.value.code == code
    return caught.value


# --- allowed fetches: pinned to the vetted address, SNI and Host kept --------------------


@pytest.mark.asyncio
async def test_public_name_is_fetched_on_the_vetted_ip_with_sni_and_host(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    async with _io(net) as io:
        assert await io.fetch("https://example.com/a.txt", relative=False) == "BODY"
    (sent,) = net.sent
    assert sent.url.host == PUBLIC  # the connection goes to the vetted address
    assert sent.url.path == "/a.txt"
    assert sent.headers["host"] == "example.com"
    assert sent.extensions["sni_hostname"] == "example.com"
    assert net.lookups == ["example.com"]


@pytest.mark.asyncio
async def test_allowed_public_ip_literal_is_fetched_without_a_lookup(net: _Net) -> None:
    async with _io(net) as io:
        assert await io.fetch(f"https://{PUBLIC}/", relative=False) == "BODY"
    assert net.lookups == []
    assert net.sent[0].url.host == PUBLIC
    assert "sni_hostname" not in net.sent[0].extensions


@pytest.mark.asyncio
async def test_dns_rebinding_cannot_move_a_vetted_connection(net: _Net) -> None:
    # The first answer is public, the next one private: the first fetch is pinned to the vetted
    # public IP (one lookup, no second resolution at connect time), the next one is refused.
    net.dns["rebind.example"] = [[PUBLIC], ["127.0.0.1"]]
    io = _io(net)
    assert await io.fetch("https://rebind.example/", relative=False) == "BODY"
    assert net.lookups == ["rebind.example"]
    assert [r.url.host for r in net.sent] == [PUBLIC]
    assert net.sent[0].extensions["sni_hostname"] == "rebind.example"
    await _blocked(io, "https://rebind.example/")
    assert [r.url.host for r in net.sent] == [PUBLIC]  # nothing ever reached 127.0.0.1


@pytest.mark.asyncio
async def test_each_host_keeps_its_own_connection_pool(net: _Net) -> None:
    # WHY: two names on one IP must not share a TLS connection made with the other's SNI.
    net.dns["a.example"] = [[PUBLIC]]
    net.dns["b.example"] = [[PUBLIC]]
    async with _io(net) as io:
        await io.fetch("https://a.example/", relative=False)
        await io.fetch("https://b.example/", relative=False)
        guarded = io._get_client()._transport
        assert isinstance(guarded, guarded_mod.GuardedTransport)
        assert set(guarded._pools) == {"a.example", "b.example"}
    assert [r.extensions["sni_hostname"] for r in net.sent] == ["a.example", "b.example"]


# --- refused destinations ------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://10.0.0.1/",
        "https://[::1]/",
        "https://[::ffff:127.0.0.1]/",
        "https://[fc00::1]/",
        "https://169.254.169.254/latest/meta-data/",
        "https://100.64.0.1/",
        "https://2130706433/",
        "https://0177.0.0.1/",
        "https://0x7f.1/",
        "https://a@127.0.0.1/",
    ],
)
async def test_refused_address_literals_never_reach_the_wire(net: _Net, url: str) -> None:
    error = await _blocked(_io(net), url)
    assert error.permanent is True
    assert net.sent == [] and net.lookups == []


@pytest.mark.asyncio
async def test_a_name_resolving_to_a_private_address_is_refused(net: _Net) -> None:
    net.dns["internal.example"] = [["10.1.2.3"]]
    await _blocked(_io(net), "https://internal.example/")
    assert net.sent == []


@pytest.mark.asyncio
async def test_one_private_answer_among_public_ones_refuses_the_name(net: _Net) -> None:
    net.dns["mixed.example"] = [[PUBLIC, "192.168.0.10"]]
    await _blocked(_io(net), "https://mixed.example/")
    assert net.sent == []


@pytest.mark.asyncio
async def test_a_name_with_no_answer_is_a_resolution_failure(net: _Net) -> None:
    net.dns["empty.example"] = [[]]
    io = _io(net)
    with pytest.raises(ResolutionError) as caught:
        await io.fetch("https://empty.example/", relative=False)
    await io.aclose()
    assert caught.value.code == ErrorCode.RESOLUTION_FAILED


@pytest.mark.asyncio
async def test_http_scheme_is_off_by_default(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    await _blocked(_io(net), "http://example.com/")
    assert net.sent == []
    async with _io(net, allow_http=True) as io:
        assert await io.fetch("http://example.com/", relative=False) == "BODY"


@pytest.mark.asyncio
async def test_loopback_only_through_the_escape_hatch(net: _Net) -> None:
    async with _io(net, allow_loopback=True) as io:
        assert await io.fetch("https://127.0.0.1/", relative=False) == "BODY"
    await _blocked(_io(net, allow_loopback=True), "https://10.0.0.1/")


# --- redirects: every hop re-checked ---------------------------------------------------------


def _redirects(chain: dict[str, str]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        location = chain.get(request.url.path)
        if location is None:
            return httpx.Response(200, text="LANDED")
        return httpx.Response(302, headers={"Location": location})

    return handler


@pytest.mark.asyncio
async def test_public_to_private_redirect_is_refused(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = _redirects({"/": "https://10.0.0.1/admin"})
    await _blocked(_io(net), "https://example.com/")
    assert [r.url.host for r in net.sent] == [PUBLIC]


@pytest.mark.asyncio
async def test_relative_location_to_a_private_host_is_refused(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.dns["internal.example"] = [["10.9.9.9"]]
    net.handler = _redirects({"/": "//internal.example/secret"})
    await _blocked(_io(net), "https://example.com/")
    assert [r.url.host for r in net.sent] == [PUBLIC]


@pytest.mark.asyncio
async def test_relative_path_location_on_the_same_host_is_followed(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = _redirects({"/": "/moved"})
    async with _io(net) as io:
        assert await io.fetch("https://example.com/", relative=False) == "LANDED"
    assert [r.url.path for r in net.sent] == ["/", "/moved"]


@pytest.mark.asyncio
async def test_three_hops_are_followed_and_the_fourth_is_refused(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = _redirects({"/0": "/1", "/1": "/2", "/2": "/3"})
    async with _io(net) as io:
        assert await io.fetch("https://example.com/0", relative=False) == "LANDED"
    net.handler = _redirects({"/0": "/1", "/1": "/2", "/2": "/3", "/3": "/4"})
    error = await _blocked(_io(net), "https://example.com/0", ErrorCode.SOURCE_REDIRECT_LIMIT)
    assert error.permanent is True


@pytest.mark.asyncio
async def test_https_to_http_redirect_is_refused_even_with_http_allowed(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = _redirects({"/": "http://example.com/plain"})
    await _blocked(_io(net, allow_http=True), "https://example.com/")
    assert [r.url.scheme for r in net.sent] == ["https"]


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x/"])
async def test_non_http_location_scheme_is_refused(net: _Net, location: str) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = _redirects({"/": location})
    await _blocked(_io(net), "https://example.com/")


# --- size and time ----------------------------------------------------------------------------


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, hang_after: int | None = None) -> None:
        self.chunks = chunks
        self.hang_after = hang_after
        self.yielded = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, chunk in enumerate(self.chunks):
            if self.hang_after is not None and index >= self.hang_after:
                await asyncio.Event().wait()  # the slow drip: never sends the next chunk
            self.yielded += 1
            yield chunk


def _gzip_chunks(decoded: int, size: int) -> list[bytes]:
    compressor = zlib.compressobj(wbits=31)
    data = compressor.compress(b"\0" * decoded) + compressor.flush()
    return [data[i : i + size] for i in range(0, len(data), size)]


@pytest.mark.asyncio
async def test_oversize_decoded_gzip_is_aborted_mid_stream(net: _Net) -> None:
    # ~10 KiB on the wire inflates to 10 MiB: the cap counts DECODED bytes and stops reading.
    net.dns["example.com"] = [[PUBLIC]]
    stream = _Chunks(_gzip_chunks(10 * 1024 * 1024, 256))
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=stream
    )
    error = await _blocked(
        _io(net, max_bytes=64 * 1024), "https://example.com/", ErrorCode.SOURCE_TOO_LARGE
    )
    assert error.permanent is True
    assert stream.yielded < len(stream.chunks)  # aborted, not read to the end


@pytest.mark.asyncio
async def test_a_body_at_the_cap_is_kept(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = lambda _r: httpx.Response(200, content=b"x" * 16)
    async with _io(net, max_bytes=16) as io:
        assert await io.fetch("https://example.com/", relative=False) == "x" * 16


@pytest.mark.asyncio
async def test_an_oversize_redirect_body_is_aborted_too(net: _Net) -> None:
    # httpx reads a redirect body before following it; the transport's raw cap bounds it.
    net.dns["example.com"] = [[PUBLIC]]
    stream = _Chunks([b"x" * 1024] * 64)
    net.handler = lambda _r: httpx.Response(302, headers={"Location": "/next"}, stream=stream)
    await _blocked(_io(net, max_bytes=4096), "https://example.com/", ErrorCode.SOURCE_TOO_LARGE)
    assert stream.yielded < len(stream.chunks)


class _SyncOnly(httpx.SyncByteStream):
    def __iter__(self):
        yield b"sync"


@pytest.mark.asyncio
async def test_a_body_the_cap_cannot_wrap_is_refused(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = lambda _r: httpx.Response(200, stream=_SyncOnly())
    io = _io(net)
    with pytest.raises(TypeError, match="not async"):
        await io.fetch("https://example.com/", relative=False)
    await io.aclose()


@pytest.mark.asyncio
async def test_slow_drip_hits_the_total_deadline(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = lambda _r: httpx.Response(200, stream=_Chunks([b"a", b"b"], hang_after=1))
    error = await _blocked(
        _io(net, total_timeout=0.2), "https://example.com/", ErrorCode.SOURCE_TIMEOUT
    )
    assert error.permanent is False  # retryable


@pytest.mark.asyncio
async def test_connect_timeout_is_a_source_timeout(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    net.handler = refuse
    error = await _blocked(_io(net), "https://example.com/", ErrorCode.SOURCE_TIMEOUT)
    assert error.permanent is False


@pytest.mark.asyncio
async def test_owned_client_uses_the_connect_timeout(net: _Net) -> None:
    async with _io(net, connect_timeout=2.5) as io:
        assert io._get_client().timeout.connect == 2.5


@pytest.mark.asyncio
async def test_environment_proxies_are_ignored(net: _Net, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://10.0.0.99:3128")
    net.dns["example.com"] = [[PUBLIC]]
    async with _io(net) as io:
        assert io._get_client().trust_env is False
        assert await io.fetch("https://example.com/", relative=False) == "BODY"
    assert [r.url.host for r in net.sent] == [PUBLIC]  # straight to the origin, not the proxy


# --- url4:// remote-node calls: peer allowlist + the same address rules --------------------


@pytest.mark.asyncio
async def test_url4_peer_not_on_the_allowlist_is_refused(net: _Net) -> None:
    net.dns["node.example"] = [[PUBLIC]]
    await _blocked(_io(net), "url4://node.example/v1?q=(a)!b")  # default allowlist: empty
    assert net.sent == [] and net.lookups == []


@pytest.mark.asyncio
async def test_allowlisted_url4_peer_is_called_over_https(net: _Net) -> None:
    net.dns["node.example"] = [[PUBLIC]]
    async with _io(net, peer_hosts=frozenset({"node.example"})) as io:
        assert await io.fetch("url4://node.example/v1?q=(a)!b", relative=False) == "BODY"
    (sent,) = net.sent
    assert (sent.url.scheme, sent.url.host, sent.headers["host"]) == (
        "https",
        PUBLIC,
        "node.example",
    )


@pytest.mark.asyncio
async def test_allowlisted_peer_still_obeys_the_address_rules(net: _Net) -> None:
    net.dns["node.example"] = [["10.0.0.7"]]
    await _blocked(_io(net, peer_hosts=frozenset({"node.example"})), "url4://node.example/v1")
    assert net.sent == []


@pytest.mark.asyncio
async def test_a_peer_redirect_off_the_allowlist_is_refused(net: _Net) -> None:
    net.dns["node.example"] = [[PUBLIC]]
    net.dns["elsewhere.example"] = [[PUBLIC_2]]
    net.handler = _redirects({"/v1": "https://elsewhere.example/v1"})
    await _blocked(_io(net, peer_hosts=frozenset({"node.example"})), "url4://node.example/v1")
    assert [r.url.host for r in net.sent] == [PUBLIC]


@pytest.mark.asyncio
async def test_peer_allowlist_does_not_gate_plain_https_sources(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    async with _io(net) as io:
        assert await io.fetch_ex(FetchRequest("https://example.com/")) is not None


# --- what stays outside the destination guard ------------------------------------------------


@pytest.mark.asyncio
async def test_relative_fetch_against_the_operator_base_url_is_trusted(net: _Net) -> None:
    # WHY: the operator chose base_url (typically the localhost node), not the expression.
    io = HttpIOLayer("http://127.0.0.1:9105", resolver=net.resolve)
    async with io:
        assert await io.fetch("/claude?q=(x)!go", relative=True) == "BODY"
    assert net.lookups == []
    assert net.sent[0].url.host == "127.0.0.1"


@pytest.mark.asyncio
async def test_a_redirect_off_the_trusted_base_url_is_guarded(net: _Net) -> None:
    net.handler = _redirects({"/claude": "https://169.254.169.254/latest"})
    io = HttpIOLayer("http://127.0.0.1:9105", resolver=net.resolve)
    with pytest.raises(ResolutionError) as caught:
        await io.fetch("/claude", relative=True)
    await io.aclose()
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED


@pytest.mark.asyncio
async def test_an_injected_client_keeps_the_size_cap() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=b"y" * 64))
    )
    io = HttpIOLayer(client=client, guard=SourceGuard(max_bytes=10))
    with pytest.raises(ResolutionError) as caught:
        await io.fetch("https://anything/", relative=False)
    assert caught.value.code == ErrorCode.SOURCE_TOO_LARGE
    await client.aclose()


@pytest.mark.asyncio
async def test_the_default_resolver_answers_a_numeric_host_without_network() -> None:
    answers = await guarded_mod.system_resolver("127.0.0.1", 443)
    assert "127.0.0.1" in answers


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ErrorCode.SOURCE_DESTINATION_BLOCKED, 422),
        (ErrorCode.SOURCE_REDIRECT_LIMIT, 422),
        (ErrorCode.SOURCE_TOO_LARGE, 413),
        (ErrorCode.SOURCE_TIMEOUT, 504),
    ],
)
def test_guard_codes_map_to_the_spec_statuses(code: ErrorCode, status: int) -> None:
    assert status_for(ResolutionError("x", code=code)) == status
    assert code.value.startswith("x.source_")


# --- resolver failures and direct transport use ----------------------------------------------


@pytest.mark.asyncio
async def test_a_resolver_failure_is_a_resolution_failure(net: _Net) -> None:
    async def broken(host: str, port: int) -> Sequence[str]:
        raise OSError("name or service not known")

    io = HttpIOLayer(resolver=broken)
    with pytest.raises(ResolutionError) as caught:
        await io.fetch("https://nowhere.example/", relative=False)
    await io.aclose()
    assert caught.value.code == ErrorCode.RESOLUTION_FAILED
    assert net.sent == []


@pytest.mark.asyncio
async def test_a_resolver_answer_that_is_not_an_address_is_refused(net: _Net) -> None:
    net.dns["odd.example"] = [["not-an-ip"]]
    await _blocked(_io(net), "https://odd.example/")
    assert net.sent == []


@pytest.mark.asyncio
async def test_the_transport_guards_a_request_built_outside_httpiolayer(net: _Net) -> None:
    # No FetchState extension: the transport still applies every address rule.
    transport = guarded_mod.GuardedTransport(SourceGuard(), resolver=net.resolve)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ResolutionError) as caught:
            await client.get("https://169.254.169.254/")
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert net.sent == []


@pytest.mark.asyncio
async def test_an_unparseable_base_url_trusts_nothing(net: _Net) -> None:
    io = HttpIOLayer("http://[::1", resolver=net.resolve)
    with pytest.raises(ResolutionError):
        await io.fetch("/claude", relative=True)
    await io.aclose()
    assert net.sent == []


@pytest.mark.asyncio
async def test_the_real_connection_factory_is_an_httpx_transport() -> None:
    transport = guarded_mod._inner_transport()
    assert isinstance(transport, httpx.AsyncHTTPTransport)
    await transport.aclose()


@pytest.mark.asyncio
async def test_an_injected_client_keeps_its_own_timeouts() -> None:
    # The total deadline belongs to the owned client; an injected one is its owner's to bound:
    # a reply that takes longer than total_timeout still lands.
    async def late(_request: httpx.Request) -> httpx.Response:
        ready = asyncio.Event()
        asyncio.get_running_loop().call_later(0.1, ready.set)
        await ready.wait()
        return httpx.Response(200, text="ok")

    client = httpx.AsyncClient(transport=httpx.MockTransport(late))
    io = HttpIOLayer(client=client, guard=SourceGuard(total_timeout=0.01))
    assert await io.fetch("https://anything/", relative=False) == "ok"
    await client.aclose()


# --- review hardening: only the first hop of a relative fetch is trusted (OME-1544) ------------


@pytest.mark.asyncio
async def test_redirect_into_base_origin_still_checked(net: _Net) -> None:
    # An expression-named public source must not reach the operator's loopback node by redirect.
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = _redirects({"/": "https://127.0.0.1:9105/admin"})
    io = HttpIOLayer("https://127.0.0.1:9105", resolver=net.resolve)
    await _blocked(io, "https://example.com/")
    assert [r.url.host for r in net.sent] == [PUBLIC]


@pytest.mark.asyncio
async def test_a_redirect_after_the_trusted_first_hop_is_checked(net: _Net) -> None:
    net.handler = _redirects({"/claude": "/elsewhere"})
    io = HttpIOLayer("https://127.0.0.1:9105", resolver=net.resolve)
    with pytest.raises(ResolutionError) as caught:
        await io.fetch("/claude", relative=True)
    await io.aclose()
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert [r.url.path for r in net.sent] == ["/claude"]


@pytest.mark.asyncio
async def test_an_absolute_target_on_the_base_origin_is_checked(net: _Net) -> None:
    # Trust follows the operator's relative fetch, not an expression that spells the origin out.
    io = HttpIOLayer("https://127.0.0.1:9105", resolver=net.resolve)
    await _blocked(io, "https://127.0.0.1:9105/admin")
    assert net.sent == []


@pytest.mark.asyncio
async def test_a_transport_without_fetch_state_trusts_no_origin(net: _Net) -> None:
    origin = ("https", "127.0.0.1", 9105)
    transport = guarded_mod.GuardedTransport(
        SourceGuard(), resolver=net.resolve, trusted=frozenset({origin})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ResolutionError) as caught:
            await client.get("https://127.0.0.1:9105/")
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert net.sent == []


# --- review hardening: bounded decoding, never a whole-chunk inflate (OME-1544) ----------------

_MIB = 1024 * 1024


@functools.cache
def _gzip_of_zeros(gib: int = 1) -> bytes:
    """``gib`` GiB of zeros, gzipped (about 1 MB on the wire per GiB)."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    block = b"\0" * _MIB
    parts = [compressor.compress(block) for _ in range(gib * 1024)]
    return b"".join([*parts, compressor.flush()])


def _gzip(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, 31)
    return compressor.compress(data) + compressor.flush()


def _split(data: bytes, size: int = 64 * 1024) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


async def _peak_while_blocked(net: _Net, chunks: list[bytes], encoding: str, limit: int) -> int:
    stream = _Chunks(chunks)
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": encoding}, stream=stream
    )
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        await _blocked(
            _io(net, max_bytes=limit), "https://example.com/", ErrorCode.SOURCE_TOO_LARGE
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


@pytest.mark.asyncio
async def test_nested_gzip_bomb_peak_memory_bounded(net: _Net) -> None:
    # gzip(gzip(1 GiB)) is ~2 KB on the wire; stacked encodings are refused before decoding.
    net.dns["example.com"] = [[PUBLIC]]
    chunks = _split(_gzip(_gzip_of_zeros()))
    peak = await _peak_while_blocked(net, chunks, "gzip, gzip", _MIB)
    assert peak < 2 * _MIB


@pytest.mark.asyncio
async def test_single_gzip_bomb_peak_memory_bounded(net: _Net) -> None:
    # gzip(1 GiB) is ~1 MB on the wire: each 64 KiB chunk would inflate to ~64 MiB at once.
    net.dns["example.com"] = [[PUBLIC]]
    chunks = _split(_gzip_of_zeros())
    peak = await _peak_while_blocked(net, chunks, "gzip", _MIB)
    assert peak < 2 * _MIB


@pytest.mark.asyncio
async def test_the_guard_asks_for_an_identity_body(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    async with _io(net) as io:
        await io.fetch("https://example.com/", relative=False)
    assert net.sent[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("encoding", "body"),
    [
        ("gzip", _gzip(b"hello")),
        ("GZIP", _gzip(b"hello")),
        ("deflate", zlib.compress(b"hello")),  # zlib-wrapped deflate
        ("deflate", zlib.compress(b"hello", wbits=-15)),  # raw deflate, as some servers send
        ("identity, gzip", _gzip(b"hello")),
        ("identity", b"hello"),
    ],
)
async def test_a_single_encoded_layer_is_decoded(net: _Net, encoding: str, body: bytes) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": encoding}, stream=_Chunks(_split(body, 3))
    )
    async with _io(net) as io:
        assert await io.fetch("https://example.com/", relative=False) == "hello"


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip, gzip", "deflate, gzip", "br", "zstd", "compress"])
async def test_stacked_or_unsupported_encodings_are_refused(net: _Net, encoding: str) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    stream = _Chunks([b"anything"])
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": encoding}, stream=stream
    )
    error = await _blocked(_io(net), "https://example.com/", ErrorCode.SOURCE_TOO_LARGE)
    assert "Content-Encoding" in str(error)
    assert stream.yielded == 0  # refused before a byte is read


@pytest.mark.asyncio
async def test_a_corrupt_encoded_body_is_a_resolution_failure(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=_Chunks([b"not gzip at all"])
    )
    await _blocked(_io(net), "https://example.com/", ErrorCode.RESOLUTION_FAILED)


# --- review hardening 2: resource caps a crafted encoding cannot defeat (OME-1544) -------------

# A non-final stored deflate block of length 0 (BFINAL=0, BTYPE=00, LEN=0, NLEN=0xffff): five raw
# bytes that decode to nothing, repeatable forever.
_EMPTY_STORED_BLOCK = b"\x00\x00\x00\xff\xff"
_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff"


def _encoded(net: _Net, encoding: str, chunks: list[bytes]) -> _Chunks:
    net.dns["example.com"] = [[PUBLIC]]
    stream = _Chunks(chunks)
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": encoding}, stream=stream
    )
    return stream


@pytest.mark.asyncio
async def test_bytes_after_a_gzip_member_are_never_buffered(net: _Net) -> None:
    # One tiny member, then 64 MiB of trailing bytes: zlib parks them all in unused_data while
    # nothing decodes, so neither the decoded cap nor any raw count used to stop the read.
    stream = _encoded(net, "gzip", [_gzip(b"a" * 10)] + [b"\0" * (64 * 1024)] * 1024)
    tracemalloc.start()
    try:
        with pytest.raises(ResolutionError):
            async with _io(net, max_bytes=64 * 1024) as io:
                await io.fetch("https://example.com/", relative=False)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert stream.yielded < len(stream.chunks)
    assert peak < 2 * _MIB


@pytest.mark.asyncio
async def test_every_gzip_member_is_decoded(net: _Net) -> None:
    _encoded(net, "gzip", _split(_gzip(b"hel") + _gzip(b"lo"), 7))
    async with _io(net) as io:
        assert await io.fetch("https://example.com/", relative=False) == "hello"


@pytest.mark.asyncio
async def test_gzip_members_share_one_decoded_cap(net: _Net) -> None:
    member = _gzip(b"\0" * (32 * 1024))
    stream = _encoded(net, "gzip", [member] * 64)
    error = await _blocked(
        _io(net, max_bytes=64 * 1024), "https://example.com/", ErrorCode.SOURCE_TOO_LARGE
    )
    assert error.permanent is True
    assert stream.yielded < len(stream.chunks)


@pytest.mark.asyncio
async def test_bytes_after_a_deflate_stream_are_refused(net: _Net) -> None:
    _encoded(net, "deflate", [zlib.compress(b"hello"), b"trailing"])
    await _blocked(_io(net), "https://example.com/", ErrorCode.RESOLUTION_FAILED)


@pytest.mark.asyncio
async def test_bytes_after_a_gzip_member_that_are_not_gzip_are_refused(net: _Net) -> None:
    _encoded(net, "gzip", [_gzip(b"hello") + b"not a gzip member"])
    await _blocked(_io(net), "https://example.com/", ErrorCode.RESOLUTION_FAILED)


@pytest.mark.asyncio
async def test_raw_bytes_that_decode_to_nothing_hit_the_raw_cap(net: _Net) -> None:
    # Endless empty stored blocks: 4 MiB on the wire, zero decoded bytes. The raw count stops it.
    filler = _EMPTY_STORED_BLOCK * (64 * 1024 // len(_EMPTY_STORED_BLOCK))
    stream = _encoded(net, "gzip", [_GZIP_HEADER] + [filler] * 64)
    error = await _blocked(
        _io(net, max_bytes=64 * 1024), "https://example.com/", ErrorCode.SOURCE_TOO_LARGE
    )
    assert error.permanent is True
    assert stream.yielded < len(stream.chunks)


@pytest.mark.asyncio
async def test_raw_bytes_that_decode_to_nothing_still_hit_the_total_deadline(net: _Net) -> None:
    net.dns["example.com"] = [[PUBLIC]]
    stream = _Chunks([_GZIP_HEADER, _EMPTY_STORED_BLOCK, _EMPTY_STORED_BLOCK], hang_after=2)
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=stream
    )
    await _blocked(_io(net, total_timeout=0.2), "https://example.com/", ErrorCode.SOURCE_TIMEOUT)


@pytest.mark.asyncio
async def test_identity_raw_cap_is_the_decoded_cap(net: _Net) -> None:
    # Stripped encoding headers cannot lift the raw cap: an identity body is capped at max_bytes.
    net.dns["example.com"] = [[PUBLIC]]
    stream = _Chunks([b"x" * 1024] * 64)
    net.handler = lambda _r: httpx.Response(
        200, headers={"Content-Encoding": "identity", "Content-Length": "16"}, stream=stream
    )
    await _blocked(_io(net, max_bytes=4096), "https://example.com/", ErrorCode.SOURCE_TOO_LARGE)
    assert stream.yielded < len(stream.chunks)


@pytest.mark.asyncio
async def test_one_huge_raw_chunk_is_decoded_a_step_at_a_time(net: _Net) -> None:
    # ~1 MB of gzip in ONE chunk: zlib's unconsumed_tail would copy it whole on every step.
    net.dns["example.com"] = [[PUBLIC]]
    data = _gzip_of_zeros()
    peak = await _peak_while_blocked(net, [data], "gzip", _MIB)
    assert peak < 2 * _MIB

"""The AI Gateway adapter behind the Engine's community-cache route (epic OME-1311).

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: the adapter asks the gateway's ``/v1/cache/entries`` for one page with only the four
known query parameters (a repeated ``model`` kept); it forwards the caller's verified identity and
trace context and nothing else of theirs; it asks for gzip only when the caller accepts it; it
yields the gateway's body as raw bytes — a gzip page arrives still compressed — with the content
headers reported; and each upstream failure maps to its public error with the response closed.
"""

from __future__ import annotations

import gzip
from collections.abc import Callable

import anyio
import httpx
import pytest

from screamingface_engine.community_cache.aigateway import AigatewayCommunityCache
from screamingface_engine.community_cache.port import (
    CachePageRequest,
    CommunityCacheBadResponse,
    CommunityCacheInvalidRequest,
    CommunityCacheRateLimited,
    CommunityCacheRejected,
    CommunityCacheTimeout,
    CommunityCacheUnavailable,
)
from screamingface_engine.connections.port import Caller

pytestmark = pytest.mark.asyncio

_CALLER = Caller(
    identity={"X-User-Email": "alice@example.com"},
    traceparent="00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
)
_PAGE = b'{"schema":"screamingface.cache-page.v1","revisions":{}}\n{"next":null}\n'


class _Closing(httpx.AsyncByteStream):
    """A streamed response body, as the network delivers one, that records whether it was closed.

    WHY not `content=`: httpx reads a bytes body eagerly, so a raw re-read would fail where a
    real network response would not.
    """

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.closed = False

    async def __aiter__(self):
        yield self._body

    async def aclose(self) -> None:
        self.closed = True


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[AigatewayCommunityCache, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(capture)
    )
    return AigatewayCommunityCache(client), seen


def _ok(body: bytes = _PAGE, **headers: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _request: httpx.Response(
        200, stream=_Closing(body), headers={"content-type": "application/x-ndjson", **headers}
    )


async def _read(page) -> bytes:
    return b"".join([chunk async for chunk in page.aiter_raw()])


# --- the request ---------------------------------------------------------------------------------


async def test_the_page_request_forwards_only_the_known_parameters() -> None:
    adapter, seen = _adapter(_ok())

    page = await adapter.open_page(
        _CALLER,
        CachePageRequest(after="abc", limit=10, count=True, models=("m1", "m2"), gzip=False),
    )
    await page.aclose()

    [request] = seen
    assert request.method == "GET"
    assert request.url.path == "/v1/cache/entries"
    assert request.url.params.multi_items() == [
        ("after", "abc"),
        ("limit", "10"),
        ("count", "true"),
        ("model", "m1"),
        ("model", "m2"),
    ]


async def test_absent_parameters_are_not_sent() -> None:
    adapter, seen = _adapter(_ok())

    await (await adapter.open_page(_CALLER, CachePageRequest())).aclose()

    assert seen[0].url.params.multi_items() == []


async def test_the_callers_identity_and_trace_are_forwarded_and_nothing_else() -> None:
    adapter, seen = _adapter(_ok())
    caller = Caller(
        identity={"X-User-Email": "alice@example.com", "Authorization": "Bearer stolen"},
        traceparent=_CALLER.traceparent,
    )

    await (await adapter.open_page(caller, CachePageRequest())).aclose()

    headers = seen[0].headers
    assert headers["x-user-email"] == "alice@example.com"
    assert headers["traceparent"] == _CALLER.traceparent
    assert "authorization" not in headers


@pytest.mark.parametrize(("accepts", "asked"), [(True, "gzip"), (False, "identity")])
async def test_gzip_is_asked_for_only_when_the_caller_accepts_it(accepts: bool, asked: str) -> None:
    adapter, seen = _adapter(_ok())

    await (await adapter.open_page(_CALLER, CachePageRequest(gzip=accepts))).aclose()

    assert seen[0].headers["accept-encoding"] == asked


# --- the page ------------------------------------------------------------------------------------


async def test_a_gzip_page_arrives_still_compressed() -> None:
    # INVARIANT: the Engine never decodes a page. Decoding would hold up to ~235 MB of rows in
    # the Engine's memory and spend its CPU re-encoding what the gateway already encoded.
    zipped = gzip.compress(_PAGE)
    adapter, _ = _adapter(_ok(zipped, **{"content-encoding": "gzip"}))

    page = await adapter.open_page(_CALLER, CachePageRequest(gzip=True))

    assert page.content_type == "application/x-ndjson"
    assert page.content_encoding == "gzip"
    assert await _read(page) == zipped
    await page.aclose()


async def test_a_plain_page_reports_no_encoding() -> None:
    adapter, _ = _adapter(_ok())

    page = await adapter.open_page(_CALLER, CachePageRequest())

    assert page.content_encoding is None
    assert await _read(page) == _PAGE
    await page.aclose()


async def test_closing_the_page_closes_the_upstream_response() -> None:
    stream = _Closing(_PAGE)
    adapter, _ = _adapter(
        lambda _request: httpx.Response(
            200, stream=stream, headers={"content-type": "application/x-ndjson"}
        )
    )

    page = await adapter.open_page(_CALLER, CachePageRequest())
    await page.aclose()

    assert stream.closed


# --- failures ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, CommunityCacheRejected),
        (403, CommunityCacheBadResponse),
        (400, CommunityCacheInvalidRequest),
        (422, CommunityCacheInvalidRequest),
        (503, CommunityCacheUnavailable),
        (504, CommunityCacheTimeout),
        (404, CommunityCacheBadResponse),
        (500, CommunityCacheBadResponse),
    ],
)
async def test_an_upstream_failure_maps_to_its_error_and_closes_the_response(
    status: int, error: type[Exception]
) -> None:
    stream = _Closing(b'{"detail": "upstream words the caller must not see"}')
    adapter, _ = _adapter(lambda _request: httpx.Response(status, stream=stream))

    with pytest.raises(error):
        await adapter.open_page(_CALLER, CachePageRequest())

    assert stream.closed


async def test_a_403_is_the_gateway_refusing_this_engine_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # WHY not 401: the gateway answers 403 only to an untrusted peer or a non-loopback caller of
    # an auth-disabled gateway. That is this Engine's deployment, not the user's identity, so
    # sending the user to sign in again could never fix it.
    adapter, _ = _adapter(lambda _request: httpx.Response(403, stream=_Closing(b"")))

    with pytest.raises(CommunityCacheBadResponse):
        await adapter.open_page(_CALLER, CachePageRequest())

    assert "AI Gateway refused this Engine as a peer (403)" in caplog.text


@pytest.mark.parametrize(
    ("retry_after", "kept"),
    [
        ("30", 30),
        ("0", 0),
        (None, None),
        ("-1", None),
        ("1.5", None),
        (b"\xb2", None),  # a Latin-1 superscript two, which `str.isdigit` accepts
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        ("999999999", 999_999_999),
        ("1234567890", None),
        ("9" * 5000, None),  # past `int()`'s digit limit, which raises rather than refuses
    ],
)
async def test_a_rate_limit_keeps_only_a_whole_seconds_retry_after(
    retry_after: str | bytes | None, kept: int | None
) -> None:
    stream = _Closing(b"")
    raw = retry_after.encode() if isinstance(retry_after, str) else retry_after
    headers: dict[bytes, bytes] = {} if raw is None else {b"retry-after": raw}
    adapter, _ = _adapter(lambda _request: httpx.Response(429, stream=stream, headers=headers))

    with pytest.raises(CommunityCacheRateLimited) as raised:
        await adapter.open_page(_CALLER, CachePageRequest())

    assert raised.value.retry_after == kept
    assert stream.closed


class _FailingClose(_Closing):
    async def aclose(self) -> None:
        raise httpx.ReadError("connection reset while closing")


async def test_a_refused_response_that_fails_to_close_still_raises_its_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, _ = _adapter(lambda _request: httpx.Response(401, stream=_FailingClose(b"")))

    with pytest.raises(CommunityCacheRejected):
        await adapter.open_page(_CALLER, CachePageRequest())

    assert "failed to close (ReadError)" in caplog.text


class _CancelledWhileClosing(_Closing):
    """Cancels the request's scope as the close begins, as a caller that went away would."""

    scope: anyio.CancelScope

    async def aclose(self) -> None:
        self.scope.cancel()
        await anyio.sleep(0)
        self.closed = True


async def test_a_cancelled_request_still_closes_a_refused_response() -> None:
    stream = _CancelledWhileClosing(b"")
    adapter, _ = _adapter(lambda _request: httpx.Response(503, stream=stream))

    with pytest.raises(CommunityCacheUnavailable), anyio.CancelScope() as scope:
        stream.scope = scope
        await adapter.open_page(_CALLER, CachePageRequest())

    assert stream.closed


async def test_a_timeout_is_a_timeout() -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    adapter, _ = _adapter(hang)

    with pytest.raises(CommunityCacheTimeout):
        await adapter.open_page(_CALLER, CachePageRequest())


async def test_a_transport_failure_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    adapter, _ = _adapter(refuse)

    with pytest.raises(CommunityCacheUnavailable):
        await adapter.open_page(_CALLER, CachePageRequest())


class _Failing(httpx.AsyncByteStream):
    """A body that sends one chunk and then fails, as a stalled or dropped upstream does."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aiter__(self):
        yield _PAGE[:10]
        raise self._error


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (httpx.ReadTimeout("stalled"), CommunityCacheTimeout),
        (httpx.RemoteProtocolError("dropped"), CommunityCacheUnavailable),
    ],
)
async def test_a_failure_mid_page_maps_to_its_error(
    failure: Exception, error: type[Exception]
) -> None:
    adapter, _ = _adapter(lambda _request: httpx.Response(200, stream=_Failing(failure)))
    page = await adapter.open_page(_CALLER, CachePageRequest())

    with pytest.raises(error):
        await _read(page)
    await page.aclose()


async def test_aclose_closes_the_client() -> None:
    adapter, _ = _adapter(_ok())

    await adapter.aclose()

    assert adapter._client.is_closed

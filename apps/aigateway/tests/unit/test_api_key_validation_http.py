from __future__ import annotations

import asyncio
import gzip
from collections.abc import AsyncIterator

import httpx
import pytest

from aigateway.core.api_key_validation_http import (
    ApiKeyValidationTransportError,
    ValidationHttpSession,
)


class _ChunkStream(httpx.AsyncByteStream):
    """A genuinely streamed (not pre-buffered) response body.

    ``httpx.Response(stream=...)`` with this leaves ``is_stream_consumed`` False,
    so ``ValidationHttpSession`` takes the incremental ``aiter_raw`` branch rather
    than the pre-buffered ``response.content`` branch that MockTransport exercises.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.yielded = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        return None


class _StreamingTransport(httpx.AsyncBaseTransport):
    def __init__(self, stream: httpx.AsyncByteStream) -> None:
        self._stream = stream

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=self._stream)


class _SlowDripStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.yielded = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.yielded += 1
        yield b'{"data":'
        await asyncio.Event().wait()
        self.yielded += 1
        yield b"[]}"

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_validation_session_returns_bounded_json_without_following_redirects() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://attacker.invalid/steal"})

    async with ValidationHttpSession(transport=httpx.MockTransport(handler)) as session:
        response = await session.request_json("GET", "https://provider.example/key")

    assert response.status_code == 302
    assert response.payload is None
    assert [str(request.url) for request in calls] == ["https://provider.example/key"]
    assert calls[0].headers["accept-encoding"] == "identity"


@pytest.mark.asyncio
async def test_validation_session_parses_json_once_with_safe_headers() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"retry-after": "7", "authorization": "must-not-survive"},
            json={"data": []},
        )
    )

    async with ValidationHttpSession(transport=transport) as session:
        response = await session.request_json("GET", "https://provider.example/key")

    assert response.status_code == 200
    assert response.payload == {"data": []}
    assert response.retry_after_seconds == 7
    assert not hasattr(response, "headers")


@pytest.mark.asyncio
async def test_validation_session_rejects_oversized_streamed_body() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, content=b'"' + (b"x" * 65536) + b'"')
    )

    async with ValidationHttpSession(transport=transport) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")


@pytest.mark.asyncio
async def test_validation_session_rejects_declared_oversized_body_before_reading() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-length": "65537"},
            content=b"{}",
        )
    )

    async with ValidationHttpSession(transport=transport) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")


@pytest.mark.asyncio
async def test_validation_session_rejects_malformed_json() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"not-json"))

    async with ValidationHttpSession(transport=transport) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")


@pytest.mark.asyncio
async def test_validation_session_does_not_retry_transport_failures() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    async with ValidationHttpSession(transport=httpx.MockTransport(handler)) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")

    assert calls == 1


@pytest.mark.asyncio
async def test_validation_session_propagates_external_cancellation() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    async with ValidationHttpSession(transport=httpx.MockTransport(handler)) as session:
        with pytest.raises(asyncio.CancelledError):
            await session.request_json("GET", "https://provider.example/key")


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "tomorrow", "2147483648"])
@pytest.mark.asyncio
async def test_validation_session_rejects_unsafe_retry_after(value: str) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, headers={"retry-after": value}, json={"error": {}})
    )

    async with ValidationHttpSession(transport=transport) as session:
        response = await session.request_json("GET", "https://provider.example/key")

    assert response.retry_after_seconds is None


@pytest.mark.asyncio
async def test_validation_session_enforces_total_deadline(monkeypatch) -> None:
    from aigateway.core import api_key_validation_http

    monkeypatch.setattr(api_key_validation_http, "_REQUEST_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(api_key_validation_http, "_TOTAL_TIMEOUT_SECONDS", 0.01)

    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={})

    async with ValidationHttpSession(transport=httpx.MockTransport(handler)) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")


@pytest.mark.asyncio
async def test_validation_session_deadline_covers_slow_stream_body(monkeypatch) -> None:
    from aigateway.core import api_key_validation_http

    monkeypatch.setattr(api_key_validation_http, "_REQUEST_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(api_key_validation_http, "_TOTAL_TIMEOUT_SECONDS", 0.01)
    stream = _SlowDripStream()

    async with ValidationHttpSession(transport=_StreamingTransport(stream)) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")

    assert stream.yielded == 1
    assert stream.closed is True


@pytest.mark.asyncio
async def test_validation_session_caps_decoded_compressed_body() -> None:
    compressed = gzip.compress(b'"' + (b"x" * 65536) + b'"')
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=compressed,
        )
    )

    async with ValidationHttpSession(transport=transport) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")


class _ClosingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_validation_session_closes_request_local_transport() -> None:
    transport = _ClosingTransport()

    async with ValidationHttpSession(transport=transport) as session:
        await session.request_json("GET", "https://provider.example/key")

    assert transport.closed is True


@pytest.mark.asyncio
async def test_validation_session_production_transport_disables_ambient_controls(
    monkeypatch,
) -> None:
    from aigateway.core import api_key_validation_http

    transport_options: dict[str, object] = {}
    client_options: dict[str, object] = {}
    original_client = httpx.AsyncClient

    def transport_factory(**kwargs):
        transport_options.update(kwargs)
        return httpx.MockTransport(lambda _request: httpx.Response(200, json={}))

    def client_factory(**kwargs):
        client_options.update(kwargs)
        return original_client(**kwargs)

    monkeypatch.setattr(api_key_validation_http.httpx, "AsyncHTTPTransport", transport_factory)
    monkeypatch.setattr(api_key_validation_http.httpx, "AsyncClient", client_factory)

    async with ValidationHttpSession():
        pass

    # The transport itself must also disable ambient env: trust_env=True would let
    # SSL_CERT_FILE / SSL_CERT_DIR (and proxy env) rebind the verified CA bundle.
    assert transport_options == {"retries": 0, "verify": True, "trust_env": False}
    assert client_options["trust_env"] is False
    assert client_options["follow_redirects"] is False
    assert client_options["verify"] is True


@pytest.mark.asyncio
async def test_validation_session_shares_one_absolute_deadline(monkeypatch) -> None:
    from aigateway.core import api_key_validation_http

    monkeypatch.setattr(api_key_validation_http, "_REQUEST_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(api_key_validation_http, "_TOTAL_TIMEOUT_SECONDS", 0.03)

    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={})

    async with ValidationHttpSession(transport=httpx.MockTransport(handler)) as session:
        first = await session.request_json("GET", "https://provider.example/auth")
        assert first.status_code == 200
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("POST", "https://provider.example/readiness")


@pytest.mark.asyncio
async def test_validation_session_sanitizes_deeply_nested_json() -> None:
    # Under 64 KiB but nested far past the JSON recursion limit: json.loads raises
    # RecursionError, which must be sanitized to a transport error, not escape raw.
    depth = 20_000
    payload = b"[" * depth + b"]" * depth
    assert len(payload) < 64 * 1024
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))

    async with ValidationHttpSession(transport=transport) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")


@pytest.mark.asyncio
async def test_validation_session_reads_genuinely_streamed_body() -> None:
    stream = _ChunkStream([b'{"da', b'ta": ', b"[]}"])

    async with ValidationHttpSession(transport=_StreamingTransport(stream)) as session:
        response = await session.request_json("GET", "https://provider.example/key")

    assert response.payload == {"data": []}
    # Proves the incremental aiter_raw branch ran (a pre-buffered body yields nothing here).
    assert stream.yielded == 3


@pytest.mark.asyncio
async def test_validation_session_caps_genuinely_streamed_body_incrementally() -> None:
    stream = _ChunkStream([b"x" * 8192 for _ in range(16)])

    async with ValidationHttpSession(transport=_StreamingTransport(stream)) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")

    # Stops once the 64 KiB bound is crossed instead of buffering the whole stream.
    assert 0 < stream.yielded < 16


@pytest.mark.asyncio
async def test_validation_session_degrades_overlong_retry_after_without_transport_error() -> None:
    # WHY (OME-307 N-1): a Retry-After longer than CPython's int-string conversion limit
    # (sys.int_info.default_max_str_digits, 4300 by default) must not raise inside int() and
    # get swallowed by the sanitizing except, which would downgrade a real 429 to a transport
    # error (UNAVAILABLE). It degrades to "no hint" and preserves the rate-limit status.
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            429, headers={"retry-after": "9" * 5000}, json={"error": {}}
        )
    )

    async with ValidationHttpSession(transport=transport) as session:
        response = await session.request_json("GET", "https://provider.example/key")

    assert response.status_code == 429
    assert response.retry_after_seconds is None


@pytest.mark.asyncio
async def test_validation_session_preserves_retry_after_at_upper_bound() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            429, headers={"retry-after": "2147483647"}, json={"error": {}}
        )
    )

    async with ValidationHttpSession(transport=transport) as session:
        response = await session.request_json("GET", "https://provider.example/key")

    assert response.retry_after_seconds == 2147483647


@pytest.mark.asyncio
async def test_validation_session_sanitizes_invalid_url() -> None:
    # WHY (OME-307 L-1): httpx.InvalidURL derives from Exception, NOT httpx.HTTPError, so it
    # escaped the sanitizing except and could surface a raw URL to the caller. A control
    # character in an interpolated model URL reaches this path (verified on httpx 0.28.1).
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={}))

    async with ValidationHttpSession(transport=transport) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "http://\x00host/models/x:generateContent")


@pytest.mark.parametrize(
    "exc",
    [httpx.CookieConflict("ambiguous cookie"), httpx.StreamError("stream misuse")],
)
@pytest.mark.asyncio
async def test_validation_session_sanitizes_non_httperror_httpx_exceptions(
    exc: Exception,
) -> None:
    # httpx.CookieConflict derives from Exception and httpx.StreamError from RuntimeError;
    # neither is an httpx.HTTPError, so both must be caught explicitly, never escape raw.
    def handler(_request: httpx.Request) -> httpx.Response:
        raise exc

    async with ValidationHttpSession(transport=httpx.MockTransport(handler)) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")


@pytest.mark.parametrize(
    "status, body",
    [
        (429, b"Too Many Requests"),
        (401, b"<html>unauthorized</html>"),
        (503, b"upstream connect error"),
        (429, b"[" * 60_000),
    ],
    ids=["plaintext-429", "html-401", "plaintext-503", "too-deep-429"],
)
@pytest.mark.asyncio
async def test_validation_session_leaves_an_undecodable_error_body_to_the_status(
    status: int, body: bytes
) -> None:
    # INVARIANT: an error body that is not JSON carries no evidence either way, so the status and
    # Retry-After still reach the provider's classifier, exactly as with an empty body.
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status, headers={"retry-after": "30"}, content=body)
    )

    async with ValidationHttpSession(transport=transport) as session:
        response = await session.request_json("GET", "https://provider.example/key")

    assert (response.status_code, response.payload, response.retry_after_seconds) == (
        status,
        None,
        30,
    )


@pytest.mark.parametrize("status", [201, 206])
@pytest.mark.asyncio
async def test_validation_session_still_rejects_a_success_body_that_is_not_json(
    status: int,
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, content=b"not-json"))

    async with ValidationHttpSession(transport=transport) as session:
        with pytest.raises(ApiKeyValidationTransportError):
            await session.request_json("GET", "https://provider.example/key")

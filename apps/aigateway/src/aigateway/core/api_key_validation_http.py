from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

_MAX_RESPONSE_BYTES = 64 * 1024
_REQUEST_TIMEOUT_SECONDS = 5.0
_TOTAL_TIMEOUT_SECONDS = 10.0
_MAX_RETRY_AFTER_SECONDS = 2_147_483_647
# WHY: an ASCII-decimal Retry-After within range is at most this many digits; a longer string
# cannot satisfy the range check, so it is rejected before int() (see _retry_after_seconds).
_MAX_RETRY_AFTER_DIGITS = len(str(_MAX_RETRY_AFTER_SECONDS))


class ApiKeyValidationTransportError(Exception):
    """Sanitized transport/response failure with no upstream text or secret material."""


@dataclass(frozen=True, slots=True)
class BoundedJsonResponse:
    status_code: int
    payload: Any | None
    retry_after_seconds: int | None
    # WHY the raw response too: a provider whose dispatch holds a response to stricter rules than
    # `payload` reflects (media type, strict finite JSON, structure bounds) can apply the SAME
    # decoder to what readiness received. Both stay within the 64 KiB bound above.
    content_type: str | None = None
    body: bytes = b""


def bounded_retry_after_seconds(value: int) -> int | None:
    """Return a positive delta-seconds hint within the supported range, else None.

    INVARIANT: ONE upper bound governs every Retry-After source — the numeric HTTP header
    parsed here and provider-structured hints (e.g. Gemini RetryInfo.retryDelay) — so no
    parser can emit an out-of-range or overflowing retry hint.
    """
    if not 0 < value <= _MAX_RETRY_AFTER_SECONDS:
        return None
    return value


def _retry_after_seconds(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    # WHY: bound the digit count before int(). CPython raises ValueError converting a string
    # longer than sys.int_info.default_max_str_digits (4300 default); caught by the sanitizing
    # except in request_json, that would downgrade a valid 429 to a transport error.
    if len(value) > _MAX_RETRY_AFTER_DIGITS:
        return None
    return bounded_retry_after_seconds(int(value))


class ValidationHttpSession:
    """One bounded, request-local HTTP client shared by both validation stages."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._deadline: float | None = None

    async def __aenter__(self) -> ValidationHttpSession:
        # INVARIANT: trust_env=False on the transport too (not just the client) so
        # ambient SSL_CERT_FILE/SSL_CERT_DIR and proxy env cannot rebind the verified
        # CA bundle or route validation through an unexpected proxy.
        transport = self._transport or httpx.AsyncHTTPTransport(
            retries=0, verify=True, trust_env=False
        )
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            verify=True,
        )
        self._deadline = asyncio.get_running_loop().time() + _TOTAL_TIMEOUT_SECONDS
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._deadline = None

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str | int] | None = None,
        json_body: Any | None = None,
    ) -> BoundedJsonResponse:
        client = self._client
        deadline = self._deadline
        if client is None or deadline is None:
            raise RuntimeError("ValidationHttpSession must be entered before use")

        remaining = deadline - asyncio.get_running_loop().time()
        timeout = min(_REQUEST_TIMEOUT_SECONDS, remaining)
        if timeout <= 0:
            raise ApiKeyValidationTransportError from None

        request_headers = dict(headers or {})
        # INVARIANT: raw identity bytes keep the 64 KiB memory bound enforceable.
        request_headers["Accept-Encoding"] = "identity"

        try:
            async with asyncio.timeout(timeout):
                async with client.stream(
                    method,
                    url,
                    headers=request_headers,
                    params=params,
                    json=json_body,
                    follow_redirects=False,
                    timeout=httpx.Timeout(_REQUEST_TIMEOUT_SECONDS),
                ) as response:
                    content_encoding = response.headers.get("content-encoding")
                    if content_encoding is not None and content_encoding.lower() != "identity":
                        raise ApiKeyValidationTransportError from None
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_length = int(content_length)
                        except ValueError:
                            declared_length = 0
                        if declared_length > _MAX_RESPONSE_BYTES:
                            raise ApiKeyValidationTransportError from None

                    body = bytearray()
                    if response.is_stream_consumed:
                        # Mock/custom transports may return a pre-buffered response.
                        if len(response.content) > _MAX_RESPONSE_BYTES:
                            raise ApiKeyValidationTransportError from None
                        body.extend(response.content)
                    else:
                        async for chunk in response.aiter_raw(chunk_size=8192):
                            if len(chunk) > _MAX_RESPONSE_BYTES - len(body):
                                raise ApiKeyValidationTransportError from None
                            body.extend(chunk)

                    payload: Any | None = None
                    if body:
                        try:
                            payload = json.loads(body)
                        except (ValueError, RecursionError):
                            # WHY only a success re-raises: an error body that is not JSON (a
                            # plaintext 429, an HTML 401) carries no evidence either way, so it
                            # reaches the classifier as an empty body does, with its status and
                            # Retry-After intact. A success that is not JSON is a broken answer.
                            if response.is_success:
                                raise ApiKeyValidationTransportError from None
                    return BoundedJsonResponse(
                        status_code=response.status_code,
                        payload=payload,
                        retry_after_seconds=_retry_after_seconds(
                            response.headers.get("retry-after")
                        ),
                        content_type=response.headers.get("content-type"),
                        body=bytes(body),
                    )
        except ApiKeyValidationTransportError:
            raise
        except (
            RecursionError,
            TimeoutError,
            ValueError,
            httpx.HTTPError,
            httpx.InvalidURL,
            httpx.CookieConflict,
            httpx.StreamError,
        ):
            # INVARIANT: provider exception text can contain credentials or raw response data.
            # RecursionError guards json.loads on a deeply nested (but small) body; it must be
            # sanitized like any other parse/transport failure, never escape raw to the caller.
            # WHY: httpx.InvalidURL/CookieConflict (Exception) and StreamError (RuntimeError)
            # are NOT httpx.HTTPError subclasses, so they need explicit entries here; a blanket
            # ``except Exception`` is deliberately avoided so it cannot conceal a programming bug.
            raise ApiKeyValidationTransportError from None

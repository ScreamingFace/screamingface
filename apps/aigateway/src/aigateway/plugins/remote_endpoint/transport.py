"""The chat POST to a configured endpoint, over one reused client per endpoint.

# INVARIANT: the client never follows redirects, reads no proxy or CA setting from the
# environment, verifies certificates and bounds the response.
# WHY no DNS or private-address guard: the operator reviews and approves every origin before it
# is configured. A guard is needed once untrusted origins are accepted automatically, or once
# network isolation is a requirement of its own.
# INVARIANT: upstream bodies and headers never cross this boundary; only the status class and a
# Retry-After within the gateway's one bound may, so shared retry policy still works.
# INVARIANT: the size bound counts the bytes held in memory. The request asks for `identity` and
# an encoded answer is refused before its body is read, because httpx decodes while it reads.
"""

from __future__ import annotations

import asyncio
from http.client import HTTPResponse
from http.cookiejar import Cookie, CookieJar
from typing import Any
from urllib.request import Request

import httpx
from fastapi import HTTPException

from aigateway.core.api_key_validation_http import bounded_retry_after_seconds

from .completion import decode_completion

_MAX_RESPONSE_BYTES = 1_000_000
# WHY bound the digits before int(): the core bound has ten digits, and int() of an arbitrarily
# long header is wasted work before a value the bound refuses anyway.
_MAX_RETRY_AFTER_DIGITS = 10
_INVALID = "The remote endpoint response is invalid."
# WHY httpx's own default bound: core admission caps concurrent calls per provider first (four by
# default), so the pool binds only when an operator lifts that cap.
_POOL_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)


class _NoCookies(CookieJar):
    """A cookie jar that keeps nothing.

    # WHY: every account's chats to one endpoint share one client, so a cookie the upstream set
    # on one account's answer would ride on the next account's request. A refusing cookie policy
    # is not enough: httpx copies the jar into a plain one before each request.
    """

    def set_cookie(self, cookie: Cookie) -> None:
        del cookie

    def extract_cookies(self, response: HTTPResponse, request: Request) -> None:
        del response, request


def _open_client(transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    # INVARIANT: core.admission is the one wall-clock authority, as for the local provider.
    return httpx.AsyncClient(
        cookies=_NoCookies(),
        follow_redirects=False,
        trust_env=False,
        timeout=None,
        limits=_POOL_LIMITS,
        transport=transport,
    )


class EndpointClient:
    """One endpoint's HTTP client: opened on first use, reused by every chat, closed once."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._closed = False
        self._closing: asyncio.Future[None] | None = None

    def open(self, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
        # WHY on first use: composition does no I/O, and the client belongs to the serving loop.
        # INVARIANT: after `aclose` no client is opened again, so a late chat cannot leak one.
        if self._closed:
            raise _unavailable()
        if self._client is None:
            self._client = _open_client(transport)
        return self._client

    async def aclose(self) -> None:
        self._closed = True
        if self._client is None:
            return
        # WHY one shielded task: httpx marks the client closed before its pool finishes closing,
        # so a cancelled close could never be retried. The task runs to its end on its own, and
        # a repeat call waits for that same close.
        if self._closing is None:
            self._closing = asyncio.ensure_future(self._client.aclose())
        await asyncio.shield(self._closing)


def _unavailable() -> HTTPException:
    return _error(502, "provider_unavailable", "The remote endpoint is unavailable.")


def _error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> HTTPException:
    return HTTPException(
        status_code=status, detail={"code": code, "message": message}, headers=headers
    )


def _upstream_error(response: httpx.Response) -> HTTPException:
    # WHY only 429/503 keep their status: they drive the shared overload retry. Anything else,
    # an upstream 401 included, is a provider failure — never the caller's own auth failure.
    if response.status_code not in (429, 503):
        return _error(502, "provider_error", "The remote endpoint returned an error.")
    seconds = _retry_after_seconds(response.headers.get("retry-after"))
    return _error(
        response.status_code,
        "provider_error",
        "The remote endpoint is busy.",
        headers=None if seconds is None else {"Retry-After": str(seconds)},
    )


def _retry_after_seconds(value: str | None) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    if len(value) > _MAX_RETRY_AFTER_DIGITS:
        return None
    return bounded_retry_after_seconds(int(value))


async def _read_bounded(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
            raise _error(502, "provider_error", _INVALID)
        body.extend(chunk)
    return bytes(body)


async def post_chat_completion(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Accept-Encoding": "identity"}
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            # INVARIANT: exactly 200, as readiness requires; another 2xx is not the contract.
            if response.status_code != 200:
                raise _upstream_error(response)
            encoding = response.headers.get("content-encoding")
            if encoding is not None and encoding.lower() != "identity":
                raise _error(502, "provider_error", _INVALID)
            completion = decode_completion(
                response.headers.get("content-type"), await _read_bounded(response)
            )
            if completion is None:
                raise _error(502, "provider_error", _INVALID)
            return completion
    except HTTPException:
        raise
    except (TimeoutError, httpx.HTTPError):
        raise _unavailable() from None

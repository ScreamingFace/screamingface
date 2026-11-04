"""URL4-driven redirect following: every hop's body is read through the byte limiter.

WHY (PR #1482 review): with ``follow_redirects=True`` httpx ``aread()``s each redirect body
before it returns the final response, so a cap or live hook applied only to that final
response comes too late — an injected client's redirect bodies were held unbounded. Here each
request is sent with ``follow_redirects=False`` and the chain is walked by URL4, so each hop is
read by :func:`read_capped` before anything is buffered.
AIDEV-NOTE: the next hop is httpx's own ``response.next_request`` (its redirect builder:
method rewrite, cross-origin ``Authorization`` drop, cookies), so only WHO reads the body changed.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from url4.io._source_policy import too_large


async def fetch_following(
    client: httpx.AsyncClient,
    request: httpx.Request,
    *,
    limit: int,
    on_chunk: Callable[[int], None] | None,
    answered: Callable[[], None],
) -> tuple[httpx.Response, bytes]:
    """The final response (closed) and its capped body, following redirects as ``client`` would.

    ``answered`` runs once the first reply arrives (any status). A client built with
    ``follow_redirects=False`` gets its 3xx back as an error, as before; the hop limit is the
    client's ``max_redirects``, surfaced as :class:`httpx.TooManyRedirects` like httpx does.
    INVARIANT: every hop's body passes ``on_chunk`` and the ``limit`` check before it is held.
    """
    follow = client.follow_redirects
    redirects = 0
    response = await client.send(request, stream=True, follow_redirects=False)
    answered()
    while True:
        try:
            following = response.next_request if follow else None
            if following is None:
                response.raise_for_status()
            body = await read_capped(response, limit, on_chunk)
        finally:
            await response.aclose()
        if following is None:
            return response, body
        redirects += 1
        if redirects > client.max_redirects:
            raise httpx.TooManyRedirects("Exceeded maximum allowed redirects.", request=following)
        response = await client.send(following, stream=True, follow_redirects=False)


async def read_capped(
    response: httpx.Response, limit: int, on_chunk: Callable[[int], None] | None = None
) -> bytes:
    """The decoded body, read chunk by chunk and abandoned as soon as it passes ``limit``.

    INVARIANT: never holds more than ``limit`` bytes — the check runs before each append, after
    ``on_chunk`` (the caller's live budget) was told the chunk's size.
    """
    body = bytearray()
    async for chunk in response.aiter_bytes():
        if on_chunk is not None:
            on_chunk(len(chunk))
        if len(body) + len(chunk) > limit:
            raise too_large(limit)
        body += chunk
    return bytes(body)

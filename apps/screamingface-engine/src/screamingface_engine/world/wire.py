"""The ASGI types and the one writer of url4's error envelope (04-review-fixes §2.4).

FEATURE (unit 3, prd/03): the sync surface answers in url4's error dialect —
``{"error": {"code", "message"}}`` — from three places: the node tier, the App's forwarder and
local mode. This module is where that shape is written, so the three cannot drift apart.

WHY in `world` and not beside one caller: the control plane may import `world`
(`.claude/scripts/check_layering.py`), so the forwarder can use this module too, and `world` is
where the node tier already lives.

INVARIANT: stdlib only. No web framework and no url4 import, so importing the wire shape costs
nothing and couples to nothing.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, MutableMapping, Sequence
from typing import Any

# These mirror httpx's own ASGI types (MutableMapping, not Mapping): the node tier must be
# assignable to `httpx.ASGITransport`'s `_ASGIApp`, and a param typed `Mapping` is too wide to
# accept the narrower `MutableMapping` message dict the transport hands in.
AsgiScope = MutableMapping[str, Any]
AsgiReceive = Callable[[], Awaitable[MutableMapping[str, Any]]]
AsgiSend = Callable[[MutableMapping[str, Any]], Awaitable[None]]
AsgiApp = Callable[[AsgiScope, AsgiReceive, AsgiSend], Awaitable[None]]

MALFORMED_HEADER = "malformed_header"
"""Engine-added code (contracts.md C1): a present-but-unusable request header.

ONE constant for the node tier and local mode (item 3, B6 review): both refuse a bad
``X-Answer-Seed`` before dispatch with the SAME 400, and a second, independently-spelled
string would let the two answers drift silently."""


async def write(
    send: AsgiSend, status: int, headers: Sequence[tuple[bytes, bytes]], body: bytes
) -> None:
    """Write one complete HTTP response: the start, then the whole body in one message."""
    await send({"type": "http.response.start", "status": status, "headers": list(headers)})
    await send({"type": "http.response.body", "body": body})


async def write_json(
    send: AsgiSend, status: int, payload: Mapping[str, Any], *, retry_after: int | None = None
) -> None:
    """Write ``payload`` as a JSON response, with ``Retry-After`` when one is given."""
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    await write(send, status, headers, json.dumps(payload).encode())


def url4_error_body(code: str, message: str) -> bytes:
    """url4's error envelope, ``{"error": {"code", "message"}}``, as response body bytes.

    INVARIANT: the ONE place the envelope's shape is spelled. The body is byte-identical to the
    one url4's own node writes, so a caller cannot tell an engine refusal from a url4 one by its
    shape — only by its ``code``.
    """
    return json.dumps({"error": {"code": code, "message": message}}).encode()


async def send_url4_error(
    send: AsgiSend, status: int, code: str, message: str, *, retry_after: int | None = None
) -> None:
    """Write url4's error envelope (:func:`url4_error_body`) as one complete response."""
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    await write(send, status, headers, url4_error_body(code, message))


__all__ = [
    "AsgiApp",
    "AsgiReceive",
    "AsgiScope",
    "AsgiSend",
    "MALFORMED_HEADER",
    "send_url4_error",
    "url4_error_body",
    "write",
    "write_json",
]

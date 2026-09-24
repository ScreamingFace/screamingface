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

ENSEMBLE_PATH_HINT = (
    "long-running work belongs on the ensemble path (POST /token, attach the WebSocket, "
    "then GET /?q=<expression>)"
)
"""The AC6 hint that closes both the node tier's own 504 reword and the App forwarder's 504 —
ONE spelling for the direction a caller whose sync request timed out should go."""


async def write(
    send: AsgiSend, status: int, headers: Sequence[tuple[bytes, bytes]], body: bytes
) -> None:
    """Write one complete HTTP response: the start, then the whole body in one message."""
    await send({"type": "http.response.start", "status": status, "headers": list(headers)})
    await send({"type": "http.response.body", "body": body})


def _json_headers(retry_after: int | None) -> list[tuple[bytes, bytes]]:
    """The headers every JSON response on this surface writes: content-type, plus ``Retry-After``
    when one is given.

    ONE helper for :func:`write_json` and :func:`send_url4_error`, so the two cannot spell the
    header list differently for the same ``retry_after``.
    """
    headers = [(b"content-type", b"application/json")]
    if retry_after is not None:
        headers.append((b"retry-after", str(retry_after).encode()))
    return headers


async def write_json(
    send: AsgiSend, status: int, payload: Mapping[str, Any], *, retry_after: int | None = None
) -> None:
    """Write ``payload`` as a JSON response, with ``Retry-After`` when one is given."""
    await write(send, status, _json_headers(retry_after), json.dumps(payload).encode())


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
    """Write url4's error envelope (:func:`url4_error_body`) as one complete response.

    INVARIANT: this reads the envelope's shape from :func:`url4_error_body` — the ONE place it is
    spelled — rather than building ``{"error": {...}}`` itself. Headers come from
    :func:`_json_headers`, the same helper :func:`write_json` uses, so the two stay
    byte-identical for the same status/body/``retry_after``.
    """
    await write(send, status, _json_headers(retry_after), url4_error_body(code, message))


__all__ = [
    "AsgiApp",
    "AsgiReceive",
    "AsgiScope",
    "AsgiSend",
    "ENSEMBLE_PATH_HINT",
    "MALFORMED_HEADER",
    "send_url4_error",
    "url4_error_body",
    "write",
    "write_json",
]

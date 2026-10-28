"""The binary-safe port of :class:`~url4.peer.server.Url4Node` — ``fetch_bytes``.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; local end-to-end run
2026-10-28).
STORY: as an operator running ``url4 serve`` I put a PNG behind an ``https`` attachment source or
in a ``[data]`` file at ``/blob/sha256/<hex>``, and the node fetches it as its exact bytes.

WHY a module of its own: the text dispatch (:mod:`url4.peer._dispatch`) and the bytes dispatch
change for different reasons; this one reuses that dispatch order and adds only what bytes need.
WHY the node needs it at all: the engine reaches ``fetch_bytes`` duck-typed on ``ctx.io``;
without it every ``https`` attachment source on a node was refused before its destination guard
ran, and a ``/blob/sha256`` ref fell back to the text read of a binary file.
"""

from __future__ import annotations

from collections.abc import Awaitable
from inspect import isawaitable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes, SupportsFetchBytes
from url4.peer._dispatch import data_route, dispatch_result

if TYPE_CHECKING:  # the node types only — this module never constructs one
    from url4.peer.server import Url4Node, _DataRoute


@runtime_checkable
class SupportsReadBytes(Protocol):
    """A data provider that can also hand over its body as raw bytes (a binary file, say)."""

    async def read_bytes(self) -> bytes: ...


async def fetch_bytes(node: Url4Node, request: FetchRequest) -> FetchedBytes:
    """The node's binary-safe port: relative targets by its own dispatch, others outbound.

    INVARIANT: an absolute target goes to the outbound layer's OWN ``fetch_bytes``, so that
    adapter's destination guard, size cap and deadline apply; a node never fetches bytes past
    them. An outbound layer without the port is refused (``unsupported_mode``), never served
    text-encoded: an attachment's bytes must be the origin's bytes.
    """
    if request.relative or request.target.startswith("/"):
        return await dispatch_bytes(node, request.target)
    outbound = node._outbound_io()
    if not isinstance(outbound, SupportsFetchBytes):
        raise no_bytes_port(request.target)
    return await outbound.fetch_bytes(request)


async def dispatch_bytes(node: Url4Node, target: str) -> FetchedBytes:
    """``dispatch_result`` as bytes: a data route is read binary-safe, the rest UTF-8 encoded.

    WHY the same branch order: an endpoint or the eval path wins its path exactly as on the
    text dispatch, and both only ever produce text, so their bytes are that text encoded (the
    ``url4.io.media.fetch_bytes`` fallback). A data route whose provider can read bytes
    (:class:`SupportsReadBytes`, e.g. a ``url4 serve`` ``[data]`` file) is never decoded.
    """
    path = target.partition("?")[0]
    if path not in node._endpoints and not node._is_eval_path(path):
        route = data_route(node, target, path)
        if route is not None:
            return await serve_data_bytes(route)
    result = await dispatch_result(node, target)
    return FetchedBytes(result.body.encode("utf-8"), result.media_type)


async def serve_data_bytes(route: _DataRoute) -> FetchedBytes:
    """Read one data route as bytes, with the media type the route declares."""
    provider = route.provider
    if isinstance(provider, SupportsReadBytes):
        return FetchedBytes(await provider.read_bytes(), route.media_type)
    body = await _text(provider() if callable(provider) else provider)
    return FetchedBytes(body.encode("utf-8"), route.media_type)


def no_bytes_port(target: str) -> ResolutionError:
    """The permanent refusal of a bytes fetch through an io layer that has no bytes port.

    WHY ``unsupported_mode``: the io lacks a capability, as a relative code pointer on an io
    without ``SupportsCode`` does; no body was seen, so its type was never unsupported.
    """
    return ResolutionError(
        f"{target!r} needs a binary-safe io layer (fetch_bytes); this one has a text port only",
        code=ErrorCode.UNSUPPORTED_MODE,
        permanent=True,
    )


async def _text(result: str | Awaitable[str]) -> str:
    return await result if isawaitable(result) else result

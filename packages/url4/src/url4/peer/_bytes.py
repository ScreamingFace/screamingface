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

from collections.abc import AsyncGenerator, Awaitable
from contextlib import aclosing, suppress
from inspect import isawaitable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from url4.core.errors import ErrorCode, ResolutionError
from url4.core.url_display import display_url
from url4.dag.attachments import whole_body_refused
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes, SupportsFetchBytes, read_whole, too_large
from url4.peer._dispatch import data_route, dispatch_result

if TYPE_CHECKING:  # the node types only — this module never constructs one
    from url4.peer.server import Url4Node, _DataRoute


@runtime_checkable
class SupportsReadBytes(Protocol):
    """A data provider that can also hand over its body as raw bytes (a binary file, say)."""

    async def read_bytes(self) -> bytes: ...


@runtime_checkable
class SupportsReadChunks(Protocol):
    """A data provider that can hand over its bytes in pieces (a ``[data]`` file, say).

    WHY: a run's live byte budget (``FetchRequest.on_chunk``) must see the bytes as they are
    read, so a refused read stops after about one piece instead of holding the whole file.
    """

    def read_chunks(self) -> AsyncGenerator[bytes]: ...


async def fetch_bytes(node: Url4Node, request: FetchRequest) -> FetchedBytes:
    """The node's binary-safe port: relative targets by its own dispatch, others outbound.

    INVARIANT: an absolute target goes to the outbound layer's OWN ``fetch_bytes``, so that
    adapter's destination guard, size cap and deadline apply; a node never fetches bytes past
    them. An outbound layer without the port is refused (``unsupported_mode``), never served
    text-encoded: an attachment's bytes must be the origin's bytes.
    """
    if request.relative or request.target.startswith("/"):
        return await dispatch_bytes(node, request.target, request)
    outbound = node._outbound_io()
    if not isinstance(outbound, SupportsFetchBytes):
        raise no_bytes_port(request.target)
    return await outbound.fetch_bytes(request)


async def dispatch_bytes(
    node: Url4Node, target: str, request: FetchRequest | None = None
) -> FetchedBytes:
    """``dispatch_result`` as bytes: a data route is read binary-safe, the rest UTF-8 encoded.

    WHY the same branch order: an endpoint or the eval path wins its path exactly as on the
    text dispatch, and both only ever produce text, so their bytes are that text encoded (the
    ``url4.io.media.fetch_bytes`` fallback). A data route whose provider can read bytes
    (:class:`SupportsReadBytes`, e.g. a ``url4 serve`` ``[data]`` file) is never decoded.
    INVARIANT (PR #1587 review finding 1): ``request``'s ``max_bytes`` / ``on_chunk`` bound
    every relative bytes read — per piece for a :class:`SupportsReadChunks` provider, after the
    read for the rest (as ``url4.io.media.read_whole`` does for a non-streaming adapter) — unless
    ``on_declared`` is set (a run's live cap): then only a chunked or an already-held ``str``
    provider is read, and any other whole-body provider is refused unread (review round 11).
    """
    path = target.partition("?")[0]
    if path not in node._endpoints and not node._is_eval_path(path):
        route = data_route(node, target, path)
        if route is not None:
            return await serve_data_bytes(route, request)
    result = await dispatch_result(node, target)
    return FetchedBytes(_bounded(request, result.body.encode("utf-8")), result.media_type)


async def serve_data_bytes(route: _DataRoute, request: FetchRequest | None = None) -> FetchedBytes:
    """Read one data route as bytes, with the media type the route declares."""
    provider = route.provider
    if isinstance(provider, SupportsReadChunks):
        return FetchedBytes(await _read_pieces(provider, request), route.media_type)
    if isinstance(provider, str):  # already held by the node: its size is exact
        # INVARIANT (PR #1587 review round 12): drawn BEFORE the encode, so a refused body's
        # UTF-8 copy is never built; two held 7 MB strings once produced 14 MB past an 8 MB cap.
        declared = _reserve(_utf8_size(provider), request)
        return FetchedBytes(_settled(request, provider.encode("utf-8"), declared), route.media_type)
    if request is not None and request.on_declared is not None:
        # INVARIANT (PR #1587 review round 11 finding 1, owner 2026-11-05 — FAIL CLOSED): under
        # a run's live cap a body is counted BEFORE it is held. A whole-body provider can only
        # be counted after its read, and a declared size is the provider's word, not a count:
        # two that declared 1 byte and returned 7 MB each once held 14 MB together. Refused
        # unread; ``on_declared(None)`` makes the run's refusal sticky (``CapBudget.reserve``).
        # WHY suppressed: the budget records its refusal (sticky) before it raises; a caller
        # whose ``on_declared`` does not raise still gets the same refusal (owner 2026-11-06).
        with suppress(ResolutionError):
            request.on_declared(None)
        raise whole_body_refused()
    if isinstance(provider, SupportsReadBytes):
        body = await provider.read_bytes()
    else:
        body = (await _text(provider() if callable(provider) else provider)).encode("utf-8")
    return FetchedBytes(_bounded(request, body), route.media_type)


def _reserve(size: int | None, request: FetchRequest | None) -> int | None:
    """Draw a held ``str`` provider's exact size before it is served, when the caller asks to.

    INVARIANT (PR #1587 review rounds 10/11, owner 2026-11-05 — FAIL CLOSED): with
    ``on_declared`` set (a run's attached blob read) the size is drawn from the run's live budget
    first; one over the budget is refused there, and one over the request's ``max_bytes`` is
    ``x.source_too_large``. Without it the body is bounded after the fact (:func:`_bounded`).
    WHY data routes only: a blob ref's target carries no ``?q=``, so an endpoint or the eval
    path refuses it (``missing_intent``) before producing any body.
    """
    if request is None or request.on_declared is None:
        return None
    request.on_declared(size)
    if size is not None and request.max_bytes is not None and size > request.max_bytes:
        raise too_large(request.max_bytes)
    return size


def _utf8_size(text: str) -> int:
    """``len(text.encode("utf-8"))`` without holding the whole encoded copy (1 MiB slices)."""
    if text.isascii():
        return len(text)
    step = 1 << 20
    return sum(len(text[i : i + step].encode("utf-8")) for i in range(0, len(text), step))


def _settled(request: FetchRequest | None, body: bytes, declared: int | None) -> bytes:
    """``body`` bounded; with a drawn ``declared`` size, only the bytes past it are drawn now."""
    if request is None or declared is None:
        return _bounded(request, body)
    if request.on_chunk is not None and len(body) > declared:
        request.on_chunk(len(body) - declared)
    if request.max_bytes is not None and len(body) > request.max_bytes:
        raise too_large(request.max_bytes)
    return body


async def _read_pieces(provider: SupportsReadChunks, request: FetchRequest | None) -> bytes:
    """The provider's pieces, each told to ``on_chunk`` and capped BEFORE it is kept.

    INVARIANT: the same order as ``read_whole`` and the guarded transport — the caller's live
    budget refuses first, then the request's own ``max_bytes`` (``x.source_too_large``).
    """
    on_chunk = None if request is None else request.on_chunk
    limit = None if request is None else request.max_bytes
    pieces: list[bytes] = []
    total = 0
    async with aclosing(provider.read_chunks()) as chunks:
        async for piece in chunks:
            if on_chunk is not None:
                on_chunk(len(piece))
            total += len(piece)
            if limit is not None and total > limit:
                raise too_large(limit)
            pieces.append(piece)
    return b"".join(pieces)


def _bounded(request: FetchRequest | None, body: bytes) -> bytes:
    return body if request is None else read_whole(request, body)


def no_bytes_port(target: str) -> ResolutionError:
    """The permanent refusal of a bytes fetch through an io layer that has no bytes port.

    WHY ``unsupported_mode``: the io lacks a capability, as a relative code pointer on an io
    without ``SupportsCode`` does; no body was seen, so its type was never unsupported.
    """
    return ResolutionError(
        f"{display_url(target)!r} needs a binary-safe io layer (fetch_bytes); this one has a text "
        "port only",
        code=ErrorCode.UNSUPPORTED_MODE,
        permanent=True,
    )


async def _text(result: str | Awaitable[str]) -> str:
    return await result if isawaitable(result) else result

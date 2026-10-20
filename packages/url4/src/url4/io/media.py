"""The binary-safe bytes port and the one text/binary media-type rule (``OME-1538``).

FEATURE: image and PDF inputs for url4 sources (epic ``OME-1529``). A source fetched
through :class:`SupportsFetchBytes` keeps its exact bytes and media type, so it can reach a
model as a file (Part G §26.2.3 ``data:`` URI) rather than as mangled text. An internal
port, not a spec change (``OME-1534`` point 4): ``Payload`` stays ``str``.

The text paths of every adapter call :func:`require_text` before decoding, so a binary body
fails with ``unsupported_content_type`` (spec C8) instead of reaching a model as mojibake.

AIDEV-NOTE: ``FetchedBytes`` / ``SupportsFetchBytes`` are port types and would sit in
``io.layer``, but that module is at its size cap (``scripts/check_module_size.py``). The
engine (``url4.dag``) may import only ``io.layer`` and ``io.idempotency``, so it reaches
``fetch_bytes`` duck-typed (``BoundedIOLayer``), never by importing this module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import FetchRequest, IOLayer, fetch_result


@dataclass(frozen=True)
class FetchedBytes:
    """A resolved body as raw bytes plus the media type the adapter observed (or ``None``)."""

    body: bytes
    media_type: str | None = None


@runtime_checkable
class SupportsFetchBytes(Protocol):
    """Optional adapter capability: binary-safe fetching.

    INVARIANT: ``body`` is the source's bytes exactly as received, never decoded and
    re-encoded, so a PNG or PDF hashes the same here as at its origin.
    """

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes: ...


async def fetch_bytes(io: IOLayer, request: FetchRequest) -> FetchedBytes:
    """Resolve ``request`` to bytes via ``fetch_bytes`` when the adapter provides it.

    WHY: an adapter without the capability can only ever produce text, so its body is
    UTF-8 encoded and its reported media type kept; nothing is lost that it had.
    """
    if isinstance(io, SupportsFetchBytes):
        return await io.fetch_bytes(request)
    result = await fetch_result(io, request)
    return FetchedBytes(result.body.encode("utf-8"), result.media_type)


def peer_set(peers: Iterable[str]) -> frozenset[str]:
    """The ``OME-1599`` interim allowlist: ``host[:port]`` authorities, lower-cased.

    An adapter declaring it answers ``blob_peer_allowed(authority)``; one that does not
    allows no cross-node blob fetch at all (fail closed, ``url4.dag.nodes.blob``).
    """
    return frozenset(peer.strip().lower() for peer in peers if peer.strip())


# Application types whose body is text even without a charset parameter.
_TEXT_APPLICATION_TYPES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/ecmascript",
        "application/x-ndjson",
        "application/ndjson",
        "application/jsonl",
        "application/yaml",
        "application/x-yaml",
        "application/toml",
        "application/sql",
        "application/graphql",
        "application/x-www-form-urlencoded",
    }
)
_TEXT_SUFFIXES = ("+json", "+xml", "+yaml")


def is_text_media_type(content_type: str | None) -> bool:
    """Whether a ``Content-Type`` (parameters allowed) denotes text the text path may decode.

    Text: no type at all (today's untyped behaviour), ``text/*``, any type declaring a
    ``charset``, the JSON/XML/YAML/JS/ndjson/form family, and ``+json``/``+xml``/``+yaml``
    suffixes. Everything else (``image/*``, ``application/pdf``,
    ``application/octet-stream``, …) is binary.

    WHY: a binary body must never reach ``response.text`` (``OME-1538``); decoding it
    produces mojibake that a model then reads silently. A text-only consumer refuses it
    with ``unsupported_content_type`` (spec C8) and a file-aware one uses ``fetch_bytes``.
    """
    head, _, params = (content_type or "").partition(";")
    media_type = head.strip().lower()
    declares_charset = any(
        p.split("=", 1)[0].strip().lower() == "charset" for p in params.split(";")
    )
    return (
        not media_type
        or declares_charset
        or media_type.startswith("text/")
        or media_type in _TEXT_APPLICATION_TYPES
        or media_type.endswith(_TEXT_SUFFIXES)
    )


def require_text(target: str, content_type: str | None) -> None:
    """Raise ``unsupported_content_type`` (spec C8) when ``content_type`` is binary.

    INVARIANT: every text-returning adapter path calls this BEFORE decoding, so a PNG
    or PDF fails loudly instead of reaching a model as mojibake (``OME-1538``).
    Permanent: a retry gets the same bytes back.
    """
    if not is_text_media_type(content_type):
        raise ResolutionError(
            f"{target!r} is {content_type!r}, which is not text; fetch it as bytes",
            code=ErrorCode.UNSUPPORTED_CONTENT_TYPE,
            permanent=True,
        )


__all__ = [
    "FetchedBytes",
    "SupportsFetchBytes",
    "fetch_bytes",
    "is_text_media_type",
    "peer_set",
    "require_text",
]

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

import re
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
# WHY: a charset parameter is a text hint only for an otherwise-unknown application type.
# These are binary whatever parameter they carry (review of PR #1478): a server that labels
# a PNG "image/png; charset=utf-8" still sends PNG bytes.
_BINARY_APPLICATION_TYPES = frozenset(
    {
        "application/octet-stream",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/x-gzip",
        "application/x-tar",
        "application/x-bzip2",
        "application/x-xz",
        "application/zstd",
        "application/x-7z-compressed",
        "application/vnd.rar",
        "application/wasm",
        "application/cbor",
        "application/msgpack",
        "application/x-protobuf",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
    }
)
_BINARY_APPLICATION_PREFIXES = (
    "application/vnd.openxmlformats-",
    "application/vnd.oasis.opendocument.",
)

# RFC 9110 §5.6.2 token / §5.6.4 quoted-string / §8.3.1 media-type, as regular expressions.
_TOKEN = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_QUOTED = r'"(?:[\t \x21\x23-\x5b\x5d-\x7e\x80-\xff]|\\[\t \x20-\x7e\x80-\xff])*"'
_PARAM_STEP = rf"[ \t]*;[ \t]*(?:({_TOKEN})=(?:{_TOKEN}|{_QUOTED}))?"
_MEDIA_TYPE = re.compile(rf"({_TOKEN}/{_TOKEN})((?:{_PARAM_STEP})*)")
_PARAMS = re.compile(_PARAM_STEP)
_OWS = " \t"


def _parse(content_type: str) -> tuple[str, frozenset[str]] | None:
    """``(bare lower-cased media type, parameter names)``, or ``None`` when invalid.

    RFC 9110 §8.3.1: ``type "/" subtype *( OWS ";" OWS [ name "=" ( token / quoted-string ) ] )``.

    INVARIANT: anything but exactly one media type is ``None`` — notably the comma-joined
    value HTTPX builds from duplicate ``Content-Type`` fields (``text/plain, image/png``),
    because a comma is legal only inside a quoted-string. A ``;charset=`` inside a quoted
    parameter value is data, never a parameter name (each quoted-string is consumed whole).
    """
    match = _MEDIA_TYPE.fullmatch(content_type.strip(_OWS))
    if match is None:
        return None
    names = {step.group(1).lower() for step in _PARAMS.finditer(match.group(2)) if step.group(1)}
    return match.group(1).lower(), frozenset(names)


def _is_binary(media_type: str) -> bool:
    return (
        media_type.split("/", 1)[0] != "application"
        or media_type in _BINARY_APPLICATION_TYPES
        or media_type.startswith(_BINARY_APPLICATION_PREFIXES)
    )


def is_text_media_type(content_type: str | None) -> bool:
    """Whether a ``Content-Type`` (parameters allowed) denotes text the text path may decode.

    Text: no type at all (today's untyped behaviour), ``text/*``, the JSON/XML/YAML/JS/
    ndjson/form family, ``+json``/``+xml``/``+yaml`` suffixes, and an otherwise-unknown
    ``application/*`` type declaring a ``charset``. Everything else is binary, including
    ``image/png; charset=utf-8`` (the charset never wins over an intrinsically binary type)
    and any value that is not exactly one valid media type (duplicate headers, ``text/``).

    WHY: a binary body must never reach ``response.text`` (``OME-1538``); decoding it
    produces mojibake that a model then reads silently. A text-only consumer refuses it
    with ``unsupported_content_type`` (spec C8) and a file-aware one uses ``fetch_bytes``.
    """
    if not content_type or not content_type.strip(_OWS):
        return True
    parsed = _parse(content_type)
    if parsed is None:
        return False
    media_type, params = parsed
    return (
        media_type.startswith("text/")
        or media_type in _TEXT_APPLICATION_TYPES
        or media_type.endswith(_TEXT_SUFFIXES)
        or ("charset" in params and not _is_binary(media_type))
    )


def bare_media_type(target: str, content_type: str | None) -> str | None:
    """The one bare, lower-cased media type of ``content_type``; ``None`` when absent.

    INVARIANT: the bytes path never exposes a comma-joined or malformed value; one that is
    not exactly one media type raises ``unsupported_content_type`` (permanent, spec C8).
    """
    if not content_type or not content_type.strip(_OWS):
        return None
    parsed = _parse(content_type)
    if parsed is None:
        raise ResolutionError(
            f"{target!r} has Content-Type {content_type!r}, which is not one valid media type",
            code=ErrorCode.UNSUPPORTED_CONTENT_TYPE,
            permanent=True,
        )
    return parsed[0]


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
    "bare_media_type",
    "fetch_bytes",
    "is_text_media_type",
    "require_text",
]

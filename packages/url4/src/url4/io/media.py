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

# RFC 9110 §5.6.2 tchar.
_TCHAR = frozenset("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_OWS = " \t"
# WHY: a Content-Type is a few dozen bytes; anything longer is refused before it is scanned,
# so a hostile server cannot make the parser work on a huge header.
_MAX_CONTENT_TYPE = 1024

# AIDEV-NOTE: a hand-written scanner on purpose, not a regex. The `*( OWS ";" OWS [param] )`
# grammar has overlapping whitespace quantifiers, and a regex of it backtracked exponentially
# (70 characters took ~11 s; security review of PR #1478). Every loop below advances `pos`,
# so parsing is linear in the (capped) header length.


def _token_end(value: str, pos: int) -> int:
    while pos < len(value) and value[pos] in _TCHAR:
        pos += 1
    return pos


def _skip_ows(value: str, pos: int) -> int:
    while pos < len(value) and value[pos] in _OWS:
        pos += 1
    return pos


def _vchar(char: str) -> bool:
    """HTAB, SP, VCHAR or obs-text: what a quoted-string may carry (RFC 9110 §5.6.4)."""
    return char == "\t" or " " <= char <= "~" or "\x80" <= char <= "\xff"


def _quoted_end(value: str, pos: int) -> int | None:
    """End of the quoted-string opening at ``pos``, or ``None`` when it is malformed."""
    pos += 1
    while pos < len(value) and value[pos] != '"':
        char = value[pos]
        if char == "\\" and pos + 1 < len(value) and _vchar(value[pos + 1]):
            pos += 2  # quoted-pair
        elif char != "\\" and _vchar(char):
            pos += 1
        else:
            return None
    return pos + 1 if pos < len(value) else None


def _value_end(value: str, pos: int) -> int | None:
    """End of a parameter value (token or quoted-string) starting at ``pos``."""
    if value[pos : pos + 1] == '"':
        return _quoted_end(value, pos)
    end = _token_end(value, pos)
    return None if end == pos else end


def _parameter(value: str, pos: int) -> tuple[int, str | None] | None:
    """``(end, lower-cased name)`` of the parameter at ``pos``; an empty one has no name."""
    if pos == len(value) or value[pos] == ";":
        return pos, None
    equals = _token_end(value, pos)
    if equals == pos or value[equals : equals + 1] != "=":
        return None
    end = _value_end(value, equals + 1)
    return None if end is None else (end, value[pos:equals].lower())


def _parameter_names(value: str, pos: int) -> frozenset[str] | None:
    """The names of ``*( OWS ";" OWS [ parameter ] )`` from ``pos`` to the end, else ``None``."""
    names: set[str] = set()
    while (pos := _skip_ows(value, pos)) < len(value):
        if value[pos] != ";":
            return None  # e.g. the "," HTTPX puts between duplicate header fields
        step = _parameter(value, _skip_ows(value, pos + 1))
        if step is None:
            return None
        pos, name = step
        if name is not None:
            names.add(name)
    return frozenset(names)


def _parse(content_type: str) -> tuple[str, frozenset[str]] | None:
    """``(bare lower-cased media type, parameter names)``, or ``None`` when invalid.

    RFC 9110 §8.3.1: ``type "/" subtype *( OWS ";" OWS [ name "=" ( token / quoted-string ) ] )``.

    INVARIANT: anything but exactly one media type is ``None`` — notably the comma-joined
    value HTTPX builds from duplicate ``Content-Type`` fields (``text/plain, image/png``),
    because a comma is legal only inside a quoted-string — and so is a header longer than
    ``_MAX_CONTENT_TYPE``. A ``;charset=`` inside a quoted parameter value is data, never a
    parameter name (each quoted-string is consumed whole).
    """
    # One past the cap is enough to know it is over; nothing longer is ever scanned.
    value = content_type.strip(_OWS)[: _MAX_CONTENT_TYPE + 1]
    slash = _token_end(value, 0)
    end = _token_end(value, slash + 1)
    if len(value) > _MAX_CONTENT_TYPE or slash == 0 or value[slash : slash + 1] != "/":
        return None
    names = None if end == slash + 1 else _parameter_names(value, end)
    return None if names is None else (value[:end].lower(), names)


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

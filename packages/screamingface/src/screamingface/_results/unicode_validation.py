"""Reject escaped Unicode corruption before incremental JSON decoding."""

import re
from collections.abc import Iterator
from pathlib import Path

from screamingface.errors import ExecutionError

_ESCAPE = re.compile(rb"\\(?:u[0-9a-fA-F]{4}|[\s\S])")
_CHUNK_BYTES = 65536


def validate_unicode(source: Path) -> None:
    # WHY: YAJL replaces lone high surrogates with '?'; validation after parsing is too late.
    escapes = iter(_escapes(source))
    for position, token in escapes:
        value = _code_unit(token)
        if 0xD800 <= value <= 0xDBFF:
            following, low = next(escapes, (-1, b""))
            if following != position + 6 or not 0xDC00 <= _code_unit(low) <= 0xDFFF:
                _invalid_surrogate()
        elif 0xDC00 <= value <= 0xDFFF:
            _invalid_surrogate()


def _code_unit(token: bytes) -> int:
    return int(token[2:], 16) if len(token) == 6 and token.startswith(b"\\u") else -1


def _invalid_surrogate() -> None:
    raise ExecutionError("Invalid result JSON: unpaired Unicode surrogate escape")


def _escapes(source: Path) -> Iterator[tuple[int, bytes]]:
    offset = 0
    pending = b""
    with source.open("rb") as stream:
        while True:
            chunk = stream.read(_CHUNK_BYTES)
            buffer = pending + chunk
            # INVARIANT: retain enough bytes to finish any six-byte escape across reads.
            limit = max(0, len(buffer) - 5) if chunk else len(buffer)
            consumed = 0
            for match in _ESCAPE.finditer(buffer):
                if match.start() >= limit:
                    consumed = match.start()
                    break
                yield offset + match.start(), match.group()
                consumed = match.end()
            else:
                consumed = max(consumed, limit)
            pending = buffer[consumed:]
            offset += consumed
            if not chunk:
                return

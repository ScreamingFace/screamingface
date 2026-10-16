"""Byte-preserving projection of one JSON string field."""

from __future__ import annotations

import json
from typing import Any

_WHITESPACE = b" \t\r\n"
_MAX_DEPTH = 128
_MAX_NODES = 100_000
_INVALID = object()


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _decode_unambiguous(content: bytes) -> Any:
    try:
        return json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (RecursionError, UnicodeDecodeError, ValueError):
        return _INVALID


def _is_bounded(value: Any) -> bool:
    stack = [(value, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_DEPTH:
            return False
        nodes += 1
        if nodes > _MAX_NODES:
            return False
        children = (
            node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
        )
        stack.extend((child, depth + 1) for child in children)
    return True


class _JsonStringLocator:
    def __init__(self, content: bytes, path: tuple[str, ...], expected: str) -> None:
        self.content = content
        self.path = path
        self.expected = expected
        self.matches: list[tuple[int, int]] = []

    def locate(self) -> tuple[tuple[int, int], ...]:
        try:
            end = self._whitespace(self._value(0, ()))
        except (IndexError, RecursionError, UnicodeDecodeError, ValueError):
            return ()
        return tuple(self.matches) if end == len(self.content) else ()

    def _whitespace(self, offset: int) -> int:
        content = self.content
        while offset < len(content) and content[offset] in _WHITESPACE:
            offset += 1
        return offset

    def _string(self, offset: int) -> tuple[int, str]:
        content = self.content
        start = offset
        offset += 1
        while offset < len(content):
            token = content[offset]
            if token == ord('"'):
                end = offset + 1
                return end, json.loads(content[start:end])
            offset += 2 if token == ord("\\") else 1
        raise ValueError("unterminated JSON string")

    def _value(self, offset: int, current: tuple[str, ...]) -> int:
        offset = self._whitespace(offset)
        token = self.content[offset]
        if token == ord('"'):
            end = self._string_value(offset, current)
        elif token == ord("{"):
            end = self._object(offset, current)
        elif token == ord("["):
            end = self._array(offset, current)
        else:
            end = self._scalar(offset)
        return end

    def _string_value(self, offset: int, current: tuple[str, ...]) -> int:
        end, decoded = self._string(offset)
        if current == self.path and decoded == self.expected:
            self.matches.append((offset, end))
        return end

    def _object(self, offset: int, current: tuple[str, ...]) -> int:
        content = self.content
        offset = self._whitespace(offset + 1)
        while content[offset] != ord("}"):
            end, key = self._string(offset)
            offset = self._whitespace(end)
            if content[offset] != ord(":"):
                raise ValueError("missing JSON object colon")
            offset = self._whitespace(self._value(offset + 1, (*current, key)))
            if content[offset] == ord("}"):
                break
            if content[offset] != ord(","):
                raise ValueError("missing JSON object comma")
            offset = self._whitespace(offset + 1)
        return offset + 1

    def _array(self, offset: int, current: tuple[str, ...]) -> int:
        content = self.content
        offset = self._whitespace(offset + 1)
        while content[offset] != ord("]"):
            offset = self._whitespace(self._value(offset, (*current, "[]")))
            if content[offset] == ord("]"):
                break
            if content[offset] != ord(","):
                raise ValueError("missing JSON array comma")
            offset = self._whitespace(offset + 1)
        return offset + 1

    def _scalar(self, offset: int) -> int:
        content = self.content
        while offset < len(content) and content[offset] not in b",]}":
            offset += 1
        return offset


def replace_json_string_at_path(
    content: bytes,
    *,
    path: tuple[str, ...],
    expected: str,
    replacement: str,
) -> bytes:
    """Replace one matching JSON string token without reserializing its document."""

    decoded = _decode_unambiguous(content)
    if decoded is _INVALID or not _is_bounded(decoded):
        return content
    matches = _JsonStringLocator(content, path, expected).locate()
    # INVARIANT: ambiguous duplicate paths remain byte-identical rather than choosing
    # a different field than the upstream validator observed.
    if len(matches) != 1:
        return content
    start, stop = matches[0]
    encoded = json.dumps(replacement, ensure_ascii=False, separators=(",", ":")).encode()
    return content[:start] + encoded + content[stop:]


__all__ = ["replace_json_string_at_path"]

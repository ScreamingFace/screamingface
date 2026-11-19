"""Write a JSON row as ASCII text, so one wide character cannot multiply a run's memory.

FEATURE: a full-set Cases read fits the run's memory budget. Python stores a ``str`` at the
width of its widest character: 1 byte a character for ASCII, 4 once a single character above
U+FFFF is present. EnigmaEval's 381 MiB ``cases.json`` holds one such character (U+1F815), and
serving it as raw text cost 1,525 MiB a copy. As ASCII it costs 381.

Standard library only: this sits on the Cases route's read path (``board_store``).
"""

from __future__ import annotations

import re

_NON_ASCII: re.Pattern[str] = re.compile(r"[^\x00-\x7f]")
# UTF-16 surrogate arithmetic, for a character above the Basic Multilingual Plane: its offset
# from U+10000 is split into a high and a low 10-bit half.
_FIRST_ASTRAL: int = 0x10000
_HIGH_SURROGATE: int = 0xD800
_LOW_SURROGATE: int = 0xDC00
_SURROGATE_BITS: int = 10
_SURROGATE_MASK: int = 0x3FF


def _json_escape(match: re.Match[str]) -> str:
    """One non-ASCII character as a JSON ``\\uXXXX`` escape.

    Worked example: "π" (U+03C0) is ``\\u03c0``; "🠕" (U+1F815) is above U+FFFF, so it is the
    UTF-16 surrogate pair ``\\ud83e\\udc15``, the only form JSON has for it. For a non-ASCII
    character this is also the spelling ``json.dumps`` writes.
    """

    code_point: int = ord(match.group())
    if code_point < _FIRST_ASTRAL:
        return f"\\u{code_point:04x}"
    offset: int = code_point - _FIRST_ASTRAL
    high: int = _HIGH_SURROGATE + (offset >> _SURROGATE_BITS)
    low: int = _LOW_SURROGATE + (offset & _SURROGATE_MASK)
    return f"\\u{high:04x}\\u{low:04x}"


def ascii_row(row: bytes) -> str:
    """One checked row as ASCII JSON text of the same value: non-ASCII becomes ``\\uXXXX``.

    WHY: Python stores a ``str`` at the width of its widest character, so one character above
    U+FFFF among a Benchmark's Cases makes the whole served text cost 4 bytes a character. An
    ASCII text always costs 1.
    INVARIANT: the value does not change. ``_check_row`` has parsed ``row`` as JSON, and in
    valid JSON a non-ASCII character can only sit inside a string, where its escape means the
    same character. url4's ``parse_collection`` re-serialises each row from its parsed value,
    so the item texts a run fans out are byte for byte what they were
    (``test_board_store_ascii_serving.py``).
    AIDEV-NOTE: the promise is "same JSON value, ASCII text", NOT "the text ``json.dumps``
    would write". Every ASCII character is left as the writer wrote it, DEL (U+007F) included,
    which ``json.dumps`` would spell ``\\u007f``. Compare served rows by value, never by
    spelling.

    Raises:
        ValueError: the bytes are not UTF-8 (the caller bounds it).
    """

    # WHY the fast path: most rows are pure ASCII (a picture is base64), and they are served
    # as the writer's own bytes, with no pattern scan.
    if row.isascii():
        return row.decode("ascii")
    return _NON_ASCII.sub(_json_escape, row.decode("utf-8"))


__all__ = ["ascii_row"]

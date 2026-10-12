"""Spec B `quoted-text` as a value: write a literal, read one back (url4 2.0).

One owner for the two directions, on top of the grammar's own escape rules
(:mod:`url4.core._lexical`): ``\\'`` and ``\\\\`` are the only escapes, and a quoted
literal holds no control character (`quoted-char = %x20-7E`; url4 also takes non-ASCII).
The wire codec (:mod:`url4.wire.subrequest`) uses these to carry a forwarded prompt
(contracts C9).
"""

from __future__ import annotations

from url4.core._lexical import _CONTROL_CHAR_RE, _unquote
from url4.core.errors import ParseError


def quote_text(text: str) -> str | None:
    """``text`` as one `quoted-text` literal, or None when it holds a control character."""
    if _CONTROL_CHAR_RE.search(text):
        return None
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def unquote_text(token: str) -> str | None:
    """The content of ``token`` when it is exactly one `quoted-text` literal, else None."""
    if not token.startswith("'"):
        return None
    try:
        return _unquote(token)
    except ParseError:
        return None


__all__ = ["quote_text", "unquote_text"]

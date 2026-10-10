"""Lexical productions shared by the grammar and the renderer (Spec B §7, §8).

Split out of :mod:`url4.core.grammar` (module-size cap): the ABNF character
classes as anchored ASCII patterns, and the ``quoted-text`` decode with its two
escapes. The grammar, the structured-value parser and the renderer all read
these, so the classes are declared once.
"""

from __future__ import annotations

import re

from url4.core._scan import iter_iteration_stars, iter_top_level, skip_quoted
from url4.core.errors import ParseError

# INVARIANT: the ABNF's ALPHA is ASCII. Python's `\w` is Unicode-aware by
# default, so every identifier pattern here compiles with re.ASCII — otherwise
# `$café` / `@bób` / `articleé=…` parse as identifiers the grammar does not
# admit (`OME-504`).
_IDENT_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://")
# identity-name = name-part / 1*DIGIT — a digit-led name followed by letters
# (`@9lives`) is NEITHER alternative and must not parse.
_IDENTITY_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+", re.ASCII)
_IDENTITY_RE = re.compile(rf"@({_IDENTITY_NAME_RE.pattern})", re.ASCII)
_VARREF_HEAD_RE = re.compile(r"\$([A-Za-z_]\w*|\d+)", re.ASCII)
_FIELD_SEG_RE = re.compile(r"[A-Za-z_]\w*", re.ASCII)
# path-segment (§ identity-collection) — the ABNF's explicit character class.
_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9\-_.~:@!$&+=]+", re.ASCII)
# INVARIANT: budget-key = 1*( ALPHA / "_" ) — digits are deliberately excluded.
_BUDGET_KEY_RE = re.compile(r"[A-Za-z_]+", re.ASCII)
# scalar-budget-value = 1*( ALPHA / DIGIT / "." / "-" / "_" )
_SCALAR_BUDGET_RE = re.compile(r"[A-Za-z0-9.\-_]+", re.ASCII)
_INDEX_SEG_RE = re.compile(r"(0|[1-9]\d*)\]")
_STRUCT_KEY_RE = re.compile(r"[A-Za-z0-9_]+")
_STRUCT_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-]+")


def _unquote(token: str) -> str:
    """Decode a fully-quoted ``'…'`` token to its content (``\\'``/``\\\\``)."""
    end = skip_quoted(token, 0)
    if end == 1:
        raise ParseError(f"unterminated quote in {token!r}", position=0)
    if end != len(token):
        raise ParseError(f"unexpected text after quoted value in {token!r}", position=end)
    return _unescape(token[1:-1])


def _unescape(content: str) -> str:
    """Decode a quoted body: the ``\\'`` and ``\\\\`` escapes, no raw control chars.

    # INVARIANT: exactly two escapes are defined. A backslash before anything
    # else is rejected, as is a raw control character (< %x20, or DEL) — httpx
    # rejects those in a URL anyway.
    """
    out: list[str] = []
    i = 0
    while i < len(content):
        char = content[i]
        if char == "\\":
            nxt = content[i + 1] if i + 1 < len(content) else ""
            if nxt not in ("\\", "'"):
                raise ParseError(
                    f"undefined escape {'\\' + nxt!r} in quoted text — the grammar "
                    r"defines only \' and \\"
                )
            out.append(nxt)
            i += 2
            continue
        if char < " " or char == "\x7f":
            raise ParseError(f"raw control character {char!r} in quoted text (spec quoted-char)")
        out.append(char)
        i += 1
    return "".join(out)


def reject_chained_intent(intent: str) -> None:
    """Refuse a second ``!`` after an intent (owner decision D-1b, Spec B §8).

    ``intent = value``, and ``bare-value`` / ``quoted-text`` end at an unquoted
    ``!``: nothing may follow an intent but ``;`` params. So ``a!b`` and
    ``'a'!'b'`` are not intents, and ``/p(x)!a!b`` has no reading. A
    value-shaped intent (a group, a struct, a holdings ref, a ``/path``, an
    iteration) carries its own ``!`` inside its own production, so it is left
    to that production.
    """
    text = intent.strip()
    if text[:1] in "({@/" or next(iter_iteration_stars(text), None) is not None:
        return
    for i, ch in iter_top_level(text):
        if ch == "!":
            raise ParseError(
                f"chained intent {text!r} — an intent is one value and only ';' params "
                "may follow it; quote a literal '!', or group a call to process its "
                "result: (/p(x)!a)!b",
                position=i,
            )


def check_tail_url_intent(intent: str) -> None:
    """A top-level absolute-URL intent is ``bare-value`` (Spec B §8): no ``(`` ``)`` ``'``.

    Nested, a call's URL intent sits inside its own production; at the top
    level it is the text's tail, where the renderer has no way to write these
    characters back. Percent-encode them (``%28`` ``%29`` ``%27``).
    """
    for ch in "()'":
        if ch in intent:
            raise ParseError(
                f"intent {intent!r} is not a bare value (Spec B §8): a top-level URL "
                f"intent cannot hold {ch!r}; percent-encode it"
            )

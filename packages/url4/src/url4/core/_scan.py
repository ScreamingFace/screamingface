"""Low-level depth-tracking scanners shared across the string decoders.

The single primitive behind url4's structure-aware parsing: track ``(``/``)``
and ``{``/``}`` nesting plus ``'…'`` quote runs (``\\'`` and ``\\\\`` escapes
honored), so callers can find balanced spans or the characters that sit outside
all nesting — spec §8 parse rule 8: only separators at depth 0 outside quotes
are structural. JSON string literals (``"…"``) are a separate skip rule for the
substitution engine's brace scan, because JSON quoting is not the grammar's.
Kept as a dependency-free leaf (imports nothing internal) so
the parser envelope-decoders (:mod:`url4.core.parser`), the grammar
(:mod:`url4.core.grammar`), and the sub-request codec (:mod:`url4.wire.subrequest`) share
one implementation instead of each carrying their own copy.
"""

from __future__ import annotations

from collections.abc import Iterator

_OPENERS = "({"
_CLOSERS = ")}"


def skip_quoted(text: str, i: int) -> int:
    """Return the index just past the quote run opening at ``i``.

    ``i`` must point at a ``'``. ``\\'`` and ``\\\\`` escapes are honored. An
    unterminated quote returns ``i + 1`` — the quote is treated as an ordinary
    literal character, preserving tolerance for malformed input. Callers can
    therefore detect the unterminated case by ``skip_quoted(t, i) == i + 1``
    (a terminated run, even the empty ``''``, always returns ``>= i + 2``).
    """
    j = i + 1
    n = len(text)
    # INVARIANT: everything scanned so far belongs to the quote run opened at
    #     ``i`` — a structural character inside the run is never exposed to a
    #     caller, so quoted regions are never split mid-run.
    # VARIANT: ``j`` strictly increases (≥ 1 per iteration; 2 across an
    #     escape), so the scan always terminates; a terminated run (even the
    #     empty ``''``) returns ≥ i + 2, only exhaustion returns i + 1.
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
        elif ch == "'":
            return j + 1
        else:
            j += 1
    return i + 1


def iter_top_level(expr: str) -> Iterator[tuple[int, str]]:
    """Yield ``(index, char)`` for every character at depth 0 outside quotes.

    ``(``/``)`` and ``{``/``}`` track one combined nesting depth and are never
    yielded; a quote run's contents (delimiters included) are never yielded, so
    callers only see the structural characters of the current level. Depth is
    clamped at 0 — a stray closer is swallowed as structural and scanning
    continues at depth 0 (malformed-input tolerance; a stray opener swallows
    the rest, as before). An unterminated ``'`` is yielded as a literal.
    """
    depth = 0
    i = 0
    n = len(expr)
    # INVARIANT: only characters at combined depth 0 OUTSIDE every quote run
    #     are yielded — a separator inside ``(…)``/``{…}`` or ``'…'`` always
    #     belongs to its enclosing region and is never seen as structural
    #     (spec §8 parse rule 8).
    # VARIANT: ``i`` strictly increases (``i = end`` skips a whole quote run,
    #     where ``end ≥ i + 1``; every other branch adds 1), so iteration ends.
    while i < n:
        ch = expr[i]
        if ch == "'":
            end = skip_quoted(expr, i)
            if end == i + 1 and depth == 0:
                yield i, ch
            i = end
            continue
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth = max(depth - 1, 0)
        elif depth == 0:
            yield i, ch
        i += 1


def iter_non_string_chars(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(index, char)`` for every char not inside a JSON string literal.

    A ``"`` whose closing ``"`` exists (``\\`` and ``\\"`` escapes honored) is
    skipped wholesale, so a structural character inside a JSON string value
    cannot perturb a depth scan. An unterminated ``"`` is yielded as an
    ordinary char — malformed input has no real string to skip.
    """
    i = 0
    n = len(text)
    # INVARIANT: a character inside a complete ``"…"`` literal is never
    #     yielded — structural characters there cannot perturb a caller's
    #     depth scan; only an unterminated ``"`` falls through as ordinary.
    # VARIANT: ``i`` strictly increases (``i = j + 1`` skips a whole literal,
    #     where ``j ≥ i + 1``; every other iteration adds 1), so iteration ends.
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j < n:
                i = j + 1
                continue
        yield i, text[i]
        i += 1


def balanced_braces(text: str, start: int) -> int | None:
    """Return the index just past the ``}`` closing the brace run at ``start``.

    ``start`` points at the first ``{`` of the run. Quote runs are skipped
    wholesale (``skip_quoted``), so a brace inside a ``'…'`` quote cannot
    desync the depth count. Returns ``None`` if the braces never balance; a
    stray ``}`` at depth 0 is swallowed as structural and scanning continues
    (malformed-input tolerance), as before.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            i = skip_quoted(text, i)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def balanced_body(text: str, start: int) -> str | None:
    """Return the substring from ``start`` up to its matching ``)``, or None.

    ``start`` is the index just inside an already-open ``(`` (depth 1). Quote
    runs are skipped wholesale so a quoted paren cannot desync the match;
    braces are not paren-structural. Returns ``None`` if the parens never
    balance.
    """
    depth = 1
    j = start
    n = len(text)
    while j < n and depth > 0:
        ch = text[j]
        if ch == "'":
            j = skip_quoted(text, j)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        j += 1
    return text[start : j - 1] if depth == 0 else None


def find_unquoted(text: str, chars: str, start: int = 0) -> int | None:
    """The first occurrence of any of ``chars`` outside quote runs (parens seen).

    Unlike :func:`find_top_level`, nesting is NOT tracked — an opener is an
    ordinary candidate character, which is what callers looking for the *first*
    ``(`` need (``find_top_level`` skips whole paren groups, so it never yields
    the opener itself).
    """
    i = start
    n = len(text)
    while i < n:
        if text[i] == "'":
            i = skip_quoted(text, i)
            continue
        if text[i] in chars:
            return i
        i += 1
    return None


def iter_iteration_stars(text: str, *, skip_leading: bool = False) -> Iterator[int]:
    """Yield the index of every depth-0 ``*`` immediately followed by ``(``.

    THE single definition of how the §5.3.3 iteration operator is recognised.
    Callers differ in what they do with a hit — take the first, slice the body,
    split around it — but not in what counts as one.

    ``skip_leading`` excludes position 0, where a ``*`` is the *expansion*
    prefix rather than iteration (§5.2 rule 9). Value-position callers set it;
    envelope-level callers, which have already consumed any expansion prefix,
    do not.
    """
    for i, ch in iter_top_level(text):
        if ch == "*" and text[i + 1 : i + 2] == "(" and not (skip_leading and i == 0):
            yield i


def one_paren_layer(text: str) -> str | None:
    """The interior of ``text`` if it is exactly one balanced paren layer.

    ``(a, b)`` → ``a, b``; ``(a)(b)`` or a non-parenthesized string → ``None``.
    ``text`` is one layer iff the first ``(``'s matching ``)`` is its very last
    character, i.e. the balanced body spans the whole interior. Leading and
    trailing whitespace is significant — strip before calling if it isn't.
    """
    if not text.startswith("("):
        return None
    body = balanced_body(text, 1)
    return body if body is not None and len(body) == len(text) - 2 else None


def find_top_level(expr: str, chars: str) -> int | None:
    """Return the index of the first depth-0 occurrence of any of ``chars``."""
    for i, ch in iter_top_level(expr):
        if ch in chars:
            return i
    return None


def split_query_segments(text: str) -> list[str]:
    """Split a query string on its depth-0, unquoted ``&`` separators.

    THE single definition of the §3.3.1 query-segment rule: an ``&`` nested
    inside ``(…)``/``{…}`` or a ``'…'`` quote belongs to its enclosing value,
    never to the parameter list. Parts are stripped; empty input yields ``[]``.
    """
    return split_top_level(text, "&")


def split_top_level(expr: str, sep: str) -> list[str]:
    """Split ``expr`` on ``sep`` at depth 0 outside quotes; parts are stripped.

    Empty (or whitespace-only) input yields ``[]``, so callers can treat "no
    segments" and "no input" uniformly.
    """
    if not expr.strip():
        return []
    parts: list[str] = []
    last = 0
    for i, ch in iter_top_level(expr):
        if ch == sep:
            parts.append(expr[last:i])
            last = i + 1
    parts.append(expr[last:])
    return [p.strip() for p in parts]


__all__ = [
    "balanced_body",
    "balanced_braces",
    "find_top_level",
    "find_unquoted",
    "iter_iteration_stars",
    "iter_non_string_chars",
    "iter_top_level",
    "one_paren_layer",
    "skip_quoted",
    "split_query_segments",
    "split_top_level",
]

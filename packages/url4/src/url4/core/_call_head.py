"""Call heads: where a relative or remote call's context opens (Spec B §8 rules 7a–7d).

Split out of :mod:`url4.core.grammar` (module-size cap). One owner for "is
this text a call target": the ``path`` production, the ``url4://`` authority
split, and the canonical-form query helpers (the ``q=(`` scan with its depth-0
``&`` rule, and the query-parameter decode before it). The grammar parses
calls with these, and the envelope splitter
(:mod:`url4.core._splitters`) asks :func:`is_call_head` before it splits a
top-level ``!``, so the two cannot disagree about which ``!`` a call owns.
"""

from __future__ import annotations

import re

from url4.core._annotations import validate_param
from url4.core._scan import iter_top_level, split_query_segments
from url4.core.errors import ParseError
from url4.core.nodes import Params

# §8 `path = segment *( "/" segment )`, `segment = *( ALPHA / DIGIT / "-" /
# "_" / "." / "~" )` — the NARROW charset, for expression-bearing paths
# (relative-expr / remote-expr).
# WHY: `render._check_path` reads this same pattern — keeps parse and render
# from drifting (`OME-507`).
PATH_RE = re.compile(r"(?:/[A-Za-z0-9\-_.~]*)+", re.ASCII)


REMOTE_SCHEME = "url4://"

# `relative-uri`'s `path-segment` — the WIDE charset.
# WHY: it admits "$", which is what makes a variable-bearing data reference like
# `/data/$topic` legal. A data path is a DIFFERENT production from an expression
# path; narrowing it to match would break those references.
_DATA_PATH_RE = re.compile(r"(?:/[A-Za-z0-9\-_.~:@!$&+=]+)+", re.ASCII)

# `port = 1*DIGIT`.
# WHY: `host = hostname / IPv4address` is deliberately NOT validated — the grammar
# defines neither `hostname` nor `IPv4address`, so a charset here would assert a
# rule the spec does not state.
_PORT_RE = re.compile(r"[0-9]+", re.ASCII)


def check_expr_path(path: str, token: str) -> None:
    """Validate an expression-bearing path against `path` / `segment`."""
    if not PATH_RE.fullmatch(path):
        raise ParseError(
            f"invalid expression path {path!r} in {token!r} — a path segment takes "
            "ALPHA / DIGIT / '-' / '_' / '.' / '~'",
        )


def check_data_path(token: str) -> None:
    """Validate a `relative-uri` path against `path-segment` (query-tail aside)."""
    path = token.partition("?")[0]
    if not _DATA_PATH_RE.fullmatch(path):
        raise ParseError(
            f"invalid data path {path!r} in {token!r}",
        )


def check_authority(authority: str, token: str) -> None:
    """Validate `authority = host [ ":" port ]` — the PORT only (see `_PORT_RE`)."""
    host, sep, port = authority.partition(":")
    if sep and not _PORT_RE.fullmatch(port):
        raise ParseError(
            f"invalid port {port!r} in {token!r} — `port = 1*DIGIT`",
        )
    if not host:
        raise ParseError(f"remote expression has no host: {token!r}")


def remote_path_offset(token: str) -> int | None:
    """The offset of the path's ``/`` in ``url4://authority/path…``, or None."""
    slash = token.find("/", len(REMOTE_SCHEME))
    return None if slash == -1 else slash


def is_call_head(head: str) -> bool:
    """True when ``head`` followed by ``(`` opens a call's context (§8 rules 7a–7d).

    ``head`` is everything before the context's ``(``: ``/path`` or
    ``url4://authority/path`` for the sugar forms, and the same target plus
    ``?[params&]q=`` for the canonical forms. The envelope splitter asks this
    before it splits a top-level ``!``, so the call's own ``intent-op intent``
    stays with the call (`OME-508`).
    """
    target = head
    if head.startswith(REMOTE_SCHEME):
        slash = remote_path_offset(head)
        if slash is None or slash == len(REMOTE_SCHEME):  # no path, or no authority
            return False
        target = head[slash:]
    qmark = target.find("?")
    if qmark == -1:
        return PATH_RE.fullmatch(target) is not None
    # Canonical: the head must end in the `q=` that `find_expression_param` locks onto.
    opened = target + "("
    return (
        PATH_RE.fullmatch(target[:qmark]) is not None
        and find_expression_param(opened, qmark) == len(target) - 2
    )


def find_expression_param(token: str, qmark: int) -> int | None:
    """The offset of ``q=(`` as a query parameter after ``qmark``, or None.

    # INVARIANT: ``&`` separates query parameters only at depth 0 outside
    # quotes — the same rule :func:`url4.wire.subrequest.extract_expression_params`
    # applies on the wire. A quote-only scan mistook an ``&`` nested inside a
    # parenthesized expression-bearing value (``processor=(/x?a=1&b=2&q=(y)!z)``)
    # for a parameter boundary and locked onto the INNER ``q=(`` (`OME-501`).
    """
    start = qmark + 1
    if token[start : start + 3] == "q=(":
        return start
    rest = token[start:]
    for i, ch in iter_top_level(rest):
        if ch == "&":
            candidate = start + i + 1
            if token[candidate : candidate + 3] == "q=(":
                return candidate
    return None


def decode_query_params(params_text: str) -> Params:
    # INVARIANT: same depth-0 rule as find_expression_param — a nested ``&``
    # belongs to its enclosing value, not to this parameter list.
    if not params_text:
        return ()
    pairs: list[tuple[str, str | None]] = []
    for segment in split_query_segments(params_text):
        if segment:
            key, eq, value = segment.partition("=")
            decoded = value if eq else None
            validate_param(key, decoded)
            pairs.append((key, decoded))
    return tuple(pairs)

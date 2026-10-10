"""String-level envelope splitters: depth/quote-aware scans above the source grammar.

Split out of :mod:`url4.core.parser` (module-size cap), which re-exports every
public name here. Each function peels one part of the surface envelope as raw
text: the outermost ``!``/``!*`` split, the ``;key=val`` per-expression
protocol parameters (spec §9.2, including the ``iteration.*`` directives of
§5.3.6), and the ``src*(body)`` iteration shape. The envelope decoder
(:func:`url4.core.parser.decode_envelope`) runs them in a fixed order.
"""

from __future__ import annotations

import warnings

from url4.core._annotations import extract_directives, split_annotation_pairs
from url4.core._call_head import is_call_head
from url4.core._scan import balanced_body, find_unquoted, iter_iteration_stars, one_paren_layer
from url4.core._scan import iter_top_level as _iter_top_level
from url4.core._scan import split_top_level as _split_top_level
from url4.core.errors import ParseError
from url4.core.nodes import IterationDirectives, Params


def split_intent(expr: str) -> tuple[str, str | None, bool]:
    """Split ``expr`` on the outermost ``!`` / ``!*`` (outside nesting/quotes).

    Returns ``(source_expression, intent, broadcast)``. ``broadcast`` is True
    for the ``!*`` operator (apply intent per source). A ``!`` that closes a
    call's context belongs to that call and is skipped: the sugar forms
    (``/path(ctx)!``, ``url4://node/path(ctx)!``) and the canonical forms
    (``/path?[params&]q=(ctx)!``, ``url4://node/path?…q=(ctx)!``).
    """
    for i, ch in _iter_top_level(expr):
        if ch == "!" and not _is_backend_call_tail(expr, i):
            if i + 1 < len(expr) and expr[i + 1] == "*":
                return expr[:i], expr[i + 2 :], True
            return expr[:i], expr[i + 1 :], False
    return expr, None, False


def owns_call_intent(expr: str) -> bool:
    """True when ``expr`` holds a call's own ``!intent`` at depth 0 (``/p(x)!a``)."""
    return any(ch == "!" and _is_backend_call_tail(expr, i) for i, ch in _iter_top_level(expr))


def _is_backend_call_tail(expr: str, bang: int) -> bool:
    """True if the ``!`` at ``bang`` closes a leading relative/remote CALL.

    ``/path(ctx)!intent`` and ``url4://node/path(ctx)!intent`` are single call
    tokens: every call production carries its own ``intent-op intent``
    (`OME-508`), so that ``!`` belongs to the CALL, not to an enclosing
    envelope. Splitting it off produced a ``RelExpr(intent=None)`` that the
    grammar cannot derive and the renderer cannot emit — and left the text path
    disagreeing with ``grammar.parse``, which has always read the whole token
    as one RelExpr.

    The discriminator: the depth-0 ``(…)`` group that closes immediately before
    the ``!``, and everything before it is a call head — the grammar decides
    that (:func:`~url4.core._call_head.is_call_head`), for the sugar forms
    (``/path``, ``url4://authority/path``) and the canonical forms
    (``/path?[params&]q=``). So ``()!intent`` (empty source list) and
    ``src*()!intent`` (iteration body) still split — their head is not a call
    head — and ``https://x!go`` still splits, since no ``)`` precedes it.
    """
    if bang < 1 or expr[bang - 1] != ")":
        return False
    opener = _depth0_opener(expr, bang - 1)
    return opener is not None and is_call_head(expr[:opener])


def _depth0_opener(expr: str, close: int) -> int | None:
    """The ``(`` of the depth-0 group whose ``)`` sits at ``close``, or None."""
    opener = find_unquoted(expr, "(")
    while opener is not None:  # walk the depth-0 groups left to right
        body = balanced_body(expr, opener + 1)
        end = None if body is None else opener + 1 + len(body)
        if end is None or end >= close:
            return opener if end == close else None
        opener = find_unquoted(expr, "(", end + 1)
    return None


def split_expr_params(expr: str) -> tuple[str, Params, IterationDirectives]:
    """Strip the trailing depth-0 ``;key[=val]`` chain (spec §9.2).

    Returns ``(clean_expr, params, directives)``: the ``iteration.*`` keys
    (§5.3.6; deprecated ``foreach.*`` spellings warn) decode into
    :class:`~url4.core.nodes.IterationDirectives`, every other key is preserved
    verbatim in ``params`` (flags carry a None value).
    """
    parts = _split_top_level(expr, ";")
    if len(parts) <= 1:
        return expr.strip(), (), IterationDirectives()
    params, directives = extract_directives(split_annotation_pairs(parts[1:]))
    return parts[0], params, directives


def split_foreach_annotations(expr: str) -> tuple[str, IterationDirectives]:
    """Deprecated pre-0.2 name for the directive split; use :func:`split_expr_params`."""
    warnings.warn(
        "split_foreach_annotations() is deprecated; use split_expr_params()",
        DeprecationWarning,
        stacklevel=2,
    )
    clean, _, directives = split_expr_params(expr)
    return clean, directives


def split_collection_iteration(source_expr: str) -> tuple[str | None, str | None]:
    """Detect the ``source*(body)`` collection-iteration pattern.

    Scans for ``*(`` at depth 0. On a match returns
    ``(collection_source, iteration_body)``; otherwise ``(None, None)``.
    """
    for i in iter_iteration_stars(source_expr):
        body = balanced_body(source_expr, i + 2)
        if body is not None:
            return source_expr[:i].strip(), body
    return None, None


def _split_at_iteration_body(text: str) -> tuple[str | None, str]:
    """Split ``text`` just after a depth-0 ``*(body)``, or ``(None, "")``.

    Returns ``(head, tail)`` where ``head`` runs from the start through the
    closing ``)`` of the iteration body and ``tail`` is whatever follows.

    # WHY: only a depth-0 ``*(`` is an envelope-level iteration. The
    # reduce-over-iteration shape ``(src*(body)!peri)!reducer`` and a
    # descriptored collection (§5.3.10) both nest their ``*(`` inside parens,
    # so they are invisible here and keep their existing decode route.
    """
    for i in iter_iteration_stars(text):
        body = balanced_body(text, i + 2)
        if body is not None:
            end = i + 2 + len(body) + 1
            return text[:end], text[end:]
    return None, ""


def split_top_level_commas(expr: str) -> list[str]:
    """Split ``expr`` on commas outside nesting/quotes; empty input → ``[]``."""
    return _split_top_level(expr, ",")


def strip_one_paren_layer(expr: str) -> str | None:
    """Return the contents of ``expr`` if it is exactly one balanced paren layer.

    ``(a, b)`` → ``a, b``; ``(a)(b)`` or a non-parenthesized string → ``None``.
    Surrounding whitespace is insignificant here (the envelope decoders hand
    over unstripped segments); the shared primitive itself is strip-free.
    """
    return one_paren_layer(expr.strip())


def split_envelope_intent(stripped: str) -> tuple[str, str | None, bool]:
    """The envelope's ``(source_expr, raw_intent, broadcast)``, iteration body first."""
    head, tail = _split_at_iteration_body(stripped)
    if head is not None:
        # Only the text AFTER the iteration body can carry the envelope's own
        # ``!intent`` / ``;params``; everything up to and including the body is
        # the source side.
        tail_src, raw_intent, broadcast = split_intent(tail) if tail else ("", None, False)
        return head + tail_src, raw_intent, broadcast
    source_expr, raw_intent, broadcast = split_intent(stripped)
    if raw_intent is not None and owns_call_intent(source_expr):
        # D-1b: a call carries its own intent, so `/p(x)!a!b` has no reading.
        raise ParseError(
            f"chained intent in {stripped!r} — a call carries its own intent and only "
            "';' params may follow it; group the call to process its result: (/p(x)!a)!b"
        )
    return source_expr, raw_intent, broadcast

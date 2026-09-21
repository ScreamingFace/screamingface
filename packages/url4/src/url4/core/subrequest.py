"""The ``?q=(context)!intent`` sub-request wire format — one codec, one owner.

A url4 relative expression ``/path(context)!intent`` is dispatched as a
localhost fetch of ``/path?[params&]q=(context)!intent`` (there is no separate
"backend call" primitive — see :mod:`url4.io.layer`). This module is the single
owner of that encoding: the executable nodes in :mod:`url4.dag.nodes` build
sub-requests with :func:`encode_subrequest`, and
:class:`~url4.io.layer.StaticIOLayer` decodes the ``?q=`` payload back with
:func:`decode_subrequest`. :func:`extract_expression_params` is the spec §3.3.1
depth-aware query-string splitter a receiving node runs first. Keeping all
sides here means the wire format has exactly one definition, and the balanced
paren scan it needs is reused from :mod:`url4.core._scan` rather than re-derived.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import unquote, unquote_plus

from url4.core._annotations import EXPRESSION_BEARING_KEYS, validate_param
from url4.core._scan import balanced_body, split_top_level
from url4.core.errors import ParseError

# Characters that cannot appear raw inside a context/intent payload:
#   ( )  would desync the balanced-paren scan that delimits the context;
#   '    would let the decoder's quote-aware scan skip a structural ')';
#   %    would be misread as a percent-escape by the decoder;
#   & #  break query parsing on a real HTTP transport;
#   space is invalid raw in a URL (spec §7.3: MUST encode as + or %20);
#   control chars (incl. newline/tab/CR) make httpx reject the URL as invalid.
# Everything else — ``$``, ordinary punctuation — is left verbatim so the wire
# form stays human-readable, which is the whole point of url4 URLs.
_WIRE_UNSAFE = re.compile(r"[()'%&# \x00-\x1f\x7f]")

# INVARIANT (spec §11.6.3): transport-only parameters are scoped to the single
# hop that received them and MUST NOT appear on an outbound sub-request. This
# frozenset is the ONE definition of that rule — the HTTP ingress
# (`url4.peer.server._reassemble`) and the sub-request builder
# (`url4.dag.nodes._wire_params`) both consume it. They previously enforced it
# independently, so a `resume=`/`rid=` written in expression text was stripped
# inbound but leaked outbound (`OME-501`).
TRANSPORT_ONLY_PARAMS = frozenset({"resume", "rid"})


def strip_transport_params(
    params: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Drop the spec §11.6.3 transport-only params from an outbound param list."""
    return [(key, value) for key, value in params if key not in TRANSPORT_ONLY_PARAMS]


def _wire_escape(text: str) -> str:
    """Percent-encode only the characters that would corrupt the wire format."""
    return _WIRE_UNSAFE.sub(lambda m: f"%{ord(m.group()):02X}", text)


def encode_subrequest(
    path: str, context: str, intent: str | None, params: Sequence[tuple[str, str]] = ()
) -> str:
    """Build the ``/path?[params&]q=(context)!intent`` relative sub-request URL.

    ``intent`` of ``None`` omits the ``!`` tail (a context-only sub-request);
    ``context`` may be empty (``()``), the reducer/processor fan-out shape.
    ``params`` are protocol parameters emitted before ``q=`` — ``q`` is ALWAYS
    the last parameter (spec §8 query-string production).

    The context, intent, and param values are wire-escaped (:func:`_wire_escape`)
    so arbitrary text — a multiline reducer input, an ``&``, a stray ``(`` —
    round-trips through the URL instead of crashing the fetch or desyncing the
    paren scan.
    """
    query = f"({_wire_escape(context)})"
    if intent is not None:
        query += f"!{_wire_escape(intent)}"
    # A valueless flag is emitted BARE (`?broadcast&…`), never as `key=`:
    # `param-value = 1*( … )` admits no empty value, so `broadcast=` is a shape
    # the decoder now rejects. Encoder and decoder agree on the flag form
    # (`OME-507`).
    prefix = "".join(
        f"{key}&" if not value else f"{key}={_wire_escape(value)}&" for key, value in params
    )
    return f"{path}?{prefix}q={query}"


def decode_subrequest(query: str) -> tuple[str, str]:
    """Decode a ``(context)!intent`` ``?q=`` payload into ``(context, intent)``.

    Inverse of :func:`encode_subrequest`: the structural ``(context)`` and the
    first ``!`` delimiter are located on the still-escaped text (content parens
    and quotes are ``%28``/``%29``/``%27`` and cannot interfere), then each part
    is unescaped.

    A payload without a leading ``(`` is treated as a bare intent (empty
    context); a payload with no ``!`` tail yields an empty intent. A payload
    whose structural parens do not balance falls back to the whole (unescaped)
    payload as context.
    """
    text = query.strip()
    if not text.startswith("("):
        return "", unquote(text)
    context = balanced_body(text, 1)
    if context is None:
        return unquote(text), ""
    rest = text[len(context) + 2 :]
    intent = rest[1:] if rest.startswith("!") else ""
    return unquote(context), unquote(intent)


def decode_subrequest_http(query: str) -> tuple[str, str]:
    """Decode a ``?q=`` payload arriving over HTTP — either wire convention.

    url4's own :func:`encode_subrequest` keeps STRUCTURAL characters raw and
    escapes only content; standard HTTP clients (httpx, a browser) encode
    everything. Spec §3.4: a node MUST accept both. A leading ``%28`` can only
    be an encoded structural ``(`` — the discriminator. For the fully-encoded
    form, one full decode restores the author's text, and structure is scanned
    on the decoded form WITHOUT re-unquoting the parts.
    """
    if not _fully_encoded(query):
        return decode_subrequest(query)
    return _split_decoded(unquote_plus(query))


def decode_expression_http(query: str) -> str:
    """A ``?q=`` payload (either convention) as full expression text.

    The eval-surface counterpart of :func:`decode_subrequest_http`: the whole
    expression — a ``(context)!intent`` group (with any trailing ``;`` chain),
    a ``/path(…)!intent`` call, a ``url4://…`` remote, an iteration — as one
    string, ready for the expression parser.
    """
    if _fully_encoded(query):
        return unquote_plus(query)
    return _decode_raw_expression(query.strip())


def _decode_raw_expression(text: str) -> str:
    """Decode a raw-convention eval payload without assuming the envelope shape.

    The §7.4 locate-structure-then-unquote-parts pipeline applies ONLY to the
    exact ``(context)[!intent]`` envelope. Every other grammar-legal shape — a
    ``/path(…)`` call head, a ``url4://`` remote, a paren-collection whose
    ``*(body)`` tail follows the closing paren — is a full expression: one
    whole-text ``unquote``, and the parser judges the decoded result. The old
    envelope-only reassembly silently truncated those shapes (`OME-530`).
    """
    if text.startswith("("):
        context = balanced_body(text, 1)
        if context is not None:
            rest = text[len(context) + 2 :]
            if not rest:
                return f"({unquote(context)})"
            if rest.startswith("!"):
                return f"({unquote(context)})!{unquote(rest[1:])}"
    return unquote(text)


def _fully_encoded(query: str) -> bool:
    # WHY: url4's raw convention wire-escapes every CONTENT paren (see
    # _WIRE_UNSAFE), so a raw "(" in a payload is always STRUCTURAL — and every
    # raw-convention envelope/expression carries at least one. A standard
    # client (curl --data-urlencode, URLSearchParams, httpx) percent-encodes
    # "(" unconditionally. A paren-free, percent-bearing payload can therefore
    # only be fully-encoded. The previous "%28"-head sniff missed every
    # non-group head — %2F relative calls, url4%3A remotes — sending them
    # through the raw decoder mangled (`OME-530`). A payload with neither raw
    # parens nor escapes is inert: both conventions decode it identically.
    if "(" in query:
        return False
    return "%" in query


def _split_decoded(text: str) -> tuple[str, str]:
    if not text.startswith("("):
        return "", text
    context = balanced_body(text, 1)
    if context is None:
        return text, ""
    rest = text[len(context) + 2 :]
    return context, rest[1:] if rest.startswith("!") else ""


def extract_expression_params(query_string: str) -> tuple[dict[str, str], str | None]:
    """Split a full query string into ``(params, raw q value)`` — spec §3.3.1.

    ``&`` separates parameters only at depth 0 outside quotes, so an ``&``
    inside a nested expression (``q=(https://a?x=1&y=2)!go``) never terminates
    the expression-bearing value.

    ``q=`` closes the query string (`OME-507`): a depth-0 parameter after it
    raises :class:`~url4.core.errors.ParseError`. A query with NO ``q=`` is not an
    error — that is a ``relative-uri`` data query, and the caller decides.

    The expression-bearing values (``q``, and ``processor`` inside the params
    dict) are returned RAW — percent-decoding them is the expression decoder's
    job (:func:`decode_subrequest`), matching the spec's processing pipeline
    (§7.4). All other param values are percent-decoded with ``unquote_plus``;
    a bare valueless segment becomes a flag param with value ``""``.
    """
    params: dict[str, str] = {}
    q: str | None = None
    for segment in split_top_level(query_string, "&"):
        if not segment:
            continue
        if q is not None:
            # INVARIANT: `query-string = *( query-param "&" ) "q=" expression-body`
            # — `q=` CLOSES the query string (`OME-507`). The grammar already
            # reads it that way: `_parse_expr_canonical` takes everything after
            # the `q=` body as the intent tail, so it rejects
            # `/p?q=(a)!'go'&tone=formal` outright. Accepting a param here
            # would let a node honour over the wire what it refuses in text.
            raise ParseError(
                f"query string {query_string!r} has a parameter after `q=` — "
                "`q=` is always the last parameter; everything after it belongs "
                "to the expression",
            )
        key, sep, value = segment.partition("=")
        if not sep:
            # A valueless flag: an accepted extension the grammar does not
            # define, so only its KEY is checked (`OME-507`, owner decision).
            validate_param(segment, None)
            params[segment] = ""
            continue
        # INVARIANT: validate the DECODED value (`OME-507`, owner decision).
        # Percent-encoding is transport beneath the grammar, so `tone=very%20
        # formal` is judged as the space-bearing value it decodes to — a node
        # refuses over HTTP exactly what it refuses in expression text.
        decoded = value if key in EXPRESSION_BEARING_KEYS else unquote_plus(value)
        if not decoded and key not in EXPRESSION_BEARING_KEYS:
            # `param-value = 1*( … )` — an empty value is not a flag (the flag
            # form has no "=" at all, handled above) and has no production.
            raise ParseError(
                f"param {key!r} has an empty value — `param-value` needs at least "
                "one character; omit the '=' for a valueless flag",
            )
        validate_param(key, decoded)
        if key == "q":
            q = value
        else:
            params[key] = decoded
    return params, q


__all__ = [
    "TRANSPORT_ONLY_PARAMS",
    "decode_expression_http",
    "decode_subrequest",
    "decode_subrequest_http",
    "encode_subrequest",
    "extract_expression_params",
    "strip_transport_params",
]

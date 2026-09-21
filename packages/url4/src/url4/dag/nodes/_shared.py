"""Shared execution helpers for the built-in node vocabulary.

Split out of the former single-module vocabulary: the pieces every node family
consumes — ``$`` substitution, the reference-edge scope frame, the group
gather/flatten machinery, fetch plumbing, and row serialization — live here
once, and the node modules import them as ``from url4.dag.nodes._shared import
...``. Nothing here knows a concrete node type; a node module may import this
one, never the reverse.

The vocabulary story — nodes holding *template* data and compiling lazily at
``resolve`` time — lives in the package docstring; this module only carries the
helpers that story stands on.

All I/O flows through ``ctx.io`` (the port); every ``$`` substitution reuses
the pure helpers in :mod:`url4.core.ensemble`. Reference-edge inputs use the
``bind:<name>`` / ``pos:<N>`` role convention — :func:`_frame` turns them into
a :class:`~url4.core.context.Context` frame chained onto ``ctx.scope``.

Node classes are ``@dataclass(eq=False)``: node identity is object identity,
which is what lets the executor memoize shared nodes (diamond dependencies) by
construction.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from url4.core.context import Context
from url4.core.ensemble import (
    substitute_env_vars,
    substitute_item,
)
from url4.core.errors import ErrorCode, ResolutionError
from url4.core.nodes import Params
from url4.core.subrequest import strip_transport_params
from url4.io.layer import FetchRequest, fetch_result

from url4.dag.node import (  # isort: skip
    ExecutionContext,
    Payload,
    SourceFailure,
)


def _as_text(value: Payload) -> str:
    if isinstance(value, SourceFailure):
        return ""
    return value if isinstance(value, str) else "\n".join(value)


def _frame(inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Context:
    """Turn ``bind:``/``pos:`` reference-edge inputs into a scope frame.

    A :class:`SourceFailure` dependency contributes no binding — the failed
    optional source's ``$name`` stays unbound and substitutes verbatim.
    """
    bindings: dict[str, str] = {}
    for role, value in inputs.items():
        if isinstance(value, SourceFailure):
            continue
        if role.startswith("bind:"):
            bindings[role[5:]] = _as_text(value)
        elif role.startswith("pos:"):
            bindings[role[4:]] = _as_text(value)
    return Context(bindings=bindings, parent=ctx.scope) if bindings else ctx.scope


# WHY: the current collection row is bound into the spawned scope under this
# reserved key rather than substituted into the expression text — a row value carrying a
# stray "(" or "!" would otherwise desync the paren/intent scanners when the row
# expression is re-compiled. The NUL prefix keeps it out of the $name namespace.
_ITEM_KEY = "\x00item"

# WHY: the default per-MapNode fan-out cap when ``;iteration.concurrency`` is not
# given. Without a default bound, a collection with no directive spawns one
# concurrent sub-executor PER ROW (thousands, for a large collection) before any
# backpressure exists — an accidental-explosion hazard against whatever backend
# the rows' fetches hit. ``;iteration.concurrency=N`` overrides this; there is
# currently no "explicitly unbounded" escape hatch — name one if a real use case
# needs it.
DEFAULT_MAP_CONCURRENCY = 8


def _current_item(scope: Context) -> str | None:
    """The row bound by an enclosing :class:`MapNode`, or None outside a map."""
    return scope.get(_ITEM_KEY)


def _substitute(text: str, scope: Context, ctx: ExecutionContext) -> str:
    """Resolve a leaf's ``$item`` (row) then ``$name``/``$N`` (scope) references.

    ``$item`` is applied first so its ``$$item`` escape still sees the raw
    template and so a row value is treated as opaque data, not re-scanned for
    ``$name``. Outside a map (no bound row) this is just
    :func:`substitute_env_vars`. ``ctx.strict_fields`` selects the spec
    §5.3.4.1 field-path error mode.
    """
    item = _current_item(scope)
    if item is not None:
        text = substitute_item(text, item, strict=ctx.strict_fields)
    return substitute_env_vars(text, scope, strict=ctx.strict_fields)


def _maybe_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def _rows_to_json(rows: list[str]) -> str:
    """Serialize iteration rows as the protocol-default JSON array (spec §5.3.8).

    A visibly structured row (a JSON object or array — error objects, structured
    results) is embedded structurally; every other row, including scalar-looking
    text (``"1"``, ``"true"``), stays a JSON string — a row is prose unless it is
    visibly structured. Shared by :class:`CollectNode` and :class:`ReduceNode`
    so both consumers of a :class:`MapNode`'s rows type them identically.
    """
    return json.dumps([_maybe_json(r) if r[:1] in "[{" else r for r in rows])


class FetchedText(str):
    """A fetched body that also carries the adapter-reported media type.

    It *is* the body string — every ``str`` operation and ``isinstance(x, str)``
    check treats it as plain text — but a downstream :class:`MapNode` /
    :class:`ExpandNode` reads :attr:`media_type` to parse the collection by its
    declared Content-Type (spec §5.3.7) instead of sniffing. The media type is
    consulted only at the fetch→collection boundary, where the payload passes
    from the producer node to the consumer unchanged; any string transformation
    (``join``, slicing) yields a plain ``str`` that correctly falls back to
    sniffing, since it is no longer the adapter's own body.
    """

    media_type: str | None

    def __new__(cls, body: str, media_type: str | None) -> FetchedText:
        text = super().__new__(cls, body)
        text.media_type = media_type
        return text


async def _fetch(ctx: ExecutionContext, request: FetchRequest) -> FetchedText:
    """Resolve ``request`` through the port, preserving the media type (§5.3.7)."""
    result = await fetch_result(ctx.io, request)
    return FetchedText(result.body, result.media_type)


def _media_type_of(payload: Payload) -> str | None:
    """The Content-Type a fetch attached to ``payload``, or None when unknown."""
    return getattr(payload, "media_type", None)


def _error_payload(exc: BaseException) -> dict:
    """One collected row's wire error object (spec §5.3.6 ``collect``).

    Preserves the exception's URL4 diagnostics — ``code`` and ``permanent`` — beside the
    kind/message pair, so a ``collect``-boundary consumer (a benchmark's outcome envelope,
    the SDK report) can render the ORIGINAL upstream failure instead of falling back to a
    default code. ``permanent`` travels as ``retryable`` (its inverse): permanent errors
    must not be retried, and every reader of this payload already keys on retryability
    (``screamingface_engine.benchmarks.aggregation.public_error``).
    """
    payload: dict[str, object] = {
        "kind": type(exc).__name__,
        "message": str(exc) or repr(exc),
    }
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        payload["code"] = code
    permanent = getattr(exc, "permanent", None)
    if isinstance(permanent, bool):
        payload["retryable"] = not permanent
    return {"error": payload}


def _wire_params(params: Params) -> list[tuple[str, str]]:
    """Protocol params for the sub-request codec; a valueless flag emits ``k=``.

    # INVARIANT: transport-only params (spec §11.6.3) are stripped here, using
    # the codec's single definition — an expression authored with ``resume=``/
    # ``rid=`` must not smuggle them onto the next hop (`OME-501`).
    """
    pairs = [(key, value if value is not None else "") for key, value in params]
    return strip_transport_params(pairs)


SlotSpec = tuple[str | None, bool]
"""One group slot: ``(name, instrumental)``. ABNF conformance (`OME-534`):
EVERY listed source contributes to the packed context — name-only descriptors
(``a: v`` / ``a=v``) included. The bool marks a scalar-``weight 0.0``
INSTRUMENTAL source: resolved and ``$name``-referenceable, excluded from the
packed sources (the replacement for the old reference-only-Binding concept)."""


@dataclass
class _Gathered:
    """The flattened view of a group's slots after failures and expansion."""

    positional: list[str]  # $N values, renumbered post-expansion
    named: dict[str, str]  # $name values (RAW — scope substitution needs them unlabeled)
    sources: list[str]  # the packed source values, in order (named → "name: value")


def _gather(
    inputs: Mapping[str, Payload], slots: tuple[SlotSpec, ...], prefix: str = "src"
) -> _Gathered:
    """Flatten group slots: skip failures, splice expansions, renumber positions.

    WHY the ``name:`` label rides only ``sources``: the packed context a
    processor sees keeps the author's key labels (`OME-534` owner decision),
    while ``named`` feeds ``$name`` substitution and must stay the raw value.
    ``prefix`` selects the dep-key family — ``src:i`` for group slots,
    ``ctx:i`` for a call's context source-list (`OME-535`).
    """
    g = _Gathered([], {}, [])
    for i, (name, instrumental) in enumerate(slots):
        value = inputs[f"{prefix}:{i}"]
        if isinstance(value, SourceFailure):
            continue
        if isinstance(value, list):
            _gather_expanded(g, value, name, instrumental)
            continue
        g.positional.append(value)
        if name is not None:
            g.named[name] = value
        if not instrumental:
            g.sources.append(f"{name}: {value}" if name is not None else value)
    return g


def _gather_expanded(
    g: _Gathered, elements: list[str], name: str | None, instrumental: bool
) -> None:
    """Expanded elements each take a position; the name binds the JSON array,
    so a ``$name[i]`` field path selects one element (spec §5.3.12.5). The
    elements pack BARE — the name labels the array binding, not each element."""
    g.positional.extend(elements)
    if name is not None:
        g.named[name] = json.dumps([_maybe_json(e) for e in elements])
    if not instrumental:
        g.sources.extend(elements)


def _check_quorum(g: _Gathered, quorum: int | None) -> None:
    # The contributing count IS len(sources) — every append above is a contribution.
    resolved = len(g.sources)
    if quorum is not None and resolved < quorum:
        raise ResolutionError(
            f"quorum not met: {resolved} of {quorum} required sources resolved",
            code=ErrorCode.QUORUM_NOT_MET,
        )

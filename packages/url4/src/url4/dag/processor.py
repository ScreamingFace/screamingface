"""Processor selection (§27.3) — one owner for the three ``processor=`` forms.

``processor-value`` has three shapes, disambiguated by content rather than by a
declared type:

===============  ===========================================  ====================
Shape            Form                                         Dispatch
===============  ===========================================  ====================
starts ``(``     3 — an expression that COMPUTES a processor  evaluate, then reclassify
has ``://``      2 — a direct URI reference                    absolute fetch
starts ``/``     (route path)                                  relative fetch
otherwise        1 — an id naming a declared processor         look up, relative fetch
===============  ===========================================  ====================

The ``/`` branch is a fourth case the three-way rule does not name: a
``processor-id`` cannot contain ``/``, and :meth:`~url4.io.layer.SupportsDefaultRoute.default_route`
has always returned a path. Keeping it means every existing ``processor="/claude"``
caller — and every adapter with no route registry — keeps working unchanged.

Id resolution lives HERE rather than in each adapter: an adapter only declares
which routes it has (:class:`~url4.io.layer.SupportsProcessorRoutes`), and the
matching rule stays in one place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from url4.core.errors import ErrorCode, ResolutionError
from url4.core.parser import build
from url4.io.layer import IOLayer, SupportsProcessorRoutes

ProcessorForm = Literal["expression", "uri", "route", "id"]

# The resolved dispatch target: the base to build the sub-request on, and
# whether it resolves against the current node.
ProcessorTarget = tuple[str, bool]


def classify_processor(value: str) -> ProcessorForm:
    """Classify a ``processor=`` value by the §27.3 disambiguation rule."""
    text = value.strip()
    if text.startswith("("):
        form: ProcessorForm = "expression"
    elif "://" in text:
        form = "uri"
    elif text.startswith("/"):
        form = "route"
    else:
        form = "id"
    return form


async def resolve_processor_target(
    value: str,
    *,
    io: IOLayer,
    spawn: Callable[[str], Awaitable[str]] | None = None,
) -> ProcessorTarget:
    """Resolve a ``processor=`` value to ``(base, relative)`` for the sub-request.

    ``spawn`` evaluates a Form-3 expression; without it, an expression-valued
    processor cannot be resolved.
    """
    form = classify_processor(value)
    if form == "expression":
        value = await _evaluate(value, spawn)
        form = classify_processor(value)
    if form == "uri":
        return value, False
    if form == "route":
        return value, True
    return _route_for_id(value, io), True


async def _evaluate(value: str, spawn: Callable[[str], Awaitable[str]] | None) -> str:
    if spawn is None:
        raise ResolutionError(
            f"processor {value!r} is an expression, but this run cannot evaluate one "
            "(no spawn hook) — pass a processor id, route, or URI instead",
            code=ErrorCode.UNKNOWN_PROCESSOR,
            permanent=True,
        )
    # INVARIANT: a Form-3 processor value is USER surface (§27.3's
    # expression-body), so it must satisfy the grammar — including the
    # mandatory intent (`OME-508`) — even though the spawn boundary itself
    # compiles permissively for the engine's own wrappers.
    build(value)
    resolved = (await spawn(value)).strip()
    # INVARIANT: reclassification is SINGLE-PASS. An expression resolving to
    # another expression is an error, not a further round — re-entering here
    # would be unbounded.
    if classify_processor(resolved) == "expression":
        raise ResolutionError(
            f"processor expression resolved to another expression ({resolved!r}); "
            "resolution is single-pass",
            code=ErrorCode.UNKNOWN_PROCESSOR,
            permanent=True,
        )
    return resolved


def _route_for_id(processor_id: str, io: IOLayer) -> str:
    """Match a bare id against the adapter's declared routes.

    Exact path first, then the ``/``-prefixed form, so both ``claude`` and
    ``/claude`` name the endpoint registered at ``/claude``.
    """
    routes = list(io.processor_routes()) if isinstance(io, SupportsProcessorRoutes) else []
    for candidate in (processor_id, f"/{processor_id}"):
        if candidate in routes:
            return candidate
    raise ResolutionError(
        f"unknown processor {processor_id!r} — this node declares "
        f"{sorted(routes) if routes else 'no routes'}",
        code=ErrorCode.UNKNOWN_PROCESSOR,
        permanent=True,
    )


__all__ = ["ProcessorForm", "ProcessorTarget", "classify_processor", "resolve_processor_target"]

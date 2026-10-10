"""The broadcast route (Spec B §6.1): one intent application per resolved source.

:class:`MergeNode` runs the intent once for one source. Split out of
:mod:`.group`, and the §6.1.4 envelope out of here (:mod:`.broadcast_result`),
to keep each module under its size cap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from url4.core.context import Context

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
    gather_or_cancel,
)

from url4.dag.nodes._shared import (  # isort: skip
    DEFAULT_MAP_CONCURRENCY,
    _as_text,
    _substitute,
)


@dataclass(eq=False)
class MergeNode:
    """One broadcast application (spec §6.1.2): merge a single source with the intent.

    ``$current`` is bound to this source's resolved data in the scope handed to
    ``process``. A *text* intent arrives as ``intent_template`` and is
    substituted here — once per source, with ``current`` in scope — rather than
    as a shared pre-substituted node; a *fetch* intent stays a shared ``intent``
    dependency (resolved exactly once) and carries no ``$current``.

    ``expanded`` (set by the compiler for an ``;expand`` source): each element is a
    source (§5.3.12.4), applied under the map concurrency bound, fail-fast. Any other
    list is one source: an iteration resolves to a single value (§5.3.8).
    """

    rds_scope: ClassVar[bool] = False  # a prompt group: lenient (C6)

    intent_template: str | None = None
    expanded: bool = False
    # {"source": …, ["intent": …], ["quorum": gate]} — the gate's value is unused;
    # depending on it orders the intent after quorum (§6.1.2).
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        source, fetched = inputs["source"], inputs.get("intent")
        if isinstance(source, SourceFailure):
            return source  # A3: a failed source runs no intent (§6.1.3)
        if self.expanded and isinstance(source, list):
            return await self._apply_each(source, fetched, ctx)
        return await self._apply(_as_text(source), fetched, ctx)

    async def _apply_each(
        self, elements: list[str], fetched: Payload | None, ctx: ExecutionContext
    ) -> list[str]:
        sem = asyncio.Semaphore(DEFAULT_MAP_CONCURRENCY)

        async def one(element: str) -> str:
            async with sem:
                return await self._apply(element, fetched, ctx)

        return await gather_or_cancel(one(element) for element in elements)

    async def _apply(self, source: str, fetched: Payload | None, ctx: ExecutionContext) -> str:
        scope = Context(bindings={"current": source}, parent=ctx.scope)
        if self.intent_template is not None:
            # WHY: _substitute so a broadcast intent nested inside an iteration
            # resolves $item too, exactly as the non-broadcast ProcessNode path
            # does; $current resolves from `scope` in the same scan.
            intent = _substitute(self.intent_template, scope, ctx)
        else:
            intent = _as_text(fetched) if fetched is not None else ""
        return await ctx.process(source, intent, scope)

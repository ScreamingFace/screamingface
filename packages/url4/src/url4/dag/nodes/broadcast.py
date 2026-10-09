"""The broadcast route (Spec B §6.1): one intent application per resolved source.

:class:`MergeNode` runs the intent once for one source; :class:`BroadcastCollectNode`
assembles the surviving parts into the §6.1.4 collection. Split out of
:mod:`.group` (its size cap) because broadcast is its own route.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.context import Context

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
)


from url4.dag.nodes._shared import (  # isort: skip
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
    """

    intent_template: str | None = None
    # {"source": …, ["intent": …], ["quorum": gate]} — the gate's value is unused;
    # depending on it orders the intent after quorum (§6.1.2).
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        if isinstance(inputs["source"], SourceFailure):
            return inputs["source"]  # A3: a failed source runs no intent (§6.1.3)
        source = _as_text(inputs["source"])
        scope = Context(bindings={"current": source}, parent=ctx.scope)
        if self.intent_template is not None:
            # WHY: _substitute so a broadcast intent nested inside an iteration
            # resolves $item too, exactly as the non-broadcast ProcessNode path
            # does; $current resolves from `scope` in the same scan.
            intent = _substitute(self.intent_template, scope, ctx)
        else:
            intent = _as_text(inputs["intent"]) if "intent" in inputs else ""
        return await ctx.process(source, intent, scope)


@dataclass(eq=False)
class BroadcastCollectNode:
    """Assemble per-source broadcast results into the §6.1.4 collection shape.

    A JSON array of ``{"source_position", "source_name", "result"}`` objects,
    ordered by source position (1-based). A failed optional source's part is
    omitted — broadcast applies across *resolved* sources (§6.1.3) — while the
    surviving parts keep their original positions. Quorum (§12.2) is not checked
    here: a gate before every :class:`MergeNode` holds the intents until it is met.
    """

    names: tuple[str | None, ...] = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"part:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        rows = [
            {
                "source_position": i + 1,
                "source_name": self.names[i] if i < len(self.names) else None,
                "result": _as_text(inputs[role]),
            }
            for i, role in enumerate(self.deps)
            if not isinstance(inputs[role], SourceFailure)
        ]
        return json.dumps(rows)

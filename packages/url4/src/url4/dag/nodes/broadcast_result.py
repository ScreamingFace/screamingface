"""The broadcast result envelope (Spec B §6.1.4): the parts as one JSON collection.

Split from :mod:`.broadcast`: the envelope changes with the result format, while
:class:`~.broadcast.MergeNode` changes with how one intent is applied.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.dag.node import DagNode, ExecutionContext, Payload, SourceFailure  # isort: skip
from url4.dag.nodes._shared import _as_text  # isort: skip


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

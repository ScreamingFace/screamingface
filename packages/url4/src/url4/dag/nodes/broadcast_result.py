"""The broadcast result envelope (Spec B §6.1.4): the parts as one JSON collection.

Split from :mod:`.broadcast` to keep that module under its size cap; the result
envelope is this module's whole content.
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
    ordered by source position (1-based). An expanded source's elements take
    consecutive positions and the names ``name[i]`` / ``src[i]`` (§5.3.12.4-5).
    A failed optional source's part is omitted — broadcast applies across
    *resolved* sources (§6.1.3) — while the surviving parts keep their original
    positions. Quorum (§12.2) is not checked here: a gate before every
    :class:`MergeNode` holds the intents until it is met.
    """

    names: tuple[str | None, ...] = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"part:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        rows: list[dict[str, object]] = []
        position = 0
        for i, role in enumerate(self.deps):
            part, name = inputs[role], self.names[i] if i < len(self.names) else None
            # Only an expanded MergeNode returns a list (one result per element);
            # its elements are the sources `name[j]` / `src[j]` (§5.3.12.5).
            parts = enumerate(part) if isinstance(part, list) else [(None, part)]
            for j, result in parts:
                position += 1
                if isinstance(result, SourceFailure):
                    continue
                rows.append(
                    {
                        "source_position": position,
                        "source_name": name if j is None else f"{name or 'src'}[{j}]",
                        "result": _as_text(result),
                    }
                )
        return json.dumps(rows)

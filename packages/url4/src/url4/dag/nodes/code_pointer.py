"""The code-pointer node: a group's URI intent, called once with its sources as JSON.

# FEATURE: RDS code pointer (url4 2.0)
#
# STORY: as a url4 author, `(sources)!/code` runs the code at `/code` once, with every
# named source as a structured input, so a deterministic combine or checker gets its
# inputs exactly as they resolved and no model sees them.
#
# INVARIANT: a code-pointer node never reads the processor route and never runs the
# eval path. Its one I/O is a fetch through ``ctx.io``, and the receiving node maps
# every error (PRD §2.4, contracts C2 and C7).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import _DATA_PATH_RE
from url4.core.intent import CodePointer
from url4.io.layer import FetchRequest
from url4.wire.rds import RdsValue, encode_rds_document, encode_rds_target

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
)


from url4.dag.nodes._shared import (  # isort: skip
    JsonText,
    SlotSpec,
    _fetch,
    _raise_if_quorum_not_met,
    _row_value,
    _substitute,
)


def code_pointer_target(pointer: CodePointer, path: str, inputs: Mapping[str, RdsValue]) -> str:
    """The C2 target of one call: the resolved path, the query-tail, and the document."""
    return encode_rds_target(path, pointer.query, encode_rds_document(inputs))


def unsupported_intent_error(value: str) -> ParseError:
    """The refusal of a URI intent that is not a url4 code pointer (PRD P2).

    WHY: the compile path (`_lowering`) and the iteration reducer (`ReduceNode`) refuse the
    same text, so the message has one owner.
    """
    return ParseError(
        f"intent {value!r} is not a url4 code pointer — a URI intent must be a "
        "/path or a url4:// reference (unsupported_mode)",
        code=ErrorCode.UNSUPPORTED_MODE,
        permanent=True,
    )


async def call_code_pointer(
    ctx: ExecutionContext, pointer: CodePointer, inputs: Mapping[str, RdsValue]
) -> str:
    """One call of a code pointer with its RDS ``inputs`` (contracts C2 and C4).

    WHY: the group node and the iteration reducer both make this call, so the target and the
    remote form are written once. A code-pointer miss is answered by the receiving node
    (``intent_error``, E1), so the reply is passed through unchanged.
    """
    # WHY: the path resolves against the outer scope, as today's intent fetch does
    # (PRD §2.5), so a `$name` in the path is never a source.
    path = _substitute(pointer.path, ctx.scope, ctx)
    # WHY: a substituted value is data, so the resolved path must still be a bare data path; a
    # value that carries a query would otherwise make a second query-tail (contracts C2).
    if "?" in path or _DATA_PATH_RE.fullmatch(path) is None:
        raise ParseError(
            f"code pointer path {path!r} is not a bare data path after substitution",
            code=ErrorCode.MALFORMED_SOURCE,
        )
    target = code_pointer_target(pointer, path, inputs)
    if pointer.authority is not None:
        return await _fetch(
            ctx,
            FetchRequest(f"url4://{pointer.authority}{target}", relative=False, kind="url4"),
        )
    return await ctx.io.fetch(target, relative=True)


async def call_reducer_code_pointer(
    ctx: ExecutionContext, pointer: CodePointer, rows: list[str]
) -> str:
    """One reducer call through a code pointer: the rows, as ``$1`` (PRD D8)."""
    return await call_code_pointer(ctx, pointer, {"$1": [_row_value(r) for r in rows]})


def _gather_rds(
    inputs: Mapping[str, Payload], slots: tuple[SlotSpec, ...]
) -> tuple[dict[str, RdsValue], int]:
    """The RDS input document's ``inputs`` for a group, and how many values resolved.

    The walk matches :func:`_gather`: a failed source is skipped, and a list (a
    ``;expand`` source) splices its elements. ``k`` is the 1-based position after
    expansion, and it names an unnamed value ``$k`` (PRD D3, D6). A named list is one
    array under its name.
    """
    values: dict[str, RdsValue] = {}
    k = 0
    for i, (name, _instrumental) in enumerate(slots):
        # INVARIANT: weight 0.0 (instrumental) is attribution metadata, not delivery
        # (ans:Q2), so an instrumental slot is an input like any other.
        value = inputs[f"src:{i}"]
        if isinstance(value, SourceFailure):
            continue
        if isinstance(value, list):
            if name is not None:
                values[name] = [_row_value(element) for element in value]
                k += len(value)
                continue
            for element in value:
                k += 1
                values[f"${k}"] = element
            continue
        k += 1
        values[name if name is not None else f"${k}"] = _rds_value(value)
    return values, k


def _rds_value(value: str) -> RdsValue:
    """A payload's typed RDS value: a JsonText is parsed, any other text stays a string."""
    if isinstance(value, JsonText):
        return json.loads(value)
    return str(value)


@dataclass(eq=False)
class CodePointerNode:
    """``(sources)!/code`` — one call to the code pointer with the group's inputs.

    ``slots`` and ``deps`` follow :class:`~url4.dag.nodes.GatherNode`: ``deps`` holds
    ``{"src:i": node}`` in slot order. ``quorum`` gates on the resolved count, and an
    instrumental source counts (it is delivered).

    ``broadcast_part`` marks one part of a broadcast, ``(a, b)!*/code`` (PRD D7). Its only
    dep is ``src:0``, and the call's single input is ``current``. A failed optional source
    returns its :class:`SourceFailure` unchanged, so :class:`BroadcastCollectNode` omits the
    row and the code pointer is not called.
    """

    pointer: CodePointer
    slots: tuple[SlotSpec, ...] = ()
    quorum: int | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)
    broadcast_part: bool = False

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        if self.broadcast_part and isinstance(inputs["src:0"], SourceFailure):
            return inputs["src:0"]
        values, resolved = _gather_rds(inputs, self.slots)
        # WHY: C7 — a code pointer's quorum miss is permanent: the same inputs fail the same way.
        _raise_if_quorum_not_met(resolved, self.quorum, permanent=True)
        return await call_code_pointer(ctx, self.pointer, values)

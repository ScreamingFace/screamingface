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

from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.errors import ErrorCode, ParseError, ResolutionError, Url4Error
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
    SlotSpec,
    _fetch,
    _gather_rds,
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

    WHY: the group node and the iteration reducer both make this call, so the target, the
    remote form and the endpoint-miss mapping are written once.
    """
    # WHY: the path resolves against the outer scope, as today's intent fetch does
    # (PRD §2.5), so a `$name` in the path is never a source.
    path = _substitute(pointer.path, ctx.scope, ctx)
    target = code_pointer_target(pointer, path, inputs)
    if pointer.authority is not None:
        return await _fetch(
            ctx,
            FetchRequest(f"url4://{pointer.authority}{target}", relative=False, kind="url4"),
        )
    try:
        return await ctx.io.fetch(target, relative=True)
    except Url4Error as exc:
        if exc.code != ErrorCode.ENDPOINT_NOT_FOUND:
            raise
        # WHY: an IO layer that is not a Url4Node reports the miss as endpoint_not_found;
        # a code pointer that is missing is an intent failure (E1), so map it here.
        raise ResolutionError(
            f"no code pointer at {path!r}", code=ErrorCode.INTENT_ERROR, permanent=True
        ) from exc


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
        if self.quorum is not None and resolved < self.quorum:
            raise ResolutionError(
                f"quorum not met: {resolved} of {self.quorum} required sources resolved",
                code=ErrorCode.QUORUM_NOT_MET,
            )
        return await call_code_pointer(ctx, self.pointer, values)

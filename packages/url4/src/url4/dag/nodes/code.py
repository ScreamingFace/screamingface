"""The RDS group: run a relative code-pointer intent once, after the gate (url4 2.0).

FEATURE: code-pointer intents run as RDS calls (``docs/spec/2026-10-10-url4-rds-code-pointer``,
rules R2–R4, contracts C4, C5, C6, C8).
STORY: as an expression author, ``(m1:…, m2:…)!/ensemble/combine/v1?reducer=vote`` runs the
node's ``@node.code`` handler once, with my sources by position and name, and no model.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from url4.core.code import CodeCall, CodeInput, SupportsCode
from url4.core.context import Context
from url4.core.errors import ErrorCode, ResolutionError, Url4Error
from url4.core.intent import CodePointer
from url4.dag.semantics.code_binding import (
    CodeSlot,
    Quorum,
    Settled,
    SlotResult,
    bind,
    broadcast_calls,
    expand,
    gate_open,
    needed,
    pointer_bindings,
)
from url4.dag.semantics.ensemble import find_references, interpolate

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
    gather_or_cancel,
)

from url4.dag.nodes._shared import _INDEX_KEY, _current_item  # isort: skip


@dataclass(eq=False)
class CodeSourcesNode:
    """Gather a code group's settled sources into one record, slot by slot.

    WHY a record: the :class:`CodeCallNode` runs this node on an isolated sub-executor
    (its preflight must run BEFORE any source starts, R4), and a sub-execution returns
    one payload. The record keeps each slot apart — text, elements, or the failure —
    where a joined string would lose the boundaries. JSON round-trips every ``str``
    exactly, so values stay byte-exact (H2).
    """

    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        record: list[dict[str, object]] = []
        for role in self.deps:
            value = inputs[role]
            if isinstance(value, SourceFailure):
                record.append({"failed": value.code})
            elif isinstance(value, list):
                record.append({"items": list(value)})
            else:
                record.append({"value": str(value)})
        return json.dumps(record)


def _decode(raw: Payload) -> list[SlotResult]:
    entries = json.loads(raw if isinstance(raw, str) else "[]")
    return [entry.get("value", entry.get("items")) for entry in entries]


@dataclass(eq=False)
class CodeCallNode:
    """A relative code-pointer group: preflight, sources, gate, bind, one call (C5).

    ``sources`` is an attribute, not an edge: the preflight (is there a code port, is the
    static pointer mounted?) must fail the group before its sources start (Lean
    ``evalGroup_unsupported``, ``evalGroup_unmounted``), so the subtree runs on its own
    sub-executor once the preflight passed — the GuardNode isolation pattern. Inside it
    every ``$``-reference substitutes strictly (B §5.3.4.1, C6), up to the next group.
    """

    rds_scope: ClassVar[bool] = True  # a code group: strict (C6)

    pointer: CodePointer
    slots: tuple[CodeSlot, ...]
    quorum: Quorum
    sources: DagNode
    broadcast: bool = False
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    @property
    def path(self) -> str:
        """The pointer path — the ``NodeStarted`` detail."""
        return self.pointer.path

    def children(self) -> list[DagNode]:
        return [*self.deps.values(), self.sources]

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        port = _code_port(ctx.io, self.pointer)
        # INVARIANT: the executor set RDS_STRICT (rds_scope) before this resolve, so the
        # sub-executor of the source subtree inherits a strict scope.
        results = _decode(await ctx.execute_node(self.sources, ctx.scope))
        settled = expand(self.slots, results)
        if not gate_open(settled, self.quorum):
            raise _gate_closed(settled, self.quorum)
        bindings = pointer_bindings(self.slots, results)
        if not self.broadcast:
            path = self._pointer_path(bindings, None, ctx)
            return await self._invoke(port, path, bind(settled))
        refs = find_references(self.pointer.path)
        rows = await gather_or_cancel(
            self._broadcast_row(port, bindings, current, call_inputs, ctx)
            for current, call_inputs in broadcast_calls(settled, refs)
        )
        return json.dumps(rows)

    async def _broadcast_row(
        self,
        port: SupportsCode,
        bindings: dict[str, str],
        current: Settled,
        inputs: tuple[CodeInput, ...],
        ctx: ExecutionContext,
    ) -> dict[str, object]:
        path = self._pointer_path(bindings, current, ctx)
        result = await self._invoke(port, path, inputs)
        # WHY this shape: B §6.1.4, the one BroadcastCollectNode gives an LLM group.
        return {"source_position": current.position, "source_name": current.name, "result": result}

    def _pointer_path(
        self, bindings: dict[str, str], current: Settled | None, ctx: ExecutionContext
    ) -> str:
        """Interpolate the pointer against the GROUP's own sources (B §6.2), strictly (C6)."""
        if self.pointer.is_static:
            return self.pointer.path
        bindings = dict(bindings)
        if current is not None:
            bindings["current"] = current.text or ""
        index = ctx.scope.get(_INDEX_KEY)
        if index is not None:
            bindings["index"] = index
        # INVARIANT: `bound=True` — a name the group does not bind (B §6.2: not the outer
        # scope) raises unbound_reference, `$current` outside a broadcast included.
        scope = Context(bindings=bindings)
        item = _current_item(ctx.scope)
        return interpolate(self.pointer.path, scope, item=item, strict=True, bound=True)

    async def _invoke(self, port: SupportsCode, path: str, inputs: tuple[CodeInput, ...]) -> str:
        call = CodeCall(path, self.pointer.params, inputs)
        try:
            result = await port.invoke_code(call)
        except Url4Error as exc:
            # WHY no pass-through, even for intent_error: C §13.6 makes it PERMANENT, and a
            # handler's own error may say otherwise. Its code stays in the message.
            raise _intent_error(path, f"{exc.code}: {exc}") from exc
        except Exception as exc:
            # WHY every exception: Spec C §13.6 — "when intent execution fails, the error
            # code is intent_error (permanent)". A handler bug is an execution failure,
            # and a caller must never retry it. Cancellation (BaseException) propagates.
            raise _intent_error(path, f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(result, str):
            raise _intent_error(path, f"returned {type(result).__name__}, not str")
        return result


def _code_port(io: object, pointer: CodePointer) -> SupportsCode:
    """The preflight (R4): a code port, and — for a static pointer — a mounted handler."""
    if not isinstance(io, SupportsCode):
        raise Url4Error(
            f"code pointer {pointer.path!r} needs a node with code mounts; this IO layer "
            "has none (run the expression on the node that owns the code)",
            code=ErrorCode.UNSUPPORTED_MODE,
            permanent=True,
        )
    if pointer.is_static and not io.has_code(pointer.path):
        raise Url4Error(
            f"no code mount at {pointer.path!r} (an endpoint or data route is not code)",
            code=ErrorCode.INTENT_ERROR,
            permanent=True,
        )
    return io


def _gate_closed(settled: list[Settled], quorum: Quorum) -> ResolutionError:
    """The closed gate's error (Lean ``evalGroup_ne_exec_of_gate_false``): no call runs.

    INVARIANT: a failed REQUIRED source has already raised its own error inside the
    source subtree (C4: "that source's code"), so a closed gate here is the quorum.
    """
    resolved = sum(entry.resolved for entry in settled)
    return ResolutionError(
        f"quorum not met: {resolved} of {needed(len(settled), quorum)} required sources resolved",
        code=ErrorCode.QUORUM_NOT_MET,
    )


def _intent_error(path: str, detail: str) -> Url4Error:
    return Url4Error(f"code {path!r} failed: {detail}", code=ErrorCode.INTENT_ERROR, permanent=True)


__all__ = ["CodeCallNode", "CodeSourcesNode"]

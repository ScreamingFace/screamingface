"""The group nodes: gather, process, broadcast merge, fan-out reduce, barriers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from url4.core.context import Context
from url4.core.errors import ResolutionError
from url4.dag.processor import resolve_processor_target
from url4.dag.semantics.ensemble import (
    FanoutResponse,
    build_reducer_input,
    substitute_response_vars,
)
from url4.wire.subrequest import encode_subrequest

from url4.dag.node import (  # isort: skip
    DagNode,
    ExecutionContext,
    Payload,
    SourceFailure,
)


from url4.dag.nodes._shared import (  # isort: skip
    SlotSpec,
    _as_text,
    _check_quorum,
    _frame,
    _gather,
    _rows_to_json,
    _substitute,
)


@dataclass(eq=False)
class BindingNode:
    """``name=value`` / ``name:value`` — a named passthrough other nodes edge to."""

    name: str
    kind: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"value": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return inputs["value"]


@dataclass(eq=False)
class LazyExprNode:
    """A Virtual Proxy over an unparsed url4 fragment.

    The fragment is compiled and executed only when this node resolves —
    the mechanism behind distributed / on-demand parsing. Reference-edge
    inputs become the scope frame the spawned sub-graph sees.
    """

    text: str
    deps: Mapping[str, DagNode] = field(default_factory=dict)

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return await ctx.spawn(self.text, _frame(inputs, ctx))


@dataclass(eq=False)
class BarrierNode:
    """Pass ``inner`` through after every ``wait:*`` dependency has resolved.

    Used to make a non-substituting intent (a URL fetch) structurally depend
    on all sources, preserving the reference engine's sources-then-intent
    resolution order.
    """

    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"inner": …, "wait:i": …}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        return inputs["inner"]


@dataclass(eq=False)
class GatherNode:
    """An intent-less group — join the contributing sources (`OME-534`).

    AST-only (`OME-508`): the surface grammar's expression always carries an
    intent, so this node is reached via hand-built ``Expression(intent=None)``
    trees and the engine's own internal wrappers, never from user text.
    A pure-instrumental group falls back to joining every slot value.
    ``quorum`` (spec §9.1) gates on the post-expansion resolved-source count.
    """

    slots: tuple[SlotSpec, ...] = ()
    quorum: int | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        g = _gather(inputs, self.slots)
        _check_quorum(g, self.quorum)
        return "\n".join(g.sources) or "\n".join(g.positional)


@dataclass(eq=False)
class InlineCollectionNode:
    """An inline parenthesized collection ``(e1, e2, …)`` feeding ``*`` (§5.3.11).

    Each authored element (a scalar, URI, sub-expression, or ``{}`` structured
    object) is ONE collection element. Unlike :class:`GatherNode` — which
    newline-joins a bare group into a single text blob for the §5.3.7
    content-sniffer — this preserves the elements as a real ordered ``list[str]``
    payload, which the enclosing :class:`MapNode` consumes directly *without*
    routing back through body sniffing. That distinction is what makes a
    one-element inline collection iterable at all: a lone scalar joined-to-text
    is a single line the sniffer rejects as a non-iterable scalar (§5.3.9), and a
    lone ``{}`` element is rejected as a JSON object (§5.3.7) — both are
    structurally impossible to represent as one collection element through the
    text path. Elements keep their serialized shape (a scalar stays scalar text;
    a ``{}`` element stays canonical JSON, so a per-row ``$item.field`` path
    resolves). A ``;expand`` element still splices into consecutive positions
    (§5.3.12); a failed ``;optional`` element contributes no element.
    """

    slots: tuple[SlotSpec, ...] = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        # Every comma-entry's value, in order, post-expansion and post-failure —
        # the authored element list, NOT a joined blob (contrast GatherNode).
        return _gather(inputs, self.slots).positional


@dataclass(eq=False)
class ProcessNode:
    """The ``(sources)!intent`` base case — merge via the ``ctx.process`` hook.

    The scope handed to ``process`` is populated with every slot value (by
    ``$N`` position — renumbered after expansion, §5.3.12.4 — and by name for
    bindings and named sources), mirroring the reference engine's
    fully-resolved list context.

    A *text* intent arrives as ``intent_template`` and substitutes HERE,
    against the populated post-gather scope — this is what keeps ``$N``
    references correct after expansion renumbers the positions (a
    pre-substituted intent node would only ever see pre-expansion slots). A
    *fetch* intent stays an ``intent`` dependency behind the barrier.
    """

    slots: tuple[SlotSpec, ...] = ()
    quorum: int | None = None
    intent_template: str | None = None
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"src:i": …, ["intent": …]}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        g = _gather(inputs, self.slots)
        _check_quorum(g, self.quorum)
        bindings = {str(i + 1): value for i, value in enumerate(g.positional)}
        bindings.update(g.named)
        scope = Context(bindings=bindings, parent=ctx.scope)
        if self.intent_template is not None:
            intent = _substitute(self.intent_template, scope, ctx)
        else:
            intent = _as_text(inputs["intent"])
        return await ctx.process("\n".join(g.sources), intent, scope)


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
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"source": …, ["intent": …]}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        source = _as_text(inputs["source"])
        scope = Context(bindings={"current": source}, parent=ctx.scope)
        if self.intent_template is not None:
            # WHY: _substitute (not bare substitute_env_vars) so a broadcast intent
            # nested inside an iteration resolves $item too, exactly as the
            # non-broadcast ProcessNode path does — $current still resolves via
            # the substitute_env_vars pass _substitute ends with.
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
    surviving parts keep their original positions.
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


@dataclass(eq=False)
class JoinNode:
    """Join ordered parts with a separator; flattens ``list[str]`` payloads."""

    sep: str = "\n"
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"part:i": node}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        parts: list[str] = []
        for role in self.deps:
            value = inputs[role]
            if isinstance(value, SourceFailure):
                continue
            parts.extend(value) if isinstance(value, list) else parts.append(value)
        return self.sep.join(parts)


@dataclass(eq=False)
class CollectNode:
    """Serialize iteration rows as the protocol-default JSON array (spec §5.3.8).

    A row that is itself a JSON *container* (an object or array — error
    objects, structured results) is embedded structurally; every other row is
    a JSON string. Scalar-looking text (``"1"``, ``"true"``) stays a string —
    a row is prose unless it is visibly structured. Row order is element order
    — the Map contract already preserves it.
    """

    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"rows": MapNode}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        rows = inputs["rows"]
        rows = rows if isinstance(rows, list) else [_as_text(rows)]
        return _rows_to_json(rows)


@dataclass(eq=False)
class FanoutReduceNode:
    """Fan-out + reduce: label the parallel relative-expression responses, reduce.

    The N sources (each a relative expression, ``call:i``) resolve in parallel;
    ``meta[i]`` carries the i-th one's ``(name, weight)`` label. The formatted
    reducer input (:func:`~url4.dag.semantics.ensemble.build_reducer_input`) is then fetched
    from the configured ``ctx.processor`` route as ``processor?q=()!<input>`` —
    the reduce step is itself a localhost fetch. A failed optional call is
    excluded from the reducer input (it is not a resolved response).
    """

    meta: tuple[tuple[str | None, float | None], ...] = ()
    deps: Mapping[str, DagNode] = field(default_factory=dict)  # {"intent": …, "call:i": …}

    async def resolve(self, inputs: Mapping[str, Payload], ctx: ExecutionContext) -> Payload:
        entries = [
            FanoutResponse(text=_as_text(inputs[f"call:{i}"]), name=name, weight=weight)
            for i, (name, weight) in enumerate(self.meta)
            if not isinstance(inputs[f"call:{i}"], SourceFailure)
        ]
        instruction = substitute_response_vars(_as_text(inputs.get("intent", "")), entries)
        # ABNF conformance (`OME-534`): a scalar weight 0.0 marks the call
        # INSTRUMENTAL — its response is $name-substitutable above but forms no
        # labeled section of the reducer input.
        contributing = [e for e in entries if e.weight != 0.0]
        reducer_input = build_reducer_input(contributing, instruction)
        if ctx.processor is None:
            # INVARIANT: the core hardcodes no processor route — with nothing
            # declared (SupportsDefaultRoute) and nothing passed, the reduce
            # cannot dispatch; fail with the fix in the message.
            raise ResolutionError(
                "fan-out reduce has no processor route — the io layer declares no "
                "routes and none was set; pass processor= (run/Client) or register "
                "a route/endpoint on the node"
            )
        # §27.3: the processor may be an id, a URI, a route path, or an
        # expression that computes one — url4.dag.processor owns that classification.
        scope = _frame(inputs, ctx)
        base, relative = await resolve_processor_target(
            ctx.processor, io=ctx.io, spawn=lambda text: ctx.spawn(text, scope)
        )
        target = encode_subrequest(base, "", reducer_input)
        return await ctx.io.fetch(target, relative=relative)

"""Group routing for code-pointer intents (url4 2.0, contracts C5, C9).

FEATURE: code-pointer intents run as RDS calls. A group whose intent is a RELATIVE_URI
lowers to a :class:`~url4.dag.nodes.code.CodeCallNode` at EVERY group site — base,
fan-out, broadcast, an iteration body (each row is a group) and an iteration reducer —
BEFORE the fan-out gate, the base merge and the broadcast merge, so no RDS group ever
reaches ``ctx.processor`` or the ``process`` hook (R1, R2).

The lowerers (:mod:`url4.dag._lowering`) call :func:`compile_group` instead of
:func:`url4.dag._wiring._compile_group`; this module imports the wiring, never the reverse.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from url4.core.intent import CodePointer, parse_code_pointer
from url4.core.nodes import (
    Binding,
    Expression,
    Iteration,
    Node,
    Params,
    RelUrl,
    Source,
    StructObject,
    Text,
    VarRef,
)
from url4.core.parser import IterationEnvelope, decode_envelope, intent_atom
from url4.dag._wiring import Edges, _build_slots, _compile_group, _Intent, _quorum_of, _Slot
from url4.dag.semantics.code_binding import CodeSlot, SlotKind, code_quorum

from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import ReduceNode, TextNode  # isort: skip
from url4.dag.nodes.code import CodeCallNode, CodeSourcesNode  # isort: skip


def compile_group(
    slots: list[_Slot],
    intent: _Intent | None,
    broadcast: bool,
    *,
    from_list: bool,
    params: Params = (),
) -> DagNode:
    """Route a group: a code-pointer intent → one RDS node; anything else → 1.5.1 wiring."""
    if intent is not None and intent.code is not None:
        return code_group(slots, intent.code, broadcast, params)
    return _compile_group(slots, intent, broadcast, from_list=from_list, quorum=_quorum_of(params))


def code_group(
    slots: list[_Slot], pointer: CodePointer, broadcast: bool, params: Params
) -> CodeCallNode:
    """``(S)!/code`` or ``(S)!*/code`` (C5): sources held off-edge, behind the preflight.

    Aggregate sources see earlier named siblings, as in an LLM group; broadcast sources
    resolve under the outer scope, as the 1.5.1 broadcast path does.
    """
    built = [slot.make({}) for slot in slots] if broadcast else _build_slots(slots)
    sources = CodeSourcesNode(deps={f"src:{i}": node for i, node in enumerate(built)})
    return CodeCallNode(pointer, _code_slots(slots), code_quorum(params), sources, broadcast)


def reduce_rows(reducer: str, rows: DagNode) -> DagNode:
    """An iteration's reducer: a code pointer gets the rows as ONE ``list`` input (D7).

    Any other reducer keeps the 1.5.1 :class:`~url4.dag.nodes.ReduceNode` path — the
    relative-expression reducer ``/reduce()!'agg'`` included (deviation A4).
    """
    # WHY `(` stays on the 1.5.1 path: every parenthesized reducer (`/reduce()`,
    # `/reduce(all)!'agg'`, a malformed `/reduce((bad`) is the relative-expression
    # reducer shape A4 keeps, and Graph.validate() parses it there. AIDEV-NOTE: this is
    # the one place a RELATIVE_URI (`classify_intent("/reduce()")`) does not run code.
    if "(" in reducer or not isinstance(intent_atom(reducer), RelUrl):
        return ReduceNode(reducer, deps={"rows": rows})
    pointer = parse_code_pointer(reducer)
    slot = CodeSlot(name=None, weight=None, required=True, kind="rows")
    return CodeCallNode(pointer, (slot,), None, CodeSourcesNode(deps={"src:0": rows}))


def call_intent(intent: Node, edges: Edges, lower: Callable[[Node, Edges], DagNode]) -> DagNode:
    """The intent of a FORWARDED call (``/p(ctx)!/code``, ``url4://n/v1(ctx)!/code``).

    C9 (Spec C §11.6.2 rule 3): a relative code pointer travels VERBATIM in the child's
    ``q=`` — the caller neither fetches nor interpolates it; the receiving node decides
    what ``/code`` means. ``$`` doubles to ``$$`` so the TextNode's one substitution pass
    yields the pointer text unchanged. Every other intent keeps its 1.5.1 lowering
    (deviation A5 for prompts).
    """
    if isinstance(intent, RelUrl):
        return TextNode(intent.value.replace("$", "$$"))
    return lower(intent, edges)


def _code_slots(slots: list[_Slot]) -> tuple[CodeSlot, ...]:
    """Each slot's input contract — ``;optional`` and the C3 value kind — from its FORM.

    # INVARIANT (C3): the value type comes from the source's expression, never from its
    # content, and both compilation paths read the same form (a tree, or a deferred
    # group's text), so ``run(text)`` and ``run(parse(text))`` type a value alike.
    """
    specs: list[CodeSlot] = []
    for slot in slots:
        kind = _form_kind(slot.form, slots, specs)
        specs.append(CodeSlot(slot.name, slot.weight, not _is_optional(slot.form), kind))
    return tuple(specs)


def _is_optional(form: Node | str | None) -> bool:
    return isinstance(form, Source) and any(key == "optional" for key, _ in form.annotations)


def _form_kind(form: Node | str | None, slots: list[_Slot], earlier: list[CodeSlot]) -> SlotKind:
    if isinstance(form, str):
        return _lazy_kind(form)
    if isinstance(form, Source) and form.expand:
        return "expand"
    node = form.value if isinstance(form, (Source, Binding)) else form
    return _value_kind(node.value if isinstance(node, Binding) else node, slots, earlier)


def _value_kind(node: Node | None, slots: list[_Slot], earlier: list[CodeSlot]) -> SlotKind:
    reference = _bare_reference(node)
    if reference is None:
        return _node_kind(node)
    # A bare `$name` / `$N` to an EARLIER sibling takes that sibling's kind (B §6.2).
    kinds: list[SlotKind] = [
        spec.kind for i, spec in enumerate(earlier) if reference in (slots[i].name, str(i + 1))
    ]
    return kinds[0] if kinds else "text"


def _node_kind(node: Node | None) -> SlotKind:
    if isinstance(node, StructObject):
        return "json"
    if isinstance(node, Iteration):
        return "json" if node.reducer is None else "text"
    return "json" if isinstance(node, Expression) and node.broadcast else "text"


def _bare_reference(node: Node | None) -> str | None:
    """The name of a whole-value `$ref` with no field path, else None."""
    if isinstance(node, VarRef):
        return node.name if not node.path else None
    if isinstance(node, Text):
        match = _BARE_REF_RE.fullmatch(node.value)
        return match.group(1) if match else None
    return None


_BARE_REF_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*|[0-9]+)")


def _lazy_kind(text: str) -> SlotKind:
    """A deferred group: a broadcast or a reducer-less iteration resolves to a collection."""
    envelope = decode_envelope(text, require_intent=False)
    if isinstance(envelope, IterationEnvelope):
        return "json" if envelope.reducer is None else "text"
    return "json" if envelope.broadcast else "text"


__all__ = ["call_intent", "compile_group", "reduce_rows"]

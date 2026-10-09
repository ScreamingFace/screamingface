"""Intent, reducer and row-intent classification for the lowering path.

Split out of :mod:`url4.dag._lowering`: how a group's intent (its ``!`` tail), an
iteration's reducer and its per-row intent are classified and lowered, and how a
slot's name, its instrumental flag and its ``$name`` references are read off the
parse tree. :func:`_body_intent_refs` is the one reading of an iteration's
template strings, shared by the text path and the AST path.

This module depends on no other lowering module. :mod:`url4.dag._lowering_text`
and :mod:`url4.dag._lowering_nodes` import it, never the reverse.
"""

from __future__ import annotations

from url4.core.errors import ErrorCode, ParseError
from url4.core.grammar import parse_value
from url4.core.intent import CodePointer, IntentMode, classify_intent
from url4.core.nodes import (
    Binding,
    Iteration,
    Node,
    RelExpr,
    RelUrl,
    RemoteExpr,
    Source,
    StructObject,
    Text,
    Url,
    VarRef,
)
from url4.core.nodes import walk as ast_walk
from url4.core.parser import intent_atom, split_intent
from url4.dag.semantics.ensemble import find_references

from url4.dag._lowering_registry import LoweringRegistry  # isort: skip
from url4.dag._wiring import Edges, _Intent  # isort: skip
from url4.dag.node import DagNode  # isort: skip
from url4.dag.nodes import MapNode, ReduceNode, TextNode  # isort: skip
from url4.dag.nodes.code_pointer import unsupported_intent_error  # isort: skip

_ROW_NAMES = frozenset({"item", "current", "index"})
"""Reserved per-row names, including the SDK index extension.

Both text and AST iteration bodies exclude these from enclosing dependency capture.
Ordinary AST references still retain `index`, which is only reserved inside iteration.
"""


def _refuse_row_intent(intent: str | None) -> None:
    """Refuse a URI per-row intent at compile, once (contracts C7), not once per row.

    WHY: a per-row intent is spawned for every row, so a bad URI would otherwise fail row by
    row at run time. A `$` (a row reference such as `$item`, or any substitution) is resolved per
    row, so the URI does not exist until a row does; the check is skipped for such an intent, and
    the row's own compile judges it. The test is any `$`, not find_references, which skips `$item`.
    """
    if intent is None or "$" in intent:
        return
    _code_pointer_of(intent_atom(intent))


def _reduce_node(reducer: str, rows: MapNode) -> ReduceNode:
    return ReduceNode(reducer, deps={"rows": rows}, pointer=_reducer_pointer(reducer))


def _reducer_pointer(reducer: str) -> CodePointer | None:
    """The code pointer an iteration reducer names, classified once here (contracts C7).

    WHY: a reducer that names no valid code pointer is refused at compile, as a per-row intent
    is. A code-pointer reducer takes only the rows, so a `!` tail on it is refused rather than
    dropped.
    """
    head, tail, _ = split_intent(reducer)
    try:
        parse_value(head)
    except ParseError:
        # WHY: a head the grammar cannot read as a value is a malformed expression, not a URI, so
        # it is not classified here. validate() and the run refuse it as they do today
        # (test_dag::test_validate_parses_reducer_instruction pins that).
        return None
    cls = classify_intent(intent_atom(head))
    if cls.mode is IntentMode.UNSUPPORTED:
        raise unsupported_intent_error(head)
    if cls.pointer is not None and tail is not None:
        raise ParseError(
            f"a code-pointer reducer {head!r} takes no `!` intent — the rows are its only input",
            code=ErrorCode.MALFORMED_SOURCE,
        )
    return cls.pointer


def _body_intent_refs(body: str, intent: str | None) -> set[str]:
    """The `$name`s an iteration's body and per-row intent mention, minus the reserved row names.

    INVARIANT: the ONE reading of an iteration's template strings. Both compilation paths need
    it — `_body_ref_edges` at lowering time and `_refs_of_ast` when collecting a slot's
    references — and if they ever disagree about which names an iteration rebinds for itself,
    the AST path silently stops wiring an outer binding while the text path keeps working. That
    divergence is invisible: the reference substitutes VERBATIM and the run still succeeds.
    """
    return (find_references(body) | (find_references(intent) if intent else set())) - _ROW_NAMES


def _body_ref_edges(body: str, intent: str | None, edges: Edges) -> dict[str, DagNode]:
    """Reference edges for the `$name`s an iteration's body and per-row intent mention.

    INVARIANT: ``item``, ``current`` and ``index`` are reserved row names, excluded here.
    They are rebound by :class:`~url4.dag.nodes.MapNode`; wiring one to an enclosing binding of
    the same name would let an outer value capture the row and silently iterate the wrong data.

    An edge is added only for a name the enclosing group actually declares, so a body that
    references nothing gains no dependency and keeps its previous concurrency.
    """
    wired: dict[str, DagNode] = {}
    for ref in sorted(_body_intent_refs(body, intent)):
        key = f"pos:{ref}" if ref.isdigit() else f"bind:{ref}"
        if key in edges:
            wired[key] = edges[key]
    return wired


def _slot_identity(ast: Node) -> tuple[str | None, bool]:
    """The slot's ``(name, instrumental)`` — ABNF contribution semantics.

    WHY Binding is never instrumental (`OME-534`): the name-only forms
    (``a: v`` / ``a=v``) are contributing sources under the ABNF; the ONLY
    instrumental marker is an explicit scalar ``weight 0.0`` on a Source.
    """
    if isinstance(ast, Binding):
        return ast.name, False
    if isinstance(ast, Source):
        return ast.name, _is_instrumental_weight(ast.weight)
    return None, False


def _is_instrumental_weight(weight: object) -> bool:
    """True for the explicit scalar ``0.0`` (structured weights never qualify)."""
    return (
        isinstance(weight, (int, float)) and not isinstance(weight, bool) and float(weight) == 0.0
    )


def _intent_from_raw(raw_intent: str | None, registry: LoweringRegistry) -> _Intent | None:
    if raw_intent is None:
        return None
    return _intent_from_ast(intent_atom(raw_intent), registry)


def _intent_from_ast(
    atom: Node | None, registry: LoweringRegistry, *, classify: bool = True
) -> _Intent | None:
    if atom is None:
        return None
    if isinstance(atom, Text):
        value = atom.value
        return _Intent(lambda edges: TextNode(value, deps=dict(edges)), text=value)
    pointer = _code_pointer_of(atom) if classify else None
    return _Intent(lambda edges: registry.lower(atom, edges), pointer=pointer)


def _code_pointer_of(atom: Node) -> CodePointer | None:
    """The code pointer a URI intent names (PRD §2.5), or None for any other intent.

    WHY: only the grammar's URI productions can be code pointers. Every other intent
    (a variable, a struct, a nested expression, a bare token) keeps its 1.5.1 lowering.
    """
    if not isinstance(atom, RelUrl | Url):
        return None
    cls = classify_intent(atom)
    if cls.mode is IntentMode.UNSUPPORTED:
        raise unsupported_intent_error(atom.value)
    return cls.pointer


def _refs_of_ast(node: Node) -> set[str]:
    refs: set[str] = set()
    for descendant in ast_walk(node):
        if isinstance(descendant, Text):
            refs |= find_references(descendant.value)
        elif isinstance(descendant, RelUrl):
            # A bare relative URI /data/$topic embeds refs in its path, the AST
            # twin of the text path's per-segment find_references (§8.2.3).
            refs |= find_references(descendant.value)
        elif isinstance(descendant, (RelExpr, RemoteExpr)) and descendant.context:
            refs |= find_references(descendant.context)
        elif isinstance(descendant, Iteration):
            # WHY read as TEXT: an iteration's body and per-row intent are template strings,
            # not child nodes — `children(Iteration)` yields only the collection — so the walk
            # cannot reach their `$name`s. Without this the enclosing group's slot declared no
            # dependency on them, `_ref_edges` emitted no `bind:` edge, and `_lower_iteration`
            # had nothing left to wire: the AST path substituted an outer reference VERBATIM,
            # which is the silent failure the text path already fixed (§6.2).
            #
            # INVARIANT: the SAME reading `_body_ref_edges` uses, shared rather than restated —
            # a slot that declares fewer references than the lowering step wires is a wiring
            # step with nothing to wire. The collection is deliberately not part of it: it
            # resolves in the ENCLOSING scope and reaches this walk as an ordinary child.
            refs |= _body_intent_refs(descendant.body, descendant.intent)
        elif isinstance(descendant, StructObject):
            refs |= find_references(descendant.raw)
        # Unlike row-body capture, ordinary references retain named index dependencies.
        elif isinstance(descendant, VarRef) and descendant.name not in {"item", "current"}:
            refs.add(descendant.name)
    return refs

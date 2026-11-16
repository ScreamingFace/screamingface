"""The binding environment admission reads a collection in: the one execution wires.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review round 11,
findings 2 and 3).
STORY: as an ensemble author, a picture under ``/rows/$1*(…)`` is refused ``x.source_not_static``
when source 1 is a model's output, and ``(xs=$ys, ys=/m(…), /rows/$xs*(…))`` is NOT refused,
because execution never binds the later ``ys`` into ``xs``.

INVARIANT (mirror ``_wiring._build_slots`` and ``_lowering._build_ctx_nodes``): a source list's
named source sees the outer scope plus only EARLIER named siblings; an unnamed source (and the
intent) sees every named sibling; ``$N`` names the N-th source when that source is named (a
group and an iteration body register positions, a call context does not, so ``$N`` there keeps
the outer meaning). A binding's value resolves in ITS definition scope, never the use site's.
INVARIANT: a name the group defines but a named source cannot see yet is ``hidden``: execution
leaves it unbound, so through a binding it is the literal ``$name`` text (``_TemplateWalk`` and
``resolve_collection`` read it so).
AIDEV-NOTE: imports only ``core``; :mod:`url4.dag._collection_shape` and
:mod:`url4.dag.source_scan` both import it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from url4.core.nodes import Binding, Node, Source


def ref_key(name: str) -> str:
    """The scope key ``$name`` reads: ``$01`` is slot 1, as ``_wiring._ref_edges``' ``int()``."""
    return str(int(name)) if name.isascii() and name.isdigit() else name


class Scope(Mapping[str, Node]):
    """Names (and positions) to binding values, each with the scope its value resolves in."""

    def __init__(
        self,
        values: Mapping[str, tuple[Node, Mapping[str, Node]]],
        hidden: frozenset[str] = frozenset(),
    ) -> None:
        self._values = dict(values)
        self._hidden = hidden

    @classmethod
    def of(cls, outer: Mapping[str, Node]) -> Scope:
        """``outer`` as a scope; a plain mapping's values resolve in that mapping (flat)."""
        if isinstance(outer, Scope):
            return outer
        return cls({ref_key(name): (value, outer) for name, value in outer.items()})

    def __getitem__(self, name: str) -> Node:
        return self._values[ref_key(name)][0]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def definition(self, name: str) -> Mapping[str, Node]:
        """The scope ``name``'s value resolves in (where it was defined)."""
        return self._values[ref_key(name)][1]

    def hides(self, name: str) -> bool:
        """``True`` when execution leaves ``name`` unbound here though the group defines it."""
        key = ref_key(name)
        return key in self._hidden and key not in self._values

    def _with(self, keys: Sequence[str], value: Node, defined_in: Scope) -> Scope:
        values = dict(self._values)
        values.update({key: (value, defined_in) for key in keys})
        return Scope(values, self._hidden)

    def _hiding(self, keys: frozenset[str]) -> Scope:
        return Scope(self._values, self._hidden | keys)


def definition_of(bound: Mapping[str, Node], name: str) -> Mapping[str, Node]:
    """Where ``bound[name]`` resolves: its definition scope, or ``bound`` itself when flat."""
    return bound.definition(name) if isinstance(bound, Scope) else bound


def hidden_in(bound: Mapping[str, Node], name: str) -> bool:
    return isinstance(bound, Scope) and bound.hides(name)


def named_value(source: Node) -> tuple[str, Node] | None:
    """A source's binding name and the value admission reads, or ``None`` when unnamed."""
    if isinstance(source, Binding):
        return source.name, source.value
    if isinstance(source, Source) and source.name is not None:
        # WHY the descriptor, not its value: ``$xs*(…)`` admission needs the binding's
        # ``;retry=`` / ``;t=`` / ``;optional`` / ``;accept=`` (``_materialize._unwrap``).
        return source.name, source
    return None


def sibling_scopes(
    sources: Sequence[Node | None], outer: Mapping[str, Node], *, positional: bool
) -> tuple[list[Scope], Scope]:
    """Each source's scope, and the full scope (unnamed sources and the intent see it).

    ``None`` marks a segment that did not parse: it keeps its position, binds nothing.
    """
    named = [
        (i, found) for i, s in enumerate(sources) if s is not None and (found := named_value(s))
    ]
    keys = {i: [name, *([str(i + 1)] if positional else [])] for i, (name, _) in named}
    pending = frozenset(key for group in keys.values() for key in group)
    full = Scope.of(outer)
    per: list[Scope | None] = [None] * len(sources)
    for i, (_, value) in named:
        here = full._hiding(pending)  # INVARIANT: later siblings are hidden, never visible
        per[i] = here
        full = full._with(keys[i], value, here)
        pending -= frozenset(keys[i])
    return [scope if scope is not None else full for scope in per], full


__all__ = ["Scope", "definition_of", "hidden_in", "named_value", "ref_key", "sibling_scopes"]

"""Typed parse tree for the url4 grammar.

The parse tree is an *algebraic data type*: a closed union of frozen
dataclasses (:data:`Node`). Nodes are pure data — they carry no behavior;
traversal (:func:`walk`) and lowering (:mod:`url4.dag.compiler`) live outside
them. Note the deliberate expression-problem split with the *executable* layer:
this closed node set has an open operation set, while the DAG in
:mod:`url4.dag` flips the axis — open node set, one fixed operation
(``resolve``) — because execution is the layer that must accept custom nodes.

This module is a leaf in the import graph — it imports nothing internal — so
consumers that only need the type names don't pull in the parser or the
execution machinery.

Node set
--------
- :class:`Text`         — inline text / a natural-language prompt (quotes are
  delimiters: a quoted value parses to its *content*, spec §5.1).
- :class:`Url`          — an absolute ``scheme://…`` reference (any scheme,
  including a bare ``url4://`` remote reference, spec §5.2 rules 3.3/5).
- :class:`RelUrl`       — a ``/path`` data reference relative to the current node.
- :class:`Binding`      — ``name=value`` / ``name:value`` (name-only descriptor).
- :class:`RelExpr`      — ``/path?params&q=(context)!intent`` relative expression.
- :class:`RemoteExpr`   — ``url4://node/path?params&q=(context)!intent``.
- :class:`SelfRef`      — ``@``, the addressed node's own holdings (spec §5.6).
- :class:`IdentityRef`  — ``@name[/collection]``, a principal's holdings (§5.6).
- :class:`VarRef`       — a standalone ``$name[.field][N]`` reference (§5.2 r8).
- :class:`StructObject` — an inline ``{key: value, …}`` record (§5.3.11.3).
- :class:`Source`       — the two-axis descriptor wrapper (§4.3): weight,
  budgets, execution annotations, and the expansion mark around a value.
- :class:`Iteration`    — ``src*(body)`` per-row map, with optional reduce (§5.3).
- :class:`Expression`   — the composite ``(sources)!intent`` (or ``!*`` broadcast).

Binding vs. Source: a *name-only* descriptor (``a=v`` / ``a:v``) stays a
:class:`Binding` — the reference engine's eager bind, excluded from the packed
sources. Any descriptor carrying weight, budgets, execution annotations, or the
expansion mark wraps in :class:`Source`, a weighted contributor that stays in
the packed sources and is referenceable by name.

Deliberately absent: there is no structural node for *embedded* ``$name`` /
``$N`` references inside text — those are resolved by string interpolation at
evaluation time (spec §8.2; see :mod:`url4.dag.semantics.ensemble`). Only a *standalone*
reference in a value position parses structurally, as :class:`VarRef`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# The closed set of per-row failure policies (§5.3.6). The surface validator
# (core._annotations) derives its accepted set from this Literal, so the wire
# grammar, the Python builders, and MapNode's dispatch cannot drift apart — and
# an unknown policy is unrepresentable on the dataclass rather than caught (or
# missed) by an == chain at resolve time.
OnErrorPolicy = Literal["skip", "fail", "collect"]

Params = tuple[tuple[str, str | None], ...]
"""Ordered ``key → value`` protocol parameters; a valueless flag carries None."""


@dataclass(frozen=True)
class Text:
    """Inline text content or a natural-language intent/prompt (quotes stripped)."""

    value: str


@dataclass(frozen=True)
class Url:
    """An absolute URI reference of any scheme (``https://…``, ``s3://…``, …).

    A bare ``url4://node/path`` *reference* (no expression body) is also a
    :class:`Url` — the scheme, not the node type, carries the URL4-awareness
    signal (spec §3.5); the I/O layer dispatches on it.
    """

    value: str


@dataclass(frozen=True)
class RelUrl:
    """A ``/path`` data reference resolved relative to the current node."""

    value: str


@dataclass(frozen=True)
class Binding:
    """A name-only descriptor: ``name=value`` (``kind="="``) or ``name:value``.

    The bound value is registered in the evaluation :class:`~url4.core.context.Context`
    so sibling sources and the intent can read it back via ``$name``. ``kind``
    records the surface form for faithful round-tripping and error messages.
    """

    name: str
    value: Node
    kind: Literal["=", ":"]


@dataclass(frozen=True)
class RelExpr:
    """A relative expression: ``/path?[params&]q=(context)!intent`` (spec §3.1.1).

    The sugar form ``/path(context)!intent[;params]`` desugars to this same
    node (spec §8.1) — both forms produce identical ASTs. ``context`` is the
    raw text inside the parens (``None`` when empty); laziness is the
    interpreter's choice. ``params`` are the expression-level protocol
    parameters (canonical ``?k=v&`` and pre-boundary sugar ``;k=v``, §8.1.2).
    """

    path: str
    context: str | None = None
    intent: Node | None = None
    params: Params = ()


@dataclass(frozen=True)
class RemoteExpr:
    """A remote expression: ``url4://authority/path?[params&]q=(context)!intent``.

    The :class:`RelExpr` shape addressed to another node (spec §3.1.1); the
    sugar form desugars identically. ``authority`` is ``host[:port]``; ``path``
    keeps its leading slash.
    """

    authority: str
    path: str
    context: str | None = None
    intent: Node | None = None
    params: Params = ()


@dataclass(frozen=True)
class SelfRef:
    """``@`` — the addressed node's own holdings (spec §5.6.1)."""


@dataclass(frozen=True)
class IdentityRef:
    """``@name[/collection]`` — a named principal's holdings (spec §5.6.2).

    ``collection`` is the slash-joined selector *without* its leading slash
    (``"notes"``, ``"drafts/2026"``), or ``None`` for the default holdings.
    Resolution semantics (access control, consent) apply at execution time.
    """

    name: str
    collection: str | None = None


@dataclass(frozen=True)
class VarRef:
    """A standalone ``$name`` / ``$N`` reference with an optional field path.

    ``path`` holds field segments as ``str`` and index segments as ``int``
    (``$item.answers[0].text`` → ``("answers", 0, "text")``, spec §5.3.4).
    Embedded references inside text are *not* VarRefs — they are interpolated
    at resolve time (spec §8.2).
    """

    name: str
    path: tuple[str | int, ...] = ()


@dataclass(frozen=True)
class StructObject:
    """An inline structured object ``{key: value, …}`` (spec §5.3.11.3).

    ``raw`` keeps the balanced-brace surface text verbatim; field decoding and
    ``$`` substitution happen at resolve time, so a value carrying references
    stays a template until then.
    """

    raw: str


@dataclass(frozen=True)
class Source:
    """The two-axis source descriptor (spec §4.3) around a value node.

    Attribution axis: ``name``, ``weight`` (scalar, or a structured mapping for
    domain-conditional weights, §4.1.1), ``budgets`` (ordered ``key → value``
    pairs; a structured budget value is a mapping). Execution axis:
    ``annotations`` (ordered ``key → value`` pairs; flags carry None).
    ``expand`` records the ``*source`` prefix / ``;expand`` mark (§5.3.12).
    """

    value: Node
    name: str | None = None
    weight: float | dict | None = None
    budgets: tuple[tuple[str, str | dict], ...] = ()
    annotations: Params = ()
    expand: bool = False


@dataclass(frozen=True)
class IterationDirectives:
    """Execution annotations for collection iteration (``;iteration.*``, §5.3.6).

    Pure data, so it lives here with the AST rather than in the parser — an
    :class:`Iteration` embeds it, and the parser imports it back. ``slice`` is
    the half-open ``[start, end)`` element range.
    """

    concurrency: int | None = None
    on_error: OnErrorPolicy = "collect"
    slice: tuple[int, int] | None = None
    fmt_result: str | None = None


# The pre-0.2 directive name; importable for one more minor version.
ForeachDirectives = IterationDirectives


@dataclass(frozen=True)
class Iteration:
    """``src*(body)`` — evaluate ``body`` once per item of a fetched collection.

    :attr:`collection` is resolved once and parsed into items (spec §5.3.7);
    :attr:`body` is a per-row template that is re-parsed after ``$item``
    substitution. The optional tails mirror the two reduce shapes:

    - :attr:`intent`  — the ``!intent`` after the iteration, reducing each
      row-group per row (``src*(body)!intent``). A template string. The
      grammar's iteration takes a full expression after ``*``, so the PARSER
      always sets it (`OME-508`); ``None`` (map-only) is an internal, AST-only
      shape the compiler still lowers.
    - :attr:`reducer` — a cross-row reducer applied to the JSON array of all
      rows (``(src*(body)!peri)!reducer``). A template string; ``None`` = no
      cross-row reduce.

    Both tails may coexist (``(src*(body)!intent)!reducer``). :attr:`directives`
    carries the ``;iteration.*`` execution annotations so the node fully
    captures the expression (``evaluate(text) == resolve(build(text))``).
    """

    collection: Node
    body: str
    intent: str | None = None
    reducer: str | None = None
    directives: IterationDirectives = field(default_factory=IterationDirectives)


@dataclass(frozen=True)
class Expression:
    """The composite ``(sources)!intent`` unit — the atomic url4 computation.

    - ``intent`` set         → ``(sources)!intent``. The grammar's expression
      always carries an intent, so the parser sets it in every surface
      position (`OME-508`).
    - ``intent is None``     → an INTERNAL carrier with no surface form of its
      own: an iteration's paren-collection, an envelope mid-assembly, or a
      hand-built group the compiler lowers to a plain gather-join.
    - ``broadcast is True``  → ``(sources)!*intent`` (apply intent per source).
    - ``params``             → the trailing ``;key=val`` per-expression
      protocol parameters (spec §9.2); the ``;broadcast`` flag is folded into
      ``broadcast`` rather than kept here.
    """

    sources: tuple[Node, ...]
    intent: Node | None = None
    broadcast: bool = False
    params: Params = ()


Node = (
    Text
    | Url
    | RelUrl
    | Binding
    | RelExpr
    | RemoteExpr
    | SelfRef
    | IdentityRef
    | VarRef
    | StructObject
    | Source
    | Iteration
    | Expression
)


def children(node: Node) -> tuple[Node, ...]:
    """Return the direct child nodes of ``node`` in source order.

    Leaf nodes have no children. :class:`Iteration`'s body/intent/reducer are
    template strings (like :attr:`RelExpr.context`), so only its
    ``collection`` is a child; :class:`StructObject` keeps raw text.
    """
    match node:
        case Binding(value=value) | Source(value=value):
            result: tuple[Node, ...] = (value,)
        case Iteration(collection=collection):
            result = (collection,)
        case RelExpr(intent=intent) | RemoteExpr(intent=intent) if intent is not None:
            result = (intent,)
        case Expression(sources=sources, intent=intent):
            result = (*sources, intent) if intent is not None else sources
        case _:
            result = ()
    return result


def walk(node: Node):
    """Yield ``node`` and all its descendants in preorder (depth-first).

    A generator, mirroring :func:`ast.walk` from the standard library.
    """
    yield node
    for child in children(node):
        yield from walk(child)


__all__ = [
    "Binding",
    "Expression",
    "ForeachDirectives",
    "IdentityRef",
    "Iteration",
    "IterationDirectives",
    "Node",
    "Params",
    "RelExpr",
    "RelUrl",
    "RemoteExpr",
    "SelfRef",
    "Source",
    "StructObject",
    "Text",
    "Url",
    "VarRef",
    "children",
    "walk",
]

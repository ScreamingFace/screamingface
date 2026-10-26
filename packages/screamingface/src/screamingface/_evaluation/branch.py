"""Compile a BranchNode to the gated url4 shape (E4c, OME-1291, branch-core §2.2, contracts C1).

FEATURE: a branch that is not selected makes zero model calls. Every Gate becomes ONE named inner
expression ``gate_N_block``::

    gate_N_after     = /ensemble/branch/v1/after(r1:0.0:$a, ...)!'after'
    gate_N_decide    = /ensemble/branch/v1/decide({after, keywords?, selectors?})?gate=gate_N
    gate_N_open_then = /ensemble/branch/v1/open($gate_N_decide)!'then'
    gate_N_then      = $gate_N_open_then*(<then body>)!'$<terminal>';iteration.on_error=fail
    gate_N_open_else / gate_N_else   (the same for otherwise)
    gate_N           = /ensemble/branch/v1/join({decision, then?, otherwise?})?binding=gate_N

The gate spec (``gate-spec.v1``) is the intent (``!'<spec>'``) of DECIDE and JOIN, as a combine
spec is the intent of a combine call, so the url4 decode reads it from the JOIN call.

and, once at the top of each Gate tree that reads a selector, ``keywords_N`` (the pure KEYWORDS
source, which also returns the Case input summary) and each LabelModel call ``selector_N`` at the
lowest scope that holds every Gate that reads it (``;optional``: a failed call takes the default).
STORY: OPEN returns a one-item collection only for the branch DECIDE chose, and url4 runs no
element of an empty collection, so the other body never runs.

WHY one named inner expression (the corrective renderer's rule): gated iterations may not sit bare
in the outer intent-bearing group.
INVARIANT (D1): a recipe body is compiled inline (no ``MEMBER_ROUTE``), so its calls reach the
Case recorder; every model call inside a gated body carries ``binding=<name>`` first (D3).
INVARIANT (D5): a body references only bindings that run unconditionally in an enclosing scope.
INVARIANT (D10): AFTER references only bindings in scope; its slots are instrumental (weight 0.0).
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from url4 import (
    Expression,
    Iteration,
    Node,
    RelExpr,
    Source,
    StructObject,
    Text,
    VarRef,
    build,
    expr,
    iterate,
    render,
    src,
    struct,
    walk,
)
from url4 import ref as url4_ref

from screamingface._evaluation.combine_spec import canonical_json
from screamingface._evaluation.model import _compiled_operation
from screamingface._evaluation.topology import _BranchWord, _RecipeTopology
from screamingface._operation_bindings import gate_join
from screamingface._surface.selectors import Keywords, LabelModel, Selector
from screamingface.branch import (
    GATE_IN_LOOP,
    MAX_GATE_DEPTH,
    WORDS,
    BranchNode,
    LazyDecision,
    _is_skip_member,
)
from screamingface.corrective import CorrectiveLoop, SelfCorrective
from screamingface.fusion import FusionNode
from screamingface.pipeline import Pipeline
from screamingface.recipe import Recipe
from screamingface.reducer import Reducer
from screamingface.signal_sources import Consistency

if TYPE_CHECKING:
    from screamingface._evaluation.candidate import _CandidateCompiler, _ResolvedRecipe

BRANCH_PREFIX = "/ensemble/branch/v1"
AFTER_ROUTE = f"{BRANCH_PREFIX}/after"
DECIDE_ROUTE = f"{BRANCH_PREFIX}/decide"
OPEN_ROUTE = f"{BRANCH_PREFIX}/open"
JOIN_ROUTE = f"{BRANCH_PREFIX}/join"
KEYWORDS_ROUTE = "/ensemble/select/v1/keywords"
GATE_SPEC_SCHEMA = "screamingface.gate-spec.v1"
_ENSEMBLE = "/ensemble/"
# The bindings any scope may read: the Case input, and a nested Recipe invocation's input.
_ALWAYS_IN_SCOPE = frozenset({"input", "_sf_recipe_input"})
_REFERENCE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_SLOT_NAMES = {"then": "then", "otherwise": "else"}

type _Path = tuple[tuple[int, str], ...]
type _Range = tuple[int, int]
_NONE: _Range = (0, 0)


# --- the tree scan --------------------------------------------------------------------------------


@dataclass(slots=True)
class _Tree:
    """One Gate tree: the selectors its Gates read and where each LabelModel call is placed."""

    keywords_binding: str | None = None
    # selector identity -> the scope path of each Gate that reads it
    readers: dict[str, list[_Path]] = field(default_factory=dict)
    # LabelModel identity -> (placement path, call binding) once placed
    placed: dict[str, tuple[_Path, str]] = field(default_factory=dict)
    selectors: dict[str, Selector] = field(default_factory=dict)
    # LabelModel identities a tree-root Gate already lists (a skip-member Fanout has several roots)
    listed: set[str] = field(default_factory=set)

    def placement(self, identity: str) -> _Path:
        """The lowest common scope of every Gate that reads ``identity`` (SL-18)."""

        paths = self.readers[identity]
        common = paths[0]
        for path in paths[1:]:
            length = 0
            while length < min(len(common), len(path)) and common[length] == path[length]:
                length += 1
            common = common[:length]
        return common


def _scan(root: object) -> _Tree:
    tree = _Tree()

    def visit(value: object, path: _Path) -> None:
        if isinstance(value, BranchNode):
            selector = value.condition.selector
            if selector is not None:
                identity = selector._identity()
                tree.selectors.setdefault(identity, selector)
                tree.readers.setdefault(identity, []).append(path)
            if value.panel is not None:
                visit(value.panel, path)
            for branch in ("then", "otherwise"):
                visit(value.body(branch), (*path, (id(value), branch)))
        else:
            for child in _recipe_children(value):
                visit(child, path)

    visit(root, ())
    return tree


def _recipe_children(value: object) -> tuple[object, ...]:  # noqa: PLR0911
    if isinstance(value, FusionNode):
        return (*value.members, value.synthesizer)
    if isinstance(value, Pipeline):
        return value._stage_values()
    if isinstance(value, CorrectiveLoop):
        return (*value.members, value.judge)
    if isinstance(value, SelfCorrective):
        return (value.member,)
    return ()


# --- the renderer state --------------------------------------------------------------------------


@dataclass(slots=True)
class _BranchState:
    """Candidate-wide counters and the active Gate tree (one per compiler)."""

    gates: int = 0
    keywords: int = 0
    selector_calls: int = 0
    selector_ids: dict[str, str] = field(default_factory=dict)
    tree: _Tree | None = None
    path: _Path = ()
    depth: int = 0
    # gate_N_block -> (min, max) model calls on the paths through that Gate (ans:Q22)
    ranges: dict[str, _Range] = field(default_factory=dict)

    def selector_id(self, selector: Selector) -> str:
        identity = selector._identity()
        if identity not in self.selector_ids:
            self.selector_ids[identity] = f"sel_{len(self.selector_ids) + 1}"
        return self.selector_ids[identity]


@dataclass(frozen=True, slots=True)
class _Selectors:
    """The selectors one Gate's DECIDE reads: per-branch reads, the spec entries, the LabelModel
    reply references in scope and the KEYWORDS reference."""

    reads: dict[str, list[Selector]]
    declared: dict[str, dict[str, object]]
    replies: dict[str, str]
    keywords: str | None


@dataclass(frozen=True, slots=True)
class _SkipSelection:
    """The combine context of every reducer over a skip-member panel (SM-11, SM-18)."""

    selection: dict[str, str]
    floor: int | None


@dataclass(frozen=True, slots=True)
class _Body:
    kind: Literal["recipe", "step", "abstain", "fail_closed", "skip"]
    sources: tuple[Node, ...] = ()
    reference: str | None = None  # the body's result reference, e.g. "$model_5"
    terminal: str | None = None  # the binding whose recorded result JOIN copies (D12)
    resolved: _ResolvedRecipe | None = None
    calls: _Range = _NONE


@contextmanager
def _tree_scope(
    compiler: _CandidateCompiler, state: _BranchState, build: Callable[[], _Tree]
) -> Iterator[None]:
    """Activate the tree ``build`` returns when none is active, and clear it on exit."""

    tree_root = state.tree is None
    if tree_root:
        state.tree = build()
        _emit_tree_top(compiler, state)
    try:
        yield
    finally:
        if tree_root:
            state.tree = None


def compile_branch(
    compiler: _CandidateCompiler,
    node: BranchNode,
    *,
    input_context: str,
    input_dependencies: tuple[str, ...],
) -> _ResolvedRecipe:
    """Render one Gate (and, at the top of a Gate tree, its selector sources)."""

    state = compiler._branch_state()
    if state.depth >= MAX_GATE_DEPTH:
        raise ValueError(f"sf.Gate nests at most {MAX_GATE_DEPTH} deep")
    member = compiler._skip_member == id(node)
    compiler._skip_member = None  # a Gate inside the member's body is an ordinary Gate
    with _tree_scope(compiler, state, lambda: _scan(node)):
        state.depth += 1
        try:
            gate = _Gate(compiler, state, node, input_context, input_dependencies, member=member)
            return gate.render()
        finally:
            state.depth -= 1


def compile_skip_fusion(
    compiler: _CandidateCompiler,
    fusion: FusionNode,
    input_context: str,
    input_dependencies: tuple[str, ...],
) -> _ResolvedRecipe:
    """A Fanout with skip-Gate members (E4c, ans:Q16, skip-members compiled shape).

    The members' selectors run once, before the panel (SM-3, SM-9), and so do the members' AFTER
    and DECIDE (D8); each member slot holds OPEN, the gated iterate and JOIN. Under
    ``quorum="all"`` every slot is required; under a numeric quorum the slots are optional, the url4
    panel takes ``quorum=0`` and the combine call checks the floor over the selected members.
    """

    state = compiler._branch_state()
    with _tree_scope(compiler, state, lambda: _members_tree(fusion)):
        hoisted: list[Node] = []
        outer, compiler._hoist = compiler._hoist, hoisted
        try:
            captured = []
            for member in fusion.members:
                if _is_skip_member(member):
                    compiler._skip_member = id(member)
                captured.append(
                    compiler._capture_recipe(
                        member,
                        input_context=input_context,
                        input_dependencies=input_dependencies,
                        synthesis=False,
                    )
                )
        finally:
            compiler._hoist = outer
            compiler._skip_member = None
    compiler._sources.extend(hoisted)
    return _skip_panel(compiler, fusion, tuple(captured), input_context, input_dependencies)


def _members_tree(fusion: FusionNode) -> _Tree:
    """One Gate tree over every member of a skip-member Fanout: one selector evaluation each."""

    tree = _Tree()
    for member in fusion.members:
        if not isinstance(member, BranchNode):
            continue
        scanned = _scan(member)
        for identity, selector in scanned.selectors.items():
            tree.selectors.setdefault(identity, selector)
            tree.readers.setdefault(identity, []).extend(scanned.readers[identity])
    return tree


def _skip_panel(
    compiler: _CandidateCompiler,
    fusion: FusionNode,
    captured: tuple[tuple[_ResolvedRecipe, tuple[Node, ...]], ...],
    input_context: str,
    input_dependencies: tuple[str, ...],
) -> _ResolvedRecipe:
    members = tuple(member for member, _ in captured)
    numeric = fusion.quorum != "all"
    compiler._panel_count += 1
    panel = f"panel_{compiler._panel_count}"
    slots = tuple(
        src(
            expr(*sources, intent=Text(member.reference)),
            name=f"member_{index}",
            weight=1.0,
            required=not (
                fusion.members[index - 1].optional
                or (numeric and _is_skip_member(fusion.members[index - 1]))
            ),
        )
        for index, (member, sources) in enumerate(captured, 1)
    )
    reads_rows = isinstance(fusion.synthesizer, Reducer)
    if not reads_rows:
        raise ValueError("a sf.Fanout with skip-Gate members closes with a reducer or a writer")
    quorum = 0 if numeric else len(members)
    compiler._append_source(
        src(
            expr(*slots, intent=Text(""), broadcast=True, params={"quorum": quorum}),
            name=panel,
            weight=0.0,
        )
    )
    skip = _skip_selection(fusion, members)
    resolved = compiler._fusion(
        fusion,
        members,
        input_context=input_context,
        input_dependencies=input_dependencies,
        panel=f"${panel}",
        selection=skip.selection,
        floor=skip.floor,
    )
    return replace(resolved, panel=f"${panel}")


def _skip_selection(fusion: FusionNode, members: Sequence[_ResolvedRecipe]) -> _SkipSelection:
    """The DECIDE of each skip member, and the quorum floor under a numeric quorum."""

    return _SkipSelection(
        selection={
            f"member_{index}": f"${_terminal(member.reference)}_decide"
            for index, member in enumerate(members, 1)
            if _is_skip_member(fusion.members[index - 1])
        },
        floor=None if fusion.quorum == "all" else int(fusion.quorum),
    )


def _emit_tree_top(compiler: _CandidateCompiler, state: _BranchState) -> None:
    """The tree's KEYWORDS source (D6) and the LabelModel calls placed at the tree top."""

    tree = state.tree
    assert tree is not None
    if not tree.selectors:
        return
    for selector in tree.selectors.values():
        state.selector_id(selector)
    keywords = {
        state.selector_id(selector): selector._spec()
        for selector in tree.selectors.values()
        if isinstance(selector, Keywords)
    }
    state.keywords += 1
    tree.keywords_binding = f"keywords_{state.keywords}"
    compiler._append_source(
        src(
            RelExpr(path=KEYWORDS_ROUTE, context="$input", intent=Text(canonical_json(keywords))),
            name=tree.keywords_binding,
            weight=0.0,
        )
    )
    _place_selectors(compiler, state)


def _place_selectors(compiler: _CandidateCompiler, state: _BranchState) -> None:
    """Emit each LabelModel call whose lowest common scope is the current path."""

    tree = state.tree
    assert tree is not None
    for identity, selector in tree.selectors.items():
        if (
            isinstance(selector, LabelModel)
            and identity not in tree.placed
            and tree.placement(identity) == state.path
        ):
            state.selector_calls += 1
            binding = f"selector_{state.selector_calls}"
            tree.placed[identity] = (state.path, binding)
            compiler._selector_call(selector, binding)


class _Gate:
    """Render one Gate block in the compiler's current scope."""

    def __init__(
        self,
        compiler: _CandidateCompiler,
        state: _BranchState,
        node: BranchNode,
        input_context: str,
        input_dependencies: tuple[str, ...],
        *,
        member: bool = False,
    ) -> None:
        self._compiler = compiler
        self._member = member
        self._state = state
        self._node = node
        self._input = input_context
        self._dependencies = input_dependencies
        state.gates += 1
        self._id = f"gate_{state.gates}"
        self._decision: _ResolvedRecipe | None = None
        self._skip_selection: _SkipSelection | None = None

    def render(self) -> _ResolvedRecipe:
        compiler, node = self._compiler, self._node
        if node.panel is not None:
            self._render_panel(node.panel)
        bodies = {branch: self._body(branch) for branch in ("then", "otherwise")}
        spec = self._spec(bodies)
        visible = _top_level_names(compiler._sources) | _ALWAYS_IN_SCOPE
        after = self._after(visible)
        decide = self._decide(spec)
        sources: list[Node] = [after, decide]
        if self._member:
            # D8: a skip-Gate member's DECIDE sits before the panel (outside the member slot), so
            # the combine call reads it in `selection` without reading a failed slot.
            assert compiler._hoist is not None
            compiler._hoist.extend(sources)
            sources = []
        slots: dict[str, str] = {}
        for branch, body in bodies.items():
            if body.sources:
                self._check_body(body, visible, (after, decide))
                slots[branch] = self._gated(branch, body, sources)
        sources.append(self._join(spec, slots))
        block = f"{self._id}_block"
        compiler._append_source(
            src(
                Expression(sources=tuple(sources), intent=Text(f"${self._id}")),
                name=block,
                weight=0.0,
            )
        )
        then_range, else_range = bodies["then"].calls, bodies["otherwise"].calls
        self._state.ranges[block] = (
            min(then_range[0], else_range[0]),
            max(then_range[1], else_range[1]),
        )
        return self._resolved(bodies)

    def _render_panel(self, panel: FusionNode) -> None:
        """The panel members and the decision call run unconditionally, before the block."""

        compiler = self._compiler
        self._decision = compiler._compile_fusion(panel, self._input, self._dependencies)
        if any(_is_skip_member(member) for member in panel.members):
            # SM-11: a second reducer step skips the same members as the decision call.
            self._skip_selection = _skip_selection(panel, self._decision.members)

    # --- bodies --------------------------------------------------------------------------------

    def _body(self, branch: Literal["then", "otherwise"]) -> _Body:  # noqa: PLR0911
        value = self._node.body(branch)
        if value is None:
            return _Body("skip")
        if isinstance(value, str):
            if value not in WORDS:
                raise ValueError("a gate branch word is 'abstain' or 'fail_closed'")
            return _Body(value)
        if isinstance(value, Reducer):
            if self._decision is None:
                raise ValueError("a step in a gate branch needs a panel")
            if value is self._node.decision_reducer():
                return _Body("step", terminal=self._decision.reference.removeprefix("$"))
            return self._step_body(branch, value)
        return self._recipe_body(branch, value)

    def _step_body(self, branch: str, reducer: Reducer) -> _Body:
        """A reducer step that is not the decision reducer: its own combine call over the same
        panel members, inside the branch body (branch-core D4)."""

        panel, decision = self._node.panel, self._decision
        assert panel is not None and decision is not None
        if any(isinstance(source, Consistency) for source in (panel.signals or {}).values()):
            raise ValueError(
                "a sf.Gate with two reducer steps cannot read sf.Consistency samples in this "
                "version"
            )
        fusion = FusionNode(
            panel.members,
            name=panel.name,
            signals=panel.signals,
            synthesizer=reducer,
            quorum=panel.quorum,
        )
        compiler, skip = self._compiler, self._skip_selection
        start = len(compiler._sources)
        compiler._gated_depth += 1
        decision_node = decision.topology.synthesizer
        if isinstance(panel.synthesizer, LazyDecision) and decision_node is not None:
            compiler._reused_signals = {signal.key: signal for signal in decision_node.signals}
        try:
            resolved = compiler._fusion(
                fusion,
                decision.members,
                input_context=self._input,
                input_dependencies=self._dependencies,
                panel=decision.panel,
                selection=None if skip is None else skip.selection,
                floor=None if skip is None else skip.floor,
            )
        finally:
            compiler._gated_depth -= 1
            compiler._reused_signals = {}
        sources = tuple(compiler._sources[start:])
        del compiler._sources[start:]
        return _Body(
            "step",
            sources=sources,
            reference=resolved.reference,
            terminal=_terminal(resolved.reference),
            resolved=resolved,
            calls=_calls_range(sources, self._state.ranges),
        )

    def _recipe_body(self, branch: str, value: Recipe) -> _Body:
        if isinstance(value, CorrectiveLoop | SelfCorrective):
            raise ValueError(GATE_IN_LOOP)
        compiler, state = self._compiler, self._state
        state.path = (*state.path, (id(self._node), branch))
        start = len(compiler._sources)
        compiler._gated_depth += 1
        try:
            _place_selectors(compiler, state)
            resolved = compiler._recipe(
                value, input_context=self._input, input_dependencies=self._dependencies
            )
        finally:
            compiler._gated_depth -= 1
            state.path = state.path[:-1]
        sources = tuple(compiler._sources[start:])
        del compiler._sources[start:]
        if resolved.selection is not None:
            raise ValueError(
                f"a sf.{resolved.selection} must be followed by sf.Synthesize inside a gate branch"
            )
        return _Body(
            "recipe",
            sources=sources,
            reference=resolved.reference,
            terminal=_terminal(resolved.reference),
            resolved=resolved,
            calls=_calls_range(sources, state.ranges),
        )

    def _gated(self, branch: str, body: _Body, sources: list[Node]) -> str:
        slot = _SLOT_NAMES[branch]
        opener = f"{self._id}_open_{slot}"
        sources.append(
            src(
                RelExpr(path=OPEN_ROUTE, context=f"${self._id}_decide", intent=Text(branch)),
                name=opener,
                weight=0.0,
            )
        )
        assert body.reference is not None
        name = f"{self._id}_{slot}"
        sources.append(
            src(
                iterate(
                    url4_ref(opener),
                    body=body.sources,
                    intent=Text(body.reference),
                    on_error="fail",
                ),
                name=name,
                weight=0.0,
            )
        )
        return f"${name}"

    # --- the endpoint sources -------------------------------------------------------------------

    def _read_selectors(self, reads: dict[str, list[Selector]]) -> dict[str, str]:
        """sel id -> the reply reference of each LabelModel this DECIDE can see (in scope)."""

        tree, state = self._state.tree, self._state
        assert tree is not None
        listed = [self._node.condition.selector, *reads["then"], *reads["otherwise"]]
        replies: dict[str, str] = {}
        for selector in listed:
            if not isinstance(selector, LabelModel):
                continue
            placed = tree.placed.get(selector._identity())
            if placed is not None and state.path[: len(placed[0])] == placed[0]:
                replies[state.selector_id(selector)] = f"${placed[1]}"
        return replies

    @functools.cached_property
    def _selectors(self) -> _Selectors:
        """Computed once, on first use after the bodies render (they place the LabelModels)."""

        reads = {branch: self._reads(branch) for branch in ("then", "otherwise")}
        declared = self._spec_selectors(reads)
        return _Selectors(reads, declared, self._read_selectors(reads), self._keywords(declared))

    def _after(self, visible: frozenset[str] | set[str]) -> Node:
        keywords, replies = self._selectors.keywords, self._selectors.replies
        references: list[str] = []
        if self._decision is not None:
            references.append(self._decision.reference)
        if _REFERENCE.fullmatch(self._input):
            references.append(self._input)
        if keywords is not None:
            references.append(keywords)
        references.extend(replies.values())
        references.extend(f"${node.name}" for node in self._ancestor_sources())
        references = list(dict.fromkeys(references))
        # D10: url4 leaves an unknown $name verbatim with no edge and no error, so DECIDE could run
        # before a call it reads; refuse that at compile time.
        for reference in references:
            if reference.removeprefix("$") not in visible:
                raise ValueError(
                    f"internal error: sf.Gate {self._id} orders after {reference}, "
                    "which is not in scope"
                )
        context = ", ".join(f"r{index}:0.0:{value}" for index, value in enumerate(references, 1))
        return src(
            RelExpr(path=AFTER_ROUTE, context=context, intent=Text("after")),
            name=f"{self._id}_after",
            weight=0.0,
        )

    def _keywords(self, selectors: dict[str, dict[str, object]]) -> str | None:
        """The KEYWORDS source reference, when this Gate reads any selector (D6)."""

        tree = self._state.tree
        if tree is None or tree.keywords_binding is None or not selectors:
            return None
        return f"${tree.keywords_binding}"

    def _decide(self, spec: str) -> Node:
        keywords, replies = self._selectors.keywords, self._selectors.replies
        context: dict[str, object] = {"after": f"${self._id}_after"}
        if keywords is not None:
            context["keywords"] = keywords
        if replies:
            context["selectors"] = replies
        return src(
            RelExpr(
                path=DECIDE_ROUTE,
                context=render(struct(context)),
                intent=Text(spec),
                params=(("gate", self._id),),
            ),
            name=f"{self._id}_decide",
            weight=0.0,
        )

    def _join(self, spec: str, slots: dict[str, str]) -> Node:
        context: dict[str, object] = {"decision": f"${self._id}_decide", **slots}
        return src(
            RelExpr(
                path=JOIN_ROUTE,
                context=render(struct(context)),
                intent=Text(spec),
                params=(("binding", self._id),),
            ),
            name=self._id,
            weight=0.0,
        )

    # --- the spec (gate-spec.v1) ------------------------------------------------------------------

    def _reads(self, branch: Literal["then", "otherwise"]) -> list[Selector]:
        """Every selector a Gate inside this branch's body reads (GU-5, Q18)."""

        return list(_scan(self._node.body(branch)).selectors.values())

    def _spec_selectors(self, reads: dict[str, list[Selector]]) -> dict[str, dict[str, object]]:
        state = self._state
        listed = [
            selector
            for selector in (
                self._node.condition.selector,
                *reads["then"],
                *reads["otherwise"],
            )
            if selector is not None
        ]
        declared: dict[str, dict[str, object]] = {}
        for selector in listed:
            selector_id = state.selector_id(selector)
            binding = None
            if isinstance(selector, LabelModel):
                tree = state.tree
                placed = None if tree is None else tree.placed.get(selector._identity())
                # WHY always placed: the bodies render before the spec, and a body places the
                # LabelModels of its own scope first.
                assert placed is not None
                binding = placed[1]
            entry: dict[str, object] = {
                "kind": "keywords" if isinstance(selector, Keywords) else "label_model",
                "multi": selector.multi,
                "labels": list(selector.labels),
                "binding": binding,
            }
            if isinstance(selector, Keywords):
                # WHY repeated here: the url4 decode rebuilds the selector from the spec alone.
                entry["rules"] = selector._spec()["rules"]
            declared[selector_id] = entry
        return declared

    def _when(self) -> dict[str, object]:
        condition = self._node.condition
        observe = condition.observe
        if condition.selector is not None:
            observe = f"{observe}:{self._state.selector_id(condition.selector)}"
        if observe.startswith("budget.remaining:"):
            observe = f"budget.remaining:{self._budget_unit(observe.partition(':')[2])}"
        return {"observe": observe, "cmp": condition.cmp, "value": condition.value}

    def _budget_unit(self, unit: str) -> str:
        budget = self._compiler._budget
        if budget is None:
            raise ValueError(
                "sf.budget.remaining() needs sf.Budgeted(...) on the candidate"
            )  # BU-12
        units = budget.units()
        if not unit:
            if len(units) != 1:
                raise ValueError("name the unit: sf.budget.remaining('usd') or ('tokens')")  # BU-13
            return units[0]
        if unit not in units:
            raise ValueError(f"sf.budget.remaining({unit!r}) reads a unit the sf.Budgeted lacks")
        return unit

    def _estimate(self) -> dict[str, object]:
        """BU-14: each branch's sf.Estimate, in units the candidate's Budget declares."""

        budget = self._compiler._budget
        estimates = dict(zip(("then", "otherwise"), self._node.estimates, strict=True))
        for estimate in estimates.values():
            if estimate is None:
                continue
            if budget is None:
                raise ValueError("sf.Estimate needs sf.Budgeted(...) on the candidate")
            for unit in estimate:
                if unit not in budget.units():
                    declared = " and ".join(budget.units())
                    raise ValueError(
                        f"sf.Estimate names {unit}, but sf.Budgeted declares only {declared}"
                    )
        return {
            branch: None if value is None else dict(value) for branch, value in estimates.items()
        }

    def _ancestor_sources(self) -> list[Source]:
        """D7 with D10: under a Budget, the named sources in the enclosing scopes that hold a model
        call. AFTER references each one, so every call whose charge DECIDE folds is upstream of
        DECIDE, and the spend it sees is the same on every run and on replay (BU-8)."""

        if self._compiler._budget is None:
            return []
        return [
            node
            for node in self._compiler._sources
            if isinstance(node, Source)
            and node.name is not None
            and any(_model_call(child) for child in _deep(node))
        ]

    def _ancestors(self) -> list[object]:
        """D7: the fingerprints of the calls upstream of DECIDE whose charges the fold counts."""

        found: list[object] = []
        for node in self._ancestor_sources():
            for child in _deep(node):
                if isinstance(child, RelExpr) and _model_call(child):
                    params = sorted(
                        (key, value) for key, value in child.params if isinstance(value, str)
                    )
                    found.append([child.path, [list(pair) for pair in params]])
        return found

    def _spec(self, bodies: dict[str, _Body]) -> str:
        then, otherwise = bodies["then"], bodies["otherwise"]
        state, reads = self._state, self._selectors.reads
        spec = {
            "schema": GATE_SPEC_SCHEMA,
            "kind": "panel" if self._node.panel is not None else "input",
            "when": self._when(),
            "then": then.kind,
            "otherwise": otherwise.kind,
            "panel": (
                None
                if self._decision is None
                else {"binding": self._decision.reference.removeprefix("$")}
            ),
            "calls": {
                "then": {"min": then.calls[0], "max": then.calls[1]},
                "otherwise": {"min": otherwise.calls[0], "max": otherwise.calls[1]},
            },
            "selectors": self._selectors.declared,
            "reads": {
                branch: [state.selector_id(selector) for selector in reads[branch]]
                for branch in ("then", "otherwise")
            },
            "estimate": self._estimate(),
            "ancestors": self._ancestors(),
            "terminal": {"then": then.terminal, "otherwise": otherwise.terminal},
        }
        # WHY canonical_json: the spec rides in a url4 intent, which rewrites a raw ``$name``.
        return canonical_json(spec)

    # --- result -------------------------------------------------------------------------------

    def _check_body(
        self, body: _Body, visible: frozenset[str] | set[str], own: Sequence[Node]
    ) -> None:
        """D5: a body reads only bindings that run unconditionally in an enclosing scope."""

        defined = _defined_names(body.sources)
        outer = {name for node in body.sources for name in _all_references(node)} - defined
        unknown = sorted(outer - set(visible))
        if unknown:
            raise ValueError(
                f"internal error: a body of sf.Gate {self._id} reads {unknown[0]!r}, which no "
                "enclosing scope defines"
            )
        unconditional = {
            name for node in (*self._compiler._sources, *own) for name in _eager_references(node)
        }
        hidden = sorted(
            name
            for name in outer & _model_call_names(self._compiler._sources)
            if name not in unconditional
        )
        if hidden:
            raise ValueError(
                f"internal error: a body of sf.Gate {self._id} reads the model call {hidden[0]!r}, "
                "which only that body needs; it would run on every Case"
            )

    def _resolved(self, bodies: dict[str, _Body]) -> _ResolvedRecipe:
        from screamingface._evaluation.candidate import _ordered_unique, _ResolvedRecipe

        node = self._node
        decision = self._decision
        recipes = [body.resolved for body in bodies.values() if body.resolved is not None]
        operation_id = f"op_{self._id}"
        depends_on = tuple(
            dict.fromkeys(
                (
                    *self._dependencies,
                    *(() if decision is None else (decision.operation_id,)),
                    *(
                        f"op_{body.terminal}"
                        for body in bodies.values()
                        if body.resolved is not None
                    ),
                )
            )
        )
        self._compiler._append_operation(
            _compiled_operation(
                id=operation_id, kind="gate", label=f"{node.name} gate", depends_on=depends_on
            )
        )
        models = _ordered_unique(
            (
                *(() if decision is None else decision.models),
                *(model for recipe in recipes for model in recipe.models),
                *self._selector_models(),
            )
        )
        topology = _RecipeTopology(
            kind="gate",
            name=node.name,
            binding=f"{self._id}_block",
            panel=None if decision is None else decision.topology,
            then_branch=_branch_topology(bodies["then"]),
            otherwise_branch=_branch_topology(bodies["otherwise"]),
            selectors=self._selector_topology(),
        )
        return _ResolvedRecipe(
            reference=f"${self._id}_block",
            operation_id=operation_id,
            name=node.name,
            kind="gate",
            models=models,
            topology=topology,
            calls=(
                *(() if decision is None else decision.calls),
                *(call for recipe in recipes for call in recipe.calls),
            ),
        )

    @functools.cached_property
    def _listed(self) -> frozenset[str]:
        """The LabelModels this Gate lists: only a tree root lists any, so a nested Gate's models
        are its bodies' alone; each root of a skip-member Fanout lists the ones it reads that no
        earlier member listed."""

        tree = self._state.tree
        if tree is None or self._state.depth != 1:
            return frozenset()
        listed = frozenset(_scan(self._node).selectors) - tree.listed
        tree.listed |= listed
        return listed

    def _selector_models(self) -> tuple[str, ...]:
        """The LabelModel routes this Gate decides with, as in ``_selector_topology``."""

        tree = self._state.tree
        if tree is None:
            return ()
        return tuple(
            selector.model.model
            for identity, selector in tree.selectors.items()
            if isinstance(selector, LabelModel) and identity in self._listed
        )

    def _selector_topology(self) -> tuple[_RecipeTopology, ...]:
        """The LabelModel calls this Gate lists (``_listed``)."""

        tree = self._state.tree
        if tree is None:
            return ()
        return tuple(
            _RecipeTopology(kind="model", name="label model", binding=binding, role="selector")
            for identity, (_, binding) in tree.placed.items()
            if identity in self._listed
        )


def _branch_topology(body: _Body) -> _RecipeTopology | _BranchWord:
    """A body that compiles sources (a recipe, or a step with its own combine call) keeps its
    topology; the decision call's own step slot and a word are the spec word."""

    if body.resolved is not None:
        return body.resolved.topology
    assert body.kind != "recipe"
    return body.kind


def _terminal(reference: str) -> str:
    """The binding whose recorded result JOIN copies: an inner Gate block names its JOIN."""

    return gate_join(reference.removeprefix("$"))


def _calls_range(nodes: Sequence[Node], ranges: dict[str, _Range]) -> _Range:
    """The model-call leaves on the shortest and longest path through ``nodes`` (ans:Q22)."""

    low = high = 0
    for node in nodes:
        if not isinstance(node, Source):
            continue
        value = node.value
        if _model_call(value):
            low, high = low + 1, high + 1
        elif isinstance(value, Expression):
            inner = ranges.get(node.name or "")
            if inner is None:
                inner = _calls_range(value.sources, ranges)
            low, high = low + inner[0], high + inner[1]
    return low, high


def _top_level_names(nodes: Sequence[Node]) -> set[str]:
    return {node.name for node in nodes if isinstance(node, Source) and node.name is not None}


def _deep(node: Node) -> Iterator[Node]:
    """``walk`` that also enters each gated iterate body, parsed as the text MapNode spawns (the
    Engine's ``parsed_iterate_body`` rule)."""

    for child in walk(node):
        yield child
        if isinstance(child, Iteration):
            body = f"({child.body})!{child.intent}" if child.intent else f"({child.body})"
            yield from _deep(build(body))


def _model_call(node: object) -> bool:
    return isinstance(node, RelExpr) and not node.path.startswith(_ENSEMBLE)


def _defined_names(nodes: Sequence[Node]) -> set[str]:
    """Every name bound anywhere inside ``nodes``, gated bodies included."""

    return {
        child.name
        for node in nodes
        for child in _deep(node)
        if isinstance(child, Source) and child.name is not None
    }


def _all_references(node: Node) -> Iterator[str]:
    """Every ``$name`` a source reads, gated bodies included: they are eager deps of the iterate
    that holds them (D5)."""

    for child in _deep(node):
        yield from _reads(child)
        if isinstance(child, Iteration) and child.intent:
            yield from _REFERENCE.findall(child.intent)


def _eager_references(node: Node) -> Iterator[str]:
    """The ``$name`` reads of a source outside every gated body (its unconditional reads)."""

    for child in walk(node):
        yield from _reads(child)


def _reads(node: Node) -> Iterator[str]:
    if isinstance(node, RelExpr):
        yield from _REFERENCE.findall(node.context or "")
        if isinstance(node.intent, Text):
            yield from _REFERENCE.findall(node.intent.value)
    elif isinstance(node, Expression) and isinstance(node.intent, Text):
        yield from _REFERENCE.findall(node.intent.value)
    elif isinstance(node, VarRef):
        yield node.name
    elif isinstance(node, StructObject):
        yield from _REFERENCE.findall(node.raw)


def _model_call_names(nodes: Sequence[Node]) -> set[str]:
    return {
        node.name
        for node in nodes
        if isinstance(node, Source) and node.name is not None and _model_call(node.value)
    }


__all__: list[str] = []

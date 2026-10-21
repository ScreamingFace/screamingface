"""The chain of the map → select → reduce surface: ``>>``, ``Pipeline`` and the block record.

FEATURE (E4b surface, surface §2): ``a >> b`` is ``Pipeline([a, b])``. A chain is read left to
right. A ``Fanout`` opens a block, and a reducer or ``Synthesize`` closes it. A closed block is one
``_Block`` record that holds its lowered node, so every rule of today's Fusion raises at the ``>>``
that closes the block (CH-9).
INVARIANT: ``lower()`` (``lowering.py``) is the only way from a chain to the compiler; a lowered
chain holds only recipes (D7-2: one ``Pipeline`` class, ``S/pipeline.py`` re-exports it).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from screamingface.recipe import (
    OPTIONAL_MEMBERS_ONLY,
    Recipe,
    _Chainable,
    _name,
    _optional,
    _recipe,
)
from screamingface.reducer import MAX_NARROW_STEPS  # O10: a bound for the spec and evidence

if TYPE_CHECKING:
    from screamingface._surface.fanout import Fanout

type _Category = Literal["map", "score", "narrow", "reduce", "write"]

# The rule messages that more than one place raises (surface §2.2).
OPEN_BLOCK = "the chain ends inside a sf.Fanout block: add a reducer or sf.Synthesize"  # CH-8
_NEEDS_TERMINAL = (  # CH-2
    "a sf.Fanout block needs a reducer or sf.Synthesize before the next stage"
)
_NAMED_OPEN = (  # CH-14
    "a named sf.Pipeline groups its stages, so close the sf.Fanout block inside it"
)
_SELECTION_GOES_ON = (  # CH-5
    "a selection goes to sf.Synthesize, a reducer, or another narrow step"
)
_ONE_JUDGE = (  # CH-3
    "a block takes one judge: sf.Judge and sf.JudgePick use the same judge signal"
)
# The step categories that close a block (surface §1).
_TERMINALS: frozenset[str] = frozenset({"reduce", "write"})


class Step(_Chainable):
    """A chain value that is not a recipe: ``Fanout`` and every step that can follow it."""

    __slots__ = ()

    _category: ClassVar[_Category]
    # Concat: only sf.Synthesize can follow it (CH-7).
    _needs_writer: ClassVar[bool] = False
    # Judge, JudgePick: the step writes the block's one judge signal (CH-3, O9).
    _writes_judge_signal: ClassVar[bool] = False

    def _recipes(self) -> tuple[Recipe, ...]:
        """The recipes this step holds as the user wrote them (members, a writer recipe)."""

        return ()

    def _reads_judge(self) -> bool:
        """Whether this step reads ``score:judge``, which only a ``sf.Judge`` step writes."""

        return False

    def _sees_every_member(self) -> bool:
        """Whether this step makes its own model call over every member (NR-C1, O11): Merge,
        JudgePick, and a Gate whose fallback is a model."""

        return False

    def __repr__(self) -> str:
        # WHY lazy: render.py imports every step module (rebuild-display §2)
        from screamingface._surface.render import render

        return render(self)


def refuse_step(value: object) -> None:
    """Refuse a step or an open chain in a place that takes a recipe (CH-8, CH-11).

    WHY here: ``S/recipe.py`` calls it from ``_recipe``, so every recipe position of today
    (a Fusion member, a Pipeline stage, a CorrectiveLoop member or judge) and of the new surface
    (a Fanout member, a Synthesize model, a chain stage) gives the same message.
    """

    if isinstance(value, Step):
        if value._category == "map":
            raise ValueError(OPEN_BLOCK)
        raise TypeError(
            f"sf.{type(value).__name__} is a step, not a recipe: put it after a sf.Fanout"
        )
    if isinstance(value, Pipeline) and value._open:
        raise ValueError(OPEN_BLOCK)


@dataclass(frozen=True, slots=True, init=False)
class _Block:
    """One closed block: ``Fanout``, at most one judge, 0–4 narrow steps, one terminal step.

    ``node`` is the lowered value (lowering §2.2). It is built here, after the block rules, so a
    bad block raises at the ``>>`` that closes it (CH-9).
    """

    fanout: Fanout
    judge: Step | None
    narrow: tuple[Step, ...]
    terminal: Step
    node: Recipe

    def __init__(
        self,
        fanout: Fanout,
        terminal: Step,
        *,
        judge: Step | None = None,
        narrow: tuple[Step, ...] = (),
    ) -> None:
        object.__setattr__(self, "fanout", fanout)
        object.__setattr__(self, "judge", judge)
        object.__setattr__(self, "narrow", narrow)
        object.__setattr__(self, "terminal", terminal)
        _check_block(judge, narrow, terminal)
        # WHY lazy: lowering.py imports this module
        from screamingface._surface.lowering import block_node

        object.__setattr__(self, "node", block_node(self))

    @property
    def name(self) -> str:
        """The name of the lowered value: it goes into the topology bytes (surface §2.1, NM-1)."""

        return self.node.name

    def _recipes(self) -> tuple[Recipe, ...]:
        return (*self.fanout._recipes(), *self.terminal._recipes())

    __hash__: ClassVar[Any] = None


def _check_block(judge: Step | None, narrow: tuple[Step, ...], terminal: Step) -> None:
    """The rules of a whole block, checked when it closes (surface §2.2)."""

    if judge is not None and terminal._writes_judge_signal:
        raise ValueError(_ONE_JUDGE)  # CH-3
    if narrow and terminal._sees_every_member():
        raise ValueError(  # NR-C1 (O11): the step would see the members the narrow step left out
            f"sf.{type(terminal).__name__} makes its own call over every member, so it cannot "
            "follow a narrow step"
        )
    reads = any(step._reads_judge() for step in (*narrow, terminal))
    if judge is not None and not reads:
        raise ValueError("sf.Judge scores the members, but no step reads score:judge")  # CH-10
    if judge is None and reads:
        raise ValueError("score:judge needs sf.Judge(...) after sf.Fanout")  # CH-10


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Pipeline(Recipe):
    """Pass one input through an ordered chain of stages and blocks; ``a >> b`` builds one.

    A stage is a route string, a recipe, or a closed block: ``Fanout``, then a reducer or
    ``Synthesize``. An unnamed nested ``Pipeline`` is flattened; a named one keeps its grouping
    and must not end inside a block (CH-14). A chain that ends inside a block is a valid value, so
    ``>>`` can build it step by step, but the compile refuses it (CH-8). ``optional=True`` is for
    a chain that is a ``Fanout`` member.
    """

    name: str
    optional: bool
    steps: tuple[Recipe | Step, ...]
    _is_named: bool = field(repr=False)
    _stages: tuple[Recipe | _Block, ...] = field(compare=False, repr=False)
    _open: tuple[Step, ...] = field(compare=False, repr=False)

    def __init__(
        self,
        steps: Sequence[str | Recipe | Step],
        *,
        name: str | None = None,
        optional: bool = False,
    ) -> None:
        object.__setattr__(self, "optional", _optional(optional))
        chain = _Chain()
        for item in _items(steps):
            chain.add(item)
        if not chain.steps:
            raise ValueError("a Pipeline requires at least one stage")
        if name is not None and chain.open:
            raise ValueError(_NAMED_OPEN)
        object.__setattr__(
            self, "name", chain.name() if name is None else _name(name, "pipeline name")
        )
        object.__setattr__(self, "steps", tuple(chain.steps))
        object.__setattr__(self, "_is_named", name is not None)
        object.__setattr__(self, "_stages", tuple(chain.stages))
        object.__setattr__(self, "_open", tuple(chain.open))

    @property
    def _recipe_marker(self) -> None:
        return None

    def __repr__(self) -> str:
        # WHY lazy: render.py imports this module
        from screamingface._surface.render import render

        return render(self)

    def _repr_html_(self) -> str:
        """The block card for a chain of one closed block, else the chain card (DS-1)."""

        from screamingface._ui.cards import block_card_html, chain_card_html

        (first, *rest) = self._stages or (None,)
        if not rest and isinstance(first, _Block) and not self._is_named and not self._open:
            return block_card_html(first)
        return chain_card_html(self)

    def _stage_values(self) -> tuple[Recipe, ...]:
        """The stages as the user wrote them, a closed block as its node: one value per stage.

        The judge-writer warning numbers these, so its stage numbers are the user's (WJ-1).
        """

        # INVARIANT: an open chain is never read as stages (CH-8 refuses it at the compile).
        assert not self._open, "an open chain has no stages"
        return tuple(stage.node if isinstance(stage, _Block) else stage for stage in self._stages)

    def _block_pipelines(self) -> tuple[Pipeline, ...]:
        """The lowered values of the blocks that lower to two stages, ``Pipeline([FusionNode,
        writer])``: a judge and a writer inside one block (WJ-1, erratum E6)."""

        return tuple(
            stage.node
            for stage in self._stages
            if isinstance(stage, _Block) and isinstance(stage.node, Pipeline)
        )

    def _held_recipes(self) -> tuple[Recipe, ...]:
        """The recipes this chain holds as the user wrote them: its recipe stages, and the members
        and writer recipes of its blocks."""

        return tuple(
            recipe
            for stage in self._stages
            for recipe in (stage._recipes() if isinstance(stage, _Block) else (stage,))
        )

    __hash__: ClassVar[Any] = None


class _Chain:
    """The left-to-right reader of one chain: closed stages, then the open block, if any."""

    def __init__(self) -> None:
        self.steps: list[Recipe | Step] = []
        self.stages: list[Recipe | _Block] = []
        self.open: list[Step] = []

    def add(self, item: str | Recipe | Step) -> None:
        if isinstance(item, Pipeline) and not item._is_named:
            self._flatten(item)
        elif isinstance(item, Step):
            self.steps.append(item)
            self._add_step(item)
        else:
            recipe = _recipe(item, "Pipeline stage")
            self.steps.append(recipe)
            self._add_stage(recipe)

    def _flatten(self, item: Pipeline) -> None:
        """An unnamed nested Pipeline is flattened, so both spellings give equal chains. Its
        closed blocks are taken as they are, and its open block continues here."""

        if item.optional:
            raise ValueError(OPTIONAL_MEMBERS_ONLY)
        self.steps.extend(item.steps)
        for stage in item._stages:
            self._add_stage(stage)
        for step in item._open:
            self._add_step(step)

    def name(self) -> str:
        """The inferred name: the stage names joined by ``->`` (an open block adds its Fanout)."""

        names = [stage.name for stage in self.stages]
        if self.open:
            names.append(cast("Fanout", self.open[0]).name)
        return "->".join(names)

    def _add_stage(self, stage: Recipe | _Block) -> None:
        if self.open:
            _check_next(self.open, "recipe")
        self.stages.append(stage)

    def _add_step(self, step: Step) -> None:
        if not self.open:
            if step._category != "map":
                raise ValueError(f"sf.{type(step).__name__} needs a sf.Fanout before it")  # CH-1
            self.open.append(step)
            return
        _check_next(self.open, step._category)
        if step._category not in _TERMINALS:
            self.open.append(step)
            return
        self.stages.append(_closed(self.open, step))
        self.open.clear()


def _check_next(open_block: list[Step], category: str) -> None:
    """Refuse a step or a recipe that cannot come next in an open block (CH-2..CH-7)."""

    if open_block[-1]._needs_writer and category != "write":
        raise ValueError("sf.Concat must be followed by sf.Synthesize")  # CH-7
    narrowed = sum(step._category == "narrow" for step in open_block)
    if category in ("map", "recipe"):
        raise ValueError(_SELECTION_GOES_ON if narrowed else _NEEDS_TERMINAL)  # CH-5, CH-2
    if category == "score" and len(open_block) > 1:
        # A judge comes once, right after the Fanout: CH-6 after a narrow step, else CH-3.
        raise ValueError("sf.Judge comes right after sf.Fanout" if narrowed else _ONE_JUDGE)
    if category == "narrow" and narrowed == MAX_NARROW_STEPS:
        raise ValueError(f"a block takes at most {MAX_NARROW_STEPS} narrow steps")  # CH-4


def _closed(open_block: list[Step], terminal: Step) -> _Block:
    """The block record of an open block and the step that closes it."""

    rest = open_block[1:]
    judge = next((step for step in rest if step._category == "score"), None)
    narrow = tuple(step for step in rest if step._category == "narrow")
    return _Block(cast("Fanout", open_block[0]), terminal, judge=judge, narrow=narrow)


def _items(values: object) -> Sequence[str | Recipe | Step]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("Pipeline stages must be an ordered sequence of model routes or Recipes")
    return cast("Sequence[str | Recipe | Step]", values)


__all__ = ["Pipeline", "Step"]

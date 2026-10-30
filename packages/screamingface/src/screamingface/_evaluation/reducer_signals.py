"""Compile the model calls a reducer reads besides its members (OME-1289).

A signal is one extra model call whose reply the combine call receives as
``context.signals[key]``. This module is the one place that turns a reducer's
``_ModelSignal`` values (``plan.signal_calls``) into url4 sources, operations and topology nodes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from url4 import RelExpr, Text, src

from screamingface._evaluation.candidate import (
    _canonical_model,
    _fusion_context,
    _model_route,
    _ResolvedRecipe,
    _url4_text,
)
from screamingface._evaluation.combine_spec import combine_spec_text
from screamingface._evaluation.model import _compiled_operation
from screamingface._evaluation.policy import resolved_params
from screamingface._evaluation.topology import (
    _operation_shape,
    _RecipeTopology,
    _signal_role,
    _SignalRole,
    _SignalTopology,
    _writer_field,
)
from screamingface._operation_bindings import OPERATION_BINDING_PARAM
from screamingface.fusion import FusionNode
from screamingface.judge import panel_judge_signal
from screamingface.reducer import (
    Reducer,
    _cannot_rebuild,
    _ModelSignal,
    _ReducerPlan,
    _require_steps,
    _spec_steps,
    _Step,
    _Steps,
)

if TYPE_CHECKING:
    from screamingface._evaluation.candidate import _CandidateCompiler


@dataclass(frozen=True, slots=True, init=False)
class _ProjectionReducer(Reducer):
    """The internal reducer of a projection call: one field's values, by member, as JSON.

    A writer model reads this call's output and nothing else, so it sees only the values of the
    field it writes (PM-6). It is never a user's Fusion synthesizer. A url4 holds it only as the
    projection of a writer, and ``_from_spec`` reads its field back.
    """

    name: str
    field: str

    def __init__(self, field: str) -> None:
        object.__setattr__(self, "name", "project")
        object.__setattr__(self, "field", field)

    def _plan(self) -> _ReducerPlan:
        steps = _Steps(
            extract=_Step("json_object"),
            reduce=_Step("project_field", {"field": self.field}),
            select=_Step("built"),
        )
        return _ReducerPlan("project", "projection", steps)

    @classmethod
    def _from_spec(cls, spec: Mapping[str, object]) -> _ProjectionReducer:
        """The projection a decoded spec is: exactly the steps this class writes, else refuse."""

        reduce = _spec_steps(spec)["reduce"]
        field = None if reduce is None else reduce[1].get("field")
        if spec["reducer"] != "project" or not isinstance(field, str):
            raise _cannot_rebuild("project")
        projection = cls(field)
        _require_steps(spec, projection._plan().steps, "project")
        return projection


@dataclass(frozen=True, slots=True)
class _CompiledSignals:
    references: Mapping[str, str]  # key -> "$binding", in the reducer's declared order
    topology: tuple[_SignalTopology, ...]
    operation_ids: tuple[str, ...]  # operation ids of the signal SOURCES (the model calls)
    models: tuple[str, ...]


def _compile_signals(
    compiler: _CandidateCompiler,
    fusion: FusionNode,
    plan: _ReducerPlan,
    members: tuple[_ResolvedRecipe, ...],
    *,
    input_context: str,
    dependencies: tuple[str, ...],
    panel: str | None = None,
) -> _CompiledSignals:
    """Attach one source per signal, in declared order, and describe them for the combine call.

    With a quorum ``panel`` the signal calls read the panel too, and a judge gets the panel form
    of its template, which says the members arrive as rows.
    """

    signals = plan.signal_calls
    if not signals:
        return _CompiledSignals(MappingProxyType({}), (), (), ())
    # INVARIANT (narrow.md §6): the plan of a whole combine call (``Reducer._combine_plan``) lists
    # each key once, so a judge that a narrow step and the main step both read is ONE call here.
    assert len({signal.key for signal in signals}) == len(signals)
    roles: list[_SignalRole] = [_signal_call_role(signal) for signal in signals]
    # INVARIANT: _reducer_synthesizer refuses a reducer without a catalog before it reaches here.
    operators = compiler._operators
    assert operators is not None
    # WHY first: a catalog without a projection operator fails before any source is appended.
    projections = {
        signal.key: combine_spec_text(
            _ProjectionReducer(signal.field), member_count=len(members), operators=operators
        )
        for signal in signals
        if signal.field is not None
    }
    # WHY no signals in the signal calls' own context: a signal reads the members, not itself.
    context = _fusion_context(input_context, members, panel=panel)
    references: dict[str, str] = {}
    topology: list[_SignalTopology] = []
    operation_ids: list[str] = []
    models: list[str] = []
    for signal, role in zip(signals, roles, strict=True):
        route = _canonical_model(signal.model)
        feed, feed_dependencies, projection = context, dependencies, None
        if signal.field is not None:
            projection = _projection_source(
                compiler,
                fusion,
                signal,
                spec_text=projections[signal.key],
                context=context,
                dependencies=dependencies,
            )
            # PM-6: the writer reads this one call and nothing else.
            feed, feed_dependencies = f"${projection.binding}", (f"op_{projection.binding}",)
        source = _model_signal_source(
            compiler,
            fusion,
            signal if panel is None or role != "judge" else panel_judge_signal(signal),
            route=route,
            role=role,
            context=feed,
            dependencies=feed_dependencies,
        )
        references[signal.key] = f"${source.binding}"
        topology.append(_SignalTopology(signal.key, source, projection))
        operation_ids.append(f"op_{source.binding}")
        models.append(route)
    return _CompiledSignals(
        references=MappingProxyType(references),
        topology=tuple(topology),
        operation_ids=tuple(operation_ids),
        models=tuple(models),
    )


def _signal_call_role(signal: _ModelSignal) -> _SignalRole:
    """The role of a signal's model call; refuse a signal whose key and field disagree.

    INVARIANT (FC-I3): a signal names a projection field exactly when its key is the
    ``writer_<field>`` key of that field. A judge, a fallback judge and a fallback writer have
    no field. The projection and the url4 recovery both rely on it.
    """

    role = _signal_role(signal.key)
    if role is None:
        raise ValueError("unsupported reducer signal")
    if _writer_field(signal.key) != signal.field:
        raise ValueError("reducer signal key does not match its field")
    return role


def _projection_source(
    compiler: _CandidateCompiler,
    fusion: FusionNode,
    signal: _ModelSignal,
    *,
    spec_text: str,
    context: str,
    dependencies: tuple[str, ...],
) -> _RecipeTopology:
    """The combine call that hands one writer the values of its field: source and operation."""

    binding = compiler._next_binding("synthesis")
    node = _RecipeTopology(kind="reducer", name="project", binding=binding)
    kind, suffix = _operation_shape(node, signal.key)
    assert kind == "combine"
    compiler._append_combine(
        binding=binding,
        operation_id=f"op_{binding}",
        context=context,
        spec_text=spec_text,
        label=f"{fusion.name} {suffix}",
        depends_on=dependencies,
    )
    return node


def _model_signal_source(
    compiler: _CandidateCompiler,
    fusion: FusionNode,
    signal: _ModelSignal,
    *,
    route: str,
    role: _SignalRole,
    context: str,
    dependencies: tuple[str, ...],
) -> _RecipeTopology:
    """One signal model call: its source, its operation and its parameter assignment."""

    binding = compiler._next_binding(role)
    # WHY the binding param first: the Engine attributes an operation's output by the call's
    # (path, params) fingerprint, so this keeps the call apart from a member on the same route.
    compiler._append_source(
        src(
            RelExpr(
                path=_model_route(route),
                context=context,
                intent=Text(_url4_text(signal.prompt)),
                params=((OPERATION_BINDING_PARAM, binding), *resolved_params(signal.params)),
            ),
            name=binding,
            weight=0.0,
        )
    )
    node = _RecipeTopology(kind="model", name=route.rsplit("/", 1)[-1], binding=binding, role=role)
    kind, suffix = _operation_shape(node, signal.key)
    compiler._append_operation(
        _compiled_operation(
            id=f"op_{binding}",
            kind=kind,
            label=f"{fusion.name} {suffix}",
            depends_on=dependencies,
        )
    )
    compiler._record_parameter_assignment(f"op_{binding}", route, signal.params)
    return node


__all__: list[str] = []

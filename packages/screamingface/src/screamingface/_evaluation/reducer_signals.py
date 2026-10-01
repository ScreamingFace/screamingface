"""Compile the model calls a reducer reads besides its members (OME-1289).

A signal is one extra model call whose reply the combine call receives as
``context.signals[key]``. This module is the one place that turns a reducer's
``_ModelSignal`` values into url4 sources, operations and topology nodes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from url4 import RelExpr, Text, src

from screamingface._evaluation.candidate import (
    _canonical_model,
    _fusion_context,
    _model_route,
    _ResolvedRecipe,
    _url4_text,
)
from screamingface._evaluation.model import _compiled_operation
from screamingface._evaluation.policy import resolved_params
from screamingface._evaluation.topology import _operation_shape, _RecipeTopology, _SignalTopology
from screamingface.fusion import Fusion
from screamingface.reducer import Reducer, _ModelSignal

if TYPE_CHECKING:
    from screamingface._evaluation.candidate import _CandidateCompiler


@dataclass(frozen=True, slots=True)
class _CompiledSignals:
    references: Mapping[str, str]  # key -> "$binding", in the reducer's declared order
    topology: tuple[_SignalTopology, ...]
    operation_ids: tuple[str, ...]  # operation ids of the signal SOURCES (the model calls)
    models: tuple[str, ...]


def _compile_signals(
    compiler: _CandidateCompiler,
    fusion: Fusion,
    reducer: Reducer,
    members: tuple[_ResolvedRecipe, ...],
    *,
    input_context: str,
    dependencies: tuple[str, ...],
) -> _CompiledSignals:
    """Attach one source per signal, in declared order, and describe them for the combine call."""

    # WHY no signals in the signal calls' own context: a signal reads the members, not itself.
    context = _fusion_context(input_context, members)
    references: dict[str, str] = {}
    topology: list[_SignalTopology] = []
    operation_ids: list[str] = []
    models: list[str] = []
    for signal in reducer._signals():
        if signal.key != "judge":
            raise ValueError("unsupported reducer signal")
        source = _model_signal_source(
            compiler,
            fusion,
            signal,
            role="judge",
            context=context,
            dependencies=dependencies,
        )
        references[signal.key] = f"${source.binding}"
        topology.append(_SignalTopology(signal.key, source))
        operation_ids.append(f"op_{source.binding}")
        models.append(_canonical_model(signal.model))
    return _CompiledSignals(
        references=MappingProxyType(references),
        topology=tuple(topology),
        operation_ids=tuple(operation_ids),
        models=tuple(models),
    )


def _model_signal_source(
    compiler: _CandidateCompiler,
    fusion: Fusion,
    signal: _ModelSignal,
    *,
    role: Literal["judge"],
    context: str,
    dependencies: tuple[str, ...],
) -> _RecipeTopology:
    """One signal model call: its source, its operation and its parameter assignment."""

    binding = compiler._next_binding(role)
    route = _canonical_model(signal.model)
    # WHY the binding param first: the Engine attributes an operation's output by the call's
    # (path, params) fingerprint, so this keeps the call apart from a member on the same route.
    compiler._append_source(
        src(
            RelExpr(
                path=_model_route(route),
                context=context,
                intent=Text(_url4_text(signal.prompt)),
                params=(("binding", binding), *resolved_params(signal.params)),
            ),
            name=binding,
            weight=0.0,
        )
    )
    node = _RecipeTopology(kind="model", name=route.rsplit("/", 1)[-1], binding=binding, role=role)
    kind, suffix = _operation_shape(node)
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

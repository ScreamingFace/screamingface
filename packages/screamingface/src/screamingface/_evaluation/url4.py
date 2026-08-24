"""Replay one complete ScreamingFace evaluation URL4 without recompiling it."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from url4 import Expression, Source, Text, build

from screamingface._core.ports import AsyncRunTransport, SyncRunTransport
from screamingface._evaluation.model import (
    Candidate,
    _canonical_url4,
    _compiled_candidate,
    _compiled_operation,
    _member_projection,
)
from screamingface._evaluation.results import report_from_url4_outcome
from screamingface._evaluation.topology import (
    _RecipeTopology,
    _topology_bindings,
    _topology_from_expression,
)
from screamingface.events import Event
from screamingface.report import Report
from screamingface.url4 import _calls as _url4_calls
from screamingface.url4 import _validate_topology


def evaluate_url4_sync(
    transport: SyncRunTransport,
    url4: str,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
) -> Report:
    """Execute one already-linked evaluation expression unchanged."""

    from screamingface._evaluation.runner import (
        _abort_event_observer,
        _evaluation_options,
        _reconcile_event_observer,
        _sync_event_observer,
    )

    _evaluation_options(on_event, progress)
    candidate = _candidate_from_url4(url4)
    observer = _sync_event_observer(
        on_event,
        progress,
        (candidate,),
        None,
        "URL4 replay",
    )
    try:
        bound = None if observer is None else observer.bind(candidate)
        outcome = transport.run(candidate, bound)
        report = report_from_url4_outcome(candidate, outcome)
    except BaseException as exc:
        _abort_event_observer(observer, exc)
        raise
    _reconcile_event_observer(observer, report)
    return report


async def evaluate_url4_async(
    transport: AsyncRunTransport,
    url4: str,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
) -> Report:
    """Asynchronously execute one already-linked evaluation expression unchanged."""

    from screamingface._evaluation.runner import (
        _abort_event_observer,
        _async_event_observer,
        _evaluation_options,
        _reconcile_event_observer,
    )

    _evaluation_options(on_event, progress)
    candidate = _candidate_from_url4(url4)
    observer = _async_event_observer(
        on_event,
        progress,
        (candidate,),
        None,
        "URL4 replay",
    )
    try:
        bound = None if observer is None else observer.bind(candidate)
        outcome = await transport.run(candidate, bound)
        report = report_from_url4_outcome(candidate, outcome)
    except BaseException as exc:
        _abort_event_observer(observer, exc)
        raise
    _reconcile_event_observer(observer, report)
    return report


def _candidate_from_url4(value: str) -> Candidate:
    """Recover the Candidate projection embedded by the ScreamingFace linker.

    The benchmark owns the outer expression. Its zero-weight ``candidate`` binding
    carries the independently compiled Candidate expression as text, which is the
    stable seam needed to rebuild Report metadata without changing the URL4 that runs.
    """

    url4 = _canonical_url4(value, "Evaluation")
    root = build(url4)
    candidate_text = _candidate_text(root)
    candidate = build(candidate_text)
    if not isinstance(candidate, Expression) or not isinstance(candidate.intent, Text):
        raise ValueError("Evaluation URL4 contains an invalid embedded Candidate expression")

    topology = _topology_from_expression(candidate)
    parsed_calls = _url4_calls(candidate)
    calls = {name: (call.model, call.dependencies) for name, call in parsed_calls.items()}
    final = _final_binding(candidate.intent.value, calls, topology)
    _validate_topology(candidate, topology, parsed_calls, final)
    selected = (
        set(_topology_bindings(topology))
        if topology.kind in {"corrective_loop", "self_corrective"}
        else _dependency_closure(final, calls)
    )
    return _candidate_from_topology(url4, topology, calls, selected)


def _candidate_from_topology(
    url4: str,
    topology: _RecipeTopology,
    calls: dict[str, tuple[str, tuple[str, ...]]],
    selected: set[str],
) -> Candidate:
    bindings = _topology_bindings(topology)
    corrective = topology.kind in {"corrective_loop", "self_corrective"}
    fusion_names = _direct_fusion_output_names(topology)
    operations = tuple(
        _compiled_operation(
            id=f"op_{name}",
            kind=bindings[name].node.role or "model",
            label=(
                f"{fusion_names.get(name, bindings[name].node.name)} "
                f"{'synthesis' if bindings[name].node.role == 'synthesis' else 'answer'}"
            ),
            depends_on=tuple(
                f"op_{dependency}" for dependency in bindings[name].operation_dependencies
            ),
        )
        for name in bindings
        if name in selected
    )
    members = (
        tuple(
            _member_projection(
                operation_id=f"op_{member.binding}",
                name=member.name,
                kind=member.kind,
                models=_models(member.binding, calls),
            )
            for member in topology.members
        )
        if topology.kind in {"fusion", "corrective_loop"}
        else ()
    )
    models = (
        tuple(dict.fromkeys(calls[name][0] for name in bindings))
        if corrective
        else _models(topology.binding, calls)
    )
    return _compiled_candidate(
        name=topology.name,
        kind=topology.kind,
        models=models,
        url4=url4,
        operations=operations,
        members=members,
    )


def _direct_fusion_output_names(value: _RecipeTopology) -> dict[str, str]:
    selected: dict[str, str] = {}

    def visit(node: _RecipeTopology) -> None:
        if node.kind == "model":
            return
        children = node.stages if node.kind == "pipeline" else node.members
        for child in children:
            visit(child)
        if node.synthesizer is not None:
            visit(node.synthesizer)
            if node.synthesizer.kind == "model":
                selected[node.binding] = node.name

    visit(value)
    return selected


def _candidate_text(root: object) -> str:
    if isinstance(root, Expression):
        for node in root.sources:
            if (
                isinstance(node, Source)
                and node.name == "candidate"
                and isinstance(node.value, Text)
            ):
                return node.value.value
    raise ValueError(
        "Evaluation URL4 must contain the embedded `candidate` recipe produced by ScreamingFace"
    )


def _candidate_calls(candidate: Expression) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {name: (call.model, call.dependencies) for name, call in _url4_calls(candidate).items()}


def _final_binding(
    intent: str,
    calls: dict[str, tuple[str, tuple[str, ...]]],
    topology: _RecipeTopology,
) -> str:
    match = re.fullmatch(r"\$(model_\d+|synthesis_\d+|loop_candidate)", intent)
    if match is None:
        raise ValueError("Evaluation URL4 Candidate has an unsupported result binding")
    selected = match.group(1)
    if topology.kind in {"corrective_loop", "self_corrective"}:
        if selected != topology.binding:
            raise ValueError("Evaluation URL4 Candidate has an unsupported result binding")
    elif selected not in calls:
        raise ValueError("Evaluation URL4 Candidate has an unsupported result binding")
    return selected


def _dependency_closure(
    name: str,
    calls: dict[str, tuple[str, tuple[str, ...]]],
) -> set[str]:
    selected: set[str] = set()

    def visit(current: str) -> None:
        if current in selected:
            return
        if current not in calls:
            raise ValueError(f"Evaluation URL4 Candidate references unknown binding {current!r}")
        for dependency in calls[current][1]:
            visit(dependency)
        selected.add(current)

    visit(name)
    return selected


def _models(
    name: str,
    calls: dict[str, tuple[str, tuple[str, ...]]],
) -> tuple[str, ...]:
    selected = _dependency_closure(name, calls)
    return tuple(dict.fromkeys(route for key, (route, _) in calls.items() if key in selected))


__all__: list[str] = []

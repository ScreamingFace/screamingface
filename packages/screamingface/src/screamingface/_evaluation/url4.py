"""Replay one complete ScreamingFace evaluation URL4 without recompiling it."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from url4 import Expression, Source, Text, build

from screamingface._core.ports import AsyncRunTransport, SyncRunTransport, _RunOutcome
from screamingface._evaluation.combine_spec import COMBINE_MODEL
from screamingface._evaluation.model import (
    Candidate,
    _candidate_kind,
    _canonical_url4,
    _compiled_candidate,
    _compiled_operation,
    _member_projection,
    _with_answer_seed,
    _with_capture,
    _with_replay_frozen_copy,
    _without_cache,
)
from screamingface._evaluation.operators import Stage, _OperatorCatalog
from screamingface._evaluation.outcome import with_run_id
from screamingface._evaluation.results import report_from_url4_outcome
from screamingface._evaluation.topology import (
    _operation_shape,
    _RecipeTopology,
    _result_binding,
    _topology_bindings,
    _topology_from_expression,
    _TopologyBinding,
)
from screamingface._operation_bindings import GATE_BLOCK, gate_join
from screamingface.errors import ExecutionError
from screamingface.events import Event
from screamingface.operation import OperationInfo
from screamingface.report import Report
from screamingface.url4 import (
    _JOIN_MODEL,
    _combine_operator_pairs,
    _topology_children,
    _validate_topology,
)
from screamingface.url4 import _calls as _url4_calls

#: What a raw-URL4 or replay evaluation is called before it runs: in the progress output, and as
#: its Run's benchmark, with 0 (unknown) Cases.
URL4_RUN_LABEL = "URL4 replay"

if TYPE_CHECKING:
    from screamingface._evaluation.runner import _AsyncOperatorLoading, _SyncOperatorLoading


def evaluate_url4_sync(
    transport: SyncRunTransport,
    url4: str,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    replay_frozen_copy: str | None = None,
    load_operators: _SyncOperatorLoading | None = None,
    use_cache: bool = True,
) -> Report:
    """Execute one already-linked evaluation expression unchanged."""

    from screamingface._evaluation.runner import (
        _abort_event_observer,
        _conclude_evaluation,
        _evaluation_options,
        _sync_event_observer,
        open_run_sync,
    )

    _evaluation_options(on_event, progress)
    replay = _replayed_url4(url4)
    candidate = replay.candidate
    if replay.pinned and load_operators is not None:
        _require_known_operators(load_operators(), replay.pinned)
    if answer_seed is not None:
        # FEATURE (OME-1193): a replayed sitting is the reproduction use case itself.
        candidate = _stamped_sitting(replay, answer_seed)
    if capture:
        # FEATURE (OME-1307): the capture request rides the Candidate, as the seed does.
        candidate = _with_capture(candidate)
    if replay_frozen_copy is not None:
        candidate = _with_replay_frozen_copy(candidate, replay_frozen_copy)
    candidate = _cache_intent(candidate, use_cache)
    observer = _sync_event_observer(
        on_event,
        progress,
        (candidate,),
        None,
        URL4_RUN_LABEL,
    )
    # INVARIANT (spec D8): raw URL4 and replay register too, right before the first token, so
    # `transport.run` always retires the binding.
    run_id = open_run_sync(transport, URL4_RUN_LABEL, 0, (candidate,))
    try:
        bound = None if observer is None else observer.bind(candidate)
        outcome = transport.run(candidate, bound)
        report = with_run_id(report_from_url4_outcome(candidate, outcome), run_id)
        _require_replay_statement(replay_frozen_copy, outcome, report)
    except BaseException as exc:
        _abort_event_observer(observer, exc)
        raise
    _conclude_evaluation(observer, report, capture)
    return report


def _cache_intent(candidate: Candidate, use_cache: bool) -> Candidate:
    """The Candidate opted out of the request cache, or unchanged (OME-1311)."""
    return candidate if use_cache else _without_cache(candidate)


async def evaluate_url4_async(
    transport: AsyncRunTransport,
    url4: str,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    replay_frozen_copy: str | None = None,
    load_operators: _AsyncOperatorLoading | None = None,
    use_cache: bool = True,
) -> Report:
    """Asynchronously execute one already-linked evaluation expression unchanged."""

    from screamingface._evaluation.runner import (
        _abort_event_observer,
        _async_event_observer,
        _conclude_evaluation,
        _evaluation_options,
        open_run_async,
    )

    _evaluation_options(on_event, progress)
    replay = _replayed_url4(url4)
    candidate = replay.candidate
    if replay.pinned and load_operators is not None:
        _require_known_operators(await load_operators(), replay.pinned)
    if answer_seed is not None:
        # FEATURE (OME-1193): see the sync twin.
        candidate = _stamped_sitting(replay, answer_seed)
    if capture:
        candidate = _with_capture(candidate)
    if replay_frozen_copy is not None:
        candidate = _with_replay_frozen_copy(candidate, replay_frozen_copy)
    candidate = _cache_intent(candidate, use_cache)
    observer = _async_event_observer(
        on_event,
        progress,
        (candidate,),
        None,
        URL4_RUN_LABEL,
    )
    run_id = await open_run_async(transport, URL4_RUN_LABEL, 0, (candidate,))
    try:
        bound = None if observer is None else observer.bind(candidate)
        outcome = await transport.run(candidate, bound)
        report = with_run_id(report_from_url4_outcome(candidate, outcome), run_id)
        _require_replay_statement(replay_frozen_copy, outcome, report)
    except BaseException as exc:
        _abort_event_observer(observer, exc)
        raise
    _conclude_evaluation(observer, report, capture)
    return report


# The two failure codes only a replay-mode Engine raises. A run that carries one has proved it was
# in replay mode: the Engine fails the call before it reaches a provider or a search service.
_REPLAY_FAILURE_CODES = frozenset({"frozen_copy_miss", "frozen_copy_unavailable"})


def _require_replay_statement(
    replay_frozen_copy: str | None, outcome: _RunOutcome, report: Report
) -> None:
    """A replay's summary must name the copy sent, unless the result itself proves replay mode.

    INVARIANT (OME-1307): the start-response echo can come from a front door while a worker
    ignored the replay env, so the run summary is checked as well. A replay run always writes
    `capture.replay`, but a copy the Engine refused (unknown, not sealed) may fail the run before
    any summary exists. Those results carry replay failure codes, which only a replay-mode Engine
    raises, so they are classified by those codes and not refused here. A run that fails the check
    may have called providers; it is not reported as a replay.
    """
    if replay_frozen_copy is None or outcome.capture_replay == replay_frozen_copy:
        return
    result = report.candidates[0]
    codes = {failure.code for failure in result.failures}
    codes.update(failure.code for case in result.cases for failure in case.failures)
    if codes & _REPLAY_FAILURE_CODES:
        return
    raise ExecutionError(
        "SF Engine did not state that it replayed the run from the frozen copy",
        code="replay_unsupported",
        permanent=True,
    )


def _candidate_from_url4(value: str) -> Candidate:
    """Recover the Candidate projection embedded by the ScreamingFace linker.

    This is the recovery-only view of ``_replayed_url4``, kept for existing callers: it does not
    expose the operators a replay must check.
    """

    return _replayed_url4(value).candidate


@dataclass(frozen=True, slots=True)
class _Replay:
    candidate: Candidate
    # The (stage, pinned id) pairs of the combine calls: the Engine's catalog must hold them.
    pinned: tuple[tuple[Stage, str], ...]
    # Own-seed model calls as ``op_id (label)``, for the fixed-seed warning (U1); never a sample
    # call (P18).
    seeded: tuple[str, ...]


def _stamped_sitting(replay: _Replay, answer_seed: int) -> Candidate:
    """Warn about own-seed calls, then stamp the declared sitting (as the Recipe path does)."""

    from screamingface._evaluation.runner import _warn_fixed_seed

    if replay.seeded:
        _warn_fixed_seed(replay.candidate.name, replay.seeded)
    return _with_answer_seed(replay.candidate, answer_seed)


def _replayed_url4(value: str) -> _Replay:
    """Recover the embedded Candidate with what a replay must check before it spends.

    The benchmark owns the outer expression. Its zero-weight ``candidate`` binding
    carries the independently compiled Candidate expression as text, which is the
    stable seam needed to rebuild Report metadata without changing the URL4 that runs.
    The pairs are what the Engine's operator catalog must hold before the replay spends.
    """

    from screamingface._evaluation.runner import _SEED_PARAM

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
    bindings = _topology_bindings(topology)
    selectors = _gate_selectors(topology)
    calls = _with_join_edges(calls, bindings, selectors)
    selected = (
        set(bindings)
        if topology.kind in {"corrective_loop", "self_corrective"}
        else _dependency_closure(gate_join(final), calls)
    )
    pinned = _combine_operator_pairs(parsed_calls)
    # No I/O here: the form check shares its message with the corrective-loop recompile.
    _OperatorCatalog.from_pinned(pinned)
    recovered = _candidate_from_topology(url4, topology, bindings, calls, selected, selectors)
    labels = {operation.id: operation.label for operation in recovered.operations}
    kinds = {operation.id: operation.kind for operation in recovered.operations}
    seeded = tuple(
        f"{operation_id} ({labels[operation_id]})"
        for binding, call in parsed_calls.items()
        if call.model != COMBINE_MODEL
        and (operation_id := f"op_{binding}") in labels
        # P18: a sample seed is part of the method (sf.Consistency); the author cannot drop it.
        and kinds[operation_id] != "sample"
        and any(name == _SEED_PARAM for name, _ in call.params)
    )
    return _Replay(recovered, pinned, seeded)


def _require_known_operators(
    catalog: _OperatorCatalog, pinned: tuple[tuple[Stage, str], ...]
) -> None:
    """Refuse a replay that pins an operator this Engine lacks (``pin`` names the id and stage).

    The pinned FORM is already checked in ``_replayed_url4``, so every id here is ``name@version``.
    """

    for stage, operator in pinned:
        catalog.pin(stage, operator)


def _candidate_from_topology(
    url4: str,
    topology: _RecipeTopology,
    bindings: dict[str, _TopologyBinding],
    calls: dict[str, tuple[str, tuple[str, ...]]],
    selected: set[str],
    selectors: dict[str, tuple[str, ...]],
) -> Candidate:
    corrective = topology.kind in {"corrective_loop", "self_corrective"}
    fusion_names = _direct_fusion_output_names(topology)
    operations = tuple(
        _replayed_operation(name, bindings[name], fusion_names)
        for name in bindings
        if name in selected
    )
    members = (
        tuple(
            _member_projection(
                operation_id=f"op_{_result_binding(member)}",
                name=member.name,
                kind=_candidate_kind(member.kind),
                models=_models(_result_binding(member), calls, selectors),
            )
            for member in topology.members
        )
        if topology.kind in {"fusion", "corrective_loop"}
        else ()
    )
    models = (
        tuple(dict.fromkeys(calls[name][0] for name in bindings if calls[name][0] != COMBINE_MODEL))
        if corrective
        else _models(_result_binding(topology), calls, selectors)
    )
    return _compiled_candidate(
        name=topology.name,
        kind=_candidate_kind(topology.kind),
        models=models,
        url4=url4,
        operations=operations,
        members=members,
    )


def _replayed_operation(
    name: str,
    binding: _TopologyBinding,
    fusion_names: dict[str, str],
) -> OperationInfo:
    node = binding.node
    kind, suffix = _operation_shape(node, binding.signal)
    return _compiled_operation(
        id=f"op_{name}",
        kind=kind,
        label=f"{fusion_names.get(name, node.name)} {suffix}",
        depends_on=tuple(f"op_{dependency}" for dependency in binding.operation_dependencies),
    )


def _direct_fusion_output_names(value: _RecipeTopology) -> dict[str, str]:
    selected: dict[str, str] = {}

    def visit(node: _RecipeTopology) -> None:
        if node.kind in {"model", "reducer"}:
            return
        for child in _child_nodes(node):
            visit(child)
        if node.synthesizer is not None:
            visit(node.synthesizer)
            if node.synthesizer.kind in {"model", "reducer"}:
                selected[node.binding] = node.name
            # a reducer's signal calls are named after their Fusion too ("a+b+c judge",
            # "a+b+c project s", "a+b+c write s")
            for signal in node.synthesizer.signals:
                selected[signal.source.binding] = node.name
                if signal.projection is not None:
                    selected[signal.projection.binding] = node.name

    visit(value)
    return selected


def _child_nodes(node: _RecipeTopology) -> tuple[_RecipeTopology, ...]:
    """The recipe children a Fusion name walk enters (E4c: a Gate's panel and recipe branches)."""

    if node.kind == "gate":
        return tuple(
            child
            for child in (node.panel, node.then_branch, node.otherwise_branch)
            if isinstance(child, _RecipeTopology)
        )
    return node.stages if node.kind == "pipeline" else node.members


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


def _final_binding(
    intent: str,
    calls: dict[str, tuple[str, tuple[str, ...]]],
    topology: _RecipeTopology,
) -> str:
    match = re.fullmatch(r"\$(model_\d+|synthesis_\d+|loop_candidate|gate_\d+_block)", intent)
    if match is None:
        raise ValueError("Evaluation URL4 Candidate has an unsupported result binding")
    selected = match.group(1)
    if GATE_BLOCK.fullmatch(selected):
        # E4c: the result of a Gate block is its JOIN call, which must be a decoded call.
        if gate_join(selected) not in calls:
            raise ValueError("Evaluation URL4 Candidate has an unsupported result binding")
    elif topology.kind in {"corrective_loop", "self_corrective"}:
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


def _gate_selectors(node: _RecipeTopology) -> dict[str, tuple[str, ...]]:
    """Each Gate's JOIN, mapped to the selector calls it lists (only a tree root lists any)."""

    gates = {}
    if node.kind == "gate":
        gates[node.join_binding] = tuple(selector.binding for selector in node.selectors)
    for child in _topology_children(node):
        gates |= _gate_selectors(child)
    return gates


def _with_join_edges(
    calls: dict[str, tuple[str, tuple[str, ...]]],
    bindings: dict[str, _TopologyBinding],
    selectors: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Give each Gate's JOIN the edges of its operation: its panel, its bodies, its selectors.

    WHY (E4c): the JOIN's context names only Gate helpers, so its parsed dependencies are empty
    and a dependency closure through it (``sf.Gate >> sf.Model``) would miss every model the Gate
    may call; each of them is part of the Candidate even when a Case does not run it.
    """

    edges = dict(calls)
    for join, own in selectors.items():
        model, dependencies = edges[join]
        block = (*bindings[join].operation_dependencies, *own)
        edges[join] = (model, tuple(dict.fromkeys((*dependencies, *block))))
    return edges


def _models(
    name: str,
    calls: dict[str, tuple[str, tuple[str, ...]]],
    selectors: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """The routes ``name`` reaches, in call order; ``selectors`` maps a Gate's JOIN to its own.

    WHY a selector moves to its JOIN (E4c): the url4 hoists a selector call above its Gate tree,
    but the compiler lists a Gate's models as panel, bodies, then selectors (``_Gate._resolved``),
    and a Candidate's models are ordered.
    """

    selected = _dependency_closure(name, calls)
    hoisted = {selector for join in selected for selector in selectors.get(join, ())}
    ordered: list[str] = []
    for key in calls:
        if key in selected and key not in hoisted:
            ordered.extend((key, *selectors.get(key, ())))
    # INVARIANT: the combine route is a join, never a model a Run needs available.
    return tuple(
        dict.fromkeys(
            route
            for route in (calls[binding][0] for binding in ordered)
            if route not in (COMBINE_MODEL, _JOIN_MODEL)
        )
    )


__all__: list[str] = []

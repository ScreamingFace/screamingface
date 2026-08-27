"""Complete validation, compilation, execution, and decoding for one Evaluation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from screamingface.errors import PlanningError

from screamingface._core.ports import AsyncRunTransport, SyncRunTransport, _RunOutcome
from screamingface._diagnostics.evaluation import _EvaluationDiagnostic
from screamingface._evaluation.benchmark import _BenchmarkResource
from screamingface._evaluation.model import (
    Candidate,
    _candidate_values,
    _Evaluation,
    _validate_limit,
)
from screamingface._evaluation.model_parameters import preflight_async, preflight_sync
from screamingface._evaluation.observers import (
    _abort_event_observer,
    _async_event_observer,
    _AsyncEventObserver,
    _evaluation_diagnostic,
    _reconcile_event_observer,
    _record_compiled_evaluation,
    _record_validated_evaluation,
    _stage_diagnostic,
    _sync_event_observer,
    _SyncEventObserver,
)
from screamingface.discovery import ModelDetails, ModelInfo
from screamingface.events import Event
from screamingface.recipe import Recipe
from screamingface.report import Report


class _ModelCatalog(Protocol):
    @property
    def models(self) -> Sequence[ModelInfo]: ...


type _SyncModelLoading = Callable[[], _ModelCatalog]
type _AsyncModelLoading = Callable[[], Awaitable[_ModelCatalog]]
type _SyncModelDetailsLoading = Callable[[str], ModelDetails]
type _AsyncModelDetailsLoading = Callable[[str], Awaitable[ModelDetails]]
type _SyncBenchmarkLoading = Callable[[str, int | None], _BenchmarkResource]
type _AsyncBenchmarkLoading = Callable[[str, int | None], Awaitable[_BenchmarkResource]]

_MAX_CANDIDATES_IN_FLIGHT = 8


def evaluate_sync(
    load_benchmark: _SyncBenchmarkLoading,
    transport: SyncRunTransport,
    load_models: _SyncModelLoading,
    load_model_details: _SyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str | None,
    limit: int | None,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
    *,
    engine_url: str,
) -> Report:
    """Run the complete synchronous Evaluation workflow behind the Client interface."""

    from screamingface._evaluation.results import report_from_outcomes

    diagnostic = _evaluation_diagnostic(
        engine_url=engine_url,
        benchmark=benchmark,
        candidates=candidates,
    )
    observer: _SyncEventObserver | None = None
    try:
        evaluation, check_disclosure = _prepare_evaluation_sync(
            load_benchmark,
            load_models,
            load_model_details,
            candidates,
            benchmark,
            limit,
            on_event,
            progress,
            diagnostic,
        )
        observer = _sync_event_observer(
            on_event,
            progress,
            tuple(evaluation.candidates),
            evaluation.case_count,
            benchmark,
            check_disclosure=check_disclosure,
            diagnostic=diagnostic,
        )
        outcomes = _run_candidates_sync(transport, tuple(evaluation.candidates), observer)
        report = report_from_outcomes(evaluation, outcomes)
    except (SystemExit, GeneratorExit) as exc:
        _abort_event_observer(observer, exc)
        raise
    except BaseException as exc:
        _abort_event_observer(observer, exc)
        _stage_diagnostic(diagnostic, exc)
        raise
    _reconcile_event_observer(observer, report)
    return report


async def evaluate_async(
    load_benchmark: _AsyncBenchmarkLoading,
    transport: AsyncRunTransport,
    load_models: _AsyncModelLoading,
    load_model_details: _AsyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str | None,
    limit: int | None,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    *,
    engine_url: str,
) -> Report:
    """Run the complete asynchronous Evaluation workflow behind the Client interface."""

    from screamingface._evaluation.results import report_from_outcomes

    diagnostic = _evaluation_diagnostic(
        engine_url=engine_url,
        benchmark=benchmark,
        candidates=candidates,
    )
    observer: _AsyncEventObserver | None = None
    try:
        evaluation, check_disclosure = await _prepare_evaluation_async(
            load_benchmark,
            load_models,
            load_model_details,
            candidates,
            benchmark,
            limit,
            on_event,
            progress,
            diagnostic,
        )
        observer = _async_event_observer(
            on_event,
            progress,
            tuple(evaluation.candidates),
            evaluation.case_count,
            benchmark,
            check_disclosure=check_disclosure,
            diagnostic=diagnostic,
        )
        outcomes = await _run_candidates_async(transport, tuple(evaluation.candidates), observer)
        report = report_from_outcomes(evaluation, outcomes)
    except (SystemExit, GeneratorExit) as exc:
        _abort_event_observer(observer, exc)
        raise
    except BaseException as exc:
        _abort_event_observer(observer, exc)
        _stage_diagnostic(diagnostic, exc)
        raise
    _reconcile_event_observer(observer, report)
    return report


def _prepare_evaluation_sync(
    load_benchmark: _SyncBenchmarkLoading,
    load_models: _SyncModelLoading,
    load_model_details: _SyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str | None,
    limit: int | None,
    on_event: object,
    progress: object,
    diagnostic: _EvaluationDiagnostic | None,
) -> tuple[_Evaluation, str | None]:
    from screamingface._evaluation.compilation import compile_evaluation

    _evaluation_options(on_event, progress)
    selected_benchmark = _benchmark_id(benchmark)
    values = _evaluation_inputs(candidates, selected_benchmark, limit)
    resource = load_benchmark(selected_benchmark, limit)
    check_disclosure = _validate_check_surface(values, selected_benchmark, resource)
    evaluation = compile_evaluation(values, resource, limit)
    _record_compiled_evaluation(diagnostic, evaluation)
    catalog = load_models()
    _probe_missing_models_sync(evaluation, catalog.models, load_model_details)
    preflight_sync(tuple(evaluation.candidates), load_model_details)
    _record_validated_evaluation(diagnostic, evaluation)
    return evaluation, check_disclosure


async def _prepare_evaluation_async(
    load_benchmark: _AsyncBenchmarkLoading,
    load_models: _AsyncModelLoading,
    load_model_details: _AsyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str | None,
    limit: int | None,
    on_event: object,
    progress: object,
    diagnostic: _EvaluationDiagnostic | None,
) -> tuple[_Evaluation, str | None]:
    from screamingface._evaluation.compilation import compile_evaluation

    _evaluation_options(on_event, progress)
    selected_benchmark = _benchmark_id(benchmark)
    values = _evaluation_inputs(candidates, selected_benchmark, limit)
    resource = await load_benchmark(selected_benchmark, limit)
    check_disclosure = _validate_check_surface(values, selected_benchmark, resource)
    evaluation = compile_evaluation(values, resource, limit)
    _record_compiled_evaluation(diagnostic, evaluation)
    catalog = await load_models()
    await _probe_missing_models_async(evaluation, catalog.models, load_model_details)
    await preflight_async(tuple(evaluation.candidates), load_model_details)
    _record_validated_evaluation(diagnostic, evaluation)
    return evaluation, check_disclosure


def _probe_missing_models_sync(
    evaluation: _Evaluation,
    models: Sequence[ModelInfo],
    load_model_details: _SyncModelDetailsLoading,
) -> None:
    from screamingface.errors import PlanningError

    for model in _missing_required_models(evaluation, models):
        try:
            load_model_details(model)
        except PlanningError as exc:
            _reraise_probe_miss(model, exc)


async def _probe_missing_models_async(
    evaluation: _Evaluation,
    models: Sequence[ModelInfo],
    load_model_details: _AsyncModelDetailsLoading,
) -> None:
    from screamingface.errors import PlanningError

    for model in _missing_required_models(evaluation, models):
        try:
            await load_model_details(model)
        except PlanningError as exc:
            _reraise_probe_miss(model, exc)


def _evaluation_options(on_event: object, progress: object) -> None:
    if on_event is not None and not callable(on_event):
        raise TypeError("on_event must be callable or None")
    if progress is not None and not isinstance(progress, bool):
        raise TypeError("progress must be True, False, or None")


def _run_candidates_sync(
    transport: SyncRunTransport,
    candidates: tuple[Candidate, ...],
    observer: _SyncEventObserver | None,
) -> tuple[tuple[Candidate, _RunOutcome], ...]:
    if len(candidates) == 1:
        candidate = candidates[0]
        selected_observer = None if observer is None else observer.bind(candidate)
        if observer is not None:
            observer.begin(candidate)
        return ((candidate, transport.run(candidate, selected_observer)),)

    with ThreadPoolExecutor(
        max_workers=min(len(candidates), _MAX_CANDIDATES_IN_FLIGHT),
        thread_name_prefix="screamingface-candidate",
    ) as executor:

        def run(candidate: Candidate) -> _RunOutcome:
            selected_observer = None if observer is None else observer.bind(candidate)
            if observer is not None:
                observer.begin(candidate)
            return transport.run(candidate, selected_observer)

        futures = ()
        try:
            futures = tuple(executor.submit(run, candidate) for candidate in candidates)
            return tuple(
                (candidate, future.result())
                for candidate, future in zip(candidates, futures, strict=True)
            )
        except BaseException as exc:
            try:
                transport.cancel_active()
            except Exception as cancel_error:  # noqa: BLE001 - preserve the original interruption
                exc.add_note(f"Stopping active SF Engine runs also failed: {cancel_error}")
            for future in futures:
                future.cancel()
            raise


async def _run_candidates_async(
    transport: AsyncRunTransport,
    candidates: tuple[Candidate, ...],
    observer: _AsyncEventObserver | None,
) -> tuple[tuple[Candidate, _RunOutcome], ...]:
    if len(candidates) == 1:
        candidate = candidates[0]
        selected_observer = None if observer is None else observer.bind(candidate)
        if observer is not None:
            await observer.begin(candidate)
        return ((candidate, await transport.run(candidate, selected_observer)),)

    gate = asyncio.Semaphore(_MAX_CANDIDATES_IN_FLIGHT)

    async def run(candidate: Candidate) -> _RunOutcome:
        async with gate:
            selected_observer = None if observer is None else observer.bind(candidate)
            if observer is not None:
                await observer.begin(candidate)
            return await transport.run(candidate, selected_observer)

    tasks = tuple(asyncio.create_task(run(candidate)) for candidate in candidates)
    try:
        outcomes = await asyncio.gather(*tasks)
    except BaseException as exc:
        # INVARIANT: sweep BEFORE cancelling the siblings, exactly as the synchronous path
        # does. Each Run discards its own capability on the way out, so cancelling first
        # empties the registry and makes this fallback a guaranteed no-op.
        try:
            await transport.cancel_active()
        except Exception as cancel_error:  # noqa: BLE001 - preserve the original interruption
            exc.add_note(f"Stopping active SF Engine runs also failed: {cancel_error}")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return tuple(zip(candidates, outcomes, strict=True))


def _missing_required_models(
    evaluation: _Evaluation,
    available: Sequence[ModelInfo],
) -> tuple[str, ...]:
    """The required Models the listing does not carry — every one defers to the probe.

    WHY no admissibility grammar here (review F10): the Engine and Gateway are the
    only authorities on what can be dynamically admitted (OME-878); a third copy of
    their shape rules in the SDK already diverged once and would force a lockstep
    three-component release the day a second provider admits. The probe is a free,
    pre-spend request: an Engine that admits lets the run proceed, one that refuses
    answers with a decoded diagnostic, and one that cannot admit at all answers
    with a plain 404 — which the probe rewrites into exactly today's refusal.
    """
    available_ids = {model.id for model in available}
    return tuple(model for model in evaluation.required_models if model not in available_ids)


def _reraise_probe_miss(model: str, exc: PlanningError) -> None:
    """Rewrite the probe's plain-404 answer into today's availability refusal.

    WHY here and not in the shared details decoder (review F8): only the probe
    KNOWS it asked about a listing-missing model, so only the probe may read a
    bare 404 as "not available on this Engine". On every other details call a
    bare 404 stays what it really is — a deployment problem
    (``engine_contract_error``), e.g. a reverse proxy without the route.
    """
    from screamingface.errors import PlanningError

    if exc.code == "engine_contract_error" and exc.status == 404:
        raise PlanningError(
            f"Model {model!r} is not available on this Engine",
            code="model_unavailable",
            permanent=True,
            details={"models": [model]},
        ) from exc
    raise exc


def _validate_check_surface(
    values: Sequence[Recipe],
    benchmark: str,
    resource: _BenchmarkResource,
) -> str | None:
    """Settle loop Recipes against a benchmark's check surface before spend.

    A missing surface fails closed. A paid surface declares the maximum number
    of benchmark-owned check calls; the returned disclosure text carries that
    cost multiplier to whichever surface shows it — the evaluation panel when
    one is rendering, a Python warning otherwise (OME-845). Returns None when
    there is nothing to disclose.
    """

    from screamingface.corrective import CorrectiveLoop, SelfCorrective
    from screamingface.errors import PlanningError

    loops = tuple(value for value in values if isinstance(value, CorrectiveLoop | SelfCorrective))
    if not loops:
        return None
    surface = resource.check_surface
    if surface is None:
        names = ", ".join(repr(value.name) for value in loops)
        raise PlanningError(
            f"Benchmark {benchmark!r} does not support mid-run checking, so corrective "
            f"candidate(s) {names} cannot run on it",
            code="check_surface_missing",
            permanent=True,
            details={"benchmark": benchmark, "candidates": [value.name for value in loops]},
        )
    if surface.expected_check_cost != "paid":
        return None
    per_case = sum(value.max_rounds * _loop_member_count(value) for value in loops)
    maximum = per_case * resource.case_count
    return (
        f"Benchmark {benchmark!r} may make up to {maximum} paid check calls "
        f"({per_case} per case x {resource.case_count} cases), in addition to the "
        "Candidate's own model calls. Passing earlier uses fewer calls; each check "
        "may retry according to the benchmark's policy."
    )


def _loop_member_count(recipe: Recipe) -> int:
    from screamingface.corrective import CorrectiveLoop

    return len(recipe.members) if isinstance(recipe, CorrectiveLoop) else 1


def _evaluation_inputs(
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
) -> tuple[Recipe, ...]:
    values = _candidate_values(candidates)
    if not isinstance(benchmark, str) or not benchmark.strip():
        raise ValueError("benchmark must be a non-empty string")
    if benchmark == "default":
        raise ValueError("benchmark must name an explicit Benchmark, not 'default'")
    _validate_limit(limit)
    return values


def _benchmark_id(value: object) -> str:
    if value is None:
        raise TypeError("benchmark is required when evaluating Recipes")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("benchmark must be a non-empty string")
    if value == "default":
        raise ValueError("benchmark must name an explicit Benchmark, not 'default'")
    return value


__all__: list[str] = []

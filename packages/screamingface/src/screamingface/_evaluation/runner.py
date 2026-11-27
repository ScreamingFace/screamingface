"""Complete validation, compilation, execution, and decoding for one Evaluation."""

from __future__ import annotations

import asyncio
import inspect
import logging
import warnings
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Literal, NoReturn, Protocol, overload

if TYPE_CHECKING:
    from screamingface.errors import PlanningError

from screamingface._core.ports import (
    AsyncRunTransport,
    SyncRunTransport,
    _ConnectionNotice,
    _ResultPersistence,
    _RunOutcome,
)
from screamingface._environment import SDK_PACKAGE_ROOT
from screamingface._evaluation.benchmark import _BenchmarkResource
from screamingface._evaluation.candidate import recipes_need_operators
from screamingface._evaluation.case_selection import selected_cases
from screamingface._evaluation.completion import completion_callback
from screamingface._evaluation.model import (
    Candidate,
    _candidate_values,
    _Evaluation,
    _validate_limit,
    _with_answer_seed,
    _with_capture,
    _without_cache,
)
from screamingface._evaluation.model_parameters import (
    _SEED_PARAM,
    preflight_async,
    preflight_sync,
)
from screamingface._evaluation.operators import _OperatorCatalog
from screamingface._evaluation.outcome import (
    _CandidatesFailed,
    raise_candidates_failed,
    settle,
)
from screamingface.discovery import ModelDetails, ModelInfo
from screamingface.events import Event
from screamingface.recipe import Recipe
from screamingface.report import CandidateResult, Report
from screamingface.warnings import FixedSeedSittingWarning


class _ModelCatalog(Protocol):
    @property
    def models(self) -> Sequence[ModelInfo]: ...


type _SyncModelLoading = Callable[[], _ModelCatalog]
type _AsyncModelLoading = Callable[[], Awaitable[_ModelCatalog]]
type _SyncModelDetailsLoading = Callable[[str], ModelDetails]
type _AsyncModelDetailsLoading = Callable[[str], Awaitable[ModelDetails]]
type _SyncBenchmarkLoading = Callable[[str, int | None, tuple[int, ...] | None], _BenchmarkResource]
type _AsyncBenchmarkLoading = Callable[
    [str, int | None, tuple[int, ...] | None], Awaitable[_BenchmarkResource]
]
type _SyncOperatorLoading = Callable[[], _OperatorCatalog]
type _AsyncOperatorLoading = Callable[[], Awaitable[_OperatorCatalog]]
# FEATURE (C12 capability gate): the Client's reader, which refuses unless the Engine advertises
# every ID it is given.
type _SyncCapabilityCheck = Callable[[frozenset[str]], None]
type _AsyncCapabilityCheck = Callable[[frozenset[str]], Awaitable[None]]

_NAMED_CALLS = 3
_logger = logging.getLogger(__name__)


@overload
def evaluate_sync(
    load_benchmark: _SyncBenchmarkLoading,
    transport: SyncRunTransport,
    load_models: _SyncModelLoading,
    load_model_details: _SyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _SyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: Literal[False] = False,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _SyncCapabilityCheck | None = None,
) -> Report: ...


@overload
def evaluate_sync(
    load_benchmark: _SyncBenchmarkLoading,
    transport: SyncRunTransport,
    load_models: _SyncModelLoading,
    load_model_details: _SyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _SyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: Literal[True] = ...,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _SyncCapabilityCheck | None = None,
) -> str: ...


@overload
def evaluate_sync(
    load_benchmark: _SyncBenchmarkLoading,
    transport: SyncRunTransport,
    load_models: _SyncModelLoading,
    load_model_details: _SyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _SyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: bool = False,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _SyncCapabilityCheck | None = None,
) -> Report | str: ...


def evaluate_sync(  # noqa: PLR0915 - the Evaluation's phases, in order
    load_benchmark: _SyncBenchmarkLoading,
    transport: SyncRunTransport,
    load_models: _SyncModelLoading,
    load_model_details: _SyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _SyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: bool = False,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _SyncCapabilityCheck | None = None,
) -> Report | str:
    """Run the complete synchronous Evaluation workflow behind the Client interface; with
    ``detach``, register the Run and return its id instead (E5 P2 spec D11, D14)."""

    from screamingface._evaluation.compilation import compile_evaluation
    from screamingface._evaluation.outcome import completed_report
    from screamingface.errors import PlanningError

    _evaluation_options(on_event, progress)
    values = _evaluation_inputs(candidates, benchmark, limit)
    # FEATURE (OME-1739): a bad Case-id list fails here, before the Engine is asked anything.
    resource = load_benchmark(benchmark, limit, selected_cases(cases, limit))
    check_disclosure = _validate_check_surface(values, benchmark, resource)
    # extract="benchmark" resolves inside compile_evaluation from resource.answer_rule, before any
    # spend (GP-1).
    evaluation = compile_evaluation(
        values,
        resource,
        limit,
        operators=_operators_sync(values, load_operators),
        warn_judge_writers=False,
    )
    # FEATURE (C12): a plan that needs Engine capabilities reads them once, fresh, now that it
    # compiled: before the Model listing, the mint, registration and the follow.
    _require_capabilities_sync(required_capabilities, require_capabilities)
    # FEATURE (OME-1193, OME-1307): stamp the declared sitting (`answer_seed`) and the capture
    # request (`capture`) onto every compiled Candidate ONCE, so the transport, the progress
    # observer and the report all see the same objects.
    selected_candidates = _cache_intent_candidates(
        _captured_candidates(
            _seeded_candidates(tuple(evaluation.candidates), answer_seed), capture
        ),
        use_cache,
    )
    # The availability probe (OME-878): a details fetch for EVERY listing-missing
    # Model — the Engine admits it (run proceeds), relays a refusal (decoded,
    # pre-spend), or answers a plain 404 that reads as today's refusal.
    prefetched: dict[str, ModelDetails] = {}
    for model in _missing_required_models(evaluation, load_models().models):
        try:
            prefetched[model] = load_model_details(model)
        except PlanningError as exc:
            _reraise_probe_miss(model, exc)
    preflight_sync(
        selected_candidates, load_model_details, answer_seed=answer_seed, prefetched=prefetched
    )
    if detach:
        return transport.register_run(
            evaluation, selected_candidates, detach=True, deadline_s=deadline_s
        )
    from screamingface._evaluation.following import canceled_if_left_sync

    # E5 P2 spec D1: the Run is registered with every start, and the Engine drives it.
    run_id = transport.register_run(evaluation, selected_candidates)
    with ExitStack() as results:
        with canceled_if_left_sync(transport, run_id):
            results.enter_context(_prepared_results(transport, evaluation, selected_candidates))
            observer = _sync_event_observer(
                on_event,
                progress,
                selected_candidates,
                evaluation.case_count,
                benchmark,
                check_disclosure=check_disclosure,
            )
        try:
            outcomes = _settled_sync(transport, evaluation, selected_candidates, observer, run_id)
            # OME-1739 F6 (the roll-call check) runs per Candidate inside the decode, so a
            # mismatch is a named Candidate failure and never reaches a Partial Report.
            report = completed_report(evaluation, outcomes, run_id)
        except BaseException as exc:
            _abort_event_observer(observer, exc)
            raise
        _conclude_evaluation(observer, report, capture)
        return report


@overload
async def evaluate_async(
    load_benchmark: _AsyncBenchmarkLoading,
    transport: AsyncRunTransport,
    load_models: _AsyncModelLoading,
    load_model_details: _AsyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _AsyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: Literal[False] = False,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _AsyncCapabilityCheck | None = None,
) -> Report: ...


@overload
async def evaluate_async(
    load_benchmark: _AsyncBenchmarkLoading,
    transport: AsyncRunTransport,
    load_models: _AsyncModelLoading,
    load_model_details: _AsyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _AsyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: Literal[True] = ...,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _AsyncCapabilityCheck | None = None,
) -> str: ...


@overload
async def evaluate_async(
    load_benchmark: _AsyncBenchmarkLoading,
    transport: AsyncRunTransport,
    load_models: _AsyncModelLoading,
    load_model_details: _AsyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _AsyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: bool = False,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _AsyncCapabilityCheck | None = None,
) -> Report | str: ...


async def evaluate_async(  # noqa: PLR0915 - see evaluate_sync
    load_benchmark: _AsyncBenchmarkLoading,
    transport: AsyncRunTransport,
    load_models: _AsyncModelLoading,
    load_model_details: _AsyncModelDetailsLoading,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    on_event: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    answer_seed: int | None = None,
    capture: bool = False,
    load_operators: _AsyncOperatorLoading | None = None,
    use_cache: bool = True,
    cases: object = None,
    detach: bool = False,
    deadline_s: int | None = None,
    required_capabilities: frozenset[str] = frozenset(),
    require_capabilities: _AsyncCapabilityCheck | None = None,
) -> Report | str:
    """Run the complete asynchronous Evaluation workflow behind the Client interface; with
    ``detach``, register the Run and return its id instead."""

    from screamingface._evaluation.compilation import compile_evaluation
    from screamingface._evaluation.outcome import completed_report
    from screamingface.errors import PlanningError

    _evaluation_options(on_event, progress)
    values = _evaluation_inputs(candidates, benchmark, limit)
    # FEATURE (OME-1739): see the sync twin.
    resource = await load_benchmark(benchmark, limit, selected_cases(cases, limit))
    check_disclosure = _validate_check_surface(values, benchmark, resource)
    # extract="benchmark" resolves inside compile_evaluation from resource.answer_rule, before any
    # spend (GP-1).
    evaluation = compile_evaluation(
        values,
        resource,
        limit,
        operators=await _operators_async(values, load_operators),
        warn_judge_writers=False,
    )
    # FEATURE (C12): see the sync twin.
    await _require_capabilities_async(required_capabilities, require_capabilities)
    # FEATURE (OME-1193, OME-1307): see the sync twin — one stamped tuple (seed and capture) for
    # transport, observer and report alike.
    selected_candidates = _cache_intent_candidates(
        _captured_candidates(
            _seeded_candidates(tuple(evaluation.candidates), answer_seed), capture
        ),
        use_cache,
    )
    # The availability probe (OME-878): a details fetch for EVERY listing-missing
    # Model — the Engine admits it (run proceeds), relays a refusal (decoded,
    # pre-spend), or answers a plain 404 that reads as today's refusal.
    prefetched: dict[str, ModelDetails] = {}
    for model in _missing_required_models(evaluation, (await load_models()).models):
        try:
            prefetched[model] = await load_model_details(model)
        except PlanningError as exc:
            _reraise_probe_miss(model, exc)
    await preflight_async(
        selected_candidates, load_model_details, answer_seed=answer_seed, prefetched=prefetched
    )
    if detach:
        return await transport.register_run(
            evaluation, selected_candidates, detach=True, deadline_s=deadline_s
        )
    from screamingface._evaluation.following import canceled_if_left_async

    run_id = await transport.register_run(evaluation, selected_candidates)
    with ExitStack() as results:
        async with canceled_if_left_async(transport, run_id):
            results.enter_context(_prepared_results(transport, evaluation, selected_candidates))
            observer = _async_event_observer(
                on_event,
                progress,
                selected_candidates,
                evaluation.case_count,
                benchmark,
                check_disclosure=check_disclosure,
            )
        try:
            outcomes = await _settled_async(
                transport, evaluation, selected_candidates, observer, run_id
            )
            # OME-1739 F6: see the sync twin; the check lives in the per-Candidate decode.
            report = completed_report(evaluation, outcomes, run_id)
        except BaseException as exc:
            _abort_event_observer(observer, exc)
            raise
        _conclude_evaluation(observer, report, capture)
        return report


def _operators_sync(
    values: Sequence[Recipe], load_operators: _SyncOperatorLoading | None
) -> _OperatorCatalog | None:
    """The Engine's operator catalog, only when a Candidate has a reducer.

    INVARIANT: a Candidate without a reducer never requests `/v1/operators`.
    """

    if load_operators is None or not recipes_need_operators(values):
        return None
    return load_operators()


async def _operators_async(
    values: Sequence[Recipe], load_operators: _AsyncOperatorLoading | None
) -> _OperatorCatalog | None:
    """The async twin of ``_operators_sync``."""

    if load_operators is None or not recipes_need_operators(values):
        return None
    return await load_operators()


def _require_capabilities_sync(
    required: frozenset[str], require: _SyncCapabilityCheck | None
) -> None:
    """Refuse a plan that needs a capability the Engine does not advertise.

    INVARIANT (C12): an empty requirement never asks the Engine, and a requirement with no
    reader fails closed instead of submitting unchecked.
    """

    if not required:
        return
    if require is None:
        _no_capability_reader(required)
    require(required)


async def _require_capabilities_async(
    required: frozenset[str], require: _AsyncCapabilityCheck | None
) -> None:
    """The async twin of ``_require_capabilities_sync``."""

    if not required:
        return
    if require is None:
        _no_capability_reader(required)
    await require(required)


def _no_capability_reader(required: frozenset[str]) -> NoReturn:
    from screamingface.errors import EngineCapabilityError

    raise EngineCapabilityError(
        "this Evaluation needs SF Engine capabilities, but no capability reader is configured",
        permanent=True,
        details={"missing": sorted(required)},
    )


def _settled_sync(
    transport: SyncRunTransport,
    evaluation: _Evaluation,
    candidates: tuple[Candidate, ...],
    observer: _SyncEventObserver | None,
    run_id: str,
) -> tuple[tuple[Candidate, _RunOutcome], ...]:
    from screamingface._evaluation.following import followed_sync
    from screamingface._evaluation.reattach import settled_from_records

    try:
        recorded, kept = followed_sync(
            transport,
            run_id,
            candidates,
            observer,
            completion_callback(evaluation, observer),
        )
        # E5 P2 spec D14: the one build every Report of a Run comes from.
        return settle(settled_from_records(transport, candidates, recorded, kept))
    except _CandidatesFailed as failed:
        settled = failed.settled
    # INVARIANT (spec §5): the private carrier never reaches the caller. Raised outside the
    # `except`, so the error does not keep the carrier as its `__context__`.
    raise_candidates_failed(evaluation, settled, run_id)


async def _settled_async(
    transport: AsyncRunTransport,
    evaluation: _Evaluation,
    candidates: tuple[Candidate, ...],
    observer: _AsyncEventObserver | None,
    run_id: str,
) -> tuple[tuple[Candidate, _RunOutcome], ...]:
    from screamingface._evaluation.following import followed_async
    from screamingface._evaluation.reattach import refetched_async, settled_from_records

    try:
        recorded, kept = await followed_async(
            transport,
            run_id,
            candidates,
            observer,
            completion_callback(evaluation, observer),
        )
        recorded, kept = await refetched_async(transport, candidates, recorded, kept)
        return settle(settled_from_records(transport, candidates, recorded, kept))
    except _CandidatesFailed as failed:
        settled = failed.settled
    raise_candidates_failed(evaluation, settled, run_id)


def _evaluation_options(on_event: object, progress: object) -> None:
    if on_event is not None and not callable(on_event):
        raise TypeError("on_event must be callable or None")
    if progress is not None and not isinstance(progress, bool):
        raise TypeError("progress must be True, False, or None")


def _sync_event_observer(
    callback: Callable[[Event], None] | None,
    progress: bool | None,
    candidates: tuple[Candidate, ...] = (),
    case_count: int | None = None,
    benchmark: str | None = None,
    check_disclosure: str | None = None,
) -> _SyncEventObserver | None:
    from screamingface._evaluation.progress import _progress_observer

    builtin = _progress_observer(
        progress,
        candidates=candidates,
        case_count=case_count,
        benchmark=benchmark,
        check_disclosure=check_disclosure,
    )
    if builtin is None and callback is None:
        return None
    return _SyncEventObserver(builtin, callback)


def _async_event_observer(
    callback: Callable[[Event], None | Awaitable[None]] | None,
    progress: bool | None,
    candidates: tuple[Candidate, ...] = (),
    case_count: int | None = None,
    benchmark: str | None = None,
    check_disclosure: str | None = None,
) -> _AsyncEventObserver | None:
    from screamingface._evaluation.progress import _progress_observer

    builtin = _progress_observer(
        progress,
        candidates=candidates,
        case_count=case_count,
        benchmark=benchmark,
        check_disclosure=check_disclosure,
    )
    if builtin is None and callback is None:
        return None
    return _AsyncEventObserver(builtin, callback)


class _SyncEventObserver:
    def __init__(
        self,
        builtin: object | None,
        callback: Callable[[Event], None] | None,
    ) -> None:
        self._builtin = builtin
        self._callback = callback
        self._lock = Lock()
        self._caller_errors: list[BaseException] = []

    def begin(self, candidate: Candidate) -> None:
        with self._lock:
            if self._builtin is not None:
                _begin_candidate_progress(self._builtin, candidate)

    def bind(self, candidate: Candidate) -> Callable[[Event], None]:
        def observe(event: Event) -> None:
            with self._lock:
                if self._builtin is not None:
                    _observe_candidate_progress(self._builtin, candidate, event)
                if self._callback is not None:
                    try:
                        self._callback(event)
                    except BaseException as exc:
                        # WHY (spec §5.1): tag the caller's own exception by identity, so
                        # the runner can abort for it (C1c) and not settle it as C1b.
                        self._caller_errors.append(exc)
                        raise

        def connection(notice: _ConnectionNotice) -> None:
            with self._lock:
                _connection_progress(self._builtin, candidate, notice)

        return _BoundObserver(observe, connection)

    def candidate_result(self, result: CandidateResult) -> None:
        selected = getattr(self._builtin, "candidate_result", None)
        if callable(selected):
            _observe_progress(selected, result)

    def candidate_failed(self, candidate: Candidate, exc: Exception) -> None:
        with self._lock:
            _candidate_failed_progress(self._builtin, candidate, exc)

    def candidate_stopped(self, candidate: Candidate) -> None:
        with self._lock:
            _candidate_stopped_progress(self._builtin, candidate)

    def raised_by_caller(self, exc: BaseException) -> bool:
        with self._lock:
            return any(exc is recorded for recorded in self._caller_errors)

    def reconcile(self, report: Report) -> None:
        _reconcile_progress(self._builtin, report)

    def abort(self, exc: BaseException) -> None:
        _abort_progress(self._builtin, exc)

    def close(self) -> None:
        _close_progress(self._builtin)


class _AsyncEventObserver:
    def __init__(
        self,
        builtin: object | None,
        callback: Callable[[Event], None | Awaitable[None]] | None,
    ) -> None:
        self._builtin = builtin
        self._callback = callback
        self._lock = asyncio.Lock()
        self._caller_errors: list[BaseException] = []

    async def begin(self, candidate: Candidate) -> None:
        async with self._lock:
            if self._builtin is not None:
                _begin_candidate_progress(self._builtin, candidate)

    def bind(self, candidate: Candidate) -> Callable[[Event], Awaitable[None]]:
        async def observe(event: Event) -> None:
            async with self._lock:
                if self._builtin is not None:
                    _observe_candidate_progress(self._builtin, candidate, event)
                if self._callback is not None:
                    try:
                        returned = self._callback(event)
                        if inspect.isawaitable(returned):
                            await returned
                    except BaseException as exc:
                        # WHY: see the sync twin (spec §5.1).
                        self._caller_errors.append(exc)
                        raise

        def connection(notice: _ConnectionNotice) -> None:
            # WHY no `self._lock`: it is an asyncio.Lock and this runs on the same loop
            # with no await, so it cannot interleave with a half-done `observe` of the
            # built-in renderer (whose call is itself synchronous).
            _connection_progress(self._builtin, candidate, notice)

        return _BoundObserver(observe, connection)

    def candidate_result(self, result: CandidateResult) -> None:
        selected = getattr(self._builtin, "candidate_result", None)
        if callable(selected):
            _observe_progress(selected, result)

    async def candidate_failed(self, candidate: Candidate, exc: Exception) -> None:
        async with self._lock:
            _candidate_failed_progress(self._builtin, candidate, exc)

    def candidate_stopped(self, candidate: Candidate) -> None:
        # WHY sync and no lock: a cancelled task must not await again; see `connection`.
        _candidate_stopped_progress(self._builtin, candidate)

    def raised_by_caller(self, exc: BaseException) -> bool:
        # WHY no lock: one event loop drives this observer, and this reads with no await.
        return any(exc is recorded for recorded in self._caller_errors)

    def reconcile(self, report: Report) -> None:
        _reconcile_progress(self._builtin, report)

    def abort(self, exc: BaseException) -> None:
        _abort_progress(self._builtin, exc)

    def close(self) -> None:
        _close_progress(self._builtin)


@dataclass(frozen=True, slots=True)
class _BoundObserver[R]:
    """One Candidate's `on_event`, which is also a `_ConnectionListener` (spec 2026-09-28 R4).

    INVARIANT: a connection notice reaches the built-in progress output only — never the
    user's callback, whose contract is the public Event set (spec R5).
    """

    observe: Callable[[Event], R]
    notify: Callable[[_ConnectionNotice], None]

    def __call__(self, event: Event) -> R:
        return self.observe(event)

    def connection(self, notice: _ConnectionNotice) -> None:
        self.notify(notice)


def _connection_progress(
    observer: object | None, candidate: Candidate, notice: _ConnectionNotice
) -> None:
    # WHY optional: a custom or older renderer may not draw connection state at all.
    selected = getattr(observer, "connection", None)
    if callable(selected):
        _observe_progress(selected, candidate, notice)


def _candidate_failed_progress(
    observer: object | None, candidate: Candidate, exc: Exception
) -> None:
    # WHY optional: a custom or older renderer may not draw a per-Candidate failure; its
    # row then changes at the final `abort`, as before.
    selected = getattr(observer, "candidate_failed", None)
    if callable(selected):
        _observe_progress(selected, candidate, exc)


def _candidate_stopped_progress(observer: object | None, candidate: Candidate) -> None:
    selected = getattr(observer, "candidate_stopped", None)
    if callable(selected):
        _observe_progress(selected, candidate)


def _close_event_observer(observer: object) -> None:
    if isinstance(observer, (_SyncEventObserver, _AsyncEventObserver)):
        observer.close()


def _reconcile_event_observer(observer: object, report: Report) -> None:
    if isinstance(observer, (_SyncEventObserver, _AsyncEventObserver)):
        observer.reconcile(report)


def _conclude_evaluation(observer: object, report: Report, capture: bool) -> None:
    """Reconcile the progress observer, mark the report ready, then say what capture missed."""
    from screamingface._evaluation.results import _warn_if_not_captured
    from screamingface._results.lifecycle import mark_report

    _reconcile_event_observer(observer, report)
    mark_report(report, "ready")
    if capture:
        _warn_if_not_captured(report)


def _abort_event_observer(observer: object, exc: BaseException) -> None:
    if isinstance(observer, (_SyncEventObserver, _AsyncEventObserver)):
        observer.abort(exc)


def _close_progress(observer: object) -> None:
    close = getattr(observer, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        _logger.exception("ScreamingFace progress cleanup failed")


def _observe_candidate_progress(observer: object, candidate: Candidate, event: Event) -> None:
    selected = getattr(observer, "observe", None)
    if not callable(selected):
        _logger.error("ScreamingFace progress observer has no Candidate observation method")
        return
    _observe_progress(selected, candidate, event)


def _begin_candidate_progress(observer: object, candidate: Candidate) -> None:
    begin = getattr(observer, "begin", None)
    if not callable(begin):
        _logger.error("ScreamingFace progress observer has no Candidate begin method")
        return
    _observe_progress(begin, candidate)


def _reconcile_progress(observer: object | None, report: Report) -> None:
    if observer is None:
        return
    reconcile = getattr(observer, "reconcile", None)
    if not callable(reconcile):
        return
    try:
        reconcile(report)
    except Exception:
        _logger.exception("ScreamingFace progress reconciliation failed")
        _close_progress(observer)


def _abort_progress(observer: object | None, exc: BaseException) -> None:
    if observer is None:
        return
    abort = getattr(observer, "abort", None)
    if not callable(abort):
        _close_progress(observer)
        return
    try:
        abort(exc)
    except Exception:
        _logger.exception("ScreamingFace progress finalization failed")
        _close_progress(observer)


def _observe_progress(observer: Callable[..., object], *values: object) -> None:
    """Keep decorative progress output outside the Evaluation failure boundary."""

    try:
        observer(*values)
    except (OSError, ValueError):
        # Closed pipes and notebook streams must not cancel paid Engine work.
        return
    except Exception:
        # Progress is decorative, so an unexpected renderer defect must not abort paid work.
        # Log it rather than swallowing it: this path needs to remain diagnosable.
        _logger.exception("ScreamingFace progress rendering failed")


def _seeded_candidates(
    candidates: tuple[Candidate, ...],
    answer_seed: int | None,
) -> tuple[Candidate, ...]:
    """Stamp the run's declared sitting onto each compiled Candidate — identity when None.

    Side effect (U1, OME-1289): also warns about own-seed calls, once per evaluation, after
    compile and before any model-details lookup or submit. WHY here and not in the caller: the
    two evaluate functions are at ruff's statement limit.
    """
    if answer_seed is None:
        return candidates
    _warn_fixed_seed_sittings(candidates)
    return tuple(_with_answer_seed(candidate, answer_seed) for candidate in candidates)


def _captured_candidates(
    candidates: tuple[Candidate, ...],
    capture: bool,
) -> tuple[Candidate, ...]:
    """Stamp the request to capture a frozen copy onto each compiled Candidate — identity when off.

    FEATURE (OME-1307): each Candidate's run opens its own copy, so each result names its own.
    """
    if not capture:
        return candidates
    return tuple(_with_capture(candidate) for candidate in candidates)


def _cache_intent_candidates(
    candidates: tuple[Candidate, ...],
    use_cache: bool,
) -> tuple[Candidate, ...]:
    """Stamp a run's opt-out of the request cache onto each compiled Candidate — identity when on.

    FEATURE (OME-1311): `use_cache=False` covers every Candidate of the evaluation.
    """
    if use_cache:
        return candidates
    return tuple(_without_cache(candidate) for candidate in candidates)


def _warn_fixed_seed_sittings(candidates: tuple[Candidate, ...]) -> None:
    """Warn once per Candidate whose own-seed calls ignore the run seed (never a refusal).

    WHY: the Engine lets a call that sets its own ``seed`` keep it and applies the run's seed only
    to calls without one, so those calls send the same request in every sitting (OME-1038) and a
    mean and CI across sittings looks tighter than the model really is. INVARIANT: the text holds
    no run seed value, because Python shows a warning once per text and line, and a text that
    changed with the sitting would repeat in every sitting.
    """
    for candidate in candidates:
        if calls := _own_seed_calls(candidate):
            _warn_fixed_seed(candidate.name, calls)


def _warn_fixed_seed(name: str, calls: tuple[str, ...]) -> None:
    """Emit the one fixed-seed warning for ``calls`` of the Candidate ``name``.

    Shared by the Recipe path and the raw URL4 replay (``_evaluation/url4.py``), so the text is
    identical. ``skip_file_prefixes`` points the warning at the researcher's line.
    """
    warnings.warn(
        f"Candidate {name!r}: a run seed is set, but {_calls_phrase(calls)}. "
        "These calls send the same request in every sitting, so the spread across "
        "sittings is not measured. If you already pass different seeds= in each "
        "sitting, this is expected: silence it with "
        'warnings.filterwarnings("ignore", category=sf.FixedSeedSittingWarning). '
        "Otherwise drop the explicit seed.",
        FixedSeedSittingWarning,
        skip_file_prefixes=(SDK_PACKAGE_ROOT,),
    )


def _own_seed_calls(candidate: Candidate) -> tuple[str, ...]:
    """Each compiled model call whose resolved params carry a ``seed``, as ``id (label)``.

    A consistency sample call (kind ``sample``, E4b part 7 P18) is left out: its seed is part of
    the method, so the author cannot drop it.
    """
    operations = {operation.id: operation for operation in candidate.operations}
    return tuple(
        f"{assignment.operation_id} ({operations[assignment.operation_id].label})"
        for assignment in candidate.parameter_assignments
        if _SEED_PARAM in assignment.params and operations[assignment.operation_id].kind != "sample"
    )


def _calls_phrase(calls: tuple[str, ...]) -> str:
    """Name the calls with the right number; a long list keeps its first few and a count."""
    shown = ", ".join(calls[:_NAMED_CALLS])
    if len(calls) > _NAMED_CALLS:
        shown += f", and {len(calls) - _NAMED_CALLS} more"
    if len(calls) == 1:
        return f"1 call sets its own seed: {shown}"
    return f"{len(calls)} calls set their own seed: {shown}"


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


__all__: list[str] = []


@contextmanager
def _prepared_results(transport, evaluation, candidates) -> Iterator[None]:
    from screamingface._results.lifecycle import evaluation_operation
    from screamingface.errors import ExecutionError

    try:
        path = (
            transport.prepare_results(evaluation, candidates)
            if isinstance(transport, _ResultPersistence)
            else None
        )
        # INVARIANT: saved Candidate recovery/display/export cannot finish its Evaluation.
        with evaluation_operation(
            {path} if path is not None else set(),
            "running",
            (ExecutionError,),
            handled_error=lambda exc: (
                isinstance(exc, ExecutionError) and exc.code == "candidates_failed"
            ),
        ):
            yield
    finally:
        # INVARIANT: cancellation, or a failure to save the membership, retires the membership
        # and the Run bindings of candidates never scheduled.
        finish = getattr(transport, "finish_results", None)
        if callable(finish):
            finish(candidates)

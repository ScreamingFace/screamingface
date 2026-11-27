"""The capability check of a submission, in the Evaluation runner (C12, Unit 6).

FEATURE: the capability gate. A plan that needs Engine capabilities reads them once, fresh, after
it compiled and before the Model listing, the token mint, registration, the root GET and the
follow.
STORY: as a researcher, an Evaluation my Engine cannot run is refused before it costs anything,
and an ordinary Evaluation pays no extra request for a check it does not need.

INVARIANT: an empty requirement never asks the Engine for its capabilities. Today every public
caller requires none; a later Router writer derives the IDs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from _route_answer_fixtures import answering, route, routed_result
from _run_transport import AsyncPlaying, ScriptedRun
from test_client_run import REPLAY_URL4, _AsyncReplayTransport, _ReplayTransport
from test_client_run import _engine as _catalogue
from test_evaluation_outcome import valid_outcome

import screamingface as sf
import screamingface._evaluation.runner as runner
from screamingface._core.ports import _AsyncRunSink, _RunOutcome, _RunSink
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface.errors import EngineCapabilityError
from screamingface.routing import RoutedAnswer

_BASE = "https://engine.example"
_CAPABILITIES = "GET /v1/capabilities"
_BENCHMARK = "GET /v1/benchmarks/draco"
_MODELS = "GET /v1/models"
_ROUTER = frozenset({"router-v1"})
_CANDIDATE = sf.Model("provider/opus", name="opus")
_TWINS = pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])


def _document(*ids: str) -> httpx.Response:
    body = {"object": "engine_capabilities", "contract": "engine-capabilities-v1"}
    return httpx.Response(200, json={**body, "capabilities": list(ids)})


class _Engine:
    """The catalogue fixture, plus one scripted capability answer per read; logs each request."""

    def __init__(self, log: list[str], *answers: httpx.Response) -> None:
        self.log = log
        self._answers = list(answers)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.log.append(f"{request.method} {request.url.path}")
        if request.url.path == "/v1/capabilities":
            return self._answers.pop(0)
        return _catalogue(request)


class _Run(ScriptedRun):
    """The run port. The real one mints, posts `/runs` and opens the root GET inside
    `register_run` and `follow_run`, so logging both shows whether any of that was reached."""

    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        return valid_outcome(candidate.name)

    def register_run(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> str:
        self.log.append("register detached" if detach else "register")
        return super().register_run(evaluation, candidates, detach=detach, deadline_s=deadline_s)

    def follow_run(self, run_id: str, candidates: tuple[Candidate, ...], sink: _RunSink) -> None:
        self.log.append("follow")
        super().follow_run(run_id, candidates, sink)


class _AsyncRun(AsyncPlaying):
    def __init__(self, log: list[str]) -> None:
        super().__init__(_Run(log))
        self.log = log

    async def follow_run(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _AsyncRunSink
    ) -> None:
        self.log.append("follow")
        await super().follow_run(run_id, candidates, sink)


def _call(
    client: Any, required: frozenset[str], *, detach: bool = False, reader: bool = True
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """What `Client.evaluate` hands the runner for one Model on draco, plus the capability gate."""

    arguments = (
        client._benchmark_resources.load,
        client._transport,
        client.models._load,
        client.models.get,
        _CANDIDATE,
        "draco",
        None,
        None,
        False,
    )
    options = {
        "load_operators": client._operator_catalog.load,
        "detach": detach,
        "required_capabilities": required,
        "require_capabilities": client._capabilities.require if reader else None,
    }
    return arguments, options


def _evaluated(
    log: list[str],
    answers: list[httpx.Response],
    submissions: list[dict[str, Any]],
    *,
    asynchronous: bool,
) -> list[object]:
    """Each submission's Report, run id or refusal, through the runner of one composed Client."""

    engine = httpx.MockTransport(_Engine(log, *answers))
    if asynchronous:
        return asyncio.run(_evaluated_async(log, engine, submissions))
    outcomes: list[object] = []
    with sf.Client(engine_url=_BASE, http_transport=engine, run_transport=_Run(log)) as client:
        for submission in submissions:
            arguments, options = _call(client, **submission)
            try:
                outcomes.append(runner.evaluate_sync(*arguments, **options))
            except sf.ScreamingFaceError as exc:
                outcomes.append(exc)
    return outcomes


async def _evaluated_async(
    log: list[str], engine: httpx.MockTransport, submissions: list[dict[str, Any]]
) -> list[object]:
    outcomes: list[object] = []
    async with sf.AsyncClient(
        engine_url=_BASE, http_transport=engine, run_transport=_AsyncRun(log)
    ) as client:
        for submission in submissions:
            arguments, options = _call(client, **submission)
            try:
                outcomes.append(await runner.evaluate_async(*arguments, **options))
            except sf.ScreamingFaceError as exc:
                outcomes.append(exc)
    return outcomes


# --- the runner ----------------------------------------------------------------------------------


@_TWINS
def test_an_empty_requirement_never_asks_and_keeps_the_request_sequence(asynchronous: bool) -> None:
    plain: list[str] = []
    gated: list[str] = []

    (report,) = _evaluated(plain, [], [{"required": frozenset()}], asynchronous=asynchronous)
    (passed,) = _evaluated(
        gated, [_document("router-v1")], [{"required": _ROUTER}], asynchronous=asynchronous
    )

    assert isinstance(report, sf.Report) and isinstance(passed, sf.Report)
    assert _CAPABILITIES not in plain
    assert plain[:2] == [_BENCHMARK, _MODELS]
    assert plain[-2:] == ["register", "follow"]
    # INVARIANT: the check adds exactly one read, and nothing else moves.
    assert [line for line in gated if line != _CAPABILITIES] == plain


@_TWINS
def test_a_present_id_costs_one_read_after_compiling_and_before_the_model_listing(
    asynchronous: bool,
) -> None:
    log: list[str] = []

    (report,) = _evaluated(
        log, [_document("router-v1")], [{"required": _ROUTER}], asynchronous=asynchronous
    )

    assert isinstance(report, sf.Report)
    assert log[:3] == [_BENCHMARK, _CAPABILITIES, _MODELS]
    assert log.count(_CAPABILITIES) == 1
    assert (log.count("register"), log.count("follow")) == (1, 1)


@_TWINS
@pytest.mark.parametrize("detach", [False, True], ids=["followed", "detached"])
def test_a_missing_id_is_refused_before_any_model_call_mint_or_registration(
    asynchronous: bool, detach: bool
) -> None:
    log: list[str] = []

    (refused,) = _evaluated(
        log, [_document()], [{"required": _ROUTER, "detach": detach}], asynchronous=asynchronous
    )

    assert isinstance(refused, EngineCapabilityError)
    assert refused.details == {"path": "/v1/capabilities", "missing": ["router-v1"]}
    # The run port (mint, POST /runs, root GET, follow) and the Model calls are never reached.
    assert log == [_BENCHMARK, _CAPABILITIES]


@_TWINS
def test_a_detached_submission_with_the_id_registers_once_and_follows_nothing(
    asynchronous: bool,
) -> None:
    log: list[str] = []

    (run_id,) = _evaluated(
        log,
        [_document("router-v1")],
        [{"required": _ROUTER, "detach": True}],
        asynchronous=asynchronous,
    )

    assert isinstance(run_id, str)
    assert log[:3] == [_BENCHMARK, _CAPABILITIES, _MODELS]
    assert log[-1] == "register detached"
    assert "follow" not in log


@_TWINS
def test_each_submission_reads_again_and_a_withdrawn_id_refuses_the_next(
    asynchronous: bool,
) -> None:
    log: list[str] = []

    first, second = _evaluated(
        log,
        [_document("router-v1"), _document()],
        [{"required": _ROUTER}, {"required": _ROUTER}],
        asynchronous=asynchronous,
    )

    assert isinstance(first, sf.Report)
    assert isinstance(second, EngineCapabilityError)
    assert log.count(_CAPABILITIES) == 2
    assert log.count("register") == 1
    assert log[-1] == _CAPABILITIES


@_TWINS
def test_a_requirement_without_a_reader_fails_closed(asynchronous: bool) -> None:
    log: list[str] = []

    (refused,) = _evaluated(
        log, [], [{"required": _ROUTER, "reader": False}], asynchronous=asynchronous
    )

    assert isinstance(refused, EngineCapabilityError)
    assert refused.details == {"missing": ["router-v1"]}
    assert log == [_BENCHMARK]


# --- composition: each Client hands its runner a reader of its own Engine, and no requirement ---


@_TWINS
def test_evaluate_hands_the_runner_a_reader_of_its_engine_and_no_requirement(
    asynchronous: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    passed: dict[str, Any] = {}
    sentinel = object()

    def capture(*_arguments: Any, **options: Any) -> object:
        passed.update(options)
        return sentinel

    async def capture_async(*arguments: Any, **options: Any) -> object:
        return capture(*arguments, **options)

    monkeypatch.setattr(runner, "evaluate_sync", capture)
    monkeypatch.setattr(runner, "evaluate_async", capture_async)
    log: list[str] = []
    engine = httpx.MockTransport(_Engine(log, _document("router-v1")))

    if asynchronous:
        evaluated = asyncio.run(_read_through_async(engine, log, passed))
    else:
        with sf.Client(engine_url=_BASE, http_transport=engine, run_transport=_Run(log)) as client:
            evaluated = client.evaluate(_CANDIDATE, benchmark="draco")
            passed["require_capabilities"](_ROUTER)

    assert evaluated is sentinel
    assert "required_capabilities" not in passed
    assert log == [_CAPABILITIES]


async def _read_through_async(
    engine: httpx.MockTransport, log: list[str], passed: dict[str, Any]
) -> object:
    async with sf.AsyncClient(
        engine_url=_BASE, http_transport=engine, run_transport=_AsyncRun(log)
    ) as client:
        evaluated = await client.evaluate(_CANDIDATE, benchmark="draco")
        await passed["require_capabilities"](_ROUTER)
    return evaluated


# --- the flows that need no capability make no capability request --------------------------------


@_TWINS
def test_an_ordinary_evaluation_makes_no_capability_request(asynchronous: bool) -> None:
    log: list[str] = []
    engine = httpx.MockTransport(_Engine(log))

    if asynchronous:
        report = asyncio.run(_evaluate_async(engine, _AsyncRun(log), _CANDIDATE, "draco"))
    else:
        with sf.Client(engine_url=_BASE, http_transport=engine, run_transport=_Run(log)) as client:
            report = client.evaluate(_CANDIDATE, benchmark="draco", progress=False)

    assert isinstance(report, sf.Report)
    assert _CAPABILITIES not in log
    assert log[-2:] == ["register", "follow"]


@_TWINS
def test_a_raw_url4_makes_no_capability_request(asynchronous: bool) -> None:
    log: list[str] = []
    engine = httpx.MockTransport(_Engine(log))

    if asynchronous:
        report = asyncio.run(_evaluate_async(engine, _AsyncReplayTransport(), REPLAY_URL4))
    else:
        with sf.Client(
            engine_url=_BASE, http_transport=engine, run_transport=_ReplayTransport()
        ) as client:
            report = client.evaluate(REPLAY_URL4, progress=False)

    assert isinstance(report, sf.Report)
    assert _CAPABILITIES not in log


async def _evaluate_async(
    engine: httpx.MockTransport, transport: Any, candidates: Any, benchmark: str | None = None
) -> object:
    async with sf.AsyncClient(
        engine_url=_BASE, http_transport=engine, run_transport=transport
    ) as client:
        if benchmark is None:
            return await client.evaluate(candidates, progress=False)
        return await client.evaluate(candidates, benchmark=benchmark, progress=False)


def test_route_answer_makes_no_capability_request() -> None:
    answer, requests = route(answering(200, routed_result()))

    assert isinstance(answer, RoutedAnswer)
    assert [request.url.path for request in requests] == ["/route-answer"]

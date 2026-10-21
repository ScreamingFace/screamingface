"""Execution errors surfaced by the single Client.evaluate operation."""

from __future__ import annotations

import json
import os
import signal
import threading
from datetime import UTC, datetime
from typing import NoReturn

import httpx
import pytest
from _model_parameter_fixtures import details as _model_details
from protocol_server import protocol_server
from url4 import RelExpr, expr, render, src, text

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._evaluation.benchmark import _CheckSurface
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.model import Candidate

BENCHMARK_URL4 = render(
    expr(
        src(
            RelExpr(path="/candidate", context="question", intent=text("$candidate")),
            name="answer",
            weight=0.0,
        ),
        src(
            RelExpr(path="/provider/judge", context="$answer", intent=text("Grade.")),
            name="grade",
            weight=0.0,
        ),
        intent=text("$grade"),
    )
)

BENCHMARK = {
    "schema": "screamingface.benchmark.v1",
    "id": "draco",
    "title": "DRACO",
    "description": "Fixture DRACO Benchmark.",
    "revision": "fixture-revision",
    "case_count": 1,
    "url4": BENCHMARK_URL4,
}

CANDIDATE_URL4 = compile_candidate(sf.Model("provider/opus", prompt="Answer.")).url4
assert CANDIDATE_URL4 is not None
REPLAY_URL4 = render(
    expr(
        src(text(CANDIDATE_URL4), name="candidate", weight=0.0),
        src("fixture", name="result", weight=0.0),
        intent=text("$result"),
    )
)
FUSION_CANDIDATE_URL4 = compile_candidate(
    sf.Fanout([sf.Model("provider/opus"), sf.Model("provider/sonnet")])
    >> sf.Synthesize("provider/synthesizer")
).url4
assert FUSION_CANDIDATE_URL4 is not None
FUSION_REPLAY_URL4 = render(
    expr(
        src(text(FUSION_CANDIDATE_URL4), name="candidate", weight=0.0),
        src("fixture", name="result", weight=0.0),
        intent=text("$result"),
    )
)
CORRECTIVE_CANDIDATE_URL4 = compile_candidate(
    sf.CorrectiveLoop(
        ["provider/member-a", "provider/member-b"],
        judge="provider/judge",
        max_rounds=2,
    ),
    check_surface=_CheckSurface(
        check_route="/benchmarks/ifeval/revision-1/check-surface",
        feedback_intent="feedback",
        expected_check_cost="free",
    ),
).url4
CORRECTIVE_REPLAY_URL4 = render(
    expr(
        src(text(CORRECTIVE_CANDIDATE_URL4), name="candidate", weight=0.0),
        src("fixture", name="result", weight=0.0),
        intent=text("$result"),
    )
)


def _model_row(model: str) -> dict[str, object]:
    return {
        "id": model,
        "object": "model",
        "owned_by": model.split("/", 1)[0],
        "supported_parameters": [],
        "supported_tools": [],
        "unsupported_parameter_behavior": "reject",
        "parameter_contract_url": f"/v1/model-parameters?model={model}",
    }


def _not_installed_response() -> httpx.Response:
    """The Engine's RFC 9457 404 for a model outside its world (OME-878)."""
    return httpx.Response(
        404,
        json={
            "type": "about:blank",
            "title": "Not Found",
            "detail": "the model is not installed on this Engine",
            "status": 404,
        },
    )


def _engine(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/models":
        response = httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    _model_row("provider/opus"),
                    _model_row("provider/judge"),
                ],
            },
        )
    elif request.url.path == "/v1/benchmarks/draco":
        response = httpx.Response(200, json=BENCHMARK)
    elif request.url.path == "/v1/model-parameters":
        response = httpx.Response(200, json=_model_details(request.url.params["model"]))
    else:
        response = httpx.Response(404)
    return response


class _ForbiddenTransport:
    called = False

    def run(self, candidate: object, on_event: object) -> NoReturn:
        self.called = True
        raise AssertionError("unavailable Models must fail before execution")

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _InterruptibleTransport:
    """Two paid boundary calls that only cooperative cancellation can release promptly."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self.both_started = threading.Event()
        self.release = threading.Event()
        self.stopped_candidates: tuple[str, ...] = ()

    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        del on_event
        with self._lock:
            self._active.add(candidate.name)
            if len(self._active) == 2:
                self.both_started.set()
        try:
            self.release.wait(timeout=0.5)
            now = datetime.now(UTC)
            return _RunOutcome(
                run_id=candidate.name,
                started_at=now,
                completed_at=now,
                result_body="unused after interruption",
                media_type="text/plain",
                root_usage=None,
            )
        finally:
            with self._lock:
                self._active.remove(candidate.name)

    def cancel_active(self) -> None:
        with self._lock:
            self.stopped_candidates = tuple(sorted(self._active))
        self.release.set()

    def close(self) -> None:
        self.release.set()


class _ReplayTransport:
    def __init__(self) -> None:
        self.candidate: Candidate | None = None

    def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        del on_event
        self.candidate = candidate
        now = datetime.now(UTC)
        return _RunOutcome(
            run_id="replay-run",
            started_at=now,
            completed_at=now,
            result_body=json.dumps(
                {
                    "schema": "screamingface.candidate-result.v1",
                    "benchmark_id": "draco",
                    "benchmark_revision": "fixture-revision",
                    "case_count": 1,
                    "score": 1.0,
                    "coverage": 1.0,
                    "metrics": {},
                    "cases": [
                        {
                            "status": "scored",
                            "case_id": 1,
                            "input": "Fixture question",
                            "output": "Fixture answer",
                            "finish_reason": "stop",
                            "refusal": None,
                            "stop_reason": None,
                            "rounds_executed": None,
                            "grade": {
                                "method": "fixture",
                                "score": 1.0,
                                "metrics": {},
                                "checks": [],
                            },
                            "failures": [],
                            "metadata": {},
                        }
                    ],
                    "failures": [],
                }
            ),
            media_type="application/json",
            root_usage=None,
        )

    def cancel_active(self) -> None:
        pass

    def close(self) -> None:
        pass


class _AsyncReplayTransport(_ReplayTransport):
    async def run(self, candidate: Candidate, on_event: object) -> _RunOutcome:
        return super().run(candidate, on_event)

    async def cancel_active(self) -> None:
        pass

    async def close(self) -> None:
        pass


def test_evaluate_replays_a_complete_url4_without_recompiling_it() -> None:
    transport = _ReplayTransport()

    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        report = client.evaluate(REPLAY_URL4, progress=False)

    assert transport.candidate is not None
    assert transport.candidate.url4 == REPLAY_URL4
    assert report.benchmark == sf.BenchmarkInfo(
        id="draco",
        revision="fixture-revision",
        case_count=1,
    )
    assert report.candidates.only.name == "opus"
    assert report.candidates.only.kind == "model"
    assert report.candidates.only.models == ("provider/opus",)
    assert report.candidates.only.url4 == REPLAY_URL4


def test_evaluate_url4_reconstructs_the_embedded_fusion_projection() -> None:
    transport = _ReplayTransport()

    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    ) as client:
        report = client.evaluate(FUSION_REPLAY_URL4, progress=False)

    candidate = report.candidates.only
    assert candidate.name == "opus+sonnet"
    assert candidate.kind == "fusion"
    assert candidate.models == (
        "provider/opus",
        "provider/sonnet",
        "provider/synthesizer",
    )
    assert [member.name for member in candidate.members] == ["opus", "sonnet"]
    assert [operation.kind for operation in candidate.operations] == [
        "model",
        "model",
        "synthesis",
    ]


def test_evaluate_url4_replays_a_corrective_recipe_without_recompiling_it() -> None:
    def corrective_engine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        _model_row("provider/member-a"),
                        _model_row("provider/member-b"),
                        _model_row("provider/judge"),
                    ],
                },
            )
        return _engine(request)

    transport = _ReplayTransport()
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(corrective_engine),
        run_transport=transport,
    ) as client:
        report = client.evaluate(CORRECTIVE_REPLAY_URL4, progress=False)

    assert transport.candidate is not None
    assert transport.candidate.url4 == CORRECTIVE_REPLAY_URL4
    candidate = report.candidates.only
    assert candidate.kind == "corrective_loop"
    assert candidate.models == (
        "provider/member-a",
        "provider/member-b",
        "provider/judge",
    )


def test_evaluate_url4_rejects_a_corrective_retry_call_hidden_from_its_recipe() -> None:
    first, rest = CORRECTIVE_REPLAY_URL4.split("/provider/member-a", 1)
    tampered_evaluation = (
        first + "/provider/member-a" + rest.replace("/provider/member-a", "/provider/hidden", 1)
    )
    transport = _ReplayTransport()

    with (
        sf.Client(
            engine_url="https://engine.example",
            http_transport=httpx.MockTransport(_engine),
            run_transport=transport,
        ) as client,
        pytest.raises(ValueError, match="does not match its Recipe metadata"),
    ):
        client.evaluate(sf.Url4(tampered_evaluation), progress=False)

    assert transport.candidate is None


@pytest.mark.parametrize("options", [{"benchmark": "draco"}, {"limit": 1}])
def test_evaluate_url4_rejects_recompilation_options(options: dict[str, object]) -> None:
    transport = _ReplayTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    )

    with client, pytest.raises(TypeError, match="must not be passed"):
        client.evaluate(REPLAY_URL4, progress=False, **options)  # type: ignore[call-overload]

    assert transport.candidate is None


@pytest.mark.asyncio
async def test_async_evaluate_replays_the_same_complete_url4() -> None:
    transport = _AsyncReplayTransport()
    client = sf.AsyncClient(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=transport,
    )

    report = await client.evaluate(REPLAY_URL4, progress=False)
    await client.aclose()

    assert transport.candidate is not None
    assert transport.candidate.url4 == REPLAY_URL4
    assert report.candidates.only.url4 == REPLAY_URL4


def test_evaluate_rejects_an_unavailable_model_before_execution() -> None:
    def engine_without_candidate(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [_model_row("provider/judge")],
                },
            )
        # Fixture fidelity (OME-878/review F10): a real Engine 404s details for a
        # model outside its world; the SDK's availability probe receives that 404
        # instead of the old pre-probe listing refusal. Assertions below unchanged.
        if (
            request.url.path == "/v1/model-parameters"
            and request.url.params["model"] == "missing/model"
        ):
            return _not_installed_response()
        return _engine(request)

    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine_without_candidate),
        run_transport=transport,
    )

    with (
        client,
        pytest.raises(
            sf.PlanningError,
            match="Model 'missing/model' is not available on this Engine",
        ) as caught,
    ):
        client.evaluate(sf.Model("missing/model"), benchmark="draco")

    assert caught.value.code == "model_unavailable"
    assert caught.value.permanent is True
    assert caught.value.details == {"models": ["missing/model"]}
    assert transport.called is False


def test_evaluate_rejects_an_unavailable_fusion_model_before_execution() -> None:
    def engine_without_synthesis(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        _model_row(model)
                        for model in ("provider/opus", "provider/gpt", "provider/judge")
                    ],
                },
            )
        # Fixture fidelity (OME-878/review F10): same as above — the probe for the
        # unlisted synthesizer receives a real Engine's not-installed 404.
        if (
            request.url.path == "/v1/model-parameters"
            and request.url.params["model"] == "provider/synthesis"
        ):
            return _not_installed_response()
        return _engine(request)

    fusion = sf.Fanout(
        [sf.Model("provider/opus"), sf.Model("provider/gpt")], name="panel"
    ) >> sf.Synthesize("provider/synthesis")
    transport = _ForbiddenTransport()
    client = sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(engine_without_synthesis),
        run_transport=transport,
    )

    with (
        client,
        pytest.raises(
            sf.PlanningError,
            match="Model 'provider/synthesis' is not available on this Engine",
        ),
    ):
        client.evaluate(fusion, benchmark="draco")

    assert transport.called is False


def test_evaluate_reports_an_unreachable_execution_transport() -> None:
    with sf.Client(
        engine_url="http://127.0.0.1:1",
        http_transport=httpx.MockTransport(_engine),
    ) as client:
        with pytest.raises(sf.EngineUnavailableError) as caught:
            client.evaluate(
                sf.Model("provider/opus"),
                benchmark="draco",
                progress=False,
            )

    assert caught.value.code == "engine_unreachable"
    assert caught.value.permanent is False
    assert caught.value.engine_url == "http://127.0.0.1:1"


def test_interrupting_concurrent_candidates_stops_every_active_engine_run() -> None:
    transport = _InterruptibleTransport()

    def interrupt_after_both_runs_start() -> None:
        if transport.both_started.wait(timeout=1):
            os.kill(os.getpid(), signal.SIGINT)

    interrupter = threading.Thread(target=interrupt_after_both_runs_start, daemon=True)
    interrupter.start()
    with (
        sf.Client(
            engine_url="https://engine.example",
            http_transport=httpx.MockTransport(_engine),
            run_transport=transport,
        ) as client,
        pytest.raises(KeyboardInterrupt),
    ):
        client.evaluate(
            [
                sf.Model("provider/opus", name="left"),
                sf.Model("provider/opus", name="right"),
            ],
            benchmark="draco",
            progress=False,
        )
    interrupter.join(timeout=1)

    assert interrupter.is_alive() is False
    assert transport.stopped_candidates == ("left", "right")


def test_concurrent_interrupt_deletes_every_active_engine_capability() -> None:
    with protocol_server(mode="http_stop") as engine:

        def interrupt_after_both_runs_start() -> None:
            if engine.state.two_started.wait(timeout=1):
                os.kill(os.getpid(), signal.SIGINT)

        interrupter = threading.Thread(target=interrupt_after_both_runs_start, daemon=True)
        interrupter.start()
        with (
            sf.Client(
                engine_url=engine.url,
                http_transport=httpx.MockTransport(_engine),
            ) as client,
            pytest.raises(KeyboardInterrupt),
        ):
            client.evaluate(
                [
                    sf.Model("provider/opus", name="left"),
                    sf.Model("provider/opus", name="right"),
                ],
                benchmark="draco",
                progress=False,
            )
        interrupter.join(timeout=1)

    assert interrupter.is_alive() is False
    assert len(engine.state.minted_tokens) == 2
    assert sorted(engine.state.deleted_tokens) == sorted(engine.state.minted_tokens)


@pytest.mark.asyncio
async def test_async_evaluate_reports_the_same_unreachable_execution_transport() -> None:
    client = sf.AsyncClient(
        engine_url="http://127.0.0.1:1",
        http_transport=httpx.MockTransport(_engine),
    )

    with pytest.raises(sf.EngineUnavailableError) as caught:
        await client.evaluate(
            sf.Model("provider/opus"),
            benchmark="draco",
            progress=False,
        )
    await client.aclose()

    assert caught.value.retryable is True
    assert caught.value.engine_url == "http://127.0.0.1:1"


@pytest.mark.asyncio
async def test_async_concurrent_cancellation_deletes_every_active_engine_capability() -> None:
    """The asynchronous sibling of the synchronous interrupt test above.

    INVARIANT: an interrupted Evaluation must leave no Run billing. The in-band ai.url4.stop
    frame is dispatched from a task that is already being cancelled and cannot be sent at all
    when the socket is what failed, so the REST capability delete is the real guarantee.
    """

    import asyncio

    with protocol_server(mode="http_stop") as engine:
        client = sf.AsyncClient(
            engine_url=engine.url,
            http_transport=httpx.MockTransport(_engine),
        )
        task = asyncio.create_task(
            client.evaluate(
                [
                    sf.Model("provider/opus", name="left"),
                    sf.Model("provider/opus", name="right"),
                ],
                benchmark="draco",
                progress=False,
            )
        )
        started = await asyncio.to_thread(engine.state.two_started.wait, 5)
        assert started is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await client.aclose()

    assert len(engine.state.minted_tokens) == 2
    assert sorted(engine.state.deleted_tokens) == sorted(engine.state.minted_tokens)

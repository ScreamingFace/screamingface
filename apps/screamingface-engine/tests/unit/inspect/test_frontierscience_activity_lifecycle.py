"""FrontierScience's real scorer and connector retain the full case lifecycle."""

import json

import httpx
import pytest

pytest.importorskip("inspect_ai")

from screamingface_engine.activity.observer import ActivityObserver  # noqa: E402
from screamingface_engine.benchmarks.definition import link_candidate  # noqa: E402
from screamingface_engine.observations import RunObservations  # noqa: E402
from screamingface_engine.world.candidate_adapter import install_candidate_invocation  # noqa: E402
from screamingface_engine.world.config import ModelSpec  # noqa: E402
from screamingface_engine.world.connector import (  # noqa: E402
    AigatewayConfig,
    build_aigateway_world,
)
from screamingface_engine_inspect.benchmarks import imported_benchmark  # noqa: E402
from url4.dag import run as execute  # noqa: E402
from url4.observe import Log  # noqa: E402


def _benchmark(tmp_path, format_name):
    benchmark = imported_benchmark("frontierscience")
    root = tmp_path / benchmark.benchmark.id
    (root / "targets").mkdir(parents=True)
    (root / "cases.json").write_text(json.dumps([{"id": 1, "input": "Explain."}]))
    (root / "targets" / "1.json").write_text(
        json.dumps({"target": "Reference", "metadata": {"format": format_name}})
    )
    return benchmark


def _transport(format_name, calls, judge_model):
    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload["model"])
        answer = "Answer"
        if payload["model"] == judge_model:
            answer = "VERDICT: 10" if format_name == "research" else "GRADE: C"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}
        )

    return httpx.MockTransport(respond)


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["olympic", "research"])
@pytest.mark.parametrize("fusion", [False, True], ids=["solo", "fusion"])
async def test_frontierscience_limit_one_activity(tmp_path, format_name, fusion):
    benchmark = _benchmark(tmp_path, format_name)
    calls = []
    judge_model = "openrouter/openai/gpt-5.4"
    events = []

    class Collector:
        def on_event(self, event):
            if isinstance(event, Log) and "sf.activity.kind" in event.attributes:
                events.append(dict(event.attributes))

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=_transport(format_name, calls, judge_model)
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                base_url="http://gateway",
                default_model="writer",
                models=tuple(
                    ModelSpec(id=name) for name in ("writer", "writer-b", "synth", judge_model)
                ),
                allow_outbound=False,
            ),
            client=client,
        )
        install_candidate_invocation(world.node)
        benchmark.benchmark.install(world.node, tmp_path)
        candidate = "(answer:0.0:/writer($input)!'Answer')!'$answer'"
        if fusion:
            candidate = (
                "(a:0.0:/writer($input)!'Answer',b:0.0:/writer-b($input)!'Answer',"
                "answer:0.0:/synth($a,$b)!'Synthesize')!'$answer'"
            )
        run = RunObservations((ActivityObserver,))
        try:
            with run.bind():
                result = json.loads(
                    await execute(
                        link_candidate(candidate, benchmark.benchmark.protocol(1)),
                        io=world.node,
                        observer=Collector(),
                    )
                )
        finally:
            await run.aclose()
            await world.aclose()
    assert result["score"] == 1.0, result
    assert len(calls) == (4 if fusion else 2)
    _assert_events(events, judge_model)


def _assert_events(events, judge_model):
    model_events = [e for e in events if e.get("sf.activity.model_id")]
    assert model_events
    assert all(str(e.get("sf.activity.case_id")) == "1" for e in model_events), model_events
    judges = [e for e in model_events if e["sf.activity.model_id"] == judge_model]
    assert all(e.get("sf.activity.role") == "judge" for e in judges)
    terminals = [e for e in events if e["sf.activity.state"] == "completed"]
    verdicts = [e for e in terminals if e["sf.activity.kind"] == "grading"]
    assert len(verdicts) == 1
    assert verdicts[0]["sf.activity.case_id"] == 1
    assert events.index(judges[-1]) < events.index(verdicts[0])
    assert terminals[-1]["sf.activity.kind"] == "aggregation"


def _failed_member_response(failure):
    if failure == "error":
        return httpx.Response(
            400, json={"detail": {"code": "bad_request", "message": "Member failed"}}
        )
    message = {"content": ""}
    if failure == "refusal":
        message["refusal"] = "I cannot comply"
    else:
        message["reasoning"] = "Unfinished reasoning"
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": message, "finish_reason": "length" if failure == "cap" else "stop"}
            ]
        },
    )


def _quorum_transport(format_name, failure, calls, judge_model):
    ordinary = _transport(format_name, calls, judge_model)

    def respond(request):
        if json.loads(request.content)["model"] == "bad":
            calls.append("bad")
            return _failed_member_response(failure)
        return ordinary.handle_request(request)

    return httpx.MockTransport(respond)


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["olympic", "research"])
@pytest.mark.parametrize("failure", ["error", "refusal", "cap"])
@pytest.mark.parametrize("quorum", [2, 3], ids=["met", "unmet"])
async def test_frontierscience_quorum_failure_and_operation_accounting(
    tmp_path, format_name, failure, quorum
):
    from pathlib import Path

    # Generated by the Client compiler: two required members and one optional member.
    candidate = (Path(__file__).parents[1] / "data" / "fusion_quorum_candidate.url4").read_text()
    candidate = candidate.replace(";quorum=2", f";quorum={quorum}")
    benchmark = _benchmark(tmp_path, format_name)
    calls = []
    judge_model = "openrouter/openai/gpt-5.4"
    async with httpx.AsyncClient(
        base_url="http://gateway",
        transport=_quorum_transport(format_name, failure, calls, judge_model),
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                base_url="http://gateway",
                default_model="good-a",
                models=tuple(
                    ModelSpec(id=name) for name in ("good-a", "good-b", "bad", "synth", judge_model)
                ),
                allow_outbound=False,
            ),
            client=client,
        )
        install_candidate_invocation(world.node)
        benchmark.benchmark.install(world.node, tmp_path)
        observations = RunObservations((ActivityObserver,))
        try:
            with observations.bind():
                result = json.loads(
                    await execute(
                        link_candidate(candidate, benchmark.benchmark.protocol(1)), io=world.node
                    )
                )
        finally:
            await observations.aclose()
            await world.aclose()
    _assert_quorum_result(result, calls, judge_model, quorum, failure)


def _assert_quorum_result(result, calls, judge_model, quorum, failure):
    met = quorum == 2
    assert calls.count("synth") == int(met)
    assert calls.count(judge_model) == int(met)
    assert (result["score"] is not None) == met
    if not met:
        assert result["cases"][0]["status"] == "failed"
        assert "quorum" in result["cases"][0]["failures"][0]["message"].lower()
        return
    operations = {op["operation_id"]: op for op in result["cases"][0]["operations"]}
    assert set(operations) == {"op_model_1", "op_model_2", "op_model_3", "op_synthesis_1"}
    for name in ("op_model_1", "op_model_2"):
        assert operations[name]["output"] == "Answer"
        assert operations[name]["accounting"] is not None
    assert operations["op_model_3"]["output"] == ("" if failure == "refusal" else None)
    assert (operations["op_synthesis_1"]["output"] == "Answer") == met


def _scope_transport(seen):
    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        answers = {"draft": "DRAFT", "good-a": "A", "good-b": "B"}
        answer = answers.get(payload["model"], "Answer")
        if payload["model"] == "openrouter/openai/gpt-5.4":
            answer = "VERDICT: 10"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": answer}, "finish_reason": "stop"}]}
        )

    return httpx.MockTransport(respond)


@pytest.mark.asyncio
@pytest.mark.parametrize("composition", ["pipeline", "synthesizer"])
async def test_frontierscience_quorum_preserves_upstream_request_contents(tmp_path, composition):
    from pathlib import Path

    # WHY: a fixed successful fake reply lets grading pass even when model
    # requests contain literal compiler bindings. Check the actual gateway body.
    candidate = (
        (Path(__file__).parents[1] / "data" / f"fusion_quorum_{composition}.url4")
        .read_text()
        .strip()
    )
    benchmark = _benchmark(tmp_path, "research")
    seen = []
    async with httpx.AsyncClient(
        base_url="http://gateway", transport=_scope_transport(seen)
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                base_url="http://gateway",
                default_model="good-a",
                models=tuple(
                    ModelSpec(id=name)
                    for name in (
                        "draft",
                        "good-a",
                        "good-b",
                        "synth",
                        "inner",
                        "openrouter/openai/gpt-5.4",
                    )
                ),
                allow_outbound=False,
            ),
            client=client,
        )
        install_candidate_invocation(world.node)
        benchmark.benchmark.install(world.node, tmp_path)
        observations = RunObservations((ActivityObserver,))
        try:
            with observations.bind():
                result = json.loads(
                    await execute(
                        link_candidate(candidate, benchmark.benchmark.protocol(1)), io=world.node
                    )
                )
        finally:
            await observations.aclose()
            await world.aclose()
    assert result["cases"][0]["status"] == "scored"
    _assert_scope_requests(seen, composition)


def _assert_scope_requests(seen, composition):
    requests = {payload["model"]: payload for payload in seen}
    inputs = {
        name: next(
            message["content"] for message in payload["messages"] if message["role"] == "user"
        )
        for name, payload in requests.items()
    }
    if composition == "pipeline":
        assert [payload["model"] for payload in seen].count("draft") == 1
        assert inputs["draft"] == "Explain."
        assert inputs["good-a"] == inputs["good-b"] == "DRAFT"
    else:
        assert json.loads(inputs["good-b"]) == {"input": "Explain.", "outputs": "member_1: A"}


def _shared_route_transport(format_name, calls, seen, judge_model):
    ordinary = _transport(format_name, calls, judge_model)

    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        if payload["model"] == "same" and any(
            message["content"] == "FAIL" for message in payload["messages"]
        ):
            calls.append("same")
            return _failed_member_response("error")
        return ordinary.handle_request(request)

    return httpx.MockTransport(respond)


@pytest.mark.asyncio
@pytest.mark.parametrize("format_name", ["olympic", "research"])
async def test_quorum_failed_shared_route_member_does_not_borrow_an_answer(tmp_path, format_name):
    from pathlib import Path

    # WHY: route + parameters do not identify the successful member after an
    # optional failure; the scored artifact must not invent the missing answer.
    candidate = (
        (Path(__file__).parents[1] / "data" / "fusion_quorum_duplicate_members.url4")
        .read_text()
        .strip()
    )
    benchmark = _benchmark(tmp_path, format_name)
    calls, seen = [], []
    judge_model = "openrouter/openai/gpt-5.4"
    async with httpx.AsyncClient(
        base_url="http://gateway",
        transport=_shared_route_transport(format_name, calls, seen, judge_model),
    ) as client:
        world = await build_aigateway_world(
            AigatewayConfig(
                base_url="http://gateway",
                default_model="same",
                models=tuple(ModelSpec(id=name) for name in ("same", "synth", judge_model)),
                allow_outbound=False,
            ),
            client=client,
        )
        install_candidate_invocation(world.node)
        benchmark.benchmark.install(world.node, tmp_path)
        observations = RunObservations((ActivityObserver,))
        try:
            with observations.bind():
                result = json.loads(
                    await execute(
                        link_candidate(candidate, benchmark.benchmark.protocol(1)), io=world.node
                    )
                )
        finally:
            await observations.aclose()
            await world.aclose()
    _assert_shared_route_result(result, calls, seen)


def _assert_shared_route_result(result, calls, seen):
    assert result["cases"][0]["status"] == "scored"
    assert calls.count("same") == 2
    synthesis = next(payload for payload in seen if payload["model"] == "synth")
    user_input = next(m["content"] for m in synthesis["messages"] if m["role"] == "user")
    assert json.loads(user_input)["outputs"] == "member_2: Answer"
    operations = {op["operation_id"]: op for op in result["cases"][0]["operations"]}
    for name in ("op_model_1", "op_model_2"):
        assert operations[name]["output"] is None
        assert operations[name]["finish_reason"] is None
    assert operations["op_synthesis_1"]["output"] == "Answer"
    assert operations["op_synthesis_1"]["accounting"] is not None

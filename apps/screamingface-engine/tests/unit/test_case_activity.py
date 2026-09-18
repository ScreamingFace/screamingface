import asyncio

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.case_context import case_scope, current_case_id
from screamingface_engine.benchmarks.definition import candidate_call
from screamingface_engine.observations import ModelCall, RunObservations
from url4 import Text, iterate, render, src, struct
from url4.peer.server import Url4Node


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_case_envelope_preserves_actual_candidate_input(monkeypatch, structured):
    from screamingface_engine.benchmarks import candidate_adapter

    inputs = []

    async def evaluate(node, expression, input_text, **kwargs):
        inputs.append((input_text, current_case_id()))
        return "answer"

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    install_candidate_invocation(node)
    value = {"question": "$item.input", "reasoning": "$reasoning"} if structured else "$item.input"
    original = render(struct(value)) if isinstance(value, dict) else value
    row = struct({"id": "007", "input": 'Quotes " here\nkeep $literal'})
    for call in (
        candidate_call(original, web_search=False),
        candidate_call(value, web_search=False, case_id="$item.id"),
    ):
        expression = iterate(
            [row],
            body=(
                src(Text("prior answer"), name="reasoning", weight=0.0),
                src(call, name="result", weight=0.0),
            ),
            intent=Text("$result"),
        )
        await node.evaluate(render(expression), env={"candidate": "recipe"})
    assert inputs[0][0] == inputs[1][0]
    assert inputs[0][1] is None
    assert inputs[1][1] == "007"
    assert current_case_id() is None
    await node.aclose()


@pytest.mark.asyncio
async def test_concurrent_case_records_and_nested_run_isolation():
    events = []
    observer = ActivityObserver()
    run = RunObservations((lambda: observer,))

    def emit(body, attributes=None, **kwargs):
        events.append(attributes)

    async def execute(case_id):
        with case_scope(case_id):
            async with ModelCall("model", emit):
                await asyncio.sleep(0)
                async with ModelCall("nested-model", emit):
                    assert current_case_id() == case_id

    with run.bind():
        await asyncio.gather(execute("first"), execute("second"))
        with case_scope("outer"):
            inner = RunObservations(())
            with inner.bind():
                assert current_case_id() is None
            await inner.aclose()
            assert current_case_id() == "outer"
        async with ModelCall("unscoped", emit):
            pass
    await run.aclose()
    for model in ("model", "nested-model"):
        records = [r for r in events if r["sf.activity.model_id"] == model]
        assert {r["sf.activity.case_id"] for r in records} == {"first", "second"}
    assert all(
        "sf.activity.case_id" not in r for r in events if r["sf.activity.model_id"] == "unscoped"
    )


@pytest.mark.parametrize("error", [ValueError, asyncio.CancelledError])
def test_case_scope_resets_after_failure(error):
    with pytest.raises(error), case_scope(42):
        assert current_case_id() == 42
        raise error()
    assert current_case_id() is None


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "not-json",
        '{"input": 3, "case_id": 42}',
        '{"input": "question", "case_id": true}',
        '{"input": "question", "case_id": ""}',
        '{"input": "question", "case_id": 42, "extra": "private"}',
    ],
)
def test_invalid_case_envelopes_fail_without_echoing_payload(payload):
    from screamingface_engine.benchmarks.case_request import candidate_input
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request

    with pytest.raises(ResolutionError, match="Invalid candidate case context"):
        candidate_input(
            Request("/benchmarks/candidate", payload, "recipe", {"context_format": "case-v1"})
        )


def test_format_is_explicit_and_plain_json_input_is_not_mistaken_for_metadata():
    from screamingface_engine.benchmarks.case_request import candidate_input
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request

    text = '{"input": "question", "case_id": 42}'
    assert candidate_input(Request("/benchmarks/candidate", text, "recipe", {})) == (text, None)
    with pytest.raises(ResolutionError):
        candidate_input(
            Request("/benchmarks/candidate", text, "recipe", {"context_format": "other"})
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_unsafe_case_identifiers_do_not_leak_or_suppress_model_activity(enabled):
    events = []
    run = RunObservations((lambda: ActivityObserver(enabled=enabled),))
    with run.bind(), case_scope("private question with spaces"):
        async with ModelCall(
            "model", lambda body, attributes=None, **kwargs: events.append(attributes)
        ):
            pass
    await run.aclose()
    assert len(events) == (2 if enabled else 0)
    assert all("sf.activity.case_id" not in event for event in events)


def test_unlabelled_calls_mask_outer_case_and_restore_it():
    with case_scope("outer"):
        with case_scope(None):
            assert current_case_id() is None
        assert current_case_id() == "outer"
    assert current_case_id() is None


@pytest.mark.asyncio
async def test_real_candidate_execution_emits_case_metadata_without_prompt_metadata():
    from url4 import RelExpr

    events, prompts = [], []
    node = Url4Node()
    install_candidate_invocation(node)

    def emit(body, attributes=None, **kwargs):
        events.append(attributes)

    @node.endpoint("/model")
    async def model(request):
        prompts.append(request.context)
        async with ModelCall("model", emit):
            return "answer"

    run = RunObservations((ActivityObserver,))
    call = candidate_call("$item.input", case_id="$item.id", web_search=False)
    expression = iterate(
        [struct({"id": "case-42", "input": "original question"})],
        body=(src(call, name="result", weight=0.0),),
        intent=Text("$result"),
    )
    recipe = render(RelExpr(path="/model", context="$input", intent=Text("Answer")))
    with run.bind():
        await node.evaluate(render(expression), env={"candidate": recipe})
    await run.aclose()
    await node.aclose()
    assert prompts == ["original question"]
    assert [r["sf.activity.state"] for r in events] == ["started", "completed"]
    assert all(r["sf.activity.case_id"] == "case-42" for r in events)

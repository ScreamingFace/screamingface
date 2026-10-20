import asyncio

import pytest

from screamingface_engine.activity.observer import ActivityObserver
from screamingface_engine.benchmarks.case_context import case_scope, current_case_id
from screamingface_engine.benchmarks.definition import candidate_invocation
from screamingface_engine.observations import ModelCall, RunObservations
from screamingface_engine.world.candidate_adapter import install_candidate_invocation
from url4 import Text, iterate, render, src, struct
from url4.peer.server import Url4Node


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_case_envelope_preserves_actual_candidate_input(monkeypatch, structured):
    from screamingface_engine.world import candidate_adapter

    inputs = []

    async def evaluate(node, expression, input_text, **kwargs):
        inputs.append((input_text, current_case_id()))
        return "answer"

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    install_candidate_invocation(node)
    # WHY (spec 2026-10-20 R2): the model input is the quoted intent; the Case facts are
    # sources beside the Recipe and never reach it.
    prompt = "$item.input / $reasoning" if structured else "$item.input"
    row = struct({"id": "007", "input": 'Quotes " here\nkeep $literal'})
    for call in (
        candidate_invocation(prompt, web_search=False),
        candidate_invocation(prompt, web_search=False, case_count=1),
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
    expected = 'Quotes " here\nkeep $literal'
    assert inputs[0][0] == (f"{expected} / prior answer" if structured else expected)
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
    "context",
    [
        "",
        "case_id: 42",
        "recipe: ",
        "case_index: 0\nrecipe: r",
        "case_id: \nrecipe: r",
        "case_id: 42\nextra: private\nrecipe: r",
        "case_id: 42\ncase_count: 1\ncase_index: 0\nrecipe: r",
    ],
)
def test_invalid_candidate_sources_fail_without_echoing_payload(context):
    # WHY (spec 2026-10-20 R2): the facts and the Recipe arrive as packed source lines —
    # none, the identity, or identity and position, in that order, then the Recipe last.
    from screamingface_engine.benchmarks.case_request import candidate_request
    from url4.core.errors import ResolutionError
    from url4.peer.server import Request

    with pytest.raises(ResolutionError, match="Invalid Candidate Invocation sources") as caught:
        candidate_request(Request("/benchmarks/candidate", context, "question", {}))
    assert "private" not in str(caught.value)


def test_the_intent_is_the_input_and_the_recipe_is_everything_after_its_name():
    from screamingface_engine.benchmarks.case_request import candidate_request
    from url4.peer.server import Request

    text = '{"input": "question", "case_id": 42}'
    plain = candidate_request(Request("/benchmarks/candidate", "recipe: r", text, {}))
    assert (plain.input_text, plain.recipe, plain.case_id, plain.position) == (
        text,
        "r",
        None,
        None,
    )
    recipe = "(a:0.0:/m($input)!'x')!'$a'\ncase_id: 9\nrecipe: nested"
    numbered = candidate_request(
        Request(
            "/benchmarks/candidate",
            f"case_id: 42\ncase_index: 0\ncase_count: 3\nrecipe: {recipe}",
            "question",
            {},
        )
    )
    assert (numbered.recipe, numbered.case_id, numbered.position) == (recipe, "42", (1, 3))


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
    call = candidate_invocation("$item.input", web_search=False, case_count=1)
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


@pytest.mark.asyncio
@pytest.mark.parametrize("case_id", [42, "007"])
async def test_transport_case_identity_joins_results_by_string_without_numeric_coercion(
    monkeypatch, case_id
):
    from screamingface_engine.world import candidate_adapter

    observed = []

    async def evaluate(node, expression, input_text, **kwargs):
        observed.append(current_case_id())
        return "answer"

    monkeypatch.setattr(candidate_adapter, "evaluate_candidate_recipe", evaluate)
    node = Url4Node()
    install_candidate_invocation(node)
    expression = iterate(
        [struct({"id": case_id, "input": "question"})],
        body=(
            src(
                candidate_invocation("$item.input", web_search=False, case_count=1),
                name="result",
            ),
        ),
        intent=Text("$result"),
    )
    await node.evaluate(render(expression), env={"candidate": "recipe"})
    await node.aclose()
    assert observed == [str(case_id)]

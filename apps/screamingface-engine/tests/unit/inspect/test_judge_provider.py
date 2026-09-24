# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against. Only unresolved-import
# reporting is relaxed; every other diagnostic stays on, and with the extra installed
# these imports type-check normally.
"""The gateway-backed judge provider — an imported eval's judge is one of OUR calls.

Think of the provider as a switchboard plug: an imported scorer asks inspect for a
model named ``screamingface/<gateway-model-id>``, and instead of dialing a provider
directly, the call comes out of OUR wall socket — the node route the aigateway
connector serves, where it is routed, metered, and identity-stamped like every other
model call in the run (OME-1240).

INVARIANT the suite defends: a judge call NEVER leaves the engine except through the
node's declared model route. No transport bound → the Case fails by name; a gateway
refusal → the Case fails by name; the judge's chat messages cross as the candidate
input envelope, byte-decodable by the connector.

Runs only with the `inspect` extra installed (`uv run --extra inspect pytest …`);
the plain gate run skips it, which is exactly the extra-less contract.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

inspect_ai_model = pytest.importorskip("inspect_ai.model")

from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model  # noqa: E402
from inspect_ai.scorer import Target, model_graded_qa  # noqa: E402
from inspect_ai.solver import TaskState  # noqa: E402

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA  # noqa: E402
from screamingface_engine.benchmarks.spine.payloads import TextPayload  # noqa: E402
from screamingface_engine.benchmarks.spine.scored import GradeRequest  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
)
from screamingface_engine_inspect.shim import inspect_grade_case  # noqa: E402
from url4.wire.subrequest import (  # noqa: E402
    decode_subrequest_http,
    extract_expression_params,
)


class _RecordingFetch:
    """A fake node fetch: records every target, answers with a fixed judge reply."""

    def __init__(self, reply: str = "GRADE: C") -> None:
        self.targets: list[str] = []
        self.reply = reply

    async def __call__(self, target: str) -> str:
        self.targets.append(target)
        return self.reply


def _request(answer: str = "Paris is the capital of France.") -> GradeRequest:
    return GradeRequest(
        case_id=3,
        input=TextPayload(text="What is the capital of France?"),
        answer=TextPayload(text=answer),
        row={"case": {"status": "answered"}},
        material={"target": "Paris"},
    )


def _decoded_call(target: str) -> tuple[str, dict[str, Any], str, str]:
    """Split one recorded fetch target into (path, params, context, intent) with
    the wire codec's OWN decoders — the same pair the node's dispatch runs."""

    path, _, query = target.partition("?")
    params, q = extract_expression_params(query)
    assert q is not None
    context, intent = decode_subrequest_http(q)
    return path, dict(params), context, intent


@pytest.mark.asyncio
async def test_the_judge_call_rides_the_declared_route_with_pinned_params() -> None:
    """The provider's whole wire contract: route, pinned params, chat envelope."""

    fetch = _RecordingFetch()
    transport = JudgeTransport(fetch=fetch, params=(("temperature", "0"),))
    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(transport):
        output = await model.generate(
            [
                ChatMessageSystem(content="You are a strict grader."),
                ChatMessageUser(content="Grade this answer."),
            ]
        )
    assert output.completion == "GRADE: C"
    assert len(fetch.targets) == 1
    path, params, context, intent = _decoded_call(fetch.targets[0])
    # INVARIANT: the model name's tail IS the gateway route — no second mapping.
    assert path == "/judge-4"
    assert params["temperature"] == "0"
    # The judge's messages cross as the candidate input envelope, connector-decodable.
    envelope: dict[str, Any] = json.loads(context)
    assert envelope["schema"] == CANDIDATE_INPUT_SCHEMA
    assert envelope["messages"] == [
        {"role": "system", "content": "You are a strict grader."},
        {"role": "user", "content": "Grade this answer."},
    ]
    assert intent == ""


@pytest.mark.asyncio
async def test_model_graded_qa_grades_through_the_gateway_seam() -> None:
    """The honesty proof: inspect's REAL judge scorer grades via the provider,
    zero adapter code in the scorer's own path."""

    fetch = _RecordingFetch(reply="The answer names Paris.\n\nGRADE: C")
    scorer = model_graded_qa(model="screamingface/judge-4")
    with bound_judge_transport(JudgeTransport(fetch=fetch)):
        outcome = await inspect_grade_case(scorer)(_request())
    assert outcome.failure_code is None
    assert outcome.score == 1.0
    # The judge's words survive into the evidence verbatim (audit trail).
    assert "The answer names Paris." in str(outcome.checks)


@pytest.mark.asyncio
async def test_an_incorrect_grade_scores_zero_through_the_same_seam() -> None:
    fetch = _RecordingFetch(reply="GRADE: I")
    scorer = model_graded_qa(model="screamingface/judge-4")
    with bound_judge_transport(JudgeTransport(fetch=fetch)):
        outcome = await inspect_grade_case(scorer)(_request(answer="Lyon."))
    assert (outcome.score, outcome.failure_code) == (0.0, None)


@pytest.mark.asyncio
async def test_a_missing_transport_fails_the_case_by_name() -> None:
    """INVARIANT: no transport bound means NO call leaves the engine — the Case
    fails as scorer_error naming the gateway seam, never a direct provider dial."""

    scorer = model_graded_qa(model="screamingface/judge-4")
    outcome = await inspect_grade_case(scorer)(_request())
    assert outcome.score is None
    assert outcome.failure_code == "scorer_error"
    assert "judge transport" in str(outcome.checks)


@pytest.mark.asyncio
async def test_a_gateway_refusal_fails_the_case_by_name() -> None:
    async def refusing(target: str) -> str:
        raise RuntimeError("the gateway refused: model overloaded")

    scorer = model_graded_qa(model="screamingface/judge-4")
    with bound_judge_transport(JudgeTransport(fetch=refusing)):
        outcome = await inspect_grade_case(scorer)(_request())
    assert outcome.score is None
    assert outcome.failure_code == "scorer_error"
    # The cause is audit material — the gateway's own words ride the evidence.
    assert "model overloaded" in str(outcome.checks)


@pytest.mark.asyncio
async def test_a_tool_bearing_judge_prompt_is_refused() -> None:
    """§7 scope: judge prompts are plain chat — a tool message cannot cross the
    candidate input envelope, so it must refuse loudly, never drop silently."""

    from inspect_ai.model import ChatMessageTool

    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=_RecordingFetch())):
        with pytest.raises(Exception, match="tool"):
            await model.generate([ChatMessageTool(content="a tool result", tool_call_id="t1")])


@pytest.mark.asyncio
async def test_the_transport_binding_is_scoped() -> None:
    """The binding must not leak past its context — the next board's grade starts clean."""

    fetch = _RecordingFetch()
    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=fetch)):
        await model.generate([ChatMessageUser(content="inside")])
    with pytest.raises(Exception, match="judge transport"):
        await model.generate([ChatMessageUser(content="outside")])
    assert len(fetch.targets) == 1


def test_the_fabricated_task_state_satisfies_the_qa_template() -> None:
    """model_graded_qa formats question/answer/criterion from the TaskState the shim
    builds — pin that the shim's minimal state carries what the template reads."""

    state = TaskState(
        model="screamingface/candidate",  # type: ignore[arg-type]
        sample_id=1,
        epoch=1,
        input="What is the capital of France?",
        messages=[ChatMessageUser(content="What is the capital of France?")],
    )
    # The template reads input_text and metadata; both must exist on a minimal state.
    assert state.input_text == "What is the capital of France?"
    assert state.metadata is not None or state.metadata == {}
    assert isinstance(Target("Paris").text, str)


@pytest.mark.asyncio
async def test_an_unparseable_judge_reply_fails_the_case_by_name() -> None:
    """INVARIANT: a judge reply with no parseable grade is that CASE's named
    failure, never an aborted aggregate. inspect returns Score(value=NaN) for an
    unscored model_graded reply; NaN must map to invalid_score_value — the wire
    model rejects non-finite scores, and the raise would escape past all 160
    already-paid cases (review finding, 2026-09-24)."""

    fetch = _RecordingFetch(reply="I cannot decide.")
    scorer = model_graded_qa(model="screamingface/judge-4")
    with bound_judge_transport(JudgeTransport(fetch=fetch)):
        outcome = await inspect_grade_case(scorer)(_request())
    assert outcome.score is None
    assert outcome.failure_code == "invalid_score_value"


@pytest.mark.asyncio
async def test_an_empty_judge_reply_fails_the_case_by_name() -> None:
    """A blank completion can never be a grade — the provider refuses it loudly
    instead of letting a scorer coerce silence into a score."""

    fetch = _RecordingFetch(reply="   ")
    scorer = model_graded_qa(model="screamingface/judge-4")
    with bound_judge_transport(JudgeTransport(fetch=fetch)):
        outcome = await inspect_grade_case(scorer)(_request())
    assert outcome.score is None
    assert outcome.failure_code == "scorer_error"
    assert "empty reply" in str(outcome.checks)


@pytest.mark.asyncio
async def test_eval_supplied_sampling_settings_are_refused() -> None:
    """The judge's sampling identity is the ROW's pinned params — an eval that
    passes its own GenerateConfig sampling would be silently dropped otherwise,
    so it must refuse by name instead."""

    from inspect_ai.model import GenerateConfig

    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=_RecordingFetch())):
        with pytest.raises(Exception, match="pinned"):
            await model.generate(
                [ChatMessageUser(content="grade this")],
                config=GenerateConfig(temperature=0.7),
            )


@pytest.mark.asyncio
async def test_an_unknown_generate_config_field_is_refused_by_default() -> None:
    """INVARIANT: the guard ALLOWS known-harmless transport fields and refuses
    everything else by name — a forbidden-list would silently admit any field it
    forgot (reasoning_effort graded persistbench at the gateway's default effort)
    and would go stale every time inspect adds a field."""

    from inspect_ai.model import GenerateConfig

    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=_RecordingFetch())):
        with pytest.raises(Exception, match="reasoning_effort"):
            await model.generate(
                [ChatMessageUser(content="grade this")],
                config=GenerateConfig(reasoning_effort="high"),
            )


@pytest.mark.asyncio
async def test_transport_level_config_fields_are_allowed() -> None:
    """Retry/timeout knobs change delivery, never the grade — they pass."""

    from inspect_ai.model import GenerateConfig

    fetch = _RecordingFetch()
    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=fetch)):
        output = await model.generate(
            [ChatMessageUser(content="grade this")],
            config=GenerateConfig(max_retries=3, timeout=10),
        )
    assert output.completion == "GRADE: C"


@pytest.mark.asyncio
async def test_a_tool_bearing_judge_call_is_refused() -> None:
    """A judge that asks for tools would grade WITHOUT them silently — the eval
    assumed it could call them. Judge prompts are plain chat; refuse by name."""

    from inspect_ai.tool import ToolInfo, ToolParams

    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(JudgeTransport(fetch=_RecordingFetch())):
        with pytest.raises(Exception, match="tool"):
            await model.generate(
                [ChatMessageUser(content="grade this")],
                tools=[ToolInfo(name="search", description="web", parameters=ToolParams())],
            )

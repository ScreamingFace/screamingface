# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A judge setting the eval passes is fine when the wire already carries it, or never sends it.

FEATURE: OME-1478 PR 1 of 2. The gateway judge sends only the row's pinned params, so it
refuses any grade-affecting setting an eval passes: a dropped setting would grade a different
benchmark, silently (OME-1240). HLE's official judge passes three, and each is honest:

- ``max_tokens=4096``: the row pins the same value, so the wire carries exactly that;
- ``response_schema`` (strict JSON output): the row pins the same ``response_format``, which
  rides the request scope to the connector, because url4 params cannot hold JSON;
- ``temperature=0``: inspect's OpenAI provider drops it for o-series judges before the request,
  so the official run never sends it; the row declares it unsent (owner's pick, 2026-11-02).

Think of the pinned params as the judge's sealed instructions: an eval may repeat a line that is
already on them, or hand over a line the row says the courier throws away, but it can never add
a line the courier would silently drop.

INVARIANT the suite defends: what reaches the wire is the row's pinned params, byte for byte,
plus the row's pinned format on a call that asks for it, and anything else the eval passes is
still refused by name.

Stand-ins: ``_RecordingFetch`` stands in for the node's model route and answers one fixed judge
reply, so no call leaves the process; ``judge-4`` and ``o3-judge`` are stand-in route names.
HLE's scorer is HLE's own.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import (  # noqa: E402
    ChatMessageUser,
    GenerateConfig,
    ResponseSchema,
    get_model,
)
from inspect_ai.util import json_schema  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine.request_scope import (  # noqa: E402
    RequestScope,
    RequestScopeError,
    current_scope,
    request_scope,
)
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
    judge_filling_model_role,
    openai_response_format,
)
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from screamingface_engine_inspect.single_shot import JudgeSpec  # noqa: E402
from url4.wire.subrequest import extract_expression_params  # noqa: E402


class _Verdict(BaseModel):
    """A stand-in judge reply schema, shaped like HLE's: a yes/no and a confidence."""

    correct: str
    confidence: int


class _RecordingFetch:
    """A fake node fetch: records every target and the format the scope asks for at that
    moment (what the connector would read), answers with a fixed judge reply."""

    def __init__(self, reply: str = "GRADE: C") -> None:
        self.targets: list[str] = []
        self.formats: list[str | None] = []
        self.reply: str = reply

    async def __call__(self, target: str) -> str:
        self.targets.append(target)
        try:
            self.formats.append(current_scope().response_format)
        except RequestScopeError:
            self.formats.append(None)
        return self.reply


def _run_scope() -> Any:
    """The run's request scope a judge call always runs under (a stand-in run scope)."""

    return request_scope(RequestScope(origin="run"))


def _schema(name: str = "_Verdict") -> ResponseSchema:
    """The response schema an eval passes for ``_Verdict``, as HLE's json_judge builds its own."""

    return ResponseSchema(name=name, json_schema=json_schema(_Verdict), description="", strict=True)


def _pinned_format(schema: ResponseSchema) -> str:
    """The ``response_format`` param a row pins for ``schema``, written as JSON text."""

    return json.dumps(openai_response_format(schema))


def _wire_params(target: str) -> dict[str, str]:
    """The params one recorded judge call carried, by the wire codec's own decoder."""

    params, _ = extract_expression_params(target.partition("?")[2])
    return dict(params)


async def _generate(transport: JudgeTransport, config: GenerateConfig) -> str:
    """One judge call through the provider with ``config``; returns the completion."""

    model = get_model("screamingface/judge-4", memoize=False)
    with _run_scope(), bound_judge_transport(transport):
        output = await model.generate([ChatMessageUser(content="grade this")], config=config)
    return output.completion


def test_the_openai_format_matches_inspects_chat_completions_shape() -> None:
    """The wire's dialect is OpenAI chat completions: inspect writes ``response_schema`` as
    this object for its OpenAI-compatible providers (``inspect_ai/model/_openai.py``)."""

    assert openai_response_format(_schema()) == {
        "type": "json_schema",
        "json_schema": {
            "name": "_Verdict",
            "schema": json_schema(_Verdict).model_dump(exclude_none=True),
            "description": "",
            "strict": True,
        },
    }


@pytest.mark.asyncio
async def test_a_setting_equal_to_a_pinned_param_passes_and_the_wire_is_unchanged() -> None:
    fetch = _RecordingFetch()
    transport = JudgeTransport(fetch=fetch, params=(("max_tokens", "4096"),))

    assert await _generate(transport, GenerateConfig(max_tokens=4096)) == "GRADE: C"
    assert _wire_params(fetch.targets[0]) == {"max_tokens": "4096"}


@pytest.mark.asyncio
async def test_a_setting_that_differs_from_its_pinned_param_is_still_refused() -> None:
    """WHY: the wire would send 4096 while the eval asked for 32768, a different exam."""

    transport = JudgeTransport(fetch=_RecordingFetch(), params=(("max_tokens", "4096"),))

    with pytest.raises(Exception, match="max_tokens"):
        await _generate(transport, GenerateConfig(max_tokens=32768))


@pytest.mark.asyncio
async def test_a_response_schema_equal_to_the_pinned_format_asks_for_it_by_the_scope() -> None:
    """The format never touches the url4 wire; the connector reads it off the scope."""

    fetch = _RecordingFetch()
    pinned: str = _pinned_format(_schema())
    transport = JudgeTransport(fetch=fetch, response_format=pinned)

    await _generate(transport, GenerateConfig(response_schema=_schema()))

    assert _wire_params(fetch.targets[0]) == {}
    assert fetch.formats == [pinned]


@pytest.mark.asyncio
async def test_a_call_with_no_response_schema_never_asks_for_the_format() -> None:
    """WHY: inspect sends response_format only when the call carries a schema."""

    fetch = _RecordingFetch()
    transport = JudgeTransport(fetch=fetch, response_format=_pinned_format(_schema()))

    await _generate(transport, GenerateConfig())

    assert fetch.formats == [None]


@pytest.mark.asyncio
async def test_a_response_schema_with_no_format_pinned_is_refused() -> None:
    """WHY: without the pin the judge would answer free text where the eval demanded JSON."""

    transport = JudgeTransport(fetch=_RecordingFetch())

    with pytest.raises(Exception, match="response_schema"):
        await _generate(transport, GenerateConfig(response_schema=_schema()))


@pytest.mark.asyncio
async def test_a_response_schema_unlike_the_pinned_format_is_refused() -> None:
    transport = JudgeTransport(
        fetch=_RecordingFetch(), response_format=_pinned_format(_schema("Other"))
    )

    with pytest.raises(Exception, match="response_schema"):
        await _generate(transport, GenerateConfig(response_schema=_schema()))


@pytest.mark.asyncio
async def test_an_unsent_setting_passes_and_never_reaches_the_wire() -> None:
    fetch = _RecordingFetch()
    transport = JudgeTransport(fetch=fetch, unsent_settings=frozenset({"temperature"}))

    await _generate(transport, GenerateConfig(temperature=0.0))

    assert "temperature" not in _wire_params(fetch.targets[0])


@pytest.mark.asyncio
async def test_an_unsent_setting_admits_only_itself() -> None:
    transport = JudgeTransport(fetch=_RecordingFetch(), unsent_settings=frozenset({"temperature"}))

    with pytest.raises(Exception, match="top_p"):
        await _generate(transport, GenerateConfig(temperature=0.0, top_p=0.5))


@pytest.mark.asyncio
async def test_the_bound_role_carries_the_pinned_params_as_its_config() -> None:
    """inspect's ``model_roles`` config, ours: a judge asking for the role with its own
    defaults (HLE's default.yaml stanza, 32768 tokens and temperature 0) gets the pinned
    4096, and the unset temperature is gap-filled as inspect does."""

    fetch = _RecordingFetch()
    params: tuple[tuple[str, str], ...] = (("max_tokens", "4096"),)
    transport = JudgeTransport(
        fetch=fetch, params=params, unsent_settings=frozenset({"temperature"})
    )
    with (
        _run_scope(),
        judge_filling_model_role("grader", "judge-4", params),
        bound_judge_transport(transport),
    ):
        model = get_model(role="grader", config=GenerateConfig(max_tokens=32768, temperature=0.0))
        assert model.config.max_tokens == 4096
        assert model.config.temperature == 0.0
        await model.generate([ChatMessageUser(content="grade this")])

    assert _wire_params(fetch.targets[0]) == {"max_tokens": "4096"}


def test_a_row_cannot_both_pin_a_setting_and_declare_it_unsent() -> None:
    with pytest.raises(ValueError, match="temperature"):
        JudgeSpec(model="judge-4", params=(("temperature", "0"),), unsent_settings=("temperature",))


def test_a_row_cannot_pin_response_format_as_a_param() -> None:
    """WHY: url4 params cannot hold JSON, so the call would fail at the wire, mid-grading."""

    with pytest.raises(ValueError, match="JudgeSpec\\(response_format="):
        JudgeSpec(model="judge-4", params=(("response_format", "x"),))


@pytest.mark.parametrize("pinned", ["not json", "[1, 2]"])
def test_a_pinned_response_format_must_be_a_json_object(pinned: str) -> None:
    with pytest.raises(ValueError, match="response_format"):
        JudgeSpec(model="judge-4", response_format=pinned)


@pytest.mark.asyncio
async def test_hles_json_judge_grades_through_the_provider_with_the_official_wire() -> None:
    """The payoff: HLE's real ``json_judge`` grades one Case through the gateway judge. The
    call carries the official run's 4096 tokens and strict JSON format and no temperature,
    and the Case gets the judge's "score" as its mark."""

    pytest.importorskip("inspect_evals")
    from inspect_evals.hle.prompts import PROMPTS
    from inspect_evals.hle.scorers import json_judge

    reply: dict[str, Any] = {
        "extracted_final_answer": "Paris",
        "reasoning": "The response names Paris.",
        "correct": "yes",
        "confidence": 90,
    }
    fetch = _RecordingFetch(reply=json.dumps(reply))
    answer_schema: Any = PROMPTS["json_judge"].output_format
    pinned_format: str = json.dumps(
        openai_response_format(
            ResponseSchema(
                name=answer_schema.__name__,
                json_schema=json_schema(answer_schema),
                description="",
                strict=True,
            )
        )
    )
    params: tuple[tuple[str, str], ...] = (("max_tokens", "4096"),)
    transport = JudgeTransport(
        fetch=fetch,
        params=params,
        unsent_settings=frozenset({"temperature"}),
        response_format=pinned_format,
    )
    request = GradeRequest(
        case_id=3,
        input=TextPayload(text="What is the capital of France?"),
        answer=TextPayload(text="Paris"),
        row={"case": {"status": "answered"}},
        material={"target": "Paris"},
    )
    with (
        _run_scope(),
        judge_filling_model_role("grader", "o3-judge", params),
        bound_judge_transport(transport),
    ):
        scorer = json_judge(prompt="json_judge", grader_role="grader", max_grader_attempts=1)
        outcome = await inspect_grade_case(scorer, named_scores=("score", "confidence"))(request)

    assert outcome.failure_code is None
    assert outcome.score == 1.0
    assert _wire_params(fetch.targets[0]) == {"max_tokens": "4096"}
    assert fetch.formats == [pinned_format]

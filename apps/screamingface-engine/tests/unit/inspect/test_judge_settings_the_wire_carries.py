# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A judge setting the eval passes is fine when the row's pins already carry it, same value.

FEATURE: OME-1478 PR 1 of 2. The gateway judge sends only the row's pinned params, so it
refuses any grade-affecting setting an eval passes: a dropped setting would grade a different
benchmark, silently (OME-1240). HLE's maintained judge (inspect_evals' default.yaml, the owner's
pick on 2026-11-02) asks for its role with ``temperature=0`` and ``max_tokens=32768``. Its row
pins the same two, so the wire sends exactly what the eval asked for, and the guard lets them
through.

Think of the pinned params as the judge's sealed instructions: an eval may repeat a line that is
already on them, word for word, but it can never add a line the courier would silently drop.

INVARIANT the suite defends: what reaches the wire is the row's pinned params, byte for byte,
and any setting the eval passes with another value, or that no pin carries, is still refused by
name.

Stand-ins: ``_RecordingFetch`` stands in for the node's model route and answers one fixed judge
reply, so no call leaves the process; ``judge-4`` is a stand-in route name. HLE's scorer is
HLE's own.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")

from inspect_ai.model import ChatMessageUser, GenerateConfig, get_model  # noqa: E402

from screamingface_engine.benchmarks.shared_grading.benchmark_aggregation import (  # noqa: E402
    GradeRequest,
)
from screamingface_engine.benchmarks.shared_grading.payloads import TextPayload  # noqa: E402
from screamingface_engine_inspect.judge_provider import (  # noqa: E402
    JudgeTransport,
    bound_judge_transport,
    judge_filling_model_role,
)
from screamingface_engine_inspect.scorer_adapter import inspect_grade_case  # noqa: E402
from url4.wire.subrequest import extract_expression_params  # noqa: E402

#: HLE's default.yaml judge stanza, as the row pins it: the settings its judge asks with.
_HLE_JUDGE_PINS: tuple[tuple[str, str], ...] = (("temperature", "0"), ("max_tokens", "32768"))


class _RecordingFetch:
    """A fake node fetch: records every target, answers with a fixed judge reply."""

    def __init__(self, reply: str = "GRADE: C") -> None:
        self.targets: list[str] = []
        self.reply: str = reply

    async def __call__(self, target: str) -> str:
        self.targets.append(target)
        return self.reply


def _wire_params(target: str) -> dict[str, str]:
    """The params one recorded judge call carried, by the wire codec's own decoder."""

    params, _ = extract_expression_params(target.partition("?")[2])
    return dict(params)


async def _generate(transport: JudgeTransport, config: GenerateConfig) -> str:
    """One judge call through the provider with ``config``; returns the completion."""

    model = get_model("screamingface/judge-4", memoize=False)
    with bound_judge_transport(transport):
        output = await model.generate([ChatMessageUser(content="grade this")], config=config)
    return output.completion


@pytest.mark.asyncio
async def test_a_setting_equal_to_a_pinned_param_passes_and_the_wire_is_unchanged() -> None:
    fetch = _RecordingFetch()
    transport = JudgeTransport(fetch=fetch, params=_HLE_JUDGE_PINS)

    completion: str = await _generate(transport, GenerateConfig(temperature=0.0, max_tokens=32768))

    assert completion == "GRADE: C"
    assert _wire_params(fetch.targets[0]) == {"temperature": "0", "max_tokens": "32768"}


@pytest.mark.asyncio
async def test_a_setting_that_differs_from_its_pinned_param_is_still_refused() -> None:
    """WHY: the wire would send 32768 while the eval asked for 4096, a different exam."""

    transport = JudgeTransport(fetch=_RecordingFetch(), params=_HLE_JUDGE_PINS)

    with pytest.raises(Exception, match="max_tokens"):
        await _generate(transport, GenerateConfig(max_tokens=4096))


@pytest.mark.asyncio
async def test_a_setting_no_pin_carries_is_still_refused_beside_one_that_is() -> None:
    """The pins admit only themselves: ``top_p`` rides nothing, so it is named."""

    transport = JudgeTransport(fetch=_RecordingFetch(), params=_HLE_JUDGE_PINS)

    with pytest.raises(Exception, match="top_p"):
        await _generate(transport, GenerateConfig(temperature=0.0, top_p=0.5))


@pytest.mark.asyncio
async def test_hles_regex_judge_grades_through_the_provider_with_the_pinned_wire() -> None:
    """The payoff: HLE's real ``regex_judge``, the role bound the way a run binds it, grades one
    Case through the gateway judge. The call carries exactly the two pins, and the Case gets
    the judge's grade as its mark."""

    pytest.importorskip("inspect_evals")
    from inspect_evals.hle.scorers import regex_judge

    fetch = _RecordingFetch(reply="The response names Paris.\nGRADE: C")
    request = GradeRequest(
        case_id=3,
        input=TextPayload(text="What is the capital of France?"),
        answer=TextPayload(text="Explanation: it is Paris.\nAnswer: Paris\nConfidence: 80%"),
        row={"case": {"status": "answered"}},
        material={"target": "Paris"},
    )
    with (
        judge_filling_model_role("grader", "judge-4"),
        bound_judge_transport(JudgeTransport(fetch=fetch, params=_HLE_JUDGE_PINS)),
    ):
        scorer = regex_judge(
            template="regex_judge_template",
            instructions="regex_judge_instructions",
            grader_role="grader",
            max_grader_attempts=3,
        )
        outcome = await inspect_grade_case(scorer, named_scores=("score", "confidence"))(request)

    assert outcome.failure_code is None
    assert outcome.score == 1.0
    assert [_wire_params(target) for target in fetch.targets] == [
        {"temperature": "0", "max_tokens": "32768"}
    ]

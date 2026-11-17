# pyright: reportMissingImports=false
# WHY file-level: this module imports the `inspect` extra's packages, absent in the
# default (extra-less) install the typecheck gate runs against.
"""A judge setting the eval passes is fine when the row's pins already carry it, same value.

FEATURE: OME-1478 PR 1 of 2. The gateway judge sends only the row's pinned params, so it
refuses any grade-affecting setting an eval passes: a dropped setting would grade a different
benchmark, silently (OME-1240). HLE's maintained judge (inspect_evals' default.yaml, the owner's
pick on 2026-11-02) asks for its role with ``temperature=0`` and ``max_tokens=32768``. Its row
pins ``temperature=0`` and a raised ``max_tokens=131072`` (OME-1939), and a run binds the role
with those pins, so the stanza fills only what they leave unset: the judge asks with exactly the
pinned values, the wire sends them, and the guard lets them through.

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

from pathlib import Path
from typing import Any, cast

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

#: HLE's judge settings as the row pins them: default.yaml's stanza with max_tokens raised from
#: 32768 to 131072 (OME-1939).
_HLE_JUDGE_PINS: tuple[tuple[str, str], ...] = (("temperature", "0"), ("max_tokens", "131072"))


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

    completion: str = await _generate(transport, GenerateConfig(temperature=0.0, max_tokens=131072))

    assert completion == "GRADE: C"
    assert _wire_params(fetch.targets[0]) == {"temperature": "0", "max_tokens": "131072"}


@pytest.mark.asyncio
async def test_a_setting_that_differs_from_its_pinned_param_is_still_refused() -> None:
    """WHY: the wire would send 131072 while the eval asked for 4096, a different exam."""

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
    Case through the gateway judge. The call carries exactly the two pins, the raised cap
    included, and the Case gets the judge's grade as its mark."""

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
        judge_filling_model_role("grader", "judge-4", _HLE_JUDGE_PINS),
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
        {"temperature": "0", "max_tokens": "131072"}
    ]


@pytest.mark.asyncio
async def test_a_role_bound_without_the_pins_lets_hles_stanza_ask_for_32768_and_is_refused() -> (
    None
):
    """WHY the role must carry the pins (OME-1939): bound bare, HLE's ``default.yaml`` stanza
    fills ``max_tokens=32768`` into the judge's settings, the row pins 131072, and the guard
    refuses every call by name. No judge call leaves the process, so no Case gets a grade."""

    pytest.importorskip("inspect_evals")
    from inspect_evals.hle.scorers import regex_judge

    fetch = _RecordingFetch(reply="GRADE: C")
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

    assert outcome.failure_code is not None
    assert "max_tokens" in str(outcome.checks)
    assert fetch.targets == []


@pytest.mark.asyncio
async def test_a_run_binds_hles_judge_role_with_the_rows_raised_cap(tmp_path: Path) -> None:
    """The run's own grading face (``single_shot``) binds the grader role with the HLE row's
    pins, so the role a scorer looks up asks for 131072, not the stanza's 32768 (OME-1939).

    Stand-in: ``_spy_aggregate`` replaces the aggregation the face wraps and only reads the
    bound role inside the face's scope; no Case is graded and no judge call is made."""

    pytest.importorskip("inspect_evals")
    from inspect_ai.model import Model, model_roles

    from screamingface_engine_inspect import single_shot
    from screamingface_engine_inspect.benchmarks import imported_benchmark

    seen: dict[str, GenerateConfig] = {}

    async def _spy_aggregate(*_args: Any, **_kwargs: Any) -> None:
        """Record the grader role's settings as the face bound them."""

        bound: Any = model_roles()["grader"]
        assert isinstance(bound, Model)  # one judge, never a list of models
        seen["config"] = bound.config

    handler = single_shot._judged_handler(  # pyright: ignore[reportPrivateUsage]
        imported_benchmark("hle"), tmp_path, cast(Any, None), _spy_aggregate
    )
    await handler("", ())

    assert seen["config"].max_tokens == 131072
    assert seen["config"].temperature == 0.0

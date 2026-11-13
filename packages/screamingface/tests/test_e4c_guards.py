"""Guards on the SDK side: fail_closed is an error, abstain is a scored decline (E4c, OME-1291).

FEATURE: guards PRD rows GU#1 (CHAR), #2 (CHAR), #17, #23, #26.
STORY: as a researcher, a Case that a guard refused fails with ``fail_closed`` and is never read
as a refusal or an abstain; a guard pattern RE2 cannot run is refused before any spend.
"""

from __future__ import annotations

import pytest

import screamingface as sf


def _failed(code: str, *, refusal: str | None = None) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=1,
        input="Question 1",
        output=None,
        finish_reason=None,
        grade=None,
        failures=(
            sf.Failure(stage="candidate", code=code, message="fixed engine text", case_id=1),
        ),
        metadata={},
        refusal=refusal,
    )


def _scored(*, output: str = "", score: float = 0.0, **extra: object) -> sf.CaseResult:
    return sf.CaseResult(
        case_id=1,
        input="Question 1",
        output=output,
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=score, metrics={}, checks=()),
        failures=(),
        metadata={},
        **extra,  # type: ignore[arg-type]
    )


def test_abstained_case_is_scored_zero_and_failed_case_has_a_code() -> None:
    # CHAR GU#1 (S/case_result.py): an abstain is a scored empty answer with score 0.0; a failure
    # carries its code and no score.
    abstained = _scored(abstained=True)
    assert (abstained.status, abstained.abstained) == ("scored", True)
    assert abstained.grade is not None and abstained.grade.score == 0.0
    with pytest.raises(ValueError, match="an abstained Case is a scored empty answer"):
        _scored(output="text", abstained=True)
    failed = _failed("fail_closed")
    assert failed.status == "failed"
    assert [failure.code for failure in failed.failures] == ["fail_closed"]
    assert failed.abstained is False


def test_refusal_is_only_refusal_text_or_provider_refusal() -> None:
    # CHAR GU#2 (S/case_result.py refusal_kind): only refusal text or provider_refusal count.
    assert _failed("provider_refusal").refusal_kind is None  # a refusal with no kind signal
    refused = sf.CaseResult(
        case_id=1,
        input="Question 1",
        output=None,
        finish_reason="content_filter",
        grade=None,
        failures=(
            sf.Failure(stage="candidate", code="provider_refusal", message="refused", case_id=1),
        ),
        metadata={},
    )
    assert refused.refusal_kind == "provider_declined"
    assert _failed("model_token_cap").refusal_kind is None


def test_fail_closed_case_is_not_a_refusal() -> None:
    # GU#17 / GU-14 (P13): fail_closed earns no refusal credit.
    assert _failed("fail_closed").refusal_kind is None
    assert _failed("fail_closed").abstained is False


@pytest.mark.parametrize(
    "pattern", [r"(a)\1", r"(?<=x)ignore", r"ignore(?=all)"], ids=["backref", "behind", "ahead"]
)
def test_keywords_guard_refuses_a_non_re2_pattern_before_spend(pattern: str) -> None:
    # GU#23 / GU-9: the SDK pre-spend check refuses what RE2 cannot run; no message echoes it.
    with pytest.raises(ValueError) as caught:
        sf.RegexClassifier([("jailbreak", pattern)])
    assert pattern not in str(caught.value)


def test_fail_closed_in_a_skip_gate_member_is_refused() -> None:
    # GU#26 / GU-17: a skip-Gate member takes a member recipe in then=, never a word.
    selector = sf.RegexClassifier([("math", "integral")], multi=True)
    with pytest.raises(ValueError, match="with a recipe in then="):
        sf.Fanout(
            [
                "prov/a",
                sf.Gate(when=sf.labels(selector).has("math"), then=sf.fail()),
            ]
        )

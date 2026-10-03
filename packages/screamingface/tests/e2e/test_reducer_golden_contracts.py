"""Contract tests for the reducer-lane golden models (OME-1289 E4a, EV-12 support).

These run in the DEFAULT test lane: no docker, no subprocesses, no key. They pin what the GSM8K vote
replay lane (``test_reducer_replay.py``) stands on, so a mistake in the golden models or in the
evidence lock shows up now and not after the user's paid recording:

- ``ReducerCandidateSpec.build()`` rebuilds the recorded candidate: a Fusion of N seeded samples
  with a Vote;
- ``ReducerGolden`` validates on read, and ``outcome()`` maps to a ``GoldenReport`` so that the five
  locks of ``compare_outcome`` run unchanged;
- ``assert_evidence_lock`` is the sixth lock: the combine evidence of the first case.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from harness.goldens import ActualOutcome, GoldenMismatch, GoldenReport, compare_outcome
from harness.reducer_golden import (
    REDUCER_GOLDEN_SCHEMA,
    ReducerCandidateSpec,
    ReducerGolden,
    assert_evidence_lock,
    load_reducer_golden,
)
from pydantic import ValidationError

import screamingface as sf
from screamingface.case_result import CaseOperation
from screamingface.combine_evidence import (
    CombineAnswerRow,
    CombineEvidence,
    CombineResult,
    CombineTallyRow,
)

_SHA = hashlib.sha256(b"rendered expression").hexdigest()
_ANSWERS = ["so 41", "so 42", "so 42", "so 42", "so 40"]


def _spec_doc() -> dict[str, Any]:
    return {
        "model": "openrouter/prov/model-x",
        "samples": 5,
        "temperature": 0.7,
        "extract": "last_number",
        "normalize": "numeric",
    }


def _row(index: int, value: str) -> CombineAnswerRow:
    return CombineAnswerRow(
        member_id=f"member_{index}",
        raw=value,
        value=value,
        status="answered",
        reason=None,
        signals={},
    )


def _answered(member_id: str, value: str) -> CombineResult:
    return CombineResult(member_id=member_id, value=value, status="answered", reason=None)


def _evidence(agreement: float = 0.6) -> CombineEvidence:
    """A real vote over the five answers above: member_2 holds the most common value first."""
    return CombineEvidence(
        kind="answer",
        reducer="vote",
        operators=("last_number@1", "numeric@1", "mode@1", "first_holder@1"),
        members=[_row(index, text.split()[-1]) for index, text in enumerate(_ANSWERS, start=1)],
        tally=[
            CombineTallyRow(value="42", score=3.0, holders=("member_2", "member_3", "member_4")),
            CombineTallyRow(value="41", score=1.0, holders=("member_1",)),
            CombineTallyRow(value="40", score=1.0, holders=("member_5",)),
        ],
        chosen=("member_2",),
        built=False,
        tie=False,
        agreement=agreement,
        result=_answered("member_2", "42"),
        dropped=0,
        finish_reason="stop",
    )


def _abstained_evidence() -> CombineEvidence:
    """A vote whose five members all failed: an honest abstain, with nothing chosen."""
    failed = [
        CombineAnswerRow(
            member_id=f"member_{index}",
            raw="",
            value=None,
            status="fail",
            reason="empty",
            signals={},
        )
        for index in range(1, 6)
    ]
    return CombineEvidence(
        kind="answer",
        reducer="vote",
        operators=("last_number@1", "numeric@1", "mode@1", "first_holder@1"),
        members=failed,
        chosen=(),
        built=False,
        tie=False,
        result=CombineResult(member_id=None, value=None, status="abstain", reason="no_votes"),
        dropped=5,
        finish_reason="stop",
    )


def _evidence_kwargs() -> dict[str, Any]:
    base = _evidence()
    return {
        "kind": base.kind,
        "reducer": base.reducer,
        "operators": base.operators,
        "members": base.members,
        "tally": base.tally,
        "chosen": base.chosen,
        "built": base.built,
        "tie": base.tie,
        "agreement": base.agreement,
        "result": base.result,
        "dropped": base.dropped,
        "finish_reason": base.finish_reason,
    }


def _case(
    case_id: str = "1",
    *,
    evidence: CombineEvidence | None = None,
    answers: Sequence[str | None] = tuple(_ANSWERS),
    synthesis_output: str = "so 42",
) -> Any:
    """The two things the evidence lock reads off a CaseResult: ``case_id`` and ``operations``."""
    operations = [
        CaseOperation(operation_id=f"op_model_{index}", output=text, finish_reason="stop")
        for index, text in enumerate(answers, start=1)
    ]
    operations.append(
        CaseOperation(
            operation_id="op_synthesis_1",
            output=synthesis_output,
            finish_reason="stop",
            combine=_evidence() if evidence is None else evidence,
        )
    )
    return SimpleNamespace(case_id=case_id, operations=tuple(operations))


def _golden_doc(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": REDUCER_GOLDEN_SCHEMA,
        "lane": "inspect-gsm8k-vote",
        "board": "inspect-gsm8k",
        "revision": "rev-1",
        "limit": 2,
        "candidate": _spec_doc(),
        "expression_sha": _SHA,
        "final_score": "0.5",
        "case_count": 2,
        "gradeable_count": 1,
        "case_statuses": {"1": "scored", "2": "failed"},
        "case_failures": {"2": [{"stage": "candidate", "code": "upstream_error"}]},
        "evidence": {"case_id": "1", "combine": _evidence().to_dict()},
    }
    document.update(overrides)
    return document


# -- ReducerCandidateSpec -----------------------------------------------------------


def _models(candidate: Any) -> list[sf.Model]:
    """The Fusion's members, each checked to be a plain Model (the Fusion types them as Recipe)."""
    assert isinstance(candidate, sf.Fusion)
    members = list(candidate.members)
    assert all(isinstance(member, sf.Model) for member in members)
    return [member for member in members if isinstance(member, sf.Model)]


def test_build_returns_a_fusion_of_n_seeded_samples_with_a_vote() -> None:
    candidate = ReducerCandidateSpec.model_validate(_spec_doc()).build()

    members = _models(candidate)
    assert [member.model for member in members] == ["openrouter/prov/model-x"] * 5
    assert [member.params for member in members] == [
        {"temperature": 0.7, "seed": seed} for seed in range(5)
    ]
    assert candidate.synthesizer == sf.Vote(extract="last_number", normalize="numeric")


def test_build_without_a_temperature_or_a_normalizer() -> None:
    document = {**_spec_doc(), "samples": 3, "temperature": None, "normalize": None}
    candidate = ReducerCandidateSpec.model_validate(document).build()

    assert [member.params for member in _models(candidate)] == [{"seed": seed} for seed in range(3)]
    assert candidate.synthesizer == sf.Vote(extract="last_number", normalize=None)


@pytest.mark.parametrize("samples", [0, 257])
def test_spec_refuses_a_sample_count_outside_the_sdk_bounds(samples: int) -> None:
    with pytest.raises(ValidationError):
        ReducerCandidateSpec.model_validate({**_spec_doc(), "samples": samples})


def test_spec_refuses_unknown_keys_and_is_frozen() -> None:
    with pytest.raises(ValidationError):
        ReducerCandidateSpec.model_validate({**_spec_doc(), "seed": 1})
    spec = ReducerCandidateSpec.model_validate(_spec_doc())
    with pytest.raises(ValidationError):
        spec.samples = 6  # type: ignore[misc]


# -- ReducerGolden ------------------------------------------------------------------


def test_golden_validates_and_maps_to_a_golden_report() -> None:
    golden = ReducerGolden.model_validate(_golden_doc())

    outcome = golden.outcome()

    assert isinstance(outcome, GoldenReport)
    assert outcome.kind == "model"
    assert outcome.models == ()  # only build_candidate reads it; the spec builds the candidate
    assert (outcome.board, outcome.revision, outcome.limit) == ("inspect-gsm8k", "rev-1", 2)
    assert outcome.expression_sha == _SHA
    assert (outcome.final_score, outcome.case_count, outcome.gradeable_count) == ("0.5", 2, 1)
    assert outcome.case_statuses == {"1": "scored", "2": "failed"}
    assert {
        case: [(f.stage, f.code) for f in entries]
        for case, entries in outcome.case_failures.items()
    } == {"2": [("candidate", "upstream_error")]}


def _actual(**overrides: Any) -> ActualOutcome:
    values: dict[str, Any] = {
        "rendered_url4": "rendered expression",
        "final_score": 0.5,
        "case_statuses": {"1": "scored", "2": "failed"},
        "coverage": 0.5,
        "case_failures": ReducerGolden.model_validate(_golden_doc()).outcome().case_failures,
    }
    values.update(overrides)
    return ActualOutcome(**values)


def test_the_five_locks_run_unchanged_on_the_mapped_outcome() -> None:
    outcome = ReducerGolden.model_validate(_golden_doc()).outcome()

    compare_outcome(outcome, _actual())
    with pytest.raises(GoldenMismatch) as score:
        compare_outcome(outcome, _actual(final_score=0.25))
    assert score.value.stage == "score"
    with pytest.raises(GoldenMismatch) as expression:
        compare_outcome(outcome, _actual(rendered_url4="another expression"))
    assert expression.value.stage == "expression"


@pytest.mark.parametrize(
    "overrides",
    [
        {"expression_sha": "not-a-sha"},
        {"schema": "screamingface.reducer-golden.v0"},
        {"gradeable_count": 2},  # counters disagree with the statuses
        {"case_failures": {}},  # a failed case must name its reason
        {"final_score": 0.5},  # the score is a decimal string, never a float
        {"unknown": 1},
        {"lane": "inspect-gsm8k-other"},  # the golden belongs to one lane and one board
        {"board": "ifeval"},
    ],
)
def test_golden_refuses_a_bad_shape_on_read(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ReducerGolden.model_validate(_golden_doc(**overrides))


def test_the_refusal_names_the_lane_script_and_not_the_board_refresh_recipe() -> None:
    with pytest.raises(ValidationError) as refused:
        ReducerGolden.model_validate(_golden_doc(case_failures={}))

    assert "e2e-refresh-golden" not in str(refused.value)
    assert "tests/e2e/fixtures/reducer_lane.py" in str(refused.value)


def test_golden_refuses_evidence_for_a_case_it_does_not_list() -> None:
    document = _golden_doc(evidence={"case_id": "9", "combine": {}})
    with pytest.raises(ValidationError):
        ReducerGolden.model_validate(document)


def test_load_reducer_golden_reads_a_file_and_names_the_file_on_error(tmp_path: Path) -> None:
    good = tmp_path / "good.reducer-golden.json"
    good.write_text(json.dumps(_golden_doc()), encoding="utf-8")
    loaded = load_reducer_golden(good)
    assert loaded.evidence.operation_id == "op_synthesis_1"
    assert loaded.candidate.samples == 5

    bad = tmp_path / "bad.reducer-golden.json"
    bad.write_text(json.dumps(_golden_doc(gradeable_count=2)), encoding="utf-8")
    with pytest.raises(ValueError, match="bad.reducer-golden.json"):
        load_reducer_golden(bad)
    broken = tmp_path / "broken.reducer-golden.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="broken.reducer-golden.json"):
        load_reducer_golden(broken)


# -- the evidence lock --------------------------------------------------------------


def _lock(cases: Sequence[Any], golden: ReducerGolden | None = None) -> None:
    assert_evidence_lock(
        ReducerGolden.model_validate(_golden_doc()) if golden is None else golden, cases
    )


def test_evidence_lock_passes_for_the_recorded_case() -> None:
    _lock([_case("2"), _case("1")])


def test_evidence_lock_names_a_missing_case() -> None:
    with pytest.raises(AssertionError, match="no case '1'"):
        _lock([_case("2")])


def test_evidence_lock_names_drifted_combine_evidence() -> None:
    drifted = _evidence().to_dict()
    drifted["chosen"] = ["member_3"]
    golden = ReducerGolden.model_validate(
        _golden_doc(evidence={"case_id": "1", "combine": drifted})
    )
    with pytest.raises(AssertionError, match="combine evidence drifted"):
        _lock([_case()], golden)


def test_evidence_lock_wants_one_reading_per_sample() -> None:
    four = CombineEvidence(
        kind="answer",
        reducer="vote",
        operators=("last_number@1",),
        members=[_row(i, "1") for i in range(1, 5)],
        chosen=("member_1",),
        built=False,
        tie=False,
        agreement=1.0,
        result=_answered("member_1", "1"),
        dropped=0,
        finish_reason="stop",
    )
    golden = ReducerGolden.model_validate(
        _golden_doc(evidence={"case_id": "1", "combine": four.to_dict()})
    )
    with pytest.raises(AssertionError, match="5 member readings"):
        _lock([_case(evidence=four)], golden)


def test_evidence_lock_wants_a_positive_agreement() -> None:
    zero = _evidence(agreement=0.0)
    golden = ReducerGolden.model_validate(
        _golden_doc(evidence={"case_id": "1", "combine": zero.to_dict()})
    )
    with pytest.raises(AssertionError, match="agreement"):
        _lock([_case(evidence=zero)], golden)


def test_evidence_lock_wants_the_synthesis_to_be_the_chosen_members_text_verbatim() -> None:
    with pytest.raises(AssertionError, match="chosen member"):
        _lock([_case(synthesis_output="so 42!")])


def test_evidence_lock_names_a_vote_that_chose_no_member() -> None:
    built = CombineResult(member_id=None, value="42", status="answered", reason=None)
    empty = CombineEvidence(**{**_evidence_kwargs(), "chosen": (), "built": True, "result": built})
    golden = ReducerGolden.model_validate(
        _golden_doc(evidence={"case_id": "1", "combine": empty.to_dict()})
    )
    with pytest.raises(AssertionError, match="chose no member"):
        _lock([_case(evidence=empty)], golden)


def test_evidence_lock_wants_every_member_output_attributed() -> None:
    answers = [*_ANSWERS[:4], None]
    with pytest.raises(AssertionError, match="op_model_5"):
        _lock([_case(answers=answers)])


class _Forged:
    """A combine reading with some attributes overridden, for what the constructor refuses."""

    def __init__(self, base: CombineEvidence, **overrides: Any) -> None:
        self._base, self._overrides = base, overrides

    def __getattr__(self, name: str) -> Any:
        return self._overrides.get(name, getattr(self._base, name))

    def to_dict(self) -> dict[str, object]:
        return self._base.to_dict()


def test_evidence_lock_refuses_an_abstained_pinned_case() -> None:
    abstained = _abstained_evidence()
    golden = ReducerGolden.model_validate(
        _golden_doc(evidence={"case_id": "1", "combine": abstained.to_dict()})
    )
    with pytest.raises(AssertionError, match="did not answer"):
        _lock([_case(evidence=abstained)], golden)


def test_evidence_lock_wants_the_result_member_to_be_the_chosen_member() -> None:
    forged = _Forged(_evidence(), result=_answered("member_3", "42"))
    case = _case()
    synthesis = SimpleNamespace(operation_id="op_synthesis_1", output="so 42", combine=forged)
    case.operations = (*case.operations[:-1], synthesis)
    with pytest.raises(AssertionError, match="did not answer"):
        _lock([case])

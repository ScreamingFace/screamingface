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
from harness.goldens import GoldenReport
from harness.reducer_golden import (
    REDUCER_GOLDEN_SCHEMA,
    ReducerCandidateSpec,
    ReducerGolden,
    SignalReplayLock,
    assert_evidence_lock,
    assert_signal_replay,
    load_reducer_golden,
)
from pydantic import ValidationError

import screamingface as sf
from screamingface.case_result import CaseOperation
from screamingface.combine_evidence import (
    CombineAnswerRow,
    CombineEvidence,
    CombineResult,
    CombineSignal,
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


def _priced_evidence(member_2_cost: float = 0.002) -> CombineEvidence:
    """The cost-weighted vote over the same five answers: every member row carries its price."""
    costs = {2: member_2_cost}
    members = [
        CombineAnswerRow(
            member_id=f"member_{index}",
            raw=text.split()[-1],
            value=text.split()[-1],
            status="answered",
            reason=None,
            signals={"cost_usd": costs.get(index, 0.001)},
            weight=costs.get(index, 0.001),
        )
        for index, text in enumerate(_ANSWERS, start=1)
    ]
    kwargs = {**_evidence_kwargs(), "members": members}
    return CombineEvidence(**kwargs, signal=CombineSignal(key="cost_usd", order=None))


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


def _trace() -> dict[str, Any]:
    return {"schema": "screamingface.report-trace.v1", "candidates": []}


def _signal_doc(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "weights": "cost_usd",
        "expression_sha": _SHA,
        "combines": {"1": json.loads(json.dumps(_priced_evidence().to_dict()))},
    }
    document.update(overrides)
    return document


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
        "signal_replay": _signal_doc(),
        "live_traces": {"vote": _trace(), "signal_vote": _trace()},
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


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema": "screamingface.reducer-golden.v0"},
        {"gradeable_count": 2},  # counters disagree with the statuses
        {"lane": "inspect-gsm8k-other"},  # the golden belongs to one lane and one board
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


def test_evidence_lock_names_drifted_combine_evidence() -> None:
    drifted = _evidence().to_dict()
    drifted["chosen"] = ["member_3"]
    golden = ReducerGolden.model_validate(
        _golden_doc(evidence={"case_id": "1", "combine": drifted})
    )
    with pytest.raises(AssertionError, match="combine evidence drifted"):
        _lock([_case()], golden)


def test_evidence_lock_wants_the_synthesis_to_be_the_chosen_members_text_verbatim() -> None:
    with pytest.raises(AssertionError, match="chosen member"):
        _lock([_case(synthesis_output="so 42!")])


# -- the signal replay lock (SG#15) and the live traces (RT#16) ---------------------


def _unpriced_combine() -> dict[str, Any]:
    return json.loads(json.dumps(_evidence().to_dict()))


def test_signal_lock_refuses_an_unpriced_recording() -> None:
    with pytest.raises(ValidationError, match="priced no call"):
        SignalReplayLock.model_validate(_signal_doc(combines={"1": _unpriced_combine()}))
    with pytest.raises(ValidationError, match="priced no call"):
        SignalReplayLock.model_validate(_signal_doc(combines={}))


@pytest.mark.parametrize(
    "live_traces",
    [
        {"vote": _trace()},  # the signal vote's trace is missing
        {"vote": _trace(), "signal_vote": {"schema": "screamingface.report-trace.v2"}},
    ],
    ids=["missing signal_vote", "wrong schema"],
)
def test_golden_needs_both_live_traces(live_traces: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ReducerGolden.model_validate(_golden_doc(live_traces=live_traces))


def _signal_golden() -> ReducerGolden:
    return ReducerGolden.model_validate(_golden_doc())


def _signal_case(evidence: CombineEvidence) -> Any:
    return _case("1", evidence=evidence)


def test_assert_signal_replay_names_a_signal_drift() -> None:
    drifted = _signal_case(_priced_evidence(member_2_cost=0.003))

    with pytest.raises(AssertionError, match="case '1'.*signals"):
        assert_signal_replay(_signal_golden(), "rendered expression", [drifted])


def test_assert_signal_replay_names_a_tally_drift_and_a_missing_case() -> None:
    other_pick = CombineEvidence(
        **{**_evidence_kwargs(), "chosen": ("member_3",), "result": _answered("member_3", "42")}
    )
    with pytest.raises(AssertionError, match="case '1'.*more than the signals.*chosen"):
        assert_signal_replay(_signal_golden(), "rendered expression", [_signal_case(other_pick)])
    with pytest.raises(AssertionError, match="case '1'.*missing"):
        assert_signal_replay(_signal_golden(), "rendered expression", [])

"""FEATURE memory fix 3 (OME-1835), unit 2: late accounting per Evidence item equals today's
whole-result reconcile.

INVARIANT defended: the parked body recomputes each Evidence item's grading accounting when it
is written, and the bytes equal ``compact_json(finalize_candidate_result(...).as_payload())``,
whose reconcile runs once on the complete result. This holds for a unique owner, for a request
key with two owners (revoked for both), and for an owner registered after an earlier Case was
parked. With nothing bound, or when no value changes, the parked text is written verbatim.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_candidate_result_contract import _failure
from test_grading_accounting import _accounting, _record, _register

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
)
from screamingface_engine.benchmarks.case_result_store import CaseResultStore
from screamingface_engine.benchmarks.contract import (
    CaseGrade,
    CaseResult,
    Check,
    Evidence,
    EvidenceProducer,
)
from screamingface_engine.benchmarks.result_body import compact_json, encode_result_body
from screamingface_engine.benchmarks.result_builder import CandidateResultBuilder
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    capture_grading_requests,
)
from screamingface_engine.operation_accounting import OperationAccounting
from screamingface_engine.operation_calls import capture_request_accounting

_BENCHMARK_ID = "healthbench"


@pytest.fixture
def store(tmp_path) -> Iterator[CaseResultStore]:
    case_store = CaseResultStore.create(tmp_path)
    yield case_store
    case_store.close()


def _owner(case_id: int) -> GradingEvidenceOwner:
    return GradingEvidenceOwner(
        benchmark_id=_BENCHMARK_ID, case_id=case_id, check_id="rubric-1", sequence=1
    )


def _case(case_id: int, provisional: OperationAccounting | None) -> CaseResult:
    evidence = Evidence(
        sequence=1,
        producer=EvidenceProducer(type="model", id="judge"),
        valid=True,
        outcome="MET",
        explanation="ok",
        raw_output="verdict",
        metadata={},
        accounting=provisional,
    )
    check = Check(
        type="rubric",
        id="rubric-1",
        label="rubric-1",
        outcome="MET",
        score=1.0,
        evidence=[evidence],
        metadata={},
    )
    return CaseResult(
        status="scored",
        case_id=case_id,
        input="question",
        output="answer",
        finish_reason="stop",
        refusal=None,
        grade=CaseGrade(method="rubric", score=1.0, metrics={}, checks=[check]),
        failures=[],
        metadata={},
    )


def _kwargs(*case_ids: int) -> dict[str, Any]:
    return {
        "benchmark_id": _BENCHMARK_ID,
        "benchmark_revision": "revision",
        "selected_cases": [
            SelectedCase(case_id=i, input="question", metadata={}) for i in case_ids
        ],
        "scorer": lambda _cases: CandidateScore(score=1.0, metrics={}),
        "failure_policy": "coverage_declare",
    }


def _held(cases: list[CaseResult]) -> str:
    ids = [case.case_id for case in cases]
    return compact_json(finalize_candidate_result(**_kwargs(*ids), cases=cases).as_payload())  # type: ignore[arg-type]


def _builder(store: CaseResultStore | None, *case_ids: int) -> CandidateResultBuilder:
    return CandidateResultBuilder(**_kwargs(*case_ids), parked=True, store=store)


def _parked(cases: list[CaseResult], store: CaseResultStore | None) -> str:
    builder = _builder(store, *[case.case_id for case in cases])  # type: ignore[misc]
    for case in cases:
        builder.add(case)
    return encode_result_body(builder.finish_body())


def _evidence_accounting(text: str) -> list[Any]:
    cases = json.loads(text)["cases"]
    return [case["grade"]["checks"][0]["evidence"][0]["accounting"] for case in cases]


def test_a_unique_owner_gets_its_accounting_at_write(store: CaseResultStore) -> None:
    with capture_request_accounting():
        with capture_grading_requests():
            _register(_owner(7))
            _record("0.1")

            held = _held([_case(7, None)])
            parked = _parked([_case(7, None)], store)

    assert parked == held
    [accounting] = _evidence_accounting(parked)
    assert accounting["usage"]["cost_usd"] == "0.1"


def test_two_owners_of_one_request_key_are_both_revoked(store: CaseResultStore) -> None:
    with capture_request_accounting():
        with capture_grading_requests():
            _register(_owner(7))
            _register(_owner(8))
            _record("0.1")

            held = _held([_case(7, _accounting("0.1")), _case(8, _accounting("0.1"))])
            parked = _parked([_case(7, _accounting("0.1")), _case(8, _accounting("0.1"))], store)

    assert parked == held
    assert _evidence_accounting(parked) == [None, None]


def test_an_owner_registered_after_an_earlier_case_was_parked(store: CaseResultStore) -> None:
    with capture_request_accounting():
        with capture_grading_requests():
            _register(_owner(7))
            _record("0.1")
            # Case 7 is parked while its owner is the only one on the request key.
            provisional = accounting_for_grading_evidence(_owner(7))
            assert provisional is not None
            builder = _builder(store, 7, 8)
            builder.add(_case(7, provisional))
            _register(_owner(8))
            builder.add(_case(8, None))
            parked = encode_result_body(builder.finish_body())

            held = _held([_case(7, _accounting("0.1")), _case(8, None)])

    assert parked == held
    assert _evidence_accounting(parked) == [None, None]


def test_with_nothing_bound_the_parked_text_is_written_verbatim(store: CaseResultStore) -> None:
    builder = _builder(store, 7, 8)
    builder.add(_case(7, _accounting("0.1")))
    builder.add(_case(8, _accounting("0.2")))
    body = builder.finish_body()

    fragments = list(body.case_fragments())

    for fragment, parked in zip(fragments, body.cases, strict=True):
        assert parked.key is not None
        assert fragment == store.read_text(parked.key)
    text = encode_result_body(body)
    assert [a["usage"]["cost_usd"] for a in _evidence_accounting(text)] == ["0.1", "0.2"]
    assert text == _held([_case(7, _accounting("0.1")), _case(8, _accounting("0.2"))])


def test_a_case_whose_accounting_does_not_change_is_written_verbatim(
    store: CaseResultStore,
) -> None:
    failed = _case(9, None).model_copy(
        update={
            "status": "failed",
            "output": None,
            "finish_reason": None,
            "grade": None,
            "failures": [_failure(case_id=9)],
        }
    )
    with capture_request_accounting():
        with capture_grading_requests():
            _register(_owner(7))
            _record("0.1")
            # Case 8's owner has no request keys and its provisional accounting is None.
            builder = _builder(store, 8, 9)
            builder.add(_case(8, None))
            builder.add(failed)
            body = builder.finish_body()

            fragments = list(body.case_fragments())
            parked = encode_result_body(body)
            held = _held([_case(8, None), failed.model_copy()])

    for fragment, case in zip(fragments, body.cases, strict=True):
        assert case.key is not None
        assert fragment == store.read_text(case.key)
    assert parked == held

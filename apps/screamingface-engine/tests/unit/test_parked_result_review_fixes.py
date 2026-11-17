"""FEATURE memory fix 3 (OME-1835), unit 2: review fixes for the parked Candidate Result.

INVARIANT defended: a picture input parks as the bytes the held result shows, placeholder and all
(a); a parking failure reaches the async endpoint's caller as CaseParkingError, never as
benchmark_unavailable (b); the spooled parked body writes the final grading accounting, as the
held result does (c); the grading view is a frozen copy of the run's join (d); a view exists only
when a grading registry and a request ledger are both bound (e).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from test_candidate_result_contract import _scored_case
from test_deliver_result import _request
from test_grading_accounting import _record, _register

from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.spool import ResultSpool, binding_result_spool
from screamingface_engine.benchmarks.aggregation import CandidateScore, SelectedCase
from screamingface_engine.benchmarks.case_result_store import CaseResultStore
from screamingface_engine.benchmarks.contract import (
    CANDIDATE_INPUT_V2_SCHEMA,
    CaseGrade,
    CaseResult,
    Check,
    Evidence,
    EvidenceProducer,
)
from screamingface_engine.benchmarks.grading_endpoints import (
    async_aggregate_endpoint,
    deliver_result,
)
from screamingface_engine.benchmarks.result_body import compact_json, encode_result_body
from screamingface_engine.benchmarks.result_builder import (
    CandidateResultBuilder,
    CaseParkingError,
)
from screamingface_engine.grading_accounting import (
    GradingEvidenceOwner,
    accounting_for_grading_evidence,
    capture_grading_requests,
    grading_accounting_view,
)
from screamingface_engine.operation_calls import capture_request_accounting
from url4.core.errors import ResolutionError

_BENCHMARK_ID = "healthbench"
# The 8-byte PNG signature, as base64; the same bytes the placeholder tests use.
_PNG = "data:image/png;base64,iVBORw0KGgo="
_PNG_BASE64 = "iVBORw0KGgo="


@pytest.fixture
def store(tmp_path) -> Iterator[CaseResultStore]:
    case_store = CaseResultStore.create(tmp_path)
    yield case_store
    case_store.close()


def _owner(case_id: int) -> GradingEvidenceOwner:
    return GradingEvidenceOwner(
        benchmark_id=_BENCHMARK_ID, case_id=case_id, check_id="rubric-1", sequence=1
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


def _case(case_id: int) -> CaseResult:
    evidence = Evidence(
        sequence=1,
        producer=EvidenceProducer(type="model", id="judge"),
        valid=True,
        outcome="MET",
        explanation="ok",
        raw_output="verdict",
        metadata={},
        accounting=None,
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


def _picture_input() -> str:
    """One user message: a question and one picture, sealed in a v2 envelope."""

    return json.dumps(
        {
            "schema": CANDIDATE_INPUT_V2_SCHEMA,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is shown?"},
                        {"type": "image_url", "image_url": {"url": _PNG}},
                    ],
                }
            ],
        },
        separators=(",", ":"),
    )


def _pictured_cases() -> list[CaseResult]:
    return [_scored_case(1, input=_picture_input()), _scored_case(2)]


def test_a_picture_input_parks_to_the_held_bytes(store: CaseResultStore) -> None:
    held = CandidateResultBuilder(**_kwargs(1, 2))
    parked = CandidateResultBuilder(**_kwargs(1, 2), parked=True, store=store)
    for case in _pictured_cases():
        held.add(case)
    for case in _pictured_cases():
        parked.add(case)

    parked_text = encode_result_body(parked.finish_body())

    assert parked_text == compact_json(held.finish_result().as_payload())
    assert "placeholder" in parked_text
    assert _PNG_BASE64 not in parked_text


@pytest.mark.asyncio
async def test_a_parking_failure_through_the_async_endpoint_is_not_benchmark_unavailable() -> None:
    async def adapter(raw, ids):
        raise CaseParkingError("disk full")

    endpoint = async_aggregate_endpoint(label="t", available_case_count=1, aggregate=adapter)

    with pytest.raises(CaseParkingError) as caught:
        await endpoint(_request())

    assert not isinstance(caught.value, ResolutionError)


@pytest.mark.asyncio
async def test_the_spooled_parked_body_carries_the_final_accounting(
    store: CaseResultStore, tmp_path
) -> None:
    with capture_request_accounting():
        with capture_grading_requests():
            _register(_owner(7))
            _record("0.1")
            held = CandidateResultBuilder(**_kwargs(7))
            held.add(_case(7))
            held_result = held.finish_result()
            parked = CandidateResultBuilder(**_kwargs(7), parked=True, store=store)
            parked.add(_case(7))
            body = parked.finish_body()
            spool = ResultSpool(
                FilesystemArtifactStore(tmp_path), inline_cap=1_000_000, hard_cap=1_000_000
            )
            with binding_result_spool(spool):
                text = await deliver_result(body)

    assert text == compact_json(held_result.as_payload())
    evidence = json.loads(text)["cases"][0]["grade"]["checks"][0]["evidence"][0]
    assert evidence["accounting"]["usage"]["cost_usd"] == "0.1"


def test_the_accounting_view_is_frozen() -> None:
    with capture_request_accounting():
        with capture_grading_requests():
            _register(_owner(7))
            _record("0.1")
            view = grading_accounting_view()
            assert view is not None
            taken = view.accounting_for(_owner(7))
            assert taken is not None
            assert taken.usage.cost_usd == "0.1"

            # WHY a second owner on the same request key: the live join revokes owner 7.
            _register(_owner(8))

            assert accounting_for_grading_evidence(_owner(7)) is None
            fresh = grading_accounting_view()
            assert fresh is not None
            assert fresh.accounting_for(_owner(7)) is None
            assert view.accounting_for(_owner(7)) == taken
            assert _owner(8) not in view.keys_by_owner


def test_the_view_is_none_unless_a_registry_and_a_ledger_are_bound() -> None:
    assert grading_accounting_view() is None
    with capture_grading_requests():
        assert grading_accounting_view() is None
    with capture_request_accounting():
        assert grading_accounting_view() is None
    with capture_request_accounting():
        with capture_grading_requests():
            assert grading_accounting_view() is not None


@pytest.mark.asyncio
async def test_the_spool_writer_reads_the_view_taken_at_finish_not_the_live_registry(
    store: CaseResultStore, tmp_path
) -> None:
    # WHY a second owner after finish_body: it revokes owner 7 in the LIVE join. The body must
    # still carry the accounting of the view taken at finish (review finding R1), as the held
    # result does, because the writer runs later on the spool's worker thread.
    with capture_request_accounting():
        with capture_grading_requests():
            _register(_owner(7))
            _record("0.1")
            held = CandidateResultBuilder(**_kwargs(7))
            held.add(_case(7))
            held_result = held.finish_result()
            parked = CandidateResultBuilder(**_kwargs(7), parked=True, store=store)
            parked.add(_case(7))
            body = parked.finish_body()

            _register(_owner(8))
            assert accounting_for_grading_evidence(_owner(7)) is None

            spool = ResultSpool(
                FilesystemArtifactStore(tmp_path), inline_cap=1_000_000, hard_cap=1_000_000
            )
            with binding_result_spool(spool):
                text = await deliver_result(body)

    assert text == compact_json(held_result.as_payload())
    evidence = json.loads(text)["cases"][0]["grade"]["checks"][0]["evidence"][0]
    assert evidence["accounting"]["usage"]["cost_usd"] == "0.1"


def test_a_case_that_cannot_be_encoded_fails_parking_with_its_reason(
    store: CaseResultStore,
) -> None:
    builder = CandidateResultBuilder(**_kwargs(7), parked=True, store=store)
    case = _case(7).model_copy(update={"output": "ANSWER: A \ud800"})

    with pytest.raises(CaseParkingError, match="cannot be encoded as UTF-8"):
        builder.add(case)

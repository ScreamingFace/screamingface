"""FEATURE memory fix 3 (OME-1835), unit 2: the parked body writes the held bytes.

INVARIANT defended: for the same inputs, ``encode_result_body(builder.finish_body())`` equals
``compact_json(finalize_candidate_result(...).as_payload())``, with a bound Case-result store and
with none. The builder keeps today's error messages and precedence, hands the capture tally the
same pairs, still runs every whole-set validator, scores projections, and fails closed (a store
error on read; a CaseParkingError, never an OSError or a ValueError, on park).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from pydantic import ValidationError
from test_candidate_result_contract import _failure, _grade, _scored_case
from test_result_body import _fixtures

from screamingface_engine.benchmarks.aggregation import (
    CandidateScore,
    SelectedCase,
    finalize_candidate_result,
)
from screamingface_engine.benchmarks.case_result_store import (
    CaseResultStore,
    CaseResultStoreError,
)
from screamingface_engine.benchmarks.contract import CaseResult, Failure
from screamingface_engine.benchmarks.replay_stability import replay_stable_failure
from screamingface_engine.benchmarks.result_body import compact_json, encode_result_body
from screamingface_engine.benchmarks.result_builder import (
    CandidateResultBuilder,
    CaseParkingError,
    ParkedResultBody,
)
from screamingface_engine.benchmarks.scoring_projection import NOT_RETAINED, scoring_projection
from screamingface_engine.capture_outcomes import capture_outcomes


@pytest.fixture
def store(tmp_path) -> Iterator[CaseResultStore]:
    case_store = CaseResultStore.create(tmp_path)
    yield case_store
    case_store.close()


def _is_fill(case: CaseResult) -> bool:
    return case.status == "failed" and any(f.code == "case_result_missing" for f in case.failures)


def _inputs(name: str) -> dict[str, Any]:
    """Fresh finalize inputs for one unit 1 fixture (held reconcile mutates Evidence in place)."""

    result = _fixtures()[name]
    return {
        "benchmark_id": result.benchmark_id,
        "benchmark_revision": result.benchmark_revision,
        "selected_cases": [
            SelectedCase(case_id=case.case_id, input=case.input, metadata=case.metadata)
            for case in result.cases
        ],
        # The fills are left out, so the builder makes them as finalize does.
        "cases": [case for case in result.cases if not _is_fill(case)],
        "scorer": lambda _cases: CandidateScore(
            score=result.score,  # type: ignore[arg-type]
            metrics=result.metrics,
            scores=result.scores,
        ),
        "failure_policy": "coverage_declare",
        "failures": result.failures,
        "inverted_grade": result.inverted_grade,
    }


def _builder(inputs: dict[str, Any], *, parked: bool, store: CaseResultStore | None):
    values = dict(inputs)
    cases: Sequence[CaseResult] = values.pop("cases")
    builder = CandidateResultBuilder(**values, parked=parked, store=store)
    for case in cases:
        builder.add(case)
    return builder


def _parked_body(inputs: dict[str, Any], store: CaseResultStore | None) -> ParkedResultBody:
    return _builder(inputs, parked=True, store=store).finish_body()


def _held_text(inputs: dict[str, Any]) -> str:
    return compact_json(finalize_candidate_result(**inputs).as_payload())


def _parked_text(inputs: dict[str, Any], store: CaseResultStore | None) -> str:
    return encode_result_body(_parked_body(inputs, store))


def _outcome(call: Callable[[], str]) -> tuple[Any, ...]:
    """The text, or the error type and its messages (a ValidationError repr shows its input)."""

    try:
        return ("ok", call())
    except Exception as exc:  # the test compares whatever each side raises
        if isinstance(exc, ValidationError):
            return ("raised", type(exc), [error["msg"] for error in exc.errors()])
        return ("raised", type(exc), [str(exc)])


def _selected(*case_ids: int) -> list[SelectedCase]:
    return [SelectedCase(case_id=i, input=f"input {i}", metadata={}) for i in case_ids]


def _kwargs(*case_ids: int, scorer=None) -> dict[str, Any]:
    return {
        "benchmark_id": "benchmark",
        "benchmark_revision": "revision",
        "selected_cases": _selected(*case_ids),
        "scorer": scorer or (lambda _cases: CandidateScore(score=1.0, metrics={})),
        "failure_policy": "coverage_declare",
    }


@pytest.mark.parametrize("bound", ["store", "memory"])
@pytest.mark.parametrize("name", sorted(_fixtures()))
def test_the_parked_body_writes_the_held_bytes(name: str, bound: str, tmp_path) -> None:
    case_store = CaseResultStore.create(tmp_path) if bound == "store" else None
    try:
        held = _outcome(lambda: _held_text(_inputs(name)))
        parked = _outcome(lambda: _parked_text(_inputs(name), case_store))
    finally:
        if case_store is not None:
            case_store.close()

    assert parked == held


def test_todays_finalize_refuses_only_the_two_wire_only_fixtures() -> None:
    # WHY: the identity test above also passes when both sides raise; this keeps it honest.
    # The unit 1 fixtures are built with model_copy (no validation). Two of them are not a result
    # finalize can make: an empty selection with nothing to explain it, and a NaN metric (open
    # wire fields must be JSON values). For those two, the parked builder must raise the same.
    held = {name: _outcome(lambda name=name: _held_text(_inputs(name))) for name in _fixtures()}

    refused = sorted(name for name, outcome in held.items() if outcome[0] == "raised")
    assert refused == ["empty_selection", "nan_metric"]


@pytest.mark.parametrize(
    ("selected", "added", "message"),
    [
        ((1, 1), (1,), "selected Case sequence cannot contain duplicate case_id values"),
        ((1, 2), (1, 1), "CandidateResult cannot contain duplicate case_id values"),
        ((1,), (1, 2), "CandidateResult contains unselected case_id values [2]"),
        # Precedence: a duplicate selection wins over a duplicate added Case.
        ((1, 1), (1, 1), "selected Case sequence cannot contain duplicate case_id values"),
    ],
)
def test_the_set_errors_keep_todays_messages(
    selected: tuple[int, ...], added: tuple[int, ...], message: str, store: CaseResultStore
) -> None:
    def cases() -> list[CaseResult]:
        return [_scored_case(i) for i in added]

    with pytest.raises(ValueError) as held:
        finalize_candidate_result(**_kwargs(*selected), cases=cases())
    builder = CandidateResultBuilder(**_kwargs(*selected), parked=True, store=store)
    for case in cases():
        builder.add(case)
    with pytest.raises(ValueError) as parked:
        builder.finish_body()

    assert str(held.value) == str(parked.value) == message
    assert type(held.value) is type(parked.value) is ValueError


def _token_cap_failed(case_id: int) -> CaseResult:
    return _scored_case(case_id).model_copy(
        update={
            "status": "failed",
            "output": None,
            "finish_reason": None,
            "grade": None,
            "failures": [
                Failure(
                    stage="candidate",
                    code="model_token_cap",
                    message="the Candidate hit its token cap",
                    retryable=False,
                    case_id=case_id,
                    metadata={},
                )
            ],
        }
    )


def _record_cases() -> list[CaseResult]:
    retryable = _scored_case(4).model_copy(
        update={
            "status": "failed",
            "output": None,
            "finish_reason": None,
            "grade": None,
            "failures": [_failure(case_id=4)],
        }
    )
    return [_scored_case(1), _token_cap_failed(3), retryable]


def test_record_case_results_receives_the_same_pairs(store: CaseResultStore) -> None:
    assert replay_stable_failure(_token_cap_failed(3))
    with capture_outcomes() as held_tally:
        finalize_candidate_result(**_kwargs(1, 2, 3, 4), cases=_record_cases())
    with capture_outcomes() as parked_tally:
        builder = CandidateResultBuilder(**_kwargs(1, 2, 3, 4), parked=True, store=store)
        for case in _record_cases():
            builder.add(case)
        builder.finish_body()

    assert parked_tally.case_results == held_tally.case_results
    assert held_tally.case_results == {"1": True, "2": True, "3": False, "4": True}


def test_the_light_result_still_validates(store: CaseResultStore) -> None:
    def scorer(_cases: Sequence[CaseResult]) -> CandidateScore:
        return CandidateScore(score=1.0, metrics={"coverage": 1.0})

    builder = CandidateResultBuilder(**_kwargs(1, scorer=scorer), parked=True, store=store)
    builder.add(_scored_case(1))

    with pytest.raises(ValueError, match="metrics.coverage is replaced by top-level coverage"):
        builder.finish_body()


def test_parked_mode_scores_projections(store: CaseResultStore) -> None:
    seen: list[str] = []

    def scorer(cases: Sequence[CaseResult]) -> CandidateScore:
        seen.extend(case.input for case in cases)
        return CandidateScore(score=1.0, metrics={})

    builder = CandidateResultBuilder(**_kwargs(1, 2, scorer=scorer), parked=True, store=store)
    views = [builder.add(_scored_case(1)), builder.add(_scored_case(2))]
    builder.finish_body()

    assert seen == [NOT_RETAINED, NOT_RETAINED]
    for view in views:
        assert view.input == NOT_RETAINED
        assert scoring_projection(view) is view


def test_held_mode_add_returns_the_case_itself() -> None:
    builder = CandidateResultBuilder(**_kwargs(1))
    case = _scored_case(1)

    assert builder.add(case) is case
    assert builder.added == 1


def test_each_finish_belongs_to_its_mode(store: CaseResultStore) -> None:
    with pytest.raises(RuntimeError):
        CandidateResultBuilder(**_kwargs(1)).finish_body()
    with pytest.raises(RuntimeError):
        CandidateResultBuilder(**_kwargs(1), parked=True, store=store).finish_result()


def test_each_parked_fragment_is_the_stored_text(store: CaseResultStore) -> None:
    body = _parked_body(_inputs("non_ascii_and_emoji"), store)

    fragments = list(body.case_fragments())

    assert len(fragments) == len(body.cases) == 2
    for fragment, parked in zip(fragments, body.cases, strict=True):
        assert parked.key is not None
        assert parked.fragment is None
        assert fragment == store.read_text(parked.key)


def test_without_a_store_the_fragments_stay_in_memory() -> None:
    body = _parked_body(_inputs("non_ascii_and_emoji"), None)

    assert all(p.key is None and p.fragment is not None for p in body.cases)
    assert list(body.case_fragments()) == [p.fragment for p in body.cases]


def test_an_unreadable_parked_case_raises_the_store_error(store: CaseResultStore) -> None:
    body = _parked_body(_inputs("baseline"), store)
    store.close()

    with pytest.raises(CaseResultStoreError):
        encode_result_body(body)


def test_an_append_failure_is_a_case_parking_error(store: CaseResultStore) -> None:
    builder = CandidateResultBuilder(**_kwargs(1), parked=True, store=store)
    store.close()

    with pytest.raises(CaseParkingError) as raised:
        builder.add(_scored_case(1))

    assert not isinstance(raised.value, (OSError, ValueError))
    assert isinstance(raised.value.__cause__, CaseResultStoreError)


def test_the_body_writes_twice_the_same(store: CaseResultStore) -> None:
    body = _parked_body(_inputs("failed_and_missing"), store)

    assert encode_result_body(body) == encode_result_body(body)


@pytest.mark.parametrize("parked", [False, True])
def test_filled_holds_the_fill_views(parked: bool, store: CaseResultStore) -> None:
    builder = CandidateResultBuilder(**_kwargs(1, 2, 3), parked=parked, store=store)
    builder.add(_scored_case(1))
    if parked:
        builder.finish_body()
    else:
        builder.finish_result()

    assert [case.case_id for case in builder.filled] == [2, 3]
    assert all(case.failures[0].code == "case_result_missing" for case in builder.filled)
    assert builder.added == 1


def test_an_empty_selection_writes_an_empty_cases_array(store: CaseResultStore) -> None:
    # A Candidate-level Failure explains the unscored result, so finalize accepts it.
    inputs = {**_kwargs(), "cases": [], "failures": [_failure(case_id=None)]}

    text = _parked_text(inputs, store)

    assert '"cases":[]' in text
    assert text == _held_text({**inputs, "failures": [_failure(case_id=None)]})


def test_emoji_is_written_raw(store: CaseResultStore) -> None:
    text = _parked_text(_inputs("non_ascii_and_emoji"), store)

    assert "😀" in text
    assert "\\ud83d" not in text


def test_a_nan_metric_is_refused_as_finalize_refuses_it(store: CaseResultStore) -> None:
    # WHY not "NaN is written as NaN": finalize cannot make a NaN metric (open wire fields must
    # be JSON values), so the parked builder must refuse it the same way.
    held = _outcome(lambda: _held_text(_inputs("nan_metric")))
    parked = _outcome(lambda: _parked_text(_inputs("nan_metric"), store))

    assert parked == held
    assert held[0] == "raised"
    assert held[2] == ["Value error, open wire fields must contain JSON values"]


def test_a_string_case_id_keeps_its_type(store: CaseResultStore) -> None:
    selected = [SelectedCase(case_id="a-1", input="Return JSON.", metadata={})]
    kwargs = {**_kwargs(), "selected_cases": selected}
    builder = CandidateResultBuilder(**kwargs, parked=True, store=store)
    builder.add(_scored_case("a-1", grade=_grade()))

    body = builder.finish_body()

    assert body.cases[0].case_id == "a-1"
    assert encode_result_body(body) == _held_text(
        {**kwargs, "cases": [_scored_case("a-1", grade=_grade())]}
    )


@pytest.mark.parametrize("name", sorted(_fixtures()))
def test_the_held_builder_finishes_todays_result(name: str) -> None:
    # INVARIANT: one finalize implementation. Written before finalize moved onto the builder,
    # so it proves the held finish against the old code.
    held = _outcome(lambda: _held_text(_inputs(name)))
    built = _outcome(
        lambda: compact_json(
            _builder(_inputs(name), parked=False, store=None).finish_result().as_payload()
        )
    )

    assert built == held


def _invalid_scored(case_id: int) -> CaseResult:
    # A scored Case with neither output nor refusal breaks the CaseResult after-validator.
    return _scored_case(case_id).model_copy(update={"output": None, "refusal": None})


@pytest.mark.parametrize("bound", ["store", "memory"])
def test_an_invalid_case_raises_todays_validation_error(bound: str, tmp_path) -> None:
    def cases() -> list[CaseResult]:
        return [_scored_case(1), _invalid_scored(2), _scored_case(3)]

    case_store = CaseResultStore.create(tmp_path) if bound == "store" else None
    try:
        with pytest.raises(ValidationError) as held:
            finalize_candidate_result(**_kwargs(1, 2, 3), cases=cases())
        builder = CandidateResultBuilder(**_kwargs(1, 2, 3), parked=True, store=case_store)
        for case in cases():
            builder.add(case)
        with pytest.raises(ValidationError) as parked:
            builder.finish_body()
    finally:
        if case_store is not None:
            case_store.close()

    assert str(parked.value) == str(held.value)
    assert [error["loc"][:2] for error in parked.value.errors()] == [("cases", 1)]


def test_a_duplicate_added_case_wins_over_an_invalid_case(store: CaseResultStore) -> None:
    builder = CandidateResultBuilder(**_kwargs(1, 2), parked=True, store=store)
    for case in [_invalid_scored(1), _scored_case(2), _scored_case(2)]:
        builder.add(case)

    with pytest.raises(ValueError) as parked:
        builder.finish_body()

    assert not isinstance(parked.value, ValidationError)
    assert str(parked.value) == "CandidateResult cannot contain duplicate case_id values"


def test_the_parked_writer_keeps_the_nan_encoding() -> None:
    # Unit 1's writer writes NaN as NaN; the parked body keeps that encoding for its head.
    body = ParkedResultBody(
        benchmark_id="benchmark",
        case_count=0,
        head_payload={"metrics": {"m": float("nan")}, "cases": []},
        cases=(),
        store=None,
    )

    assert encode_result_body(body) == '{"metrics":{"m":NaN},"cases":[]}'

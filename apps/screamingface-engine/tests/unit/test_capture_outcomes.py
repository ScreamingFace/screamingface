"""E14 F-B3 — the run-scoped capture tally and the `capture.status` rule (design §5.2 item 5).

FEATURE: OME-1307 — a capture run is `complete` only when the copy opened, sealed, and every chat
call and tool result is `stored`. D1: a cancelled or crashed call is an `error`. Q27: no outcome is
forgiven, so a call that left no entry at its key makes the run partial.
STORY: as a researcher who submits a score, the run's summary tells me whether it can be replayed.

A separate module (append-only gate).
"""

from __future__ import annotations

import pytest

from screamingface_engine.capture_outcomes import (
    CaptureOutcome,
    CaptureTally,
    Lane,
    Status,
    capture_outcomes,
    current_capture_tally,
    record_capture_outcome,
    record_case_results,
)

_COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"


def _tally(
    *outcomes: tuple[Lane, Status, str | None],
    open_failed: bool = False,
    seal_failed: bool = False,
) -> CaptureTally:
    tally = CaptureTally(
        mode="capture",
        frozen_copy_id=None if open_failed else _COPY,
        open_failed=open_failed,
        sealed=not open_failed and not seal_failed,
    )
    tally.outcomes.extend(CaptureOutcome(*outcome) for outcome in outcomes)
    return tally


@pytest.mark.parametrize(
    ("tally", "status", "partial"),
    [
        (_tally(), "complete", {}),
        (_tally(("chat", "stored", "a"), ("tool", "stored", "b")), "complete", {}),
        (_tally(("chat", "failed", "a")), "partial", {"failed": 1}),
        (_tally(("tool", "refused", "a"), ("chat", "refused", "b")), "partial", {"refused": 2}),
        (_tally(("chat", "missing", "a")), "partial", {"missing": 1}),
        (_tally(("chat", "stored", "a"), open_failed=True), "partial", {"open": 1}),
        (_tally(("chat", "stored", "a"), seal_failed=True), "partial", {"seal": 1}),
        # D1: a cancelled or crashed call is an error, and nothing replaced it.
        (_tally(("chat", "error", "a")), "partial", {"error": 1}),
        # Q27 (review round 2026-10-12): no outcome is forgiven, not even by a later stored answer.
        (_tally(("chat", "error", "a"), ("chat", "stored", "a")), "partial", {"error": 1}),
        (_tally(("tool", "error", "a"), ("tool", "stored", "a")), "partial", {"error": 1}),
        (_tally(("chat", "error", "a"), ("chat", "stored", "b")), "partial", {"error": 1}),
        (_tally(("chat", "stored", "a"), ("chat", "error", "a")), "partial", {"error": 1}),
        # ... failed, refused and missing stay lost.
        (
            _tally(("chat", "failed", "a"), ("chat", "stored", "a")),
            "partial",
            {"failed": 1},
        ),
        (
            _tally(("chat", "error", "a"), ("chat", "failed", "a")),
            "partial",
            {"failed": 1, "error": 1},
        ),
        # `ambiguous` (a re-issued or retried call) is never forgiven, by any later call.
        (_tally(("chat", "ambiguous", "a")), "partial", {"ambiguous": 1}),
        (
            _tally(("chat", "ambiguous", "a"), ("chat", "stored", "a")),
            "partial",
            {"ambiguous": 1},
        ),
        # An outcome with no digest cannot be matched to a retry.
        (_tally(("chat", "error", None), ("chat", "stored", None)), "partial", {"error": 1}),
        (
            _tally(("chat", "failed", "a"), ("tool", "missing", "b"), seal_failed=True),
            "partial",
            {"failed": 1, "missing": 1, "seal": 1},
        ),
    ],
)
def test_capture_status_rule(tally: CaptureTally, status: str, partial: dict[str, int]) -> None:
    assert tally.status() == status
    attributes = tally.attributes()
    assert attributes["capture.status"] == status
    assert {
        key.removeprefix("capture.partial."): value
        for key, value in attributes.items()
        if key.startswith("capture.partial.")
    } == partial


def test_a_copy_that_was_never_sealed_is_partial_seal() -> None:
    # A run that ended without sealing (stopped, or the seal never ran) is not complete.
    tally = CaptureTally(mode="capture", frozen_copy_id=_COPY)

    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.seal"] == 1
    tally.sealed = True
    assert tally.status() == "complete"
    assert "capture.partial.seal" not in tally.attributes()


def test_a_capture_run_states_its_copy_even_with_no_call() -> None:
    attributes = _tally().attributes()

    assert attributes == {"capture.frozen_copy_id": _COPY, "capture.status": "complete"}


def test_a_capture_run_whose_copy_never_opened_states_no_copy() -> None:
    attributes = _tally(open_failed=True).attributes()

    assert attributes == {"capture.status": "partial", "capture.partial.open": 1}


def test_a_replay_run_states_only_the_copy_it_replays() -> None:
    tally = CaptureTally(mode="replay", frozen_copy_id=_COPY)
    tally.outcomes.append(CaptureOutcome("chat", "failed", "a"))

    assert tally.attributes() == {"capture.replay": _COPY}


def test_a_normal_run_states_nothing() -> None:
    assert CaptureTally().attributes() == {}


def test_a_capture_attributes_carry_no_request_content() -> None:
    attributes = _tally(("chat", "failed", "a" * 64)).attributes()

    assert all(isinstance(value, (str, int)) for value in attributes.values())
    assert "a" * 64 not in str(attributes)


def test_the_tally_is_bound_for_a_scope_and_restored_after_it() -> None:
    assert current_capture_tally() is None
    record_capture_outcome(CaptureOutcome("chat", "stored"))  # no tally bound: a no-op

    with capture_outcomes() as tally:
        record_capture_outcome(CaptureOutcome("chat", "stored", "a"))
        assert current_capture_tally() is tally

    assert tally.outcomes == [CaptureOutcome("chat", "stored", "a")]
    assert current_capture_tally() is None


# ── OME-1775 (R1, R4): a no-answer outcome in a failed Case does not make the run partial ─────


def _outcome(
    status: Status,
    *,
    answered: bool,
    lane: Lane = "chat",
    digest: str | None = "a",
    case_id: str | None = "1",
    case_key: str = "k",
    occurrence: int | None = 0,
) -> CaptureOutcome:
    return CaptureOutcome(
        lane=lane,
        status=status,
        digest=digest,
        case_id=case_id,
        case_key=case_key,
        occurrence=occurrence,
        answered=answered,
    )


def _case_tally(*outcomes: CaptureOutcome, case_results: dict[str, bool]) -> CaptureTally:
    tally = CaptureTally(mode="capture", frozen_copy_id=_COPY, sealed=True)
    tally.outcomes.extend(outcomes)
    tally.case_results.update(case_results)
    return tally


def test_an_error_with_no_answer_in_a_failed_case_is_not_partial() -> None:
    # R1: a cancelled call gave the model no answer, and its Case failed, so a replay fails it too.
    tally = _case_tally(_outcome("error", answered=False), case_results={"1": False})

    assert tally.status() == "complete"
    assert "capture.partial.error" not in tally.attributes()


@pytest.mark.parametrize("status", ["failed", "refused", "missing"])
def test_a_non_2xx_outcome_with_no_answer_in_a_failed_case_is_not_partial(status: Status) -> None:
    tally = _case_tally(_outcome(status, answered=False), case_results={"1": False})

    assert tally.status() == "complete"
    assert not [key for key in tally.attributes() if key.startswith("capture.partial.")]


@pytest.mark.parametrize("status", ["failed", "refused", "missing"])
def test_a_non_2xx_answer_in_a_failed_case_stays_partial(status: Status) -> None:
    # R4: a 2xx answer the copy did not store is a replay miss where the capture used an answer.
    tally = _case_tally(_outcome(status, answered=True), case_results={"1": False})

    assert tally.status() == "partial"
    assert tally.attributes()[f"capture.partial.{status}"] == 1


def test_a_no_answer_outcome_in_a_scored_case_stays_partial() -> None:
    # R4: the Case scored, so a replay that misses where the capture went on would change it.
    tally = _case_tally(_outcome("error", answered=False), case_results={"1": True})

    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.error"] == 1


@pytest.mark.parametrize(
    ("outcome", "case_results"),
    [
        (_outcome("error", answered=False, case_id=None), {"1": False}),
        (_outcome("error", answered=False), {}),
    ],
    ids=["call-names-no-case", "case-not-in-results"],
)
def test_a_no_answer_outcome_is_forgiven_only_for_a_case_known_to_have_failed(
    outcome: CaptureOutcome, case_results: dict[str, bool]
) -> None:
    tally = _case_tally(outcome, case_results=case_results)

    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.error"] == 1


def test_an_ambiguous_outcome_in_a_failed_case_stays_partial() -> None:
    tally = _case_tally(_outcome("ambiguous", answered=False), case_results={"1": False})

    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.ambiguous"] == 1


@pytest.mark.parametrize(
    ("later_digest", "later_case_key", "status"),
    [
        ("a", "k", "partial"),
        ("b", "k", "complete"),
        ("a", "k2", "complete"),
    ],
    ids=["same-request-same-case-key", "other-request", "other-case-key"],
)
def test_a_no_answer_outcome_is_not_forgiven_when_a_later_occurrence_of_its_request_answered(
    later_digest: str, later_case_key: str, status: str
) -> None:
    # The retry guard (OME-1775 §4.1): url4 retried the failed call at the next occurrence and
    # got an answer, which a replay would not reproduce. Another request or key is not the retry.
    tally = _case_tally(
        _outcome("error", answered=False, occurrence=0),
        _outcome(
            "stored",
            answered=True,
            digest=later_digest,
            case_key=later_case_key,
            occurrence=1,
        ),
        case_results={"1": False},
    )

    assert tally.status() == status


@pytest.mark.parametrize(
    "results",
    [[("1", False), ("1", True)], [("1", True), ("1", False)]],
    ids=["failed-then-scored", "scored-then-failed"],
)
def test_a_case_that_scored_for_one_candidate_is_not_failed_for_the_run(
    results: list[tuple[str, bool]],
) -> None:
    # R1 (many Candidates): a run holds one final result per Candidate; a scored Case stays scored.
    with capture_outcomes() as tally:
        record_capture_outcome(_outcome("error", answered=False))
        for case_id, scored in results:
            record_case_results([(case_id, scored)])
    tally.mode = "capture"
    tally.frozen_copy_id = _COPY
    tally.sealed = True

    assert tally.case_results == {"1": True}
    assert tally.status() == "partial"
    assert tally.attributes()["capture.partial.error"] == 1


def test_recording_case_results_with_no_tally_bound_is_a_no_op() -> None:
    record_case_results([("1", True)])

    assert current_capture_tally() is None

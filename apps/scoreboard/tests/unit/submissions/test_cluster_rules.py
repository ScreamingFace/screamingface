"""SC-12, SC-15, SC-16 and the pure rules behind them (labels, receipt columns, binding, cursors).

FEATURE: OME-1307 (E14).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from scoreboard.core.paging import Cursor, InvalidCursor, decode_cursor, encode_cursor
from scoreboard.core.submissions.clustering import publication_needed, result_labels
from scoreboard.core.submissions.receipts import (
    ReceiptClaims,
    ReceiptNotYours,
    check_receipt_binding,
    receipt_columns,
)
from scoreboard.scores.cluster_rules import cluster_revision, replay_columns, result_fields
from scoreboard.scores.schemas import ReplayClaim, ScoreSubmission
from tests.unit.submissions._receipts import ANA, TRACE_ID, URL4_A


def _claims(**overrides: Any) -> ReceiptClaims:
    values: dict[str, Any] = {
        "sub": ANA,
        "vid": uuid.uuid4(),
        "tid": TRACE_ID,
        "sha": "a" * 64,
        "n": 412,
        "c": 420,
        "cov": "complete",
        "iat": 1_700_000_000,
    }
    values.update(overrides)
    return ReceiptClaims(**values)


def _submission(**overrides: Any) -> ScoreSubmission:
    values: dict[str, Any] = {
        "benchmark_id": "pub",
        "spec_id": "kevins-best",
        "url4_expression": URL4_A,
        "submitted_by": ANA,
        "score": 0.5,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
    }
    values.update(overrides)
    return ScoreSubmission(**values)


def test_cluster_key_uses_resolved_revision_not_client_metadata() -> None:
    typed_and_metadata = _submission(benchmark_revision="r2", metadata={"benchmark_revision": "r1"})
    metadata_only = _submission(metadata={"benchmark_revision": "r1"})
    neither = _submission()
    junk = _submission(metadata={"benchmark_revision": 7})

    assert cluster_revision(typed_and_metadata) == "r2"
    assert cluster_revision(metadata_only) == "r1"
    assert cluster_revision(neither) is None
    assert cluster_revision(junk) is None


def test_partial_receipt_stored_as_partial() -> None:
    claims = _claims(cov="partial", n=412, c=420)

    columns = receipt_columns(claims)

    assert columns["cache_coverage_status"] == "partial"
    assert result_labels(
        coverage_status="partial",
        entry_count=412,
        call_count=420,
        replayed_from_result_id=None,
        replay_hits=None,
        replay_misses=None,
    ) == ["partial cache (412 of 420 calls)"]


def test_receipt_columns_are_all_set_or_all_none() -> None:
    claims = _claims()

    assert receipt_columns(claims) == {
        "cache_version_id": claims.vid,
        "cache_version_sha256": "a" * 64,
        "cache_entry_count": 412,
        "cache_call_count": 420,
        "cache_coverage_status": "complete",
    }
    assert receipt_columns(None) == dict.fromkeys(
        (
            "cache_version_id",
            "cache_version_sha256",
            "cache_entry_count",
            "cache_call_count",
            "cache_coverage_status",
        )
    )


def test_labels_partial_first_then_replay_then_nothing() -> None:
    source = uuid.uuid4()

    both = result_labels(
        coverage_status="partial",
        entry_count=1,
        call_count=2,
        replayed_from_result_id=source,
        replay_hits=3,
        replay_misses=1,
    )
    replay_only = result_labels(
        coverage_status="complete",
        entry_count=2,
        call_count=2,
        replayed_from_result_id=source,
        replay_hits=3,
        replay_misses=1,
    )
    none = result_labels(
        coverage_status=None,
        entry_count=None,
        call_count=None,
        replayed_from_result_id=None,
        replay_hits=None,
        replay_misses=None,
    )

    assert both == ["partial cache (1 of 2 calls)", f"replay of {source} (3/4)"]
    assert replay_only == [f"replay of {source} (3/4)"]
    assert none == []


def test_new_versioned_result_gets_private_publication_row() -> None:
    assert publication_needed(receipt_columns(_claims())) is True
    assert publication_needed(receipt_columns(None)) is False


def test_replay_columns_are_all_set_or_all_none() -> None:
    result_id, version_id, baseline = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    claim = ReplayClaim(
        result_id=result_id,
        cache_version_id=version_id,
        hits=10,
        misses=2,
        repeated_key_collapses=3,
        pinned_baseline_result_id=baseline,
    )

    assert replay_columns(claim) == {
        "replayed_from_result_id": result_id,
        "replay_hits": 10,
        "replay_misses": 2,
        "pinned_baseline_result_id": baseline,
        "replay_repeated_key_collapses": 3,
    }
    assert replay_columns(None) == dict.fromkeys(
        (
            "replayed_from_result_id",
            "replay_hits",
            "replay_misses",
            "pinned_baseline_result_id",
            "replay_repeated_key_collapses",
        )
    )


def test_result_fields_copy_the_run_and_never_the_client_seed() -> None:
    submission = _submission(
        correct_questions=3,
        models=["openrouter/a/b"],
        client={"name": "sdk", "version": "1", "platform": "test"},
        run_cost_usd="1.250000",
        run_cost_status="complete",
    )

    fields = result_fields(submission, run_id="run-1", claims=_claims())

    assert (fields.reporter, fields.run_id, fields.score) == (ANA, "run-1", 0.5)
    assert fields.correct_questions == 3
    assert fields.models == ["openrouter/a/b"]
    assert fields.ran_with_providers == ["openrouter"]
    assert (fields.client_name, fields.client_version, fields.client_platform) == (
        "sdk",
        "1",
        "test",
    )
    # G5, decided (default): the seed is never taken from the client.
    assert fields.answer_seed is None
    assert fields.receipt["cache_coverage_status"] == "complete"
    assert fields.replay["replayed_from_result_id"] is None


@pytest.mark.parametrize(
    ("claim_sub", "trace_id", "check_subject", "raises"),
    [
        pytest.param(ANA, TRACE_ID, True, False, id="match"),
        pytest.param("ANA@X.org ", TRACE_ID, True, False, id="casefold-and-strip"),
        pytest.param("other@x.org", TRACE_ID, True, True, id="other-subject"),
        pytest.param("other@x.org", TRACE_ID, False, False, id="subject-not-checked"),
        pytest.param(ANA, "b" * 32, False, True, id="trace-mismatch-even-unchecked-subject"),
        pytest.param(ANA, None, True, True, id="no-trace-id"),
    ],
)
def test_receipt_binding(
    claim_sub: str, trace_id: str | None, check_subject: bool, raises: bool
) -> None:
    claims = _claims(sub=claim_sub)

    def call() -> None:
        check_receipt_binding(claims, submitter=ANA, trace_id=trace_id, check_subject=check_subject)

    if raises:
        with pytest.raises(ReceiptNotYours):
            call()
    else:
        call()


def test_cursor_round_trips_and_is_url_safe() -> None:
    cursor = Cursor(submitted_at=datetime(2026, 9, 29, 12, 30, tzinfo=UTC), id=uuid.uuid4())

    text = encode_cursor(cursor)

    assert decode_cursor(text) == cursor
    assert "=" not in text
    assert all(ch.isalnum() or ch in "-_" for ch in text)


@pytest.mark.parametrize(
    "text",
    [
        "!!!",
        "",
        "e30",  # {}
        "W10",  # []
        "eyJ0IjoieCIsImkiOiJ5In0",  # {"t":"x","i":"y"}
    ],
)
def test_a_cursor_that_does_not_decode_is_invalid(text: str) -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(text)


def test_a_cursor_with_other_keys_is_invalid() -> None:
    import base64
    import json

    body = json.dumps(
        {"t": "2026-09-29T12:30:00+00:00", "i": str(uuid.uuid4()), "x": 1}, separators=(",", ":")
    )
    text = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")

    with pytest.raises(InvalidCursor):
        decode_cursor(text)


def test_a_receipt_needs_a_named_submitter_when_the_subject_is_checked() -> None:
    with pytest.raises(ReceiptNotYours):
        check_receipt_binding(_claims(), submitter=None, trace_id=TRACE_ID, check_subject=True)

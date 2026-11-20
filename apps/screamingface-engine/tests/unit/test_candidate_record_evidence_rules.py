"""The evidence rules the Client's fold held, pinned on the Engine's fold (E5 P2 plan, CP1).

FEATURE: a detached Run (OME-1837). The Client used to fold a Candidate's frames into its outcome
(`screamingface/_engine/contract.py`, `_RunState`); it now reads the record this fold builds. This
file holds cache evidence, the capture summary, client provenance and span time clamping; root
detection is in `test_candidate_record_rules.py`. Each test names the Client test it ports.

STORY: as a researcher, my Report and my board submission carry the cache evidence, the frozen
copy and the provenance the Client's own fold would have read from the same run.

The input is the real Engine stream of the cache-hit contract, fed to the fold in publish order.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_candidate_record_rules import (
    _CHILD,
    _ROOT,
    _events,
    _frame,
    _Frames,
    _record,
    _result,
    _started,
    _succeeded,
    _terminated,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
GATEWAY_HIT = _REPO_ROOT / "apps/aigateway/tests/fixtures/cache_hit_contract/openrouter_hit.json"
_SAVED = "0.012345"
_COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"
_UNPRICED = "cache.saved_cost.unpriced_hits"
_REPORTED_HITS = "cache.saved_cost.reported_hits"
_ARCHIVE_HITS = "cache.saved_cost.archive_hits"
_SAVED_COST = "cache.saved_cost_usd"
_ARCHIVE_COST = "cache.saved_cost_archive_usd"
_CAPTURE_KEYS = ("capture.frozen_copy_id", "capture.status", "capture.replay")


def _summary(frames: _Frames) -> dict[str, Any]:
    return next(
        f["data"]["attributes"]
        for f in frames
        if f["type"] == "ai.url4.log" and "cache.hits" in f["data"]["attributes"]
    )


def _without_summary(frames: _Frames) -> _Frames:
    """The stream with the summary's cache counts stripped (an older Engine, or a dropped one)."""
    attributes = _summary(frames)
    for key in [k for k in attributes if k.startswith("cache.")]:
        del attributes[key]
    return frames


def _hit_span(frames: _Frames) -> dict[str, Any]:
    return next(
        f["data"]
        for f in frames
        if f["type"] == "ai.url4.span" and f["data"].get("cache_status") == "hit"
    )


# --- Cache evidence (test_cache_hit_contract.py, test_cached_run_not_complete.py,
# test_archive_cost.py) ----------------------------------------------------------------------------


def test_the_real_stream_carries_the_gateways_saving() -> None:
    """Ports `test_the_decoder_recovers_the_gateways_saving_from_the_stream` and
    `test_the_real_engine_stream_reports_its_one_hit`."""
    record = _succeeded(_events())

    assert record["cache_saved_cost_usd"] == _SAVED
    assert record["cache_saved_cost_archive_usd"] is None
    assert record["cache_hits"] == 1
    # INVARIANT (PRD I1): the hit's own spend is zero; the saving never enters it.
    assert Decimal(record["usage"]["cost"]["total_usd"]) == 0


def test_the_saving_is_the_one_the_gateway_recorded_at_fill_time() -> None:
    """Ports `test_the_saving_is_the_one_the_gateway_recorded_at_fill_time`."""
    body = json.loads(GATEWAY_HIT.read_text(encoding="utf-8"))["body"]
    reference = body["_aigw"]["usage_accounting"]["cache"]["reference"]

    assert reference["direct_cost"]["unit"] == "openrouter_credits"
    saved = _succeeded(_events())["cache_saved_cost_usd"]
    assert Decimal(reference["direct_cost"]["amount"]) == Decimal(saved)


def test_the_run_summary_wins_over_spans_that_hide_hits() -> None:
    frames = _events()
    _summary(frames)["cache.hits"] = 5

    assert _succeeded(frames)["cache_hits"] == 5


def test_hit_spans_count_when_the_engine_sends_no_summary() -> None:
    assert _succeeded(_without_summary(_events()))["cache_hits"] == 1


def test_a_run_that_never_touched_the_cache_counts_zero() -> None:
    frames = _without_summary(_events())
    _hit_span(frames)["cache_status"] = "bypass"

    assert _succeeded(frames)["cache_hits"] == 0


def test_the_real_summary_says_no_hit_was_unpriced() -> None:
    assert _succeeded(_events())["cache_unpriced_hits"] == 0


def test_the_summary_count_of_unpriced_hits_is_carried() -> None:
    frames = _events()
    _summary(frames).update({"cache.hits": 3, _UNPRICED: 2})

    assert _succeeded(frames)["cache_unpriced_hits"] == 2


def test_a_summary_without_the_unpriced_count_leaves_it_unknown() -> None:
    frames = _events()
    del _summary(frames)[_UNPRICED]

    assert _succeeded(frames)["cache_unpriced_hits"] is None


def test_a_saving_missing_from_the_spans_is_taken_from_the_summary() -> None:
    frames = _events()
    _hit_span(frames)["cache_saved_cost_usd"] = None

    record = _succeeded(frames)
    assert record["cache_saved_cost_usd"] == _SAVED
    assert record["cache_unpriced_hits"] == 0


def test_the_summary_amounts_win_over_disagreeing_span_totals() -> None:
    frames = _events()
    _hit_span(frames)["cache_saved_cost_usd"] = "0.000001"

    assert _succeeded(frames)["cache_saved_cost_usd"] == _SAVED


def test_the_summary_carries_the_archive_total() -> None:
    frames = _events()
    attributes = _summary(frames)
    attributes[_REPORTED_HITS], attributes[_ARCHIVE_HITS] = 0, 1
    del attributes[_SAVED_COST]
    attributes[_ARCHIVE_COST] = "2.383944"
    _hit_span(frames)["cache_saved_cost_usd"] = None

    record = _succeeded(frames)
    assert record["cache_saved_cost_usd"] is None
    assert record["cache_saved_cost_archive_usd"] == "2.383944"
    assert record["cache_unpriced_hits"] == 0


_CORRUPTIONS: dict[str, Callable[[dict[str, Any]], object]] = {
    "counts-do-not-sum": lambda a: a.__setitem__(_REPORTED_HITS, 0),
    "hits-without-amount": lambda a: a.pop(_SAVED_COST),
    "amount-without-hits": lambda a: a.__setitem__(_ARCHIVE_COST, "1.000000"),
    "counts-missing": lambda a: (a.pop(_REPORTED_HITS), a.pop(_ARCHIVE_HITS)),
}


@pytest.mark.parametrize("corrupt", _CORRUPTIONS.values(), ids=_CORRUPTIONS.keys())
def test_an_inconsistent_summary_proves_nothing(
    corrupt: Callable[[dict[str, Any]], object],
) -> None:
    """INVARIANT: fail CLOSED. A summary that contradicts itself cannot certify `complete`."""
    frames = _events()
    corrupt(_summary(frames))

    assert _succeeded(frames)["cache_unpriced_hits"] is None


def test_more_hit_spans_than_the_summary_counted_proves_nothing() -> None:
    frames = _events()
    next(f for f in frames if f["type"] == "ai.url4.span" and f["data"]["cache_status"] is None)[
        "data"
    ]["cache_status"] = "hit"

    record = _succeeded(frames)
    assert record["cache_hits"] == 2
    assert record["cache_unpriced_hits"] is None


# --- The capture summary (test_capture_summary.py) -----------------------------------------------


def _captured(attributes: dict[str, object]) -> dict[str, Any] | None:
    frames = _events()
    summary = _summary(frames)
    for key in [k for k in summary if k in _CAPTURE_KEYS or k.startswith("capture.partial.")]:
        del summary[key]
    summary.update(attributes)
    return _record(frames)


def test_the_record_reads_the_frozen_copy_and_the_capture_status() -> None:
    record = _captured({"capture.frozen_copy_id": _COPY, "capture.status": "complete"})

    assert record is not None
    assert (record["frozen_copy_id"], record["capture_status"]) == (_COPY, "complete")
    assert record["capture_replay"] is None


def test_a_partial_run_may_have_no_frozen_copy() -> None:
    record = _captured({"capture.status": "partial", "capture.partial.open": 1})

    assert record is not None
    assert (record["frozen_copy_id"], record["capture_status"]) == (None, "partial")


def test_the_record_reads_the_copy_the_engine_replayed() -> None:
    record = _captured({"capture.replay": _COPY})

    assert record is not None
    assert (record["capture_replay"], record["frozen_copy_id"], record["capture_status"]) == (
        _COPY,
        None,
        None,
    )


def test_an_older_engine_without_the_attributes_leaves_them_unknown() -> None:
    """INVARIANT: absent means unknown, never `partial`."""
    record = _captured({})

    assert record is not None
    assert (record["frozen_copy_id"], record["capture_status"], record["capture_replay"]) == (
        None,
        None,
        None,
    )


def test_the_partial_reasons_are_the_non_zero_counts_only() -> None:
    record = _captured(
        {"capture.status": "partial", "capture.partial.local": 1, "capture.partial.failed": 0}
    )

    assert record is not None
    assert record["capture_partial_reasons"] == ["local"]


# --- Client provenance (test_report_client_provenance.py) ---------------------------------------


def _versioned(versions: list[object], *, source: str = _ROOT) -> dict[str, Any]:
    logs = [
        _frame(
            "ai.url4.log",
            {
                "severity_text": "INFO",
                "severity_number": 9,
                "body": "Client software version",
                "attributes": {"screamingface.client.version": version},
            },
            source=source,
            at=10 + n,
        )
        for n, version in enumerate(versions)
    ]
    return _succeeded([_started(), *logs, _result(), _terminated()])


def test_the_roots_version_is_the_records() -> None:
    assert _versioned(["0.1.2+original"])["client_version"] == "0.1.2+original"


@pytest.mark.parametrize(
    "versions", [[], [None], [42], [""], ["x" * 129], ["secret\nvalue"], ["é"], ["a", "b", "a"]]
)
def test_missing_invalid_or_conflicting_evidence_is_unknown(versions: list[object]) -> None:
    assert _versioned(versions)["client_version"] is None


def test_a_childs_log_cannot_stamp_the_root() -> None:
    assert _versioned(["1.0"], source=_CHILD)["client_version"] is None


def test_repeated_equal_evidence_names_the_caller() -> None:
    assert _versioned(["1.0", "1.0"])["client_version"] == "1.0"
    assert _versioned(["2.0"])["client_version"] == "2.0"


# --- Span time clamping (test_span_time_tolerance.py) --------------------------------------------


def test_an_inverted_hit_span_still_counts_its_hit_and_its_saving() -> None:
    """INVARIANT: clamp, never drop. A span that ends one clock step before it starts (the host
    stepped its wall clock back) still counts; the summary is emptied, so the spans alone count."""
    frames = _without_summary(_events())
    span = _hit_span(frames)
    span["end"] = "2026-09-28T00:00:03.789000Z"

    record = _succeeded(frames)
    assert record["cache_hits"] == 1
    assert record["cache_saved_cost_usd"] == _SAVED

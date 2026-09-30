"""The root replay counters reach the run outcome (E14, OME-1307, RP-16 decode part, C12).

FEATURE: OME-1307 (E14). The engine closes a run that carried a replay grant with one cache-summary
log frame that holds `cache.version.hits`, `cache.version.misses` and
`cache.version.repeated_key_collapses` (contract C12, D7 X-7). The SDK reads them from the ROOT
source only, like the client version (`test_report_client_provenance.py`).

INVARIANT: a telemetry defect never ends a paid run. A bad value leaves the counters unknown
(`None`) and raises nothing.
"""

from __future__ import annotations

import pytest
from test_engine_contract import URL4, frame

from screamingface._core.ports import _ReplayCounts, _RunOutcome
from screamingface._engine.contract import _RunState

ROOT = "/trace/run_1/node/root"
CHILD = "/trace/run_1/node/child"
_HITS = "cache.version.hits"
_MISSES = "cache.version.misses"
_COLLAPSES = "cache.version.repeated_key_collapses"


def _summary(attributes: dict[str, object], *, source: str = ROOT, sequence: int) -> str:
    return frame(
        "ai.url4.log",
        {
            "severity_text": "INFO",
            "severity_number": 9,
            "body": "Cache summary",
            "attributes": attributes,
        },
        sequence=sequence,
        source=source,
    )


def _counters(hits: object, misses: object, collapses: object) -> dict[str, object]:
    return {_HITS: hits, _MISSES: misses, _COLLAPSES: collapses}


def _outcome(*summaries: tuple[dict[str, object], str]) -> _RunOutcome:
    """Drive one run: started, the given cache-summary frames (attributes, source), then done."""
    state = _RunState(URL4)
    state.accept(frame("ai.url4.started", {"url4": URL4}, sequence=1))
    sequence = 2
    for attributes, source in summaries:
        state.accept(_summary(attributes, source=source, sequence=sequence))
        sequence += 1
    state.accept(
        frame(
            "ai.url4.result",
            {"body": '{"schema":"result"}', "media_type": "application/json"},
            sequence=sequence,
        )
    )
    accepted = state.accept(
        frame("ai.url4.terminated", {"status": "succeeded", "error": None}, sequence=sequence + 1)
    )
    assert accepted.outcome is not None
    return accepted.outcome


def test_rp16_root_replay_counters_reach_the_outcome() -> None:
    outcome = _outcome((_counters(412, 8, 0), ROOT))

    assert outcome.replay_counts == _ReplayCounts(412, 8, 0)


def test_rp16_a_run_with_no_counter_frame_has_no_counts() -> None:
    assert _outcome().replay_counts is None


def test_rp16_a_child_source_frame_is_ignored() -> None:
    assert _outcome((_counters(412, 8, 0), CHILD)).replay_counts is None


def test_rp16_the_last_valid_root_frame_wins() -> None:
    outcome = _outcome((_counters(1, 1, 1), ROOT), (_counters(412, 8, 0), ROOT))

    assert outcome.replay_counts == _ReplayCounts(412, 8, 0)


def test_rp16_zero_counts_are_counts_not_absence() -> None:
    """A grant run that hit nothing reports `0, 0, 0`: known zeros, unlike `None`."""
    assert _outcome((_counters(0, 0, 0), ROOT)).replay_counts == _ReplayCounts(0, 0, 0)


@pytest.mark.parametrize(
    "attributes",
    [
        _counters(True, 8, 0),
        _counters(412, False, 0),
        _counters(412, 8, True),
        _counters(-1, 8, 0),
        _counters(412, -8, 0),
        _counters(412, 8, -1),
        _counters(1.5, 8, 0),
        _counters("412", 8, 0),
        _counters(None, 8, 0),
        {_HITS: 412, _MISSES: 8},
        {_HITS: 412},
        {},
    ],
    ids=[
        "bool-hits",
        "bool-misses",
        "bool-collapses",
        "negative-hits",
        "negative-misses",
        "negative-collapses",
        "float",
        "text",
        "null",
        "missing-collapses",
        "missing-two",
        "empty",
    ],
)
def test_rp16_a_bad_or_partial_counter_set_leaves_none_and_does_not_raise(
    attributes: dict[str, object],
) -> None:
    assert _outcome((attributes, ROOT)).replay_counts is None


def test_rp16_a_bad_later_frame_keeps_the_last_valid_counts() -> None:
    outcome = _outcome((_counters(412, 8, 0), ROOT), (_counters(True, 8, 0), ROOT))

    assert outcome.replay_counts == _ReplayCounts(412, 8, 0)

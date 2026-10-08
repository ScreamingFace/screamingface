"""The Client reads the run's frozen copy from the Engine summary (E14 B5, design §5.2, §7).

FEATURE: OME-1307 — `capture.frozen_copy_id`, `capture.status` and `capture.replay` travel from the
Engine's run summary into `_RunOutcome` and onto `CandidateResult`, next to `cache.hits`.
STORY: as a researcher who submits a score, my result knows which frozen copy holds the run and
whether the copy holds every answer of it. An older Engine that states neither leaves both fields
None, which the submission then omits.

The input is the real Engine stream of `test_cache_hit_contract`. Only the attributes of its
cache summary line are replaced, so the decoder reads the real frame shape.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from test_cache_hit_contract import _URL4, RUN_EVENTS
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport

import screamingface as sf
from screamingface._core.ports import _RunOutcome
from screamingface._engine.contract import _RunState
from screamingface.errors import ExecutionError

_COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"
_CAPTURE_KEYS = ("capture.frozen_copy_id", "capture.status", "capture.replay")


def _decode(attributes: dict[str, object]) -> _RunOutcome:
    """Decode the real stream with the cache summary's capture attributes replaced."""
    events: list[dict[str, Any]] = json.loads(RUN_EVENTS.read_text(encoding="utf-8"))
    for event in events:
        if event["type"] == "ai.url4.log" and "cache.hits" in event["data"]["attributes"]:
            kept = {
                key: value
                for key, value in event["data"]["attributes"].items()
                if key not in _CAPTURE_KEYS and not key.startswith("capture.partial.")
            }
            event["data"]["attributes"] = {**kept, **attributes}
    state = _RunState(_URL4)
    outcome = None
    for event in events:
        accepted = state.accept(json.dumps(event))
        if accepted.outcome is not None:
            outcome = accepted.outcome
    assert outcome is not None
    return outcome


def test_the_decoder_reads_the_frozen_copy_and_the_capture_status() -> None:
    outcome = _decode({"capture.frozen_copy_id": _COPY, "capture.status": "complete"})

    assert outcome.frozen_copy_id == _COPY
    assert outcome.capture_status == "complete"
    assert outcome.capture_replay is None


def test_a_partial_run_may_have_no_frozen_copy() -> None:
    # The copy failed to open: the run is `partial` (reason `open`) and names no copy.
    outcome = _decode({"capture.status": "partial", "capture.partial.open": 1})

    assert outcome.frozen_copy_id is None
    assert outcome.capture_status == "partial"


def test_the_decoder_reads_the_copy_the_engine_replayed() -> None:
    outcome = _decode({"capture.replay": _COPY})

    assert outcome.capture_replay == _COPY
    assert outcome.frozen_copy_id is None
    assert outcome.capture_status is None


def test_an_older_engine_without_the_attributes_leaves_them_unknown() -> None:
    # INVARIANT: absent means unknown, never `partial`.
    outcome = _decode({})

    assert outcome.frozen_copy_id is None
    assert outcome.capture_status is None
    assert outcome.capture_replay is None


@pytest.mark.parametrize(
    "attributes",
    [
        {"capture.status": "maybe"},
        {"capture.status": True},
        {"capture.status": "complete", "capture.frozen_copy_id": 7},
        {"capture.status": "complete", "capture.replay": 7},
    ],
)
def test_a_malformed_capture_attribute_stops_the_run(attributes: dict[str, object]) -> None:
    with pytest.raises(ExecutionError, match="capture summary"):
        _decode(attributes)


# --- onto CandidateResult -------------------------------------------------------------------------


class _VersionedTransport(_ReplayTransport):
    def __init__(self, **fields: object) -> None:
        super().__init__()
        self._fields = fields

    def run(self, candidate: object, on_event: object) -> _RunOutcome:
        return replace(super().run(candidate, on_event), **self._fields)  # type: ignore[arg-type]


def _result(**fields: object) -> sf.CandidateResult:
    with sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(_engine),
        run_transport=_VersionedTransport(**fields),
    ) as client:
        (result,) = client.evaluate(REPLAY_URL4, progress=False).candidates
    return result


def test_the_result_carries_the_frozen_copy_of_its_run() -> None:
    result = _result(frozen_copy_id=_COPY, capture_status="complete")

    assert (result.frozen_copy_id, result.capture_status) == (_COPY, "complete")
    exported = result.to_dict()
    assert exported["frozen_copy_id"] == _COPY
    assert exported["capture_status"] == "complete"


def test_a_result_without_capture_data_has_none_and_exports_null() -> None:
    result = _result()

    assert (result.frozen_copy_id, result.capture_status) == (None, None)
    assert result.to_dict()["frozen_copy_id"] is None
    assert result.to_dict()["capture_status"] is None


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"frozen_copy_id": "not-a-uuid", "capture_status": "complete"}, "frozen_copy_id"),
        ({"frozen_copy_id": 7, "capture_status": "complete"}, "frozen_copy_id"),
        ({"frozen_copy_id": _COPY.upper(), "capture_status": "complete"}, "frozen_copy_id"),
        ({"capture_status": "yes"}, "capture_status"),
        # INVARIANT: the board refuses a copy id without a status, so the Client never builds that
        # pair.
        ({"frozen_copy_id": _COPY}, "frozen_copy_id"),
    ],
)
def test_the_result_refuses_an_invalid_frozen_copy(fields: dict[str, object], message: str) -> None:
    base = _result()
    values = {
        "benchmark": base.benchmark,
        "run_id": base.run_id,
        "started_at": base.started_at,
        "completed_at": base.completed_at,
        "name": base.name,
        "kind": base.kind,
        "url4": base.url4,
        "models": base.models,
        "operations": base.operations,
        "score": base.score,
        "coverage": base.coverage,
        "metrics": dict(base.metrics),
        "cases": base.cases,
        "members": base.members,
        "failures": base.failures,
        "usage": base.usage,
    }

    with pytest.raises((TypeError, ValueError), match=message):
        sf.CandidateResult(**values, **fields)  # type: ignore[arg-type]

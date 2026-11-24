"""The Client reads the run's frozen copy from the Engine summary (E14 B5, design §5.2, §7).

FEATURE: OME-1307 — `capture.frozen_copy_id`, `capture.status` and `capture.replay` travel from the
Engine's run summary into `_RunOutcome` and onto `CandidateResult`, next to `cache.hits`.
STORY: as a researcher who submits a score, my result knows which frozen copy holds the run and
whether the copy holds every answer of it. An older Engine that states neither leaves both fields
None, which the submission then omits.

Reading them from the run summary is the Engine's fold's rule, pinned in
`apps/screamingface-engine/tests/unit/test_candidate_record_evidence_rules.py`; this file pins
how the Client carries them onto the result.
"""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from test_client_run import REPLAY_URL4, _engine, _ReplayTransport

import screamingface as sf
from screamingface._core.ports import _RunOutcome

_COPY = "0b1f6d3a-5c0e-4a8e-9a3f-2f6f8f4c7d11"
_CAPTURE_KEYS = ("capture.frozen_copy_id", "capture.status", "capture.replay")


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

    assert (result.pinned_cache, result.capture_status) == (_COPY, "complete")
    exported = result.to_dict()
    assert exported["frozen_copy_id"] == _COPY
    assert exported["capture_status"] == "complete"


def test_local_partial_reason_shows_on_the_result() -> None:
    # Q23 and design §7: the submitter's own result names `local`. `sf.reproduce` cannot, because
    # the board does not store the partial reasons.
    result = _result(
        frozen_copy_id=_COPY, capture_status="partial", capture_partial_reasons=("local",)
    )

    assert result.capture_partial_reasons == ("local",)
    assert result.to_dict()["capture_partial_reasons"] == ["local"]


def test_a_result_without_capture_data_has_none_and_exports_null() -> None:
    result = _result()

    assert (result.pinned_cache, result.capture_status) == (None, None)
    assert result.to_dict()["frozen_copy_id"] is None
    assert result.to_dict()["capture_status"] is None


_MESSAGES = {
    "pinned_cache": "Candidate pinned_cache must be a UUID string or None",
    "capture_status": "capture_status must be 'complete', 'partial' or None",
    "pinned_cache_without_status": "Candidate pinned_cache requires capture_status",
}


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"pinned_cache": "not-a-uuid", "capture_status": "complete"}, "pinned_cache"),
        ({"pinned_cache": 7, "capture_status": "complete"}, "pinned_cache"),
        ({"pinned_cache": _COPY.upper(), "capture_status": "complete"}, "pinned_cache"),
        ({"capture_status": "yes"}, "capture_status"),
        # INVARIANT: the board refuses a copy id without a status, so the Client never builds that
        # pair.
        ({"pinned_cache": _COPY}, "pinned_cache_without_status"),
    ],
)
def _constructed(**fields: object) -> sf.CandidateResult:
    """A result built directly from the fixture's parts, with `fields` replaced."""
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
    return sf.CandidateResult(**values, **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"pinned_cache": "not-a-uuid", "capture_status": "complete"}, "pinned_cache"),
        ({"pinned_cache": 7, "capture_status": "complete"}, "pinned_cache"),
        ({"pinned_cache": _COPY.upper(), "capture_status": "complete"}, "pinned_cache"),
        ({"capture_status": "yes"}, "capture_status"),
        # INVARIANT: the board refuses a copy id without a status, so the Client never builds that
        # pair.
        ({"pinned_cache": _COPY}, "pinned_cache_without_status"),
    ],
)
def test_the_result_refuses_an_invalid_frozen_copy(fields: dict[str, object], message: str) -> None:
    with pytest.raises((TypeError, ValueError)) as caught:
        _constructed(**fields)

    # OME-1613: the exact message, not a regex search over it (owner rule).
    assert str(caught.value) == _MESSAGES[message]


def test_the_partial_reasons_are_sorted_once_and_must_be_strings() -> None:
    assert _constructed(
        capture_partial_reasons=["local", "failed", "local"]
    ).capture_partial_reasons == (
        "failed",
        "local",
    )
    with pytest.raises(TypeError, match="each reason as a string"):
        _constructed(capture_partial_reasons=["local", 1])

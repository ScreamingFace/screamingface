"""The graded aggregate route returns the Candidate Result model, and the run's spool streams it.

FEATURE: memory fix 3 (OME-1835), unit 1. The async aggregate route awaits `finish_result`,
so `deliver_result` sees the model. With no spool bound the text is today's string; with the
run's spool bound, a result over the inline cap leaves as a reference the run redeems.
"""

import pytest
from test_shared_grading_aggregation import _Hook, _path, _selected

from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.spool import ResultSpool, binding_result_spool
from screamingface_engine.benchmarks.aggregation import CandidateScore
from screamingface_engine.benchmarks.grading_endpoints import compact_json
from screamingface_engine.benchmarks.shared_grading.incremental import Scoring
from screamingface_engine.benchmarks.shared_grading.incremental_routes import (
    aggregate_result_endpoint,
)
from url4.peer.server import Request


def _scoring() -> Scoring:
    return Scoring(
        _path(_Hook()),
        "board",
        "v1",
        _selected(1, 2),
        lambda _: (5, -3),
        lambda cases: CandidateScore(score=0.5, metrics={}),
    )


@pytest.mark.asyncio
async def test_the_graded_route_without_a_spool_returns_todays_string() -> None:
    raw = "[]"
    expected = compact_json(await _scoring().finish(raw))
    request = Request(path="/aggregate", params={}, context=raw, intent="aggregate:2")
    handler = aggregate_result_endpoint(
        label="t", available_case_count=2, load=lambda ids: _scoring()
    )
    assert await handler(request) == expected


@pytest.mark.asyncio
async def test_the_graded_route_streams_through_the_spool(tmp_path) -> None:
    raw = "[]"
    expected = compact_json(await _scoring().finish(raw))
    request = Request(path="/aggregate", params={}, context=raw, intent="aggregate:2")
    handler = aggregate_result_endpoint(
        label="t", available_case_count=2, load=lambda ids: _scoring()
    )
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=16, hard_cap=10_000_000)
    with binding_result_spool(spool):
        ref = await handler(request)
    artifact = spool.redeem(ref)
    assert artifact is not None
    assert (tmp_path / artifact.id).read_bytes() == expected.encode("utf-8")

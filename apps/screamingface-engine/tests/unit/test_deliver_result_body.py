"""A ResultBody is delivered as a CandidateResult is (OME-1835, unit 2).

FEATURE memory fix 3 (OME-1835), unit 2: a ResultBody is delivered as a CandidateResult is.
A parked body (or a held one) takes the same path: streamed into the bound spool, else written
whole with ``encode_result_body``. INVARIANT defended: the bytes are the same as the held
CandidateResult's, a store failure reaches the caller as itself, and it is never
``benchmark_unavailable``.
"""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from test_deliver_result import _delivered_records, _request, expected, large, small

from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.spool import ResultSpool, binding_result_spool
from screamingface_engine.benchmarks.case_result_store import CaseResultStoreError
from screamingface_engine.benchmarks.grading_endpoints import (
    async_aggregate_endpoint,
    deliver_result,
    deliver_result_sync,
)
from screamingface_engine.benchmarks.result_body import HeldResultBody
from screamingface_engine.candidate_scope import candidate_invocation_scope
from url4.core.errors import ResolutionError


class _UnreadableBody:
    """A parked body whose first Case cannot be read back."""

    def head(self) -> dict[str, Any]:
        return HeldResultBody(small).head()

    def case_fragments(self) -> Iterator[str]:
        yield from ()
        raise CaseResultStoreError("Case-result row '0' is corrupt")


@pytest.mark.asyncio
async def test_a_body_without_a_spool_is_its_encoded_text():
    assert await deliver_result(HeldResultBody(small)) == expected(small)


@pytest.mark.asyncio
async def test_a_small_body_returns_its_text_through_the_spool(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=1_000_000, hard_cap=1_000_000)
    with binding_result_spool(spool):
        text = await deliver_result(HeldResultBody(small))
        assert text == expected(small)
        assert spool.redeem(text) is None


@pytest.mark.asyncio
async def test_a_large_body_returns_a_reference_to_the_same_bytes(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool):
        ref = await deliver_result(HeldResultBody(large))
        assert ref != expected(large)
        artifact = spool.redeem(ref)
    assert artifact is not None
    assert (tmp_path / artifact.id).read_bytes() == expected(large).encode("utf-8")


@pytest.mark.asyncio
async def test_inside_a_candidate_invocation_a_body_is_its_encoded_text(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool), candidate_invocation_scope():
        assert await deliver_result(HeldResultBody(large)) == expected(large)
    assert list(tmp_path.iterdir()) == []


def test_the_sync_face_delivers_a_body(tmp_path):
    assert deliver_result_sync(HeldResultBody(small)) == expected(small)
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool):
        ref = deliver_result_sync(HeldResultBody(large))
        assert ref != expected(large)
        artifact = spool.redeem(ref)
    assert artifact is not None
    assert (tmp_path / artifact.id).read_bytes() == expected(large).encode("utf-8")


@pytest.mark.asyncio
async def test_the_async_endpoint_streams_a_body(tmp_path):
    async def adapter(raw, ids):
        return HeldResultBody(large)

    endpoint = async_aggregate_endpoint(label="t", available_case_count=1, aggregate=adapter)
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool):
        ref = await endpoint(_request())
        artifact = spool.redeem(ref)
    assert artifact is not None
    assert (tmp_path / artifact.id).read_bytes() == expected(large).encode("utf-8")


@pytest.mark.asyncio
async def test_an_unreadable_parked_case_is_not_benchmark_unavailable(tmp_path):
    async def adapter(raw, ids):
        return _UnreadableBody()

    endpoint = async_aggregate_endpoint(label="t", available_case_count=1, aggregate=adapter)
    with pytest.raises(CaseResultStoreError) as caught:
        await endpoint(_request())
    assert not isinstance(caught.value, ResolutionError)

    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=1_000_000, hard_cap=1_000_000)
    with binding_result_spool(spool):
        with pytest.raises(CaseResultStoreError) as caught:
            await endpoint(_request())
    assert not isinstance(caught.value, ResolutionError)


@pytest.mark.asyncio
async def test_delivered_is_logged_for_a_body(caplog):
    caplog.set_level(logging.INFO, logger="screamingface_engine.process_memory")
    await deliver_result(HeldResultBody(small))
    records = _delivered_records(caplog)
    assert len(records) >= 1
    assert "cases=1" in records[-1].getMessage()

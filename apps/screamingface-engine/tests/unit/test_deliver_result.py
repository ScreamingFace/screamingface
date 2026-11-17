"""The async aggregate endpoint hands its CandidateResult to the run's spool (OME-1835, unit 1).

FEATURE: memory fix 3. ``deliver_result`` writes a CandidateResult one Case at a time into the
bound spool, in a worker thread. A plain mapping, no bound spool, or a call inside a Candidate
invocation takes today's whole-string path.
INVARIANT defended: the delivered bytes are ``compact_json(as_payload())``, a store or disk
failure reaches the caller as itself (never ``benchmark_unavailable``), and an oversized result
is refused as ``result_too_large``.
"""

import logging

import pytest
from test_candidate_result_contract import _candidate

from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.ports import ArtifactSink
from screamingface_engine.artifacts.spool import ResultSpool, binding_result_spool
from screamingface_engine.benchmarks.grading_endpoints import (
    aggregate_endpoint,
    async_aggregate_endpoint,
    compact_json,
    deliver_result,
)
from screamingface_engine.candidate_scope import candidate_invocation_scope
from url4.core.errors import ResolutionError
from url4.peer.server import Request

small = _candidate()
large = _candidate().model_copy(
    update={"metrics": {"pass_rate": 1.0, "strict_accuracy": 1.0, "pad": "é" * 400}}
)


def expected(result) -> str:
    return compact_json(result.as_payload())


def _request(intent="aggregate:1"):
    return Request(path="/aggregate", params={}, context="[]", intent=intent)


class _BrokenSink:
    def write(self, chunk: bytes) -> None:
        raise OSError("disk full")

    def commit(self):
        raise AssertionError("commit must not run after a failed write")

    def abort(self) -> None:
        pass


class _BrokenStore:
    def open_sink(self) -> ArtifactSink:
        return _BrokenSink()


@pytest.mark.asyncio
async def test_without_a_spool_a_model_is_todays_string():
    assert await deliver_result(small) == expected(small)


@pytest.mark.asyncio
async def test_a_mapping_is_todays_string_even_with_a_spool(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=1_000_000, hard_cap=1_000_000)
    with binding_result_spool(spool):
        assert await deliver_result({"a": 1}) == '{"a":1}'
        assert spool.redeem('{"a":1}') is None


@pytest.mark.asyncio
async def test_a_small_result_returns_its_text_through_the_spool(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=1_000_000, hard_cap=1_000_000)
    with binding_result_spool(spool):
        text = await deliver_result(small)
        assert text == expected(small)
        assert spool.redeem(text) is None


@pytest.mark.asyncio
async def test_a_large_result_returns_a_reference_to_todays_bytes(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool):
        ref = await deliver_result(large)
        assert ref != expected(large)
        artifact = spool.redeem(ref)
    assert artifact is not None
    assert (tmp_path / artifact.id).read_bytes() == expected(large).encode("utf-8")


@pytest.mark.asyncio
async def test_inside_a_candidate_invocation_the_result_is_todays_string(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool), candidate_invocation_scope():
        assert await deliver_result(large) == expected(large)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_an_oversized_result_is_result_too_large(tmp_path):
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=64)
    with binding_result_spool(spool):
        with pytest.raises(ResolutionError) as caught:
            await deliver_result(large)
    assert caught.value.code == "result_too_large"
    assert caught.value.permanent is True
    assert str(caught.value).startswith("result is ")


@pytest.mark.asyncio
async def test_a_sink_failure_is_not_benchmark_unavailable():
    spool = ResultSpool(_BrokenStore(), inline_cap=8, hard_cap=1_000_000)

    async def adapter(raw, ids):
        return large

    endpoint = async_aggregate_endpoint(label="t", available_case_count=1, aggregate=adapter)
    with binding_result_spool(spool):
        with pytest.raises(OSError) as caught:
            await endpoint(_request())
    assert not isinstance(caught.value, ResolutionError)


@pytest.mark.asyncio
async def test_the_async_endpoint_streams_a_model(tmp_path):
    async def adapter(raw, ids):
        return large

    endpoint = async_aggregate_endpoint(label="t", available_case_count=1, aggregate=adapter)
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool):
        ref = await endpoint(_request())
        artifact = spool.redeem(ref)
    assert artifact is not None
    assert (tmp_path / artifact.id).read_bytes() == expected(large).encode("utf-8")
    assert await endpoint(_request()) == expected(large)


def _sync_endpoint(result):
    def adapter(raw, ids):
        return result

    return aggregate_endpoint(label="t", available_case_count=1, aggregate=adapter)


def test_the_sync_endpoint_streams_a_model(tmp_path):
    endpoint = _sync_endpoint(large)
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool):
        ref = endpoint(_request())
        assert ref != expected(large)
        artifact = spool.redeem(ref)
    assert artifact is not None
    assert (tmp_path / artifact.id).read_bytes() == expected(large).encode("utf-8")
    assert endpoint(_request()) == expected(large)


def test_the_sync_endpoint_keeps_a_mapping_as_todays_string(tmp_path):
    endpoint = _sync_endpoint({"a": 1})
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=1_000_000)
    with binding_result_spool(spool):
        assert endpoint(_request()) == '{"a":1}'
        assert spool.redeem('{"a":1}') is None


def test_the_sync_endpoint_refuses_an_oversized_model_as_result_too_large(tmp_path):
    endpoint = _sync_endpoint(large)
    spool = ResultSpool(FilesystemArtifactStore(tmp_path), inline_cap=64, hard_cap=64)
    with binding_result_spool(spool):
        with pytest.raises(ResolutionError) as caught:
            endpoint(_request())
    assert caught.value.code == "result_too_large"
    assert caught.value.permanent is True


def test_a_sync_sink_failure_is_not_benchmark_unavailable():
    endpoint = _sync_endpoint(large)
    spool = ResultSpool(_BrokenStore(), inline_cap=8, hard_cap=1_000_000)
    with binding_result_spool(spool):
        with pytest.raises(OSError) as caught:
            endpoint(_request())
    assert not isinstance(caught.value, ResolutionError)


def _delivered_records(caplog) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.getMessage().startswith("process memory point=aggregate_delivered")
    ]


@pytest.mark.asyncio
async def test_delivered_is_logged_on_every_model_path(caplog):
    caplog.set_level(logging.INFO, logger="screamingface_engine.process_memory")
    await deliver_result(small)
    delivered = len(_delivered_records(caplog))
    assert delivered >= 1
    await deliver_result({"a": 1})
    assert len(_delivered_records(caplog)) == delivered

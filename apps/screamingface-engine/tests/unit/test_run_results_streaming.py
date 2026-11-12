"""A driver-started run's spilled result streams into its Candidate's prefix (E5 P2 spec D9a,
memory fix 3).

FEATURE: a detached Run (OME-1837). STORY: as a researcher whose Candidate returns a very large
result, it is kept for my Run in full without the runner ever holding it whole in memory.

INVARIANT: the result is kept under its Candidate's prefix and its own checksum, which is the
artifact the result frame names; a write the store refuses is retried within the write budget.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import IO

import pytest

from screamingface_engine.artifacts.run_results import (
    FilesystemRunResultStore,
    ResultSink,
    RunResultStoreUnavailable,
    RunResultWriter,
    result_key,
    result_prefix,
)
from screamingface_engine.artifacts.spool import ResultSpool

PREFIX = result_prefix("run_" + "a" * 32, 3)


def test_a_spilled_result_is_kept_whole_under_its_prefix_and_checksum(tmp_path: Path) -> None:
    store = FilesystemRunResultStore(tmp_path)
    spool = ResultSpool(RunResultWriter(ResultSink(PREFIX, store)), inline_cap=8, hard_cap=10_000)
    body = "x" * 4000

    reference = spool.deliver(lambda write: [write(body[i : i + 100]) for i in range(0, 4000, 100)])
    artifact = spool.redeem(reference)

    digest = hashlib.sha256(body.encode()).hexdigest()
    assert artifact is not None
    assert (artifact.sha256, artifact.size_bytes) == (digest, 4000)
    assert (tmp_path / result_key(PREFIX, digest)).read_text() == body


class _FlakyStore(FilesystemRunResultStore):
    def __init__(self, root: Path, failures: int) -> None:
        super().__init__(root)
        self.failures = failures

    def put_file(self, key: str, handle: IO[bytes], size: int, sha256: str) -> None:
        if self.failures:
            self.failures -= 1
            raise OSError("the store is down")
        super().put_file(key, handle, size, sha256)


def test_a_refused_write_is_retried_within_the_budget(tmp_path: Path) -> None:
    store = _FlakyStore(tmp_path, failures=1)
    sink = RunResultWriter(ResultSink(PREFIX, store, budget_s=5.0)).open_sink()
    sink.write(b"chunk")

    artifact = sink.commit()

    assert (tmp_path / result_key(PREFIX, artifact.sha256)).read_bytes() == b"chunk"


def test_a_store_down_past_the_budget_fails_the_write(tmp_path: Path) -> None:
    sink = RunResultWriter(ResultSink(PREFIX, _FlakyStore(tmp_path, 99), budget_s=0.0)).open_sink()
    sink.write(b"chunk")

    with pytest.raises(RunResultStoreUnavailable):
        sink.commit()


def test_a_pool_with_no_store_opens_no_sink() -> None:
    with pytest.raises(RunResultStoreUnavailable):
        RunResultWriter(ResultSink(PREFIX, None)).open_sink()

"""The cache-upload job runner's state machine, with a fake loader (OME-952).

Every branch here maps to a refusal code the console renders, so the branches are the API:
checksum, row-count, revision mismatch (and its forced override), the replace guard, the size
cap, and the slicer's own refusals. The loader is stubbed because its behaviour is pinned
against real Postgres in `tests/integration/test_cache_snapshot_upload_postgres.py`; what this
module owns is the DECISIONS around it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from aigateway.core.request_cache.bulk_loader import (
    LoadOutcome,
    ReplaceGuardBlocked,
    StagedRowCountMismatch,
)
from aigateway.core.request_cache.snapshot import CopyHeaderMismatch, NoCopyBlock
from aigateway.core.request_cache.upload_job import (
    CacheJobRecord,
    CacheUploadBusy,
    CacheUploadRunner,
    UploadAcceptance,
)

_LIVE = {
    "parameter_contract": "aigw-parameter-contract-2026-08b",
    "openrouter_adapter": "openrouter-global-cache-2026-08d",
}
_SHA = "b" * 64


class FakeLoader:
    """Records the call and answers with a scriptable outcome or exception."""

    def __init__(
        self,
        outcome: LoadOutcome | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.outcome = outcome or LoadOutcome(staged_rows=10, live_before=5, live_after=10)
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, path: Path, **kwargs: Any) -> LoadOutcome:
        self.calls.append({"path": path, **kwargs})
        if self.raises is not None:
            raise self.raises
        return self.outcome


def _manifest_raw(**overrides: Any) -> bytes:
    payload: dict[str, Any] = {
        "schema": "screamingface.cache-snapshot.v1",
        "generated_at": "2026-08-22",
        "row_count": 10,
        "sha256": _SHA,
        "revisions": dict(_LIVE),
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


def _acceptance(
    tmp_path: Path,
    *,
    manifest_raw: bytes | None = None,
    mode: str = "merge",
    force: bool = False,
    acknowledge_loss: bool = False,
    actual_bytes: int = 1024,
) -> UploadAcceptance:
    upload = tmp_path / "snapshot.sql.gz"
    upload.write_bytes(b"payload")
    return UploadAcceptance(
        upload_path=upload,
        sha256_hex=_SHA,
        actual_bytes=actual_bytes,
        manifest_raw=manifest_raw,
        mode=mode,  # type: ignore[arg-type]
        force=force,
        acknowledge_loss=acknowledge_loss,
        actor="admin@openmined.org",
    )


def _runner(loader: FakeLoader, max_bytes: int = 1024 * 1024) -> CacheUploadRunner:
    return CacheUploadRunner(
        loader=loader,  # type: ignore[arg-type]
        revisions=lambda: dict(_LIVE),
        max_upload_bytes=max_bytes,
    )


async def _start_and_wait(
    runner: CacheUploadRunner, acceptance: UploadAcceptance
) -> CacheJobRecord:
    record = runner.start(acceptance)
    task = runner._task
    assert task is not None
    await asyncio.wait_for(asyncio.gather(task), timeout=5)
    return record


# --- happy paths -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_verified_manifest_loads_with_counters_and_clean_state(tmp_path) -> None:
    loader = FakeLoader(
        LoadOutcome(staged_rows=100, live_before=40, live_after=90)
    )  # 50 keys were new, 50 replaced
    runner = _runner(loader)
    record = await _start_and_wait(runner, _acceptance(tmp_path, manifest_raw=_manifest_raw()))

    assert record.state == "complete"
    assert record.manifest_present is True
    assert record.staged_rows == 100
    assert record.inserted_rows == 50
    assert record.updated_rows == 50
    assert record.finished_at is not None
    assert not record.warnings
    # The spooled file is the job's to remove once terminal.
    # The spooled upload is deleted once the job is terminal.
    assert not Path(str(loader.calls[0]["path"])).exists()


@pytest.mark.asyncio
async def test_a_manifestless_load_warns_revisions_unverified(tmp_path) -> None:
    loader = FakeLoader()
    runner = _runner(loader)
    record = await _start_and_wait(runner, _acceptance(tmp_path))

    assert record.state == "complete"
    assert record.warnings == ["revisions_unverified"]
    assert loader.calls[0]["expected_rows"] is None


# --- refusals ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_checksum_mismatch_refuses_before_any_load(tmp_path) -> None:
    loader = FakeLoader()
    runner = _runner(loader)
    record = await _start_and_wait(
        runner,
        _acceptance(tmp_path, manifest_raw=_manifest_raw(sha256="c" * 64)),
    )
    assert record.state == "refused"
    assert record.refusal == "checksum_mismatch"
    assert loader.calls == []


@pytest.mark.asyncio
async def test_a_revision_mismatch_refuses_unless_forced(tmp_path) -> None:
    loader = FakeLoader()
    runner = _runner(loader)
    stale = _manifest_raw(
        revisions={**_LIVE, "openrouter_adapter": "openrouter-global-cache-2026-08a"}
    )
    record = await _start_and_wait(runner, _acceptance(tmp_path, manifest_raw=stale))
    assert record.refusal == "revision_mismatch"
    assert loader.calls == []

    loader2 = FakeLoader()
    runner2 = _runner(loader2)
    forced = await _start_and_wait(runner2, _acceptance(tmp_path, manifest_raw=stale, force=True))
    assert forced.state == "complete"
    assert forced.forced is True
    assert forced.warnings == ["revision_mismatch_forced"]


@pytest.mark.asyncio
async def test_a_row_count_mismatch_refused_by_the_loader_maps_to_its_code(tmp_path) -> None:
    loader = FakeLoader(raises=StagedRowCountMismatch(staged=9, declared=10))
    runner = _runner(loader)
    record = await _start_and_wait(runner, _acceptance(tmp_path, manifest_raw=_manifest_raw()))
    assert record.refusal == "row_count_mismatch"
    assert record.staged_rows is None


@pytest.mark.asyncio
async def test_the_replace_guard_maps_to_its_code(tmp_path) -> None:
    loader = FakeLoader(raises=ReplaceGuardBlocked(live=200, staged=100))
    runner = _runner(loader)
    record = await _start_and_wait(
        runner, _acceptance(tmp_path, mode="replace", manifest_raw=_manifest_raw())
    )
    assert record.refusal == "newer_rows_would_be_lost"
    assert "100 row(s) newer" in (record.error or "")


@pytest.mark.parametrize(
    ("raises", "code"),
    [
        (NoCopyBlock("missing"), "no_copy_block"),
        (CopyHeaderMismatch(("a",)), "column_layout_mismatch"),
    ],
)
@pytest.mark.asyncio
async def test_slicer_refusals_map_to_their_codes(tmp_path, raises, code) -> None:
    runner = _runner(FakeLoader(raises=raises))
    record = await _start_and_wait(runner, _acceptance(tmp_path))
    assert record.refusal == code


@pytest.mark.asyncio
async def test_a_bad_manifest_refuses_as_invalid(tmp_path) -> None:
    runner = _runner(FakeLoader())
    record = await _start_and_wait(runner, _acceptance(tmp_path, manifest_raw=b"{not json"))
    assert record.refusal == "manifest_invalid"


@pytest.mark.asyncio
async def test_an_oversized_upload_refuses_without_touching_the_loader(tmp_path) -> None:
    loader = FakeLoader()
    runner = _runner(loader, max_bytes=128)
    record = await _start_and_wait(
        runner, _acceptance(tmp_path, actual_bytes=1024, manifest_raw=None)
    )
    assert record.refusal == "upload_too_large"
    assert loader.calls == []


@pytest.mark.asyncio
async def test_an_unexpected_loader_failure_lands_as_failed_not_refused(tmp_path) -> None:
    runner = _runner(FakeLoader(raises=RuntimeError("disk vanished")))
    record = await _start_and_wait(runner, _acceptance(tmp_path))
    assert record.state == "failed"
    assert record.refusal is None
    assert "disk vanished" in (record.error or "")


# --- the single slot ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_second_upload_while_one_runs_is_busy(tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_loader(path: Path, **kwargs: Any) -> LoadOutcome:
        started.set()
        await release.wait()
        return LoadOutcome(staged_rows=1, live_before=0, live_after=1)

    runner = CacheUploadRunner(loader=slow_loader, revisions=lambda: dict(_LIVE))
    first = runner.start(_acceptance(tmp_path))
    await started.wait()
    with pytest.raises(CacheUploadBusy):
        runner.start(_acceptance(tmp_path))
    release.set()
    await asyncio.sleep(0)
    while not first.finished_at:
        await asyncio.sleep(0)

    # After completion the slot frees, and the busy record joins the history.
    second = runner.start(_acceptance(tmp_path))
    while not second.finished_at:
        await asyncio.sleep(0)
    assert [job.state for job in runner.jobs()] == ["complete", "complete"]


@pytest.mark.asyncio
async def test_history_is_bounded(tmp_path) -> None:
    loader = FakeLoader(LoadOutcome(staged_rows=0, live_before=0, live_after=0))
    runner = CacheUploadRunner(
        loader=loader,  # type: ignore[arg-type]
        revisions=lambda: dict(_LIVE),
        history_limit=2,
    )
    for _ in range(3):
        record = await _start_and_wait(runner, _acceptance(tmp_path))
    assert len(runner.jobs()) == 2
    assert runner.get(record.id) is record
    assert runner.get(uuid.uuid4()) is None

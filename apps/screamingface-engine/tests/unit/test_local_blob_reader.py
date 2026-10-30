"""Local mode's in-process runs read the run blob store too (OME-1529; OME-1545 x OME-1540).

FEATURE: image and PDF inputs, on `screamingface-engine serve --local`. The Runner binds the run
blob store's reader around its run (`runner.blob_reader`); local mode runs each run as an
`asyncio.Task` in the App's own process and bound nothing, so a ref-only file the App stored for
the run read as `source_not_found` there. These tests pin that an in-process run gets the same
`ScopedBlobReader` binding, scoped to ITS topic and verified identity, for the run's task only.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from test_attachment_parts import _PDF_URI
from test_inprocess_runner import _drain_until_terminal, _subtree
from test_runner_blob_reader import EMAIL, REF, TOPIC, _app_stores

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.adapters.memory import InMemoryEventStream
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.runner import main
from screamingface_engine.runner.blob_reader import bound_run_blob_reader
from screamingface_engine.world.attachment_parts import AttachmentPartError, attachment_parts
from url4.streaming.interfaces import Completed, ExecStep, Executor, TraceContext
from url4.streaming.protocol import ResultData

pytestmark = pytest.mark.asyncio


class _ReadsTheRef(Executor):
    """Reads the ref-only attachment the way a model call does; records what it got."""

    def __init__(self) -> None:
        self.parts: list[Any] = []
        self.codes: list[str] = []

    async def execute(
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:
        try:
            self.parts.extend(await attachment_parts((REF,)))
        except AttachmentPartError as exc:
            self.codes.append(exc.code)
        yield Completed(result=ResultData(body="ok"), subtree_cost=_subtree())


def _runner(
    stream: InMemoryEventStream, executor: Executor, base_env: Mapping[str, str]
) -> InProcessJobRunner:
    return InProcessJobRunner(
        stream, lambda env: executor, base_env=base_env, run_binding=bound_run_blob_reader
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    return {job_env.ARTIFACTS_DIR: str(tmp_path / "artifacts")}


async def test_an_in_process_run_reads_the_file_the_app_stored_for_it(tmp_path: Path) -> None:
    _app_stores(tmp_path)
    stream, executor = InMemoryEventStream(), _ReadsTheRef()

    await _runner(stream, executor, _base_env(tmp_path)).schedule(
        TOPIC, "'hi'", 30, identity={"X-User-Email": EMAIL}
    )
    await _drain_until_terminal(stream, TOPIC)

    assert executor.codes == []
    assert executor.parts == [{"type": "file", "file": {"file_data": _PDF_URI}}]


async def test_another_tenants_file_stays_not_found_in_process(tmp_path: Path) -> None:
    """INVARIANT (F3 step 1): the scope is the run's verified caller, never the digest alone."""
    _app_stores(tmp_path, email="bob@example.org")
    stream, executor = InMemoryEventStream(), _ReadsTheRef()

    await _runner(stream, executor, _base_env(tmp_path)).schedule(
        TOPIC, "'hi'", 30, identity={"X-User-Email": EMAIL}
    )
    await _drain_until_terminal(stream, TOPIC)

    assert executor.parts == []
    assert executor.codes == ["source_not_found"]


async def test_the_binding_belongs_to_the_run_task_not_the_scheduler(tmp_path: Path) -> None:
    """INVARIANT: one process serves every caller; a reader leaking into the request's context
    would hand the next thing that runs there this run's tenant scope."""
    _app_stores(tmp_path)
    stream, executor = InMemoryEventStream(), _ReadsTheRef()

    await _runner(stream, executor, _base_env(tmp_path)).schedule(
        TOPIC, "'hi'", 30, identity={"X-User-Email": EMAIL}
    )
    await _drain_until_terminal(stream, TOPIC)

    with pytest.raises(AttachmentPartError) as caught:
        await attachment_parts((REF,))
    assert caught.value.code == "source_not_found"


async def test_a_half_configured_s3_store_refuses_at_schedule(tmp_path: Path) -> None:
    """The refusal arrives before any run is admitted — not as a task dying with no frame."""
    stream = InMemoryEventStream()
    runner = _runner(stream, _ReadsTheRef(), {job_env.ARTIFACT_STORE: "s3"})

    with pytest.raises(ValueError, match="not fully configured"):
        await runner.schedule(TOPIC, "'hi'", 30, identity={"X-User-Email": EMAIL})

    assert runner.active_count() == 0
    assert not await runner.exists(TOPIC)


async def test_the_local_app_binds_the_reader_into_its_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kills the mutation that drops `run_binding` from `create_local_app`."""
    _app_stores(tmp_path)
    executor = _ReadsTheRef()
    monkeypatch.setattr(main, "build_executor", lambda env, **kw: executor)
    app = create_local_app(Settings(jwt_secret="s" * 32), env=_base_env(tmp_path))
    runner: InProcessJobRunner = app.state.job_runner

    await runner.schedule(TOPIC, "'hi'", 30, identity={"X-User-Email": EMAIL})
    while await runner.exists(TOPIC):
        await asyncio.sleep(0)

    assert executor.parts == [{"type": "file", "file": {"file_data": _PDF_URI}}]

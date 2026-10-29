"""The Runner binds the run blob store's reader around its run (OME-1529; OME-1545 x OME-1540).

FEATURE: image and PDF inputs. A url4 snapshot may hold only the ref of a file the App stored for
this run (``PUT /blob/sha256/<hex>``); the model call reads it through the run-scoped
``BlobReader`` (spec ``docs/spec/2026-10-16-OME-1535-file-input-execution.md`` F3). These tests pin
that the Runner binds that reader for the run's duration, scoped to the run's topic and verified
identity, that store corruption surfaces as the connector's permanent ``x.blob_digest_mismatch``
naming only the digest, and that an env naming no run binds nothing (today's behaviour).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_aigateway_connector import _MODEL
from test_attachment_parts import _PDF_BYTES, _PDF_URI, _send
from test_runner_process_handoffs import _frames, _Publisher, _Sink

from screamingface_engine import job_env
from screamingface_engine.artifacts.blobs import BlobScope, BlobStore, FilesystemBlobObjects
from screamingface_engine.runner import main
from screamingface_engine.runner.blob_reader import bound_run_blob_reader
from screamingface_engine.world.attachment_parts import attachment_parts
from url4 import Attachment
from url4.core.errors import ResolutionError
from url4.streaming.interfaces import EventPublisher

pytestmark = pytest.mark.asyncio

TOPIC = "R" * 64
EMAIL = "alice@example.org"
PDF_HEX = hashlib.sha256(_PDF_BYTES).hexdigest()
REF = Attachment(digest=f"sha256:{PDF_HEX}", media_type="application/pdf")


def _env(tmp_path: Path, topic: str = TOPIC) -> dict[str, str]:
    env = {job_env.TOPIC: topic, job_env.ARTIFACTS_DIR: str(tmp_path / "artifacts")}
    env.update(job_env.identity_to_env({"X-User-Email": EMAIL}))
    return env


def _app_stores(tmp_path: Path, email: str = EMAIL) -> Path:
    """What the App's upload route does for this run; the path of the stored bytes."""
    scope = BlobScope.for_caller(email, TOPIC)
    BlobStore(FilesystemBlobObjects(tmp_path / "artifacts")).ingest(
        scope, PDF_HEX, "application/pdf", _PDF_BYTES
    )
    return tmp_path / "artifacts" / scope.key_prefix / PDF_HEX


async def test_a_ref_only_attachment_is_served_through_the_runs_reader(tmp_path: Path) -> None:
    _app_stores(tmp_path)

    with bound_run_blob_reader(_env(tmp_path)):
        gw, result = await _send("Summarize.", (REF,))

    assert result == "42"
    (post,) = gw.posts_to(_MODEL)
    assert json.loads(post.content)["messages"][-1]["content"][0] == {
        "type": "file",
        "file": {"file_data": _PDF_URI},
    }


async def test_a_corrupt_stored_copy_is_a_permanent_digest_mismatch(tmp_path: Path) -> None:
    secret = b"%PDF-corrupted-bytes-never-echoed"
    _app_stores(tmp_path).write_bytes(secret)

    with bound_run_blob_reader(_env(tmp_path)), pytest.raises(ResolutionError) as caught:
        await _send("Summarize.", (REF,))

    assert caught.value.code == "x.blob_digest_mismatch"
    assert caught.value.permanent
    # INVARIANT (F3): the digest names the file; no byte of it reaches the error.
    assert REF.digest in str(caught.value)
    assert secret.decode() not in str(caught.value)


async def test_a_digest_stored_for_another_tenant_is_not_found(tmp_path: Path) -> None:
    _app_stores(tmp_path, email="bob@example.org")

    with bound_run_blob_reader(_env(tmp_path)), pytest.raises(ResolutionError) as caught:
        await _send("Summarize.", (REF,))

    assert caught.value.code == "source_not_found"
    assert caught.value.permanent


@pytest.mark.parametrize("topic", ["", "not-a-run-id"])
async def test_an_env_naming_no_run_binds_nothing(tmp_path: Path, topic: str) -> None:
    """Today's behaviour is kept: with no run to scope blobs to, a ref-only file is unreadable."""
    _app_stores(tmp_path)

    with bound_run_blob_reader(_env(tmp_path, topic)), pytest.raises(ResolutionError) as caught:
        await _send("Summarize.", (REF,))

    assert caught.value.code == "source_not_found"


async def test_the_runner_binds_the_reader_for_the_whole_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kills the mutation that drops the binding from `_run_process`."""
    _app_stores(tmp_path)
    for name, value in _env(tmp_path).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(job_env.EXPRESSION, "'hi'")
    monkeypatch.setenv(job_env.STREAM_GRACE_S, "0")
    monkeypatch.setenv(job_env.RECLAIM_OWNER, "worker")
    monkeypatch.delenv(job_env.TRACEPARENT, raising=False)
    monkeypatch.setattr(main, "build_executor", lambda *a, **k: object())
    monkeypatch.setattr(main, "span_sink", lambda env: _Sink())
    seen: list[Any] = []

    async def _run_and_log(
        executor: Any, relay: EventPublisher, params: Any, traceparent: str | None
    ) -> None:
        seen.extend(await attachment_parts((REF,)))
        for frame in _frames("succeeded"):
            await relay.publish(params.topic, frame)

    monkeypatch.setattr(main, "_run_and_log", _run_and_log)

    await main._run_process(_Publisher())  # type: ignore[arg-type]  # noqa: SLF001

    assert seen == [{"type": "file", "file": {"file_data": _PDF_URI}}]

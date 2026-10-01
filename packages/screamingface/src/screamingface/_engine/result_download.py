"""Stream completed Engine results to durable files; no whole-body buffering."""

from __future__ import annotations

import asyncio
import codecs
import hashlib
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

import httpx

from screamingface._core.ports import _ResultArtifact, _RunOutcome
from screamingface._results.store import SavedRun, storage_error, sync_directory
from screamingface.errors import EngineUnavailableError, ExecutionError


class _Download:
    def __init__(self, saved: SavedRun, stream: IO[bytes]) -> None:
        self.saved = saved
        self.stream = stream
        self.digest = hashlib.sha256()
        self.received = 0
        self.decoder = codecs.getincrementaldecoder("utf-8")()

    def write(self, chunk: bytes) -> None:
        artifact = self.saved.outcome.artifact
        assert artifact is not None
        self.received += len(chunk)
        if self.received > artifact.size_bytes:
            raise ExecutionError(
                "SF Engine result artifact exceeded its ticket: expected "
                f"{artifact.size_bytes} bytes, received at least {self.received}",
                code="result_integrity_mismatch",
                permanent=True,
            )
        self.decoder.decode(chunk)
        self.digest.update(chunk)
        self.stream.write(chunk)

    def finish(self) -> None:
        artifact = self.saved.outcome.artifact
        assert artifact is not None
        self.decoder.decode(b"", final=True)
        if self.received != artifact.size_bytes or self.digest.hexdigest() != artifact.sha256:
            raise ExecutionError(
                "SF Engine result artifact failed integrity verification: "
                f"expected {artifact.size_bytes} bytes, received {self.received}",
                code="result_integrity_mismatch",
                permanent=True,
            )
        self.stream.flush()
        os.fsync(self.stream.fileno())


def _response(response: httpx.Response, saved: SavedRun) -> None:
    from screamingface._engine.transport import _raise_response

    if response.status_code in (404, 410):
        age = datetime.now(UTC) - saved.outcome.completed_at
        raise ExecutionError(
            f"Result unavailable or expired on the Engine (age {age}); "
            f"no local copy for saved run {saved.key}.",
            code="result_expired",
            permanent=True,
        )
    _raise_response(response, "fetch the Run's result artifact")


def _finish(saved: SavedRun, temporary: Path) -> _RunOutcome:
    temporary.replace(saved.path)
    sync_directory(saved.path.parent)
    return replace(saved.outcome, result_body=None, result_path=saved.path)


def _once_sync(http: httpx.Client, saved: SavedRun, token: str) -> _RunOutcome:
    artifact = saved.outcome.artifact
    assert artifact is not None
    with NamedTemporaryFile(dir=saved.path.parent, prefix=".download-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer = _Download(saved, stream.file)
            with http.stream(
                "GET", _artifact_path(artifact), headers={"URL4-Capability": token}
            ) as response:
                if not response.is_success:
                    response.read()
                    _response(response, saved)
                for chunk in response.iter_bytes(chunk_size=65536):
                    writer.write(chunk)
            writer.finish()
            stream.close()
            return _finish(saved, temporary)
        finally:
            temporary.unlink(missing_ok=True)


async def _once_async(http: httpx.AsyncClient, saved: SavedRun, token: str) -> _RunOutcome:
    artifact = saved.outcome.artifact
    assert artifact is not None
    with NamedTemporaryFile(dir=saved.path.parent, prefix=".download-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer = _Download(saved, stream.file)
            async with http.stream(
                "GET", _artifact_path(artifact), headers={"URL4-Capability": token}
            ) as response:
                if not response.is_success:
                    await response.aread()
                    _response(response, saved)
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    writer.write(chunk)
            writer.finish()
            stream.close()
            return _finish(saved, temporary)
        finally:
            temporary.unlink(missing_ok=True)


def download_sync(http: httpx.Client, saved: SavedRun, mint: Callable[[], str]) -> _RunOutcome:
    if saved.outcome.artifact is None:
        return saved.persist_inline()
    error: httpx.HTTPError | None = None
    for delay in (0.0, 0.2, 0.8):
        time.sleep(delay)
        try:
            return _once_sync(http, saved, mint())
        except httpx.HTTPError as exc:
            error = exc
        except UnicodeDecodeError as exc:
            raise ExecutionError(
                "SF Engine result artifact is not UTF-8 text",
                code="result_integrity_mismatch",
                permanent=True,
            ) from exc
        except OSError as exc:
            raise storage_error(exc, saved.key) from exc
    raise EngineUnavailableError(
        f"Could not fetch result; recover saved run {saved.key}", engine_url=saved.engine_url
    ) from error


async def download_async(
    http: httpx.AsyncClient, saved: SavedRun, mint: Callable[[], Awaitable[str]]
) -> _RunOutcome:
    if saved.outcome.artifact is None:
        return saved.persist_inline()
    error: httpx.HTTPError | None = None
    for delay in (0.0, 0.2, 0.8):
        await asyncio.sleep(delay)
        try:
            return await _once_async(http, saved, await mint())
        except httpx.HTTPError as exc:
            error = exc
        except UnicodeDecodeError as exc:
            raise ExecutionError(
                "SF Engine result artifact is not UTF-8 text",
                code="result_integrity_mismatch",
                permanent=True,
            ) from exc
        except OSError as exc:
            raise storage_error(exc, saved.key) from exc
    raise EngineUnavailableError(
        f"Could not fetch result; recover saved run {saved.key}", engine_url=saved.engine_url
    ) from error


def _artifact_path(artifact: _ResultArtifact) -> str:
    # INVARIANT: recovery metadata cannot turn a fetch into an arbitrary Engine GET.
    if re.fullmatch(r"[0-9a-f]{64}", artifact.id) is None:
        raise ExecutionError("Saved result artifact id must be sha256 hex", permanent=True)
    return f"/artifacts/{artifact.id}"

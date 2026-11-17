"""Stream completed Engine results to durable files; no whole-body buffering.

A result is redeemed from one of two places: a pre-P2 artifact ticket (`GET /artifacts/{id}`,
with a fresh capability), or a driver-started Candidate's result in its Run's run-results store
(`GET /runs/{id}/candidates/{index}/result`, as the Run's owner; E5 P2 spec D9a).
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import hashlib
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

import httpx

from screamingface._core.ports import _ResultArtifact, _RunOutcome, _RunResult
from screamingface._results.store import SavedRun, storage_error, sync_directory
from screamingface.errors import EngineUnavailableError, ExecutionError

_ERROR_BODY_LIMIT = 65536
_RETRY_DELAYS = (0.0, 0.2, 0.8)
_RUN_ID = re.compile(r"run_[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class _Ticket:
    """Where a result is redeemed, and what it must be. ``capability``: the route needs a
    freshly minted capability (an artifact ticket), not only the caller's identity."""

    path: str
    size_bytes: int
    sha256: str
    capability: bool


class _Download:
    def __init__(self, ticket: _Ticket, stream: IO[bytes] | None = None) -> None:
        self.ticket = ticket
        self.stream = stream
        self.chunks: list[bytes] = []
        self.digest = hashlib.sha256()
        self.received = 0
        self.decoder = codecs.getincrementaldecoder("utf-8")()

    def write(self, chunk: bytes) -> None:
        self.received += len(chunk)
        # INVARIANT: never buffer or write past the declared size; it is the memory bound.
        if self.received > self.ticket.size_bytes:
            raise ExecutionError(
                "SF Engine result artifact exceeded its ticket: expected "
                f"{self.ticket.size_bytes} bytes, received at least {self.received}",
                code="result_integrity_mismatch",
                permanent=True,
            )
        self.decoder.decode(chunk)
        self.digest.update(chunk)
        if self.stream is None:
            self.chunks.append(chunk)
        else:
            self.stream.write(chunk)

    def finish(self) -> None:
        self.decoder.decode(b"", final=True)
        ticket = self.ticket
        if self.received != ticket.size_bytes or self.digest.hexdigest() != ticket.sha256:
            raise ExecutionError(
                "SF Engine result artifact failed integrity verification: "
                f"expected {ticket.size_bytes} bytes, received {self.received}",
                code="result_integrity_mismatch",
                permanent=True,
            )
        if self.stream is not None:
            self.stream.flush()
            os.fsync(self.stream.fileno())

    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8")


def _response(response: httpx.Response, outcome: _RunOutcome, key: str | None = None) -> None:
    from screamingface._engine.transport import _raise_response

    if response.status_code in (404, 410):
        age = datetime.now(UTC) - outcome.completed_at
        copy = "" if key is None else f"; no local copy for saved run {key}"
        raise ExecutionError(
            f"Result unavailable or expired on the Engine (age {age}){copy}.",
            code="result_expired",
            permanent=True,
        )
    _raise_response(response, "fetch the Run's result artifact")


def _error_response(response: httpx.Response, body: bytes) -> httpx.Response:
    # INVARIANT: diagnostic error bodies never bypass the bounded download contract.
    headers = {
        name: value
        for name, value in response.headers.items()
        if name not in {"content-encoding", "content-length"}
    }
    return httpx.Response(
        response.status_code, headers=headers, content=body, request=response.request
    )


def _finish(saved: SavedRun, temporary: Path) -> _RunOutcome:
    temporary.replace(saved.path)
    sync_directory(saved.path.parent)
    return replace(saved.outcome, result_body=None, result_path=saved.path)


def _require_identity(response: httpx.Response) -> None:
    # WHY: HTTPX decompresses before chunking, so chunk_size cannot bound encoded responses.
    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
        raise ExecutionError(
            "SF Engine result artifact must use identity content encoding",
            code="result_integrity_mismatch",
            permanent=True,
        )


def _headers(ticket: _Ticket, token: str | None) -> dict[str, str]:
    headers = {"Accept-Encoding": "identity"}
    if ticket.capability:
        assert token is not None
        headers["URL4-Capability"] = token
    return headers


def _stream_sync(
    http: httpx.Client, ticket: _Ticket, token: str | None, writer: _Download, outcome, key
) -> None:
    with http.stream("GET", ticket.path, headers=_headers(ticket, token)) as response:
        if not response.is_success:
            if response.status_code in (404, 410):
                _response(response, outcome, key)
            if response.headers.get("content-encoding", "identity") != "identity":
                _response(_error_response(response, b""), outcome, key)
            body = next(response.iter_bytes(chunk_size=_ERROR_BODY_LIMIT), b"")
            _response(_error_response(response, body), outcome, key)
        _require_identity(response)
        for chunk in response.iter_bytes(chunk_size=65536):
            writer.write(chunk)
    writer.finish()


async def _stream_async(
    http: httpx.AsyncClient, ticket: _Ticket, token: str | None, writer: _Download, outcome, key
) -> None:
    async with http.stream("GET", ticket.path, headers=_headers(ticket, token)) as response:
        if not response.is_success:
            if response.status_code in (404, 410):
                _response(response, outcome, key)
            if response.headers.get("content-encoding", "identity") != "identity":
                _response(_error_response(response, b""), outcome, key)
            body = await anext(response.aiter_bytes(chunk_size=_ERROR_BODY_LIMIT), b"")
            _response(_error_response(response, body), outcome, key)
        _require_identity(response)
        async for chunk in response.aiter_bytes(chunk_size=65536):
            writer.write(chunk)
    writer.finish()


def _once_sync(
    http: httpx.Client, saved: SavedRun, ticket: _Ticket, token: str | None
) -> _RunOutcome:
    with NamedTemporaryFile(dir=saved.path.parent, prefix=".download-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer = _Download(ticket, stream.file)
            _stream_sync(http, ticket, token, writer, saved.outcome, saved.key)
            stream.close()
            return _finish(saved, temporary)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


async def _once_async(
    http: httpx.AsyncClient, saved: SavedRun, ticket: _Ticket, token: str | None
) -> _RunOutcome:
    with NamedTemporaryFile(dir=saved.path.parent, prefix=".download-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer = _Download(ticket, stream.file)
            await _stream_async(http, ticket, token, writer, saved.outcome, saved.key)
            stream.close()
            return _finish(saved, temporary)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def download_sync(http: httpx.Client, saved: SavedRun, mint: Callable[[], str]) -> _RunOutcome:
    if saved.outcome.artifact is None and saved.outcome.run_result is None:
        return saved.persist_inline()
    # INVARIANT: malformed saved tickets fail before authentication or an HTTP request.
    ticket = _validate_ticket(saved)
    error: httpx.HTTPError | None = None
    for delay in _RETRY_DELAYS:
        time.sleep(delay)
        try:
            return _once_sync(http, saved, ticket, mint() if ticket.capability else None)
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
    if saved.outcome.artifact is None and saved.outcome.run_result is None:
        return saved.persist_inline()
    # INVARIANT: malformed saved tickets fail before authentication or an HTTP request.
    ticket = _validate_ticket(saved)
    error: httpx.HTTPError | None = None
    for delay in _RETRY_DELAYS:
        await asyncio.sleep(delay)
        try:
            token = await mint() if ticket.capability else None
            return await _once_async(http, saved, ticket, token)
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


def fetch_result_sync(http: httpx.Client, outcome: _RunOutcome) -> _RunOutcome:
    """``outcome`` with its Run result read into ``result_body``, for a Client that saves no
    results; the size and checksum are checked as a saved download's are."""
    result = outcome.run_result
    if result is None:
        return outcome
    ticket = _run_result_ticket(result)
    error: httpx.HTTPError | None = None
    for delay in _RETRY_DELAYS:
        time.sleep(delay)
        writer = _Download(ticket)
        try:
            _stream_sync(http, ticket, None, writer, outcome, None)
        except httpx.HTTPError as exc:
            error = exc
            continue
        return replace(outcome, result_body=_text(writer))
    raise EngineUnavailableError(
        "Could not fetch the Run's result", engine_url=str(http.base_url)
    ) from error


async def fetch_result_async(http: httpx.AsyncClient, outcome: _RunOutcome) -> _RunOutcome:
    """The async twin of ``fetch_result_sync``."""
    result = outcome.run_result
    if result is None:
        return outcome
    ticket = _run_result_ticket(result)
    error: httpx.HTTPError | None = None
    for delay in _RETRY_DELAYS:
        await asyncio.sleep(delay)
        writer = _Download(ticket)
        try:
            await _stream_async(http, ticket, None, writer, outcome, None)
        except httpx.HTTPError as exc:
            error = exc
            continue
        return replace(outcome, result_body=_text(writer))
    raise EngineUnavailableError(
        "Could not fetch the Run's result", engine_url=str(http.base_url)
    ) from error


def _text(writer: _Download) -> str:
    try:
        return writer.text()
    except UnicodeDecodeError as exc:
        raise ExecutionError(
            "SF Engine result artifact is not UTF-8 text",
            code="result_integrity_mismatch",
            permanent=True,
        ) from exc


def _validate_ticket(saved: SavedRun) -> _Ticket:
    outcome = saved.outcome
    if outcome.run_result is not None:
        ticket = _run_result_ticket(outcome.run_result)
    else:
        assert outcome.artifact is not None
        ticket = _Ticket(
            _artifact_path(outcome.artifact),
            outcome.artifact.size_bytes,
            outcome.artifact.sha256,
            capability=True,
        )
    times = (saved.outcome.started_at, saved.outcome.completed_at)
    # INVARIANT: expiration diagnostics subtract UTC times, so saved times must be aware.
    if any(value.tzinfo is None or value.utcoffset() is None for value in times):
        raise ExecutionError(
            "Saved result timestamps must be timezone-aware",
            code="result_metadata_invalid",
        )
    if saved.outcome.completed_at < saved.outcome.started_at:
        raise ExecutionError(
            "Saved result completion precedes its start", code="result_metadata_invalid"
        )
    return ticket


def _run_result_ticket(result: _RunResult) -> _Ticket:
    # INVARIANT: recovery metadata cannot redirect a fetch or bypass size/hash verification.
    if (
        not isinstance(result.run_id, str)
        or _RUN_ID.fullmatch(result.run_id) is None
        or isinstance(result.index, bool)
        or not isinstance(result.index, int)
        or result.index < 0
        or isinstance(result.size_bytes, bool)
        or not isinstance(result.size_bytes, int)
        or result.size_bytes < 0
        or not isinstance(result.sha256, str)
        or _SHA256.fullmatch(result.sha256) is None
    ):
        raise ExecutionError(
            "Saved Run result must name a Run id and an index, with a sha256 and a size",
            code="result_metadata_invalid",
            permanent=True,
        )
    return _Ticket(
        f"/runs/{result.run_id}/candidates/{result.index}/result",
        result.size_bytes,
        result.sha256,
        capability=False,
    )


def _artifact_path(artifact: _ResultArtifact) -> str:
    # INVARIANT: recovery metadata cannot redirect a fetch or bypass size/hash verification.
    if (
        not isinstance(artifact.id, str)
        or re.fullmatch(r"[0-9a-f]{64}", artifact.id) is None
        or isinstance(artifact.size_bytes, bool)
        or not isinstance(artifact.size_bytes, int)
        or artifact.size_bytes < 0
        or not isinstance(artifact.sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", artifact.sha256) is None
    ):
        raise ExecutionError(
            "Saved result artifact id/hash must be sha256 hex and size must be nonnegative",
            code="result_metadata_invalid",
            permanent=True,
        )
    return f"/artifacts/{artifact.id}"

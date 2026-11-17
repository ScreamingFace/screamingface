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
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO

import httpx

from screamingface._core.ports import _ResultArtifact, _RunOutcome, _RunResult
from screamingface._core.retry import _RETRYABLE_STATUS
from screamingface._core.wire import _NO_LOGIN, _REPLAY_SAFE
from screamingface._engine.runs import _RUN_ID, _SHA256
from screamingface._results.store import SavedRun, storage_error, sync_directory
from screamingface.errors import EngineUnavailableError, ExecutionError

_ERROR_BODY_LIMIT = 65536
_RETRY_DELAYS = (0.0, 0.2, 0.8)


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
        # In memory, the decoded text is kept, not the bytes: each chunk is decoded once.
        self.pieces: list[str] = []
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
        decoded = self.decoder.decode(chunk)
        self.digest.update(chunk)
        if self.stream is None:
            self.pieces.append(decoded)
        else:
            self.stream.write(chunk)

    def finish(self) -> None:
        self.pieces.append(self.decoder.decode(b"", final=True))
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
        return "".join(self.pieces)


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


def _extensions(ticket: _Ticket, login: bool) -> dict[str, bool]:
    """The request's marks. WHY ``_NO_LOGIN``: a follow's fetch may not start an interactive
    sign-in (E5 P2 spec D15). WHY ``_REPLAY_SAFE`` on the Run result route: reading it changes
    nothing on the Engine, so an Access challenge re-sends it after the sign-in and an edge
    failure is retried; an artifact ticket's capability is minted for one request."""
    marks = {} if login else {_NO_LOGIN: True}
    if not ticket.capability:
        marks[_REPLAY_SAFE] = True
    return marks


def _stream_sync(
    http: httpx.Client,
    ticket: _Ticket,
    token: str | None,
    writer: _Download,
    outcome,
    key,
    *,
    login: bool = True,
) -> None:
    with http.stream(
        "GET", ticket.path, headers=_headers(ticket, token), extensions=_extensions(ticket, login)
    ) as response:
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
    http: httpx.AsyncClient,
    ticket: _Ticket,
    token: str | None,
    writer: _Download,
    outcome,
    key,
    *,
    login: bool = True,
) -> None:
    async with http.stream(
        "GET", ticket.path, headers=_headers(ticket, token), extensions=_extensions(ticket, login)
    ) as response:
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
    http: httpx.Client, saved: SavedRun, ticket: _Ticket, token: str | None, login: bool = True
) -> _RunOutcome:
    with NamedTemporaryFile(dir=saved.path.parent, prefix=".download-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer = _Download(ticket, stream.file)
            _stream_sync(http, ticket, token, writer, saved.outcome, saved.key, login=login)
            stream.close()
            return _finish(saved, temporary)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


async def _once_async(
    http: httpx.AsyncClient,
    saved: SavedRun,
    ticket: _Ticket,
    token: str | None,
    login: bool = True,
) -> _RunOutcome:
    with NamedTemporaryFile(dir=saved.path.parent, prefix=".download-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            writer = _Download(ticket, stream.file)
            await _stream_async(http, ticket, token, writer, saved.outcome, saved.key, login=login)
            stream.close()
            return _finish(saved, temporary)
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)


def kept_here(saved: SavedRun) -> _RunOutcome | None:
    """The result already at ``saved.path`` with the size and sha256 its ticket names, else
    None. WHY: the Report built when a Run ends, and `Run.report()` on the machine that followed
    it, find the results the follow fetched there and fetch none of them again (E5 P2 spec
    D14)."""
    expected = saved.outcome.artifact or saved.outcome.run_result
    if expected is None or not saved.path.is_file():
        return None
    if saved.path.stat().st_size != expected.size_bytes:
        return None
    with saved.path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return replace(saved.outcome, result_path=saved.path) if digest == expected.sha256 else None


def download_sync(
    http: httpx.Client, saved: SavedRun, mint: Callable[[], str], *, login: bool = True
) -> _RunOutcome:
    if saved.outcome.artifact is None and saved.outcome.run_result is None:
        return saved.persist_inline()
    # INVARIANT: malformed saved tickets fail before authentication or an HTTP request.
    ticket = _validate_ticket(saved)
    here = kept_here(saved)
    if here is not None:
        return here
    return _retried_sync(
        lambda: _once_sync(http, saved, ticket, mint() if ticket.capability else None, login),
        _saved_retry(saved),
    )


async def download_async(
    http: httpx.AsyncClient,
    saved: SavedRun,
    mint: Callable[[], Awaitable[str]],
    *,
    login: bool = True,
) -> _RunOutcome:
    if saved.outcome.artifact is None and saved.outcome.run_result is None:
        return saved.persist_inline()
    # INVARIANT: malformed saved tickets fail before authentication or an HTTP request.
    ticket = _validate_ticket(saved)
    here = await asyncio.to_thread(kept_here, saved)
    if here is not None:
        return here

    async def attempt() -> _RunOutcome:
        token = await mint() if ticket.capability else None
        return await _once_async(http, saved, ticket, token, login)

    return await _retried_async(
        attempt,
        _saved_retry(saved),
    )


def fetch_result_sync(
    http: httpx.Client, outcome: _RunOutcome, *, login: bool = True
) -> _RunOutcome:
    """``outcome`` with its Run result read into ``result_body``, for a Client that saves no
    results; the size and checksum are checked as a saved download's are."""
    result = outcome.run_result
    if result is None:
        return outcome
    ticket = _run_result_ticket(result)

    def attempt() -> _RunOutcome:
        writer = _Download(ticket)
        _stream_sync(http, ticket, None, writer, outcome, None, login=login)
        return replace(outcome, result_body=writer.text())

    return _retried_sync(attempt, _Retry("Could not fetch the Run's result", str(http.base_url)))


async def fetch_result_async(
    http: httpx.AsyncClient, outcome: _RunOutcome, *, login: bool = True
) -> _RunOutcome:
    """The async twin of ``fetch_result_sync``."""
    result = outcome.run_result
    if result is None:
        return outcome
    ticket = _run_result_ticket(result)

    async def attempt() -> _RunOutcome:
        writer = _Download(ticket)
        await _stream_async(http, ticket, None, writer, outcome, None, login=login)
        return replace(outcome, result_body=writer.text())

    return await _retried_async(
        attempt, _Retry("Could not fetch the Run's result", str(http.base_url))
    )


@dataclass(frozen=True, slots=True)
class _Retry:
    """What a fetch that never got through says, and the saved run whose file a storage
    failure names (None for a result read into memory)."""

    message: str
    engine_url: str
    key: str | None = None


def _saved_retry(saved: SavedRun) -> _Retry:
    return _Retry(
        f"Could not fetch result; recover saved run {saved.key}", saved.engine_url, saved.key
    )


def _retried_sync(attempt: Callable[[], _RunOutcome], retry: _Retry) -> _RunOutcome:
    """One fetch, tried up to three times: a lost connection or an edge failure is tried again,
    anything else raised at once. The one copy of the rule every result fetch shares."""
    error: Exception | None = None
    for delay in _RETRY_DELAYS:
        time.sleep(delay)
        try:
            return attempt()
        except Exception as exc:  # noqa: BLE001 - sorted by `_transient`, else re-raised
            error = _transient(exc, retry)
    raise EngineUnavailableError(retry.message, engine_url=retry.engine_url) from error


async def _retried_async(
    attempt: Callable[[], Awaitable[_RunOutcome]], retry: _Retry
) -> _RunOutcome:
    """The async twin of ``_retried_sync``."""
    error: Exception | None = None
    for delay in _RETRY_DELAYS:
        await asyncio.sleep(delay)
        try:
            return await attempt()
        except Exception as exc:  # noqa: BLE001 - sorted by `_transient`, else re-raised
            error = _transient(exc, retry)
    raise EngineUnavailableError(retry.message, engine_url=retry.engine_url) from error


def _transient(exc: Exception, retry: _Retry) -> Exception:
    """``exc`` when another try may succeed; otherwise what the fetch raises, raised here.

    WHY an edge status too: a Client built for `sf.reports.get` has no retrying transport, and
    one 503 or 520 from the edge must not fail a result the Engine holds (`_core.retry` names
    which statuses are transient; 500 is not)."""
    if isinstance(exc, httpx.HTTPError):
        return exc
    if isinstance(exc, ExecutionError) and exc.status in _RETRYABLE_STATUS:
        return exc
    if isinstance(exc, UnicodeDecodeError):
        raise _not_text() from exc
    if isinstance(exc, OSError) and retry.key is not None:
        raise storage_error(exc, retry.key) from exc
    raise exc


def _not_text() -> ExecutionError:
    return ExecutionError(
        "SF Engine result artifact is not UTF-8 text",
        code="result_integrity_mismatch",
        permanent=True,
    )


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
        or _SHA256.fullmatch(artifact.id) is None
        or isinstance(artifact.size_bytes, bool)
        or not isinstance(artifact.size_bytes, int)
        or artifact.size_bytes < 0
        or not isinstance(artifact.sha256, str)
        or _SHA256.fullmatch(artifact.sha256) is None
    ):
        raise ExecutionError(
            "Saved result artifact id/hash must be sha256 hex and size must be nonnegative",
            code="result_metadata_invalid",
            permanent=True,
        )
    return f"/artifacts/{artifact.id}"

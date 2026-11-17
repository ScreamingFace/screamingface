"""The Engine's `/runs` routes (E5 P1 spec §4.1, E5 P2 spec §4.1), sync and async, decoded into
frozen records.

FEATURE: first-class Runs (OME-1785) and a detached Run (OME-1837). STORY: as a researcher, I send
my evaluation to the Engine once, with every Candidate's start, and reopen, follow or cancel it
from any notebook.

INVARIANT (P2 D2): Runs are required. `POST /runs` carries every Candidate's start, and a refusal
raises: nothing runs without a Run.
INVARIANT (P2 D16): only a 422 or 404 with no `code` reads as an Engine older than P2; every
refusal a P2 Engine makes is coded, and `runs_off` says Runs are off.
INVARIANT (§4.1): on reads and cancel, a 404 with code `run_not_found` means the id is unknown or
foreign (`KeyError`); any other 404 means this Engine does not serve Runs (`runs_unavailable`).
"""

from __future__ import annotations

import builtins
import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, NoReturn, cast, get_args
from urllib.parse import quote, urlencode

import httpx

from screamingface._core.wire import _REPLAY_SAFE
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    ExecutionError,
    ScreamingFaceError,
)

RUNS_PATH = "/runs"
RUN_NOT_FOUND = "run_not_found"
RUNS_UNAVAILABLE = "runs_unavailable"
RUNS_OFF = "runs_off"
ENGINE_UPGRADE_REQUIRED = "engine_upgrade_required"
CONTEXT_MISMATCH = "context_mismatch"
#: The Engine's largest `GET /runs` page.
MAX_PAGE_SIZE = 200

RunState = Literal["running", "complete", "partial", "errored", "canceled", "interrupted"]
CandidateState = Literal[
    "pending", "scheduled", "running", "succeeded", "failed", "timed_out", "stopped", "lost"
]
StopReason = Literal["canceled", "orphaned", "deadline"]
#: The Engine's Run id. INVARIANT: checked on decode, because it names a file in the local result
#: store (spec D8), so no other text from the Engine ever becomes a path.
_RUN_ID = re.compile(r"run_[0-9a-f]{32}")
_RUN_STATES = frozenset(get_args(RunState))
_CANDIDATE_STATES = frozenset(get_args(CandidateState))
_STOP_REASONS = frozenset(get_args(StopReason))
_SHA256 = re.compile(r"[0-9a-f]{64}")

#: One Engine call: ``(method, path, json=None) -> response``, marked safe to replay. Every
#: `/runs` call is: `POST` carries `client_key`, `DELETE` is idempotent, and reads change nothing.
Request = Callable[..., httpx.Response]
AsyncRequest = Callable[..., Awaitable[httpx.Response]]


@dataclass(frozen=True, slots=True)
class StartRequest:
    """One Candidate's start (P2 spec D8): its url4 and the flags the start route took as
    headers. The Engine's driver sends it for the Candidate, so the Client never starts one."""

    name: str
    url4: str
    answer_seed: int | None = None
    capture: bool = False
    use_cache: bool = True
    replay_frozen_copy: str | None = None

    def __post_init__(self) -> None:
        # INVARIANT (OME-1307): the Engine refuses both together, so no start carries both.
        if self.capture and self.replay_frozen_copy is not None:
            raise ValueError("capture and replay_frozen_copy are mutually exclusive")

    def body(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url4": self.url4,
            "answer_seed": self.answer_seed,
            "capture": self.capture,
            "use_cache": self.use_cache,
            "replay_frozen_copy": self.replay_frozen_copy,
        }


@dataclass(frozen=True, slots=True)
class ContextRef:
    """The Run's context as the Engine keeps it: its checksum and size (P2 spec D9b)."""

    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class RunRequest:
    """What `POST /runs` registers: every Candidate's start, in evaluation order, and the
    ``context`` the Client needs to rebuild the Report on another machine (P2 spec §4.1)."""

    client_key: str
    benchmark: str
    case_count: int
    candidates: tuple[StartRequest, ...]
    client_version: str
    context: str | None = None
    detach: bool = False
    deadline_s: int | None = None

    def body(self) -> dict[str, object]:
        return {
            "client_key": self.client_key,
            "benchmark": self.benchmark,
            "case_count": self.case_count,
            "candidates": [start.body() for start in self.candidates],
            "client_version": self.client_version,
            "context": self.context,
            "detach": self.detach,
            "deadline_s": self.deadline_s,
        }


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    name: str
    state: CandidateState
    attempt_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    cost_usd: Decimal | None
    error_code: str | None
    # P2 (spec §4.1): ``start`` and ``record`` only on the full read; ``record`` stays the
    # Engine's object, decoded where a Candidate's outcome is built (`run_record.py`).
    index: int = 0
    start: StartRequest | None = None
    record: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    case_count: int
    candidates: tuple[CandidateRecord, ...]
    # P2 (spec §4.1). WHY defaults: an Engine from before P2 still answers the reads.
    detached: bool = False
    deadline_at: datetime | None = None
    stopped_by: StopReason | None = None
    context: ContextRef | None = None


def marked_request(http: httpx.Client, *, timeout: float | None = None) -> Request:
    """``http``'s calls, marked safe to replay; ``timeout`` bounds each (default: the client's)."""
    bound = httpx.USE_CLIENT_DEFAULT if timeout is None else timeout

    def request(method: str, path: str, json: object = None) -> httpx.Response:
        return http.request(method, path, json=json, timeout=bound, extensions={_REPLAY_SAFE: True})

    return request


def marked_async_request(http: httpx.AsyncClient, *, timeout: float | None = None) -> AsyncRequest:
    """The async twin of ``marked_request``."""
    bound = httpx.USE_CLIENT_DEFAULT if timeout is None else timeout

    async def request(method: str, path: str, json: object = None) -> httpx.Response:
        return await http.request(
            method, path, json=json, timeout=bound, extensions={_REPLAY_SAFE: True}
        )

    return request


# --- sync ---------------------------------------------------------------------------------


def create_sync(request: Request, run: RunRequest) -> RunRecord:
    """Register the Run, which the Engine then starts and drives (P2 spec D1)."""
    try:
        response = request("POST", RUNS_PATH, json=run.body())
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc
    return _created(response)


def get_sync(request: Request, run_id: str, *, summary: bool = False) -> RunRecord:
    """The Run; with ``summary``, without each Candidate's start and record (P2 spec §4.1)."""
    path = _run_path(run_id) + ("?view=summary" if summary else "")
    return _decode_run(_json(_answer(_send_sync(request, "GET", path), run_id)))


def context_sync(request: Request, run_id: str, expected: ContextRef) -> str:
    """The Run's context, checked against the checksum the Run holds (P2 spec D9b)."""
    response = _send_sync(request, "GET", f"{_run_path(run_id)}/context")
    return _checked_context(_answer_object(response, run_id), expected)


def cancel_sync(request: Request, run_id: str) -> None:
    _answer(_send_sync(request, "DELETE", _run_path(run_id)), run_id)


def list_sync(
    request: Request,
    *,
    state: RunState | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> tuple[RunRecord, ...]:
    runs: builtins.list[RunRecord] = []
    cursor: str | None = None
    while True:
        path = _list_path(state, since, limit - len(runs), cursor)
        page, cursor = _decode_page(_json(_answer(_send_sync(request, "GET", path), None)))
        runs.extend(page)
        # WHY an empty page ends it too: a cursor that adds nothing would loop forever.
        if cursor is None or not page or len(runs) >= limit:
            return tuple(runs[:limit])


def _send_sync(request: Request, method: str, path: str) -> httpx.Response:
    try:
        return request(method, path)
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc


# --- async --------------------------------------------------------------------------------


async def create_async(request: AsyncRequest, run: RunRequest) -> RunRecord:
    try:
        response = await request("POST", RUNS_PATH, json=run.body())
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc
    return _created(response)


async def get_async(request: AsyncRequest, run_id: str, *, summary: bool = False) -> RunRecord:
    path = _run_path(run_id) + ("?view=summary" if summary else "")
    return _decode_run(_json(_answer(await _send_async(request, "GET", path), run_id)))


async def context_async(request: AsyncRequest, run_id: str, expected: ContextRef) -> str:
    response = await _send_async(request, "GET", f"{_run_path(run_id)}/context")
    return _checked_context(_answer_object(response, run_id), expected)


async def cancel_async(request: AsyncRequest, run_id: str) -> None:
    _answer(await _send_async(request, "DELETE", _run_path(run_id)), run_id)


async def _send_async(request: AsyncRequest, method: str, path: str) -> httpx.Response:
    try:
        return await request(method, path)
    except httpx.HTTPError as exc:
        raise _unreachable(exc) from exc


# --- answers ------------------------------------------------------------------------------


def _run_path(run_id: str) -> str:
    # WHY quoted whole: the id is the caller's text, so it must stay one path segment.
    return f"{RUNS_PATH}/{quote(run_id, safe='')}"


def _list_path(
    state: RunState | None, since: datetime | None, limit: int, cursor: str | None
) -> str:
    params: dict[str, str] = {}
    if state is not None:
        params["state"] = state
    if since is not None:
        params["since"] = since.isoformat()
    params["limit"] = str(min(limit, MAX_PAGE_SIZE))
    if cursor is not None:
        params["cursor"] = cursor
    return f"{RUNS_PATH}?{urlencode(params)}"


def _created(response: httpx.Response) -> RunRecord:
    if response.status_code in (200, 201):
        return _decode_run(_json(response))
    raise _refused(response)


def _refused(response: httpx.Response) -> ScreamingFaceError:
    """Why `POST /runs` registered nothing (P2 spec §4.1, D2, D16)."""
    status = response.status_code
    code = problem_code(response)
    refusal: ScreamingFaceError
    if code is None and status in (404, 422):
        refusal = EngineCapabilityError(
            "This SF Engine is older than this Client, so it cannot run an evaluation as a Run",
            code=ENGINE_UPGRADE_REQUIRED,
            status=status,
            permanent=True,
            hint="Upgrade the SF Engine to one that runs detached Runs, or ask its operator to.",
        )
    elif status == 404 and code == RUNS_OFF:
        refusal = ExecutionError(
            "Runs are off on this SF Engine, so it cannot run an evaluation",
            code=RUNS_OFF,
            status=status,
            permanent=True,
            hint="Ask the SF Engine's operator to turn Runs on.",
        )
    elif status in (401, 403):
        refusal = AuthenticationError(
            "The SF Engine refused the caller", code=code, status=status, permanent=True
        )
    else:
        detail = _problem_detail(response)
        refusal = ExecutionError(
            f"The SF Engine refused the Run{f': {detail}' if detail else ''}",
            code=code,
            status=status,
            permanent=status < 500,
        )
    return refusal


def _answer_object(response: httpx.Response, run_id: str) -> httpx.Response:
    """``response`` when it carries the object; its coded 404 (`context_not_found`,
    `result_not_found`) raised as that, any other refusal as a Runs refusal."""
    code = problem_code(response)
    if response.status_code == 404 and code not in (None, RUN_NOT_FOUND, RUNS_OFF):
        raise ExecutionError(
            f"The SF Engine no longer holds this object of Run {run_id}",
            code=code,
            status=404,
            permanent=True,
        )
    return _answer(response, run_id)


def _checked_context(response: httpx.Response, expected: ContextRef) -> str:
    body = response.content
    if len(body) != expected.size_bytes or hashlib.sha256(body).hexdigest() != expected.sha256:
        raise ExecutionError(
            "The Run's context does not match the checksum the Run holds",
            code=CONTEXT_MISMATCH,
            permanent=True,
        )
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        _malformed()


def _unreachable(exc: httpx.HTTPError) -> EngineUnavailableError:
    try:
        url = exc.request.url
    except RuntimeError:
        origin = ""
    else:
        origin = f"{url.scheme}://{url.netloc.decode('ascii')}"
    return EngineUnavailableError("Could not reach the SF Engine to read Runs", engine_url=origin)


def _answer(response: httpx.Response, run_id: str | None) -> httpx.Response:
    if response.is_success:
        return response
    status = response.status_code
    code = problem_code(response)
    if status == 404 and code == RUN_NOT_FOUND and run_id is not None:
        raise KeyError(run_id)
    if status == 404:
        raise ExecutionError(
            "This SF Engine does not serve Runs",
            code=RUNS_UNAVAILABLE,
            status=404,
            permanent=True,
            hint="Update the SF Engine, or ask its operator to turn Runs on.",
        )
    if status in (401, 403):
        raise AuthenticationError(
            "The SF Engine refused the caller", code=code, status=status, permanent=True
        )
    raise ExecutionError(
        f"The SF Engine answered HTTP {status} to a Runs call",
        code=code,
        status=status,
        permanent=status < 500,
    )


def problem_code(response: httpx.Response) -> str | None:
    return _problem_text(response, "code")


def _problem_detail(response: httpx.Response) -> str | None:
    return _problem_text(response, "detail")


def _problem_text(response: httpx.Response, name: str) -> str | None:
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type != "application/problem+json":
        return None
    try:
        problem: object = response.json()
    except ValueError:
        return None
    value = problem.get(name) if isinstance(problem, dict) else None
    return value if isinstance(value, str) else None


def _json(response: httpx.Response) -> object:
    try:
        return response.json()
    except (ValueError, RecursionError):
        _malformed()


def _decode_page(value: object) -> tuple[builtins.list[RunRecord], str | None]:
    page = _object(value)
    runs = page.get("runs")
    cursor = page.get("next_cursor")
    if not isinstance(runs, builtins.list) or not (cursor is None or isinstance(cursor, str)):
        _malformed()
    return [_decode_run(run) for run in runs], cursor


def _decode_run(value: object) -> RunRecord:
    run = _object(value)
    candidates = run.get("candidates")
    case_count = run.get("case_count")
    if not isinstance(candidates, builtins.list) or not _is_int(case_count):
        _malformed()
    detached = run.get("detached", False)
    if not isinstance(detached, bool):
        _malformed()
    return RunRecord(
        id=_run_id(run.get("id")),
        state=cast(RunState, _choice(run.get("state"), _RUN_STATES)),
        created_at=_time(run.get("created_at")),
        finished_at=_optional(run.get("finished_at"), _time),
        benchmark=_text(run.get("benchmark")),
        case_count=cast(int, case_count),
        candidates=tuple(
            _decode_candidate(candidate, index) for index, candidate in enumerate(candidates)
        ),
        detached=detached,
        deadline_at=_optional(run.get("deadline_at"), _time),
        stopped_by=cast(StopReason | None, _optional(run.get("stopped_by"), _stop_reason)),
        context=_optional(run.get("context"), _context_ref),
    )


def _decode_candidate(value: object, position: int) -> CandidateRecord:
    candidate = _object(value)
    index = candidate.get("index", position)
    if not _is_int(index):
        _malformed()
    return CandidateRecord(
        name=_text(candidate.get("name")),
        state=cast(CandidateState, _choice(candidate.get("state"), _CANDIDATE_STATES)),
        attempt_id=_optional(candidate.get("attempt_id"), _text),
        started_at=_optional(candidate.get("started_at"), _time),
        finished_at=_optional(candidate.get("finished_at"), _time),
        cost_usd=_optional(candidate.get("cost_usd"), _cost),
        error_code=_optional(candidate.get("error_code"), _text),
        index=cast(int, index),
        start=_optional(candidate.get("start"), _start),
        record=_optional(candidate.get("record"), _object),
    )


def _start(value: object) -> StartRequest:
    start = _object(value)
    seed = start.get("answer_seed")
    capture = start.get("capture", False)
    use_cache = start.get("use_cache", True)
    replay = start.get("replay_frozen_copy")
    if (
        not (seed is None or _is_int(seed))
        or not isinstance(capture, bool)
        or not isinstance(use_cache, bool)
        or not (replay is None or isinstance(replay, str))
    ):
        _malformed()
    return StartRequest(
        name=_text(start.get("name")),
        url4=_text(start.get("url4")),
        answer_seed=cast(int | None, seed),
        capture=capture,
        use_cache=use_cache,
        replay_frozen_copy=replay,
    )


def _context_ref(value: object) -> ContextRef:
    context = _object(value)
    digest = context.get("sha256")
    size = context.get("size_bytes")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None or not _is_int(size):
        _malformed()
    return ContextRef(sha256=digest, size_bytes=cast(int, size))


def _stop_reason(value: object) -> str:
    return _choice(value, _STOP_REASONS)


def _object(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        _malformed()
    return cast(Mapping[str, object], value)


def _optional[T](value: object, decode: Callable[[object], T]) -> T | None:
    return None if value is None else decode(value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        _malformed()
    return value


def _run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        _malformed()
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _choice(value: object, allowed: frozenset[str]) -> str:
    # WHY the type first: a list or an object is unhashable, and `in` would raise TypeError,
    # which no caller treats as a malformed answer.
    if not isinstance(value, str) or value not in allowed:
        _malformed()
    return value


def _time(value: object) -> datetime:
    try:
        moment = datetime.fromisoformat(_text(value))
    except ValueError:
        _malformed()
    if moment.tzinfo is None:
        _malformed()
    return moment


def _cost(value: object) -> Decimal:
    # WHY a string: cost is exact everywhere on the wire, so it is never a JSON float.
    try:
        cost = Decimal(_text(value))
    except InvalidOperation:
        _malformed()
    if not cost.is_finite():
        _malformed()
    return cost


def _malformed() -> NoReturn:
    raise ExecutionError(
        "The SF Engine answered a Runs call with a malformed body",
        code="engine_contract_error",
        permanent=True,
    )


__all__ = [
    "CONTEXT_MISMATCH",
    "ENGINE_UPGRADE_REQUIRED",
    "MAX_PAGE_SIZE",
    "RUNS_OFF",
    "RUNS_UNAVAILABLE",
    "AsyncRequest",
    "CandidateRecord",
    "CandidateState",
    "ContextRef",
    "Request",
    "RunRecord",
    "RunRequest",
    "RunState",
    "StartRequest",
    "StopReason",
    "cancel_async",
    "cancel_sync",
    "context_async",
    "context_sync",
    "create_async",
    "create_sync",
    "get_async",
    "get_sync",
    "list_sync",
    "marked_async_request",
    "marked_request",
]

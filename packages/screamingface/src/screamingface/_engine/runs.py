"""The Engine's `/runs` routes (E5 P1 spec §4.1), sync and async, decoded into frozen records.

FEATURE: first-class Runs (OME-1785). STORY: as a researcher, every evaluation I start is
recorded on the Engine, so I can reopen, follow or cancel it from any notebook.

INVARIANT (D7): registering never fails an evaluation. Any failure of `POST /runs` (any non-2xx
answer, a malformed one, or an unreachable Engine) is one `Unavailable`, never an exception.
INVARIANT (§4.1): on reads and cancel, a 404 with code `run_not_found` means the id is unknown or
foreign (`KeyError`); any other 404 means this Engine does not serve Runs (`runs_unavailable`).
"""

from __future__ import annotations

import builtins
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
    EngineUnavailableError,
    ExecutionError,
    ScreamingFaceError,
)

RUNS_PATH = "/runs"
RUN_NOT_FOUND = "run_not_found"
RUNS_UNAVAILABLE = "runs_unavailable"
#: The Engine's largest `GET /runs` page.
MAX_PAGE_SIZE = 200

RunState = Literal["running", "complete", "partial", "errored", "canceled", "interrupted"]
CandidateState = Literal[
    "pending", "scheduled", "running", "succeeded", "failed", "timed_out", "stopped", "lost"
]
#: The Engine's Run id. INVARIANT: checked on decode, because it names a file in the local result
#: store (spec D8), so no other text from the Engine ever becomes a path.
_RUN_ID = re.compile(r"run_[0-9a-f]{32}")
_RUN_STATES = frozenset(get_args(RunState))
_CANDIDATE_STATES = frozenset(get_args(CandidateState))

#: One Engine call: ``(method, path, json=None) -> response``, marked safe to replay. Every
#: `/runs` call is: `POST` carries `client_key`, `DELETE` is idempotent, and reads change nothing.
Request = Callable[..., httpx.Response]
AsyncRequest = Callable[..., Awaitable[httpx.Response]]


@dataclass(frozen=True, slots=True)
class RunRequest:
    """What `POST /runs` registers. Candidates are named in evaluation order; a start names one
    by its index here (`X-SF-Run-Candidate`)."""

    client_key: str
    benchmark: str
    case_count: int
    candidates: tuple[str, ...]
    client_version: str

    def body(self) -> dict[str, object]:
        return {
            "client_key": self.client_key,
            "benchmark": self.benchmark,
            "case_count": self.case_count,
            "candidates": builtins.list(self.candidates),
            "client_version": self.client_version,
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


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    state: RunState
    created_at: datetime
    finished_at: datetime | None
    benchmark: str
    case_count: int
    candidates: tuple[CandidateRecord, ...]


@dataclass(frozen=True, slots=True)
class Unavailable:
    """`POST /runs` did not register the Run (D7); ``reason`` says why, for the one notice."""

    reason: str


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


def create_sync(request: Request, run: RunRequest) -> RunRecord | Unavailable:
    try:
        response = request("POST", RUNS_PATH, json=run.body())
    except (httpx.HTTPError, ScreamingFaceError) as exc:
        return _unreached(exc)
    return _created(response)


def get_sync(request: Request, run_id: str) -> RunRecord:
    return _decode_run(_json(_answer(_send_sync(request, "GET", _run_path(run_id)), run_id)))


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


async def create_async(request: AsyncRequest, run: RunRequest) -> RunRecord | Unavailable:
    try:
        response = await request("POST", RUNS_PATH, json=run.body())
    except (httpx.HTTPError, ScreamingFaceError) as exc:
        return _unreached(exc)
    return _created(response)


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


def _created(response: httpx.Response) -> RunRecord | Unavailable:
    if response.status_code not in (200, 201):
        return Unavailable(f"the SF Engine answered HTTP {response.status_code}")
    try:
        return _decode_run(_json(response))
    except ExecutionError as exc:
        return Unavailable(exc.message)


def _unreached(exc: Exception) -> Unavailable:
    return Unavailable(f"the SF Engine could not be reached ({type(exc).__name__})")


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
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type != "application/problem+json":
        return None
    try:
        problem: object = response.json()
    except ValueError:
        return None
    code = problem.get("code") if isinstance(problem, dict) else None
    return code if isinstance(code, str) else None


def _json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
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
    return RunRecord(
        id=_run_id(run.get("id")),
        state=cast(RunState, _choice(run.get("state"), _RUN_STATES)),
        created_at=_time(run.get("created_at")),
        finished_at=_optional(run.get("finished_at"), _time),
        benchmark=_text(run.get("benchmark")),
        case_count=cast(int, case_count),
        candidates=tuple(_decode_candidate(candidate) for candidate in candidates),
    )


def _decode_candidate(value: object) -> CandidateRecord:
    candidate = _object(value)
    return CandidateRecord(
        name=_text(candidate.get("name")),
        state=cast(CandidateState, _choice(candidate.get("state"), _CANDIDATE_STATES)),
        attempt_id=_optional(candidate.get("attempt_id"), _text),
        started_at=_optional(candidate.get("started_at"), _time),
        finished_at=_optional(candidate.get("finished_at"), _time),
        cost_usd=_optional(candidate.get("cost_usd"), _cost),
        error_code=_optional(candidate.get("error_code"), _text),
    )


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
    if value not in allowed:
        _malformed()
    return cast(str, value)


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
    "MAX_PAGE_SIZE",
    "RUNS_UNAVAILABLE",
    "AsyncRequest",
    "CandidateRecord",
    "CandidateState",
    "Request",
    "RunRecord",
    "RunRequest",
    "RunState",
    "Unavailable",
    "cancel_async",
    "cancel_sync",
    "create_async",
    "create_sync",
    "get_sync",
    "list_sync",
    "marked_async_request",
    "marked_request",
]

"""One Scoreboard call as data, and the pure rule that settles each attempt of it.

WHY data: the sync and async `Leaderboards` twins differ only by `await`. A call that names its
request, its status codes and its re-send rule is built once, by a pure function, and sent by
`call_sync` or `call_async`, so there is one way to make a Scoreboard call and the twins cannot
drift. The loop itself is `_core/attempts.py`.

INVARIANT: `settle` is pure and runs the decoder OUTSIDE the retry decision, so a malformed 200
body is never sent again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType
from typing import Final, NoReturn

import httpx

from screamingface._core.attempts import _Again, _Attempt, _Done, _Step, drive_async, drive_sync
from screamingface._core.wire import detail_code as _wire_detail_code
from screamingface.errors import LeaderboardError

_NO_CODES: Final[Mapping[int, str]] = MappingProxyType({})


def _never(_outcome: _Attempt, _error: LeaderboardError) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class _Resend:
    """The re-send rule of one call: how many times, after which failure, and how long to wait.

    `backoff` maps the number of the re-send (1 for the first) to seconds. `None` means send
    again at once and never call `sleep`.
    """

    limit: int = 0
    when: Callable[[_Attempt, LeaderboardError], bool] = _never
    backoff: Callable[[int], float] | None = None

    def next_step(self, attempt: int, outcome: _Attempt, error: LeaderboardError) -> _Again | None:
        if attempt >= self.limit or not self.when(outcome, error):
            return None
        return _Again(None if self.backoff is None else self.backoff(attempt + 1))


_NO_RESEND: Final = _Resend()


@dataclass(frozen=True, slots=True)
class _ScoreboardCall[T]:
    method: str
    path: str
    # INVARIANT: no default (`_core/wire.py` default-deny). Every call site states it.
    replay_safe: bool
    decode: Callable[[object, str], T]  # (payload, scoreboard_url)
    operation: str = "load"
    # WHY non-empty means coded: a board that gives a status map sends `{"detail": {"code": ...}}`
    # (D7 X-8), so a call with a map also opts into `detail.code`. The map is the status fallback
    # for a proxy, or a board before E14a, that sends a status with no coded body.
    codes: Mapping[int, str] = _NO_CODES
    params: Mapping[str, object] | None = None
    json: Mapping[str, object] | None = None
    headers: Mapping[str, str] | None = None
    timeout: float | None = None
    missing: tuple[str, str] | None = None
    # WHY a flag: the board sends an uncoded 409 on a submit for a transient race, and only that
    # one is retryable with a hint.
    retry_uncoded_409: bool = False
    resend: _Resend = _NO_RESEND
    # WHY the handler decides: whether a failure is "the board is down" is the caller's policy, so
    # it stays in one place per call. Return the error to raise instead, or None to keep this one.
    on_failure: Callable[[str, LeaderboardError], Exception | None] | None = None

    def send[R](self, request: Callable[..., R]) -> R:
        return request(
            self.method,
            self.path,
            params=self.params,
            json=self.json,
            headers=self.headers,
            replay_safe=self.replay_safe,
            **_timeout_argument(self.timeout),
        )


def settle[T](
    call: _ScoreboardCall[T], scoreboard_url: str, attempt: int, outcome: _Attempt
) -> _Step[T]:
    """Done with the decoded body, send again, or raise the terminal error. Pure."""
    try:
        payload = _payload(call, scoreboard_url, outcome)
    except LeaderboardError as error:
        again = call.resend.next_step(attempt, outcome, error)
        if again is not None:
            return again
        mapped = None if call.on_failure is None else call.on_failure(scoreboard_url, error)
        if mapped is not None:
            raise mapped from error
        raise
    return _Done(call.decode(payload, scoreboard_url))


def call_sync[T](
    request: Callable[..., httpx.Response],
    scoreboard_url: str,
    call: _ScoreboardCall[T],
    sleep: Callable[[float], object],
) -> T:
    return drive_sync(
        lambda: call.send(request),
        partial(settle, call, scoreboard_url),
        sleep,
        (httpx.HTTPError,),
    )


async def call_async[T](
    request: Callable[..., Awaitable[httpx.Response]],
    scoreboard_url: str,
    call: _ScoreboardCall[T],
    sleep: Callable[[float], Awaitable[None]],
) -> T:
    return await drive_async(
        lambda: call.send(request),
        partial(settle, call, scoreboard_url),
        sleep,
        (httpx.HTTPError,),
    )


def _payload(call: _ScoreboardCall[object], scoreboard_url: str, outcome: _Attempt) -> object:
    if isinstance(outcome, httpx.Response):
        return _response_json(outcome, scoreboard_url, call)
    _unreachable(scoreboard_url, outcome)


def _timeout_argument(timeout: float | None) -> dict[str, float]:
    # WHY only when given: the default call shape must not change, so the client's own timeout
    # still applies to every call that does not name one.
    return {} if timeout is None else {"timeout": timeout}


def _response_json(
    response: httpx.Response,
    scoreboard_url: str,
    call: _ScoreboardCall[object],
) -> object:
    if response.status_code == 404 and call.missing is not None:
        code, message = call.missing
        raise LeaderboardError(
            message,
            scoreboard_url=scoreboard_url,
            code=code,
            status=404,
            permanent=True,
        )
    if not response.is_success:
        details = _error_details(response)
        suffix = f" ({details})" if isinstance(details, str) and details else ""
        # WHY a coded 409 is a fixed fact (`system_name_taken`, `cache_version_already_bound`): the
        # board sends an uncoded 409 for a transient race, and only that one gets the retry hint.
        submission_conflict = (
            response.status_code == 409
            and call.retry_uncoded_409
            and _wire_detail_code(details) is None
        )
        raise LeaderboardError(
            f"Could not {call.operation} the Scoreboard: HTTP {response.status_code}{suffix}",
            scoreboard_url=scoreboard_url,
            code=_error_code(details, response.status_code, call),
            status=response.status_code,
            permanent=(
                response.status_code < 500
                and response.status_code != 429
                and not submission_conflict
            ),
            details=details,
            hint="Retry the submission." if submission_conflict else None,
        )
    try:
        return response.json()
    except ValueError as exc:
        _invalid("response must be JSON", exc)


def _error_details(response: httpx.Response) -> object:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, Mapping) and isinstance(payload.get("detail"), str):
        return payload["detail"]
    return payload


def _error_code(details: object, status: int, call: _ScoreboardCall[object]) -> str:
    if call.codes:
        coded = _wire_detail_code(details)
        if coded is not None:
            return coded
    return _status_code(status, call)


def _status_code(status: int, call: _ScoreboardCall[object]) -> str:
    return call.codes.get(status, "scoreboard_contract_error")


def _unreachable(scoreboard_url: str, exc: Exception) -> NoReturn:
    raise LeaderboardError(
        "Could not reach the configured ScreamingFace Scoreboard",
        scoreboard_url=scoreboard_url,
        code="scoreboard_unreachable",
        permanent=False,
    ) from exc


def _invalid(message: str, cause: BaseException | None = None) -> NoReturn:
    error = LeaderboardError(
        f"Invalid Scoreboard Leaderboard response: {message}",
        code="invalid_leaderboard",
        permanent=True,
    )
    if cause is None:
        raise error
    raise error from cause


__all__: list[str] = []

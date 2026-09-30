"""`_freeze_step` settles one freeze attempt (E14 simplify, contract C2a).

The rule is pure but for the injected jitter, so each case calls it directly: attempt 0 and 1
against every kind of outcome. One retry in all (`_ATTEMPTS == 2`), only after a 502, 503, 504 or
a transport error, and never after an error that is not a transient network fault.
"""

from __future__ import annotations

import httpx
import pytest

import screamingface as sf
from screamingface._core.attempts import _Again, _Attempt, _Done, _Step
from screamingface._core.ports import _FreezeOutcome, _FreezeUnavailable, _FrozenCacheVersion
from screamingface._engine.cache_versions import _freeze_step, _send_freeze

JITTER_S = 1.75
FROZEN_BODY = {
    "receipt": "jws",
    "cache_version_id": "9b2c5f52-3c0a-4a37-8a54-6c3f1c1c5b11",
    "entry_count": 3,
    "call_count": 5,
    "missing_count": 0,
    "coverage_status": "complete",
    "archive_sha256": "a" * 64,
}


class _Jitter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return JITTER_S


def _step(attempt: int, outcome: _Attempt) -> tuple[_Step[_FreezeOutcome], int]:
    jitter = _Jitter()
    return _freeze_step(attempt, outcome, jitter), jitter.calls


def _unavailable(step: _Step[_FreezeOutcome]) -> str:
    assert isinstance(step, _Done)
    assert isinstance(step.value, _FreezeUnavailable)
    return step.value.reason


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_retryable_status_on_the_first_attempt_waits_one_jitter_and_sends_again(
    status: int,
) -> None:
    step, jitter_calls = _step(0, httpx.Response(status))

    assert step == _Again(JITTER_S)
    assert jitter_calls == 1


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_retryable_status_on_the_last_attempt_is_final_and_calls_no_jitter(status: int) -> None:
    step, jitter_calls = _step(1, httpx.Response(status))

    assert _unavailable(step) == f"http_{status}"
    assert jitter_calls == 0


@pytest.mark.parametrize("attempt", [0, 1])
def test_a_200_is_done_with_the_frozen_version_on_any_attempt(attempt: int) -> None:
    step, jitter_calls = _step(attempt, httpx.Response(200, json=FROZEN_BODY))

    assert isinstance(step, _Done)
    assert isinstance(step.value, _FrozenCacheVersion)
    assert step.value.receipt == "jws"
    assert jitter_calls == 0


@pytest.mark.parametrize("attempt", [0, 1])
def test_a_200_with_a_bad_body_is_done_as_invalid_response(attempt: int) -> None:
    step, _ = _step(attempt, httpx.Response(200, json={"receipt": ""}))

    assert _unavailable(step) == "invalid_response"


@pytest.mark.parametrize("attempt", [0, 1])
def test_a_429_is_never_retried(attempt: int) -> None:
    step, jitter_calls = _step(attempt, httpx.Response(429))

    assert _unavailable(step) == "http_429"
    assert jitter_calls == 0


@pytest.mark.parametrize(
    ("error", "reason"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("down"), "unreachable")],
)
def test_a_transport_error_is_retried_once_and_then_final(
    error: httpx.TransportError, reason: str
) -> None:
    first, first_jitter = _step(0, error)
    last, last_jitter = _step(1, error)

    assert first == _Again(JITTER_S)
    assert first_jitter == 1
    assert _unavailable(last) == reason
    assert last_jitter == 0


@pytest.mark.parametrize("attempt", [0, 1])
def test_an_authentication_error_is_final_at_once(attempt: int) -> None:
    step, jitter_calls = _step(attempt, sf.AuthenticationError("login failed"))

    assert _unavailable(step) == "engine_auth_failed"
    assert jitter_calls == 0


@pytest.mark.parametrize("attempt", [0, 1])
@pytest.mark.parametrize(
    "error",
    [httpx.DecodingError("bad gzip"), sf.EngineUnavailableError("down", engine_url="https://e")],
)
def test_an_error_that_is_not_a_transient_network_fault_is_final_at_once(
    attempt: int, error: Exception
) -> None:
    step, jitter_calls = _step(attempt, error)

    assert _unavailable(step) == "unreachable"
    assert jitter_calls == 0


def test_the_freeze_request_keeps_its_call_shape() -> None:
    seen: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def request(*args: object, **kwargs: object) -> str:
        seen.append((args, kwargs))
        return "response"

    assert _send_freeze(request, "trace-1") == "response"
    assert seen == [
        (("POST", "/v1/cache-versions"), {"json": {"trace_id": "trace-1"}, "timeout": 60.0})
    ]

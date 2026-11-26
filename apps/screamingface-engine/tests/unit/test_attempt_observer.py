"""The C8 attempt observer at the Engine HTTP transport seam (Unit 5.2).

FEATURE: Router Recipe extension. One logical model call may make several Engine HTTP attempts
(the transport/queue retry, the OME-1872 Candidate retry, a cache re-issue), and the Gateway may
make several upstream sends for each (`X-AIGW-Upstream-Attempts`, C7). The observer counts both
without changing what the transport returns or whether it retries.

INVARIANT: unknown is never zero. A lost reply or a missing header makes `upstream_attempts`
unknown; `possibly_billed` is false only when every attempt is known to have reached no provider.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

import httpx
import pytest

from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.operation_calls import AttemptFact
from screamingface_engine.world.attempt_facts import AttemptObserver
from screamingface_engine.world.gateway_transport import _post_answered, _post_completion
from url4.core.errors import ResolutionError

_HEADER = "X-AIGW-Upstream-Attempts"
_BODY = {"model": "openrouter/anthropic/claude-x", "messages": []}
_ANSWER = {"choices": []}

Step = httpx.Response | Exception


def _ok(count: str | None = "1", status: int = 200, body: object = _ANSWER) -> httpx.Response:
    headers = {} if count is None else {_HEADER: count}
    return httpx.Response(status, json=body, headers=headers)


def _queue_refusal(count: str | None) -> httpx.Response:
    return _ok(count, 503, {"detail": {"code": "provider_queue_timeout", "message": "busy"}})


@contextmanager
def _no_backoff() -> Iterator[None]:
    with mock.patch.multiple(
        "screamingface_engine.world.gateway_transport",
        _TRANSPORT_BACKOFF_BASE_S=0.0,
        _TRANSPORT_BACKOFF_JITTER_S=0.0,
    ):
        yield


def _transport(steps: list[Step]) -> Callable[[httpx.Request], httpx.Response]:
    remaining = list(steps)

    def handle(_request: httpx.Request) -> httpx.Response:
        step = remaining.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    return handle


async def _post(steps: list[Step], observer: AttemptObserver | None) -> tuple[Any, bool]:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_transport(steps)), base_url="http://aigateway.test"
    ) as client:
        with _no_backoff():
            return await _post_completion(client, headers={}, body=_BODY, observer=observer)


def _facts(observer: AttemptObserver) -> tuple[int, int | None, bool]:
    attempts = observer.attempts()
    assert attempts is not None
    return attempts.engine_attempts, attempts.upstream_attempts, attempts.possibly_billed


# --- the pure observer ----------------------------------------------------------------------------


def test_no_attempt_is_no_fact() -> None:
    assert AttemptObserver().attempts() is None


@pytest.mark.parametrize(
    ("header", "upstream", "billed"),
    [("1", 1, True), ("3", 3, True), ("0", 0, False), (None, None, True)],
)
def test_one_answered_attempt(header: str | None, upstream: int | None, billed: bool) -> None:
    observer = AttemptObserver()
    observer.answered(_ok(header).headers, queue_refusal=False)

    assert _facts(observer) == (1, upstream, billed)


# WHY bytes for the full-width digit: httpx takes a `str` header value as ASCII only, while the
# wire can carry its UTF-8 bytes, which httpx then decodes back to "１" — not a C7 count.
@pytest.mark.parametrize("header", ["-1", "1.0", "x", "1, 2", "", " 1", "+1", "01", "１".encode()])
def test_an_unreadable_header_is_unknown_never_zero(header: str | bytes) -> None:
    raw = header if isinstance(header, bytes) else header.encode()
    observer = AttemptObserver()
    observer.answered(httpx.Headers({_HEADER.encode(): raw}), queue_refusal=False)

    assert _facts(observer) == (1, None, True)


def test_a_queue_refusal_without_a_header_reached_no_provider() -> None:
    observer = AttemptObserver()
    observer.answered(_queue_refusal(None).headers, queue_refusal=True)

    assert _facts(observer) == (1, None, False)


@pytest.mark.parametrize(("never_sent", "billed"), [(True, False), (False, True)])
def test_a_lost_reply_is_unknown(never_sent: bool, billed: bool) -> None:
    observer = AttemptObserver()
    observer.lost(never_sent=never_sent)

    assert _facts(observer) == (1, None, billed)


def test_a_final_zero_keeps_the_earlier_count() -> None:
    observer = AttemptObserver()
    observer.answered(_ok("2").headers, queue_refusal=False)
    observer.answered(_ok("0").headers, queue_refusal=False)

    assert _facts(observer) == (2, 2, True)


def test_an_earlier_unknown_survives_a_later_count() -> None:
    observer = AttemptObserver()
    observer.lost(never_sent=True)
    observer.answered(_ok("1").headers, queue_refusal=False)

    assert _facts(observer) == (2, None, True)


def _aigw(*hops: object, status: str = "complete", omitted: object = 0) -> dict[str, Any]:
    """A chat reply's `_aigw` block whose accounting attempts carry ``hops`` redirect hops."""
    attempts = [{"redirect_hop_count": hop} for hop in hops]
    return {
        "usage_accounting": {
            "capture_status": status,
            "omitted_attempts": omitted,
            "attempts": attempts,
        }
    }


@pytest.mark.parametrize(
    ("header", "aigw", "upstream"),
    [
        pytest.param("2", _aigw(0, 0), 2, id="agrees"),
        pytest.param("3", _aigw(0, 1), 3, id="agrees-with-a-redirect"),
        pytest.param("1", _aigw(0, 1), None, id="disagrees"),
        pytest.param("2", _aigw(0), None, id="disagrees-low"),
        pytest.param("1", _aigw(0, 0, status="partial"), 1, id="partial"),
        pytest.param("1", _aigw(0, 0, omitted=1), 1, id="omitted"),
        pytest.param("1", _aigw(0, 0, omitted=False), 1, id="omitted-not-a-count"),
        pytest.param("1", _aigw(0, "x"), 1, id="malformed-hop"),
        pytest.param("1", _aigw(0, -1), 1, id="negative-hop"),
        pytest.param("1", _aigw(0, True), 1, id="boolean-hop"),
        pytest.param(
            "1",
            {"usage_accounting": {**_aigw(0)["usage_accounting"], "attempts": [{}, 1]}},
            1,
            id="malformed-attempt",
        ),
        pytest.param("1", {"usage_accounting": None}, 1, id="no-accounting"),
        pytest.param("1", None, 1, id="no-aigw"),
    ],
)
def test_complete_accounting_cross_checks_the_last_header(
    header: str, aigw: object, upstream: int | None
) -> None:
    observer = AttemptObserver()
    observer.answered(_ok(header).headers, queue_refusal=False)
    observer.check_accounting(aigw)

    assert _facts(observer)[1] == upstream
    assert _facts(observer)[2] is True


# --- through `_post_completion` -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_return_is_unchanged_with_and_without_an_observer() -> None:
    plain = await _post([httpx.ReadError(""), _ok("1")], None)
    observer = AttemptObserver()
    observed = await _post([httpx.ReadError(""), _ok("1")], observer)

    assert isinstance(observed, tuple)
    assert len(observed) == 2
    assert (observed[0].status_code, observed[1]) == (plain[0].status_code, plain[1]) == (200, True)
    assert _facts(observer) == (2, None, True)


@pytest.mark.asyncio
async def test_a_connect_failure_then_an_answer() -> None:
    observer = AttemptObserver()
    await _post([httpx.ConnectError(""), _ok("1")], observer)

    assert _facts(observer) == (2, None, True)


@pytest.mark.asyncio
async def test_a_queue_retry_counts_both_tries() -> None:
    observer = AttemptObserver()
    await _post([_queue_refusal("0"), _ok("2")], observer)

    assert _facts(observer) == (2, 2, True)


@pytest.mark.asyncio
async def test_the_observer_counts_a_final_transport_failure() -> None:
    observer = AttemptObserver()

    with pytest.raises(ResolutionError) as caught:
        await _post([httpx.ReadError(""), httpx.ReadError("")], observer)

    assert caught.value.code == "aigateway_transport_error"
    assert _facts(observer) == (2, None, True)


@pytest.mark.asyncio
async def test_never_sent_failures_only_are_not_billed() -> None:
    observer = AttemptObserver()

    with pytest.raises(ResolutionError):
        await _post([httpx.ConnectError(""), httpx.ConnectError("")], observer)

    assert _facts(observer) == (2, None, False)


@pytest.mark.asyncio
async def test_the_candidate_retry_carries_the_same_observer() -> None:
    observer = AttemptObserver()
    steps: list[Step] = [_ok("1", 503, {"detail": "busy"}), _ok("1")]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_transport(steps)), base_url="http://aigateway.test"
    ) as client:
        with (
            candidate_invocation_scope(),
            mock.patch(
                "screamingface_engine.world.candidate_call_retry.retry_wait", return_value=0.0
            ),
        ):
            response, billed = await _post_answered(
                client, headers={}, body=_BODY, probe=None, observer=observer
            )

    assert (response.status_code, billed) == (200, True)
    assert _facts(observer) == (2, 2, True)


def test_the_fact_document_is_the_c8_shape() -> None:
    fact = AttemptFact("router_1", "failed", "aigateway_http_503", 2, None, True)

    assert fact.document() == {
        "binding": "router_1",
        "status": "failed",
        "code": "aigateway_http_503",
        "engine_attempts": 2,
        "upstream_attempts": None,
        "possibly_billed": True,
    }

"""OME-1872 — a Candidate model call the gateway failed for a moment is asked again.

FEATURE: OME-1872. The AI gateway answers 429 when a provider stays busy past its own retries,
and 500/502 when it breaks itself. The connector marks those temporary, and a Candidate call
(the model or Fusion being scored) now waits and asks again, 2 times, before the Case fails.
STORY: as a researcher, a Case's score reflects the model's answer, never one bad minute at
the gateway.

INVARIANT: only a Candidate call retries. A judge keeps its own 2 re-asks, and a replay never
retries (it would read the same captured error again).
"""

from __future__ import annotations

import httpx
import pytest
from frozen_copy_support import (
    CHAT,
    REPLAY_CHAT,
    Gateway,
    capture_scope,
    chat,
    error,
    replay_scope,
    run_call,
    stored,
)

from screamingface_engine.candidate_scope import candidate_invocation_scope
from screamingface_engine.capture_outcomes import CALL_OCCURRENCE_HEADER, REPLAY_FIELD
from screamingface_engine.request_scope import RequestScope, request_scope
from screamingface_engine.world import candidate_call_retry as policy
from screamingface_engine.world import connector
from url4.streaming.protocol import CachePolicy

_RUN = RequestScope(origin="run")


@pytest.fixture(autouse=True)
def _waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record each retry's wait instead of sleeping it, with no jitter."""
    waits: list[float] = []

    async def record(_attempt: int, delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(connector, "_wait_to_retry", record)
    monkeypatch.setattr(policy, "_jitter", lambda _low, _high: 0.0)
    return waits


def _busy(retry_after: str | None = None) -> httpx.Response:
    """The gateway's 429 after its own provider retries gave up."""
    headers: dict[str, str] = {} if retry_after is None else {"Retry-After": retry_after}
    return httpx.Response(
        429, headers=headers, json={"detail": {"code": "rate_limited", "message": "m"}}
    )


async def _candidate_call(gateway: Gateway, scope: RequestScope = _RUN):
    """One model call made while the Candidate answers, as the Candidate adapter marks it."""
    with candidate_invocation_scope():
        return await run_call(gateway, scope, web_search=False)


@pytest.mark.asyncio
async def test_a_candidate_call_the_gateway_rate_limited_once_is_answered(
    _waits: list[float],
) -> None:
    gateway = Gateway([_busy(), chat("the real answer")])

    _tally, answer, failure = await _candidate_call(gateway)

    assert failure is None and answer == "the real answer"
    sent = gateway.calls(CHAT)
    assert len(sent) == 2
    # WHY: the retry is the SAME request, so the gateway cache and a capture key it the same.
    assert sent[0][1] == sent[1][1]
    assert _waits == [10.0]


@pytest.mark.asyncio
async def test_a_candidate_call_failing_on_every_try_still_fails_as_temporary(
    _waits: list[float],
) -> None:
    gateway = Gateway([error(502, "bad_gateway")])

    _tally, answer, failure = await _candidate_call(gateway)

    assert answer is None and failure is not None
    assert failure.code == "bad_gateway"
    assert failure.permanent is False, "the Case still reports a temporary infrastructure failure"
    assert len(gateway.calls(CHAT)) == policy.CANDIDATE_CALL_RETRIES + 1 == 3
    assert _waits == [10.0, 30.0]


@pytest.mark.asyncio
async def test_a_judge_call_is_not_retried_by_the_connector(_waits: list[float]) -> None:
    # WHY: a judge already gets 2 re-asks (judge_redraw.py or url4's ;retry=2); a connector
    # retry on top would give each judge item 3 x 3 = 9 tries.
    gateway = Gateway([_busy(), chat()])

    _tally, answer, failure = await run_call(gateway, _RUN, web_search=False)

    assert answer is None and failure is not None and failure.permanent is False
    assert len(gateway.calls(CHAT)) == 1
    assert _waits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 422])
async def test_a_permanent_refusal_is_not_retried(status: int) -> None:
    gateway = Gateway([error(status, "refused"), chat()])

    _tally, _answer, failure = await _candidate_call(gateway)

    assert failure is not None and failure.permanent is True
    assert len(gateway.calls(CHAT)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
async def test_every_temporary_status_is_retried(status: int) -> None:
    gateway = Gateway([error(status, "blip"), chat("ok")])

    _tally, answer, failure = await _candidate_call(gateway)

    assert failure is None and answer == "ok"
    assert len(gateway.calls(CHAT)) == 2


@pytest.mark.asyncio
async def test_the_gateway_retry_after_lengthens_the_wait(_waits: list[float]) -> None:
    gateway = Gateway([_busy("45"), _busy("999"), chat()])

    _tally, _answer, failure = await _candidate_call(gateway)

    assert failure is None
    # 45 s beats the 10 s schedule; 999 s is capped so one header cannot stall a Case for long.
    assert _waits == [45.0, policy.RETRY_AFTER_CAP_S]


@pytest.mark.parametrize(
    ("retry_number", "retry_after", "expected"),
    [
        (1, None, 10.0),
        (2, None, 30.0),
        (1, "5", 10.0),  # a shorter hint never shortens the schedule
        (1, "60", 60.0),
        (2, "100000", 120.0),
        (1, "soon", 10.0),
        (1, "-3", 10.0),
        (1, "nan", 10.0),
        (1, "inf", 10.0),
    ],
)
def test_retry_wait_schedule(retry_number: int, retry_after: str | None, expected: float) -> None:
    assert policy.retry_wait(retry_number, retry_after) == expected


def test_jitter_is_added_to_the_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    # WHY: concurrent Cases rate-limited together must not all come back at the same instant.
    monkeypatch.setattr(policy, "_jitter", lambda low, high: high)
    assert policy.retry_wait(1, None) == 10.0 + policy.JITTER_S


@pytest.mark.asyncio
async def test_a_retry_that_does_not_fit_the_deadline_is_not_started(
    monkeypatch: pytest.MonkeyPatch, _waits: list[float]
) -> None:
    clock: list[float] = [100.0]
    monkeypatch.setattr(connector.time, "monotonic", lambda: clock[0])
    gateway = Gateway([_busy(), chat()])

    # 8 s left: the 10 s wait alone outlasts it.
    _tally, answer, failure = await _candidate_call(
        gateway, RequestScope(origin="run", deadline=108.0)
    )

    assert answer is None and failure is not None and failure.permanent is False
    assert len(gateway.calls(CHAT)) == 1
    assert _waits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("first", "billed"), [(429, False), (500, True), (502, True)])
async def test_a_retry_after_a_5xx_is_marked_possibly_billed(first: int, billed: bool) -> None:
    # WHY: a 5xx can come after the provider charged for the call; a gateway 429 means it gave up
    # before the provider accepted it. A recorded fact only — the price is the successful request's.
    gateway = Gateway([error(first, "blip"), chat()])
    async with gateway.client() as client:
        with request_scope(_RUN), candidate_invocation_scope():
            _resp, outcome = await connector._fetch_completion(
                client, headers={}, body={"model": "m"}, cache=CachePolicy()
            )
    assert outcome.retried is billed


@pytest.mark.asyncio
async def test_a_capture_call_answered_on_retry_records_the_answer_not_ambiguous() -> None:
    # The copy holds the 429 and then the 200 at one call key; replay serves the 200.
    gateway = Gateway([_busy(), chat("ok", stored())])

    tally, answer, failure = await _candidate_call(gateway, capture_scope())

    assert failure is None and answer == "ok"
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "stored")]
    assert len({h[CALL_OCCURRENCE_HEADER] for h, _b in gateway.calls(CHAT)}) == 1


@pytest.mark.asyncio
async def test_a_capture_call_failing_on_every_try_is_not_ambiguous() -> None:
    # WHY: the copy holds only errors at the key, and replay serves the last one, reproducing
    # this failure. Nothing the model never used is stored, so nothing is ambiguous.
    failed = httpx.Response(
        429, headers=stored(), json={"detail": {"code": "rate_limited", "message": "m"}}
    )
    gateway = Gateway([failed])

    tally, _answer, failure = await _candidate_call(gateway, capture_scope())

    assert failure is not None
    assert [(o.lane, o.status) for o in tally.outcomes] == [("chat", "stored")]
    assert "capture.partial.ambiguous" not in tally.attributes()


@pytest.mark.asyncio
async def test_a_replay_call_never_retries_a_captured_failure(_waits: list[float]) -> None:
    # WHY: a replay serves what the copy holds; asking again reads the same captured 429.
    captured = httpx.Response(
        429,
        headers={REPLAY_FIELD: "hit"},
        json={"detail": {"code": "rate_limited", "message": "m"}},
    )
    gateway = Gateway(replay_steps=[captured, chat()])

    _tally, answer, failure = await _candidate_call(gateway, replay_scope())

    assert answer is None and failure is not None
    assert len(gateway.calls(REPLAY_CHAT)) == 1
    assert _waits == []

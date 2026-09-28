"""A model call's completion, failure, and stalls are visible in the log (OME-1126).

FEATURE: model-call lifecycle observability.

STORY: as an operator watching a paid run, the log must distinguish "the model is still
thinking" from "the call is dead" — during the OME-1126 hunt both looked like minutes of
silence after a single dispatch line, and the only way to tell was the provider's
website.

INVARIANT under test: every gateway round trip logs its terminal outcome (model,
duration, finish_reason or error code); a call in flight past the heartbeat threshold
logs repeatedly until it resolves; and NO lifecycle record ever carries prompt or
response text (OME-990 — the runtime log must never hold prompt bytes).
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

import httpx
import pytest

from screamingface_engine.request_scope import RequestScope
from screamingface_engine.world import connector as connector_module
from screamingface_engine.world.config import ModelSpec
from screamingface_engine.world.connector import AigatewayConfig, _chat_completion_loop
from screamingface_engine.world.errors import RunnerRequestError

pytestmark = pytest.mark.asyncio

_MODEL = "openrouter/test/candidate"
_PROMPT = "SECRET-PROMPT-TEXT what is 2+2?"
_LOGGER = "screamingface_engine.runner.connector"


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _completion(content: str = "4") -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    }


async def _run_loop(monkeypatch: pytest.MonkeyPatch, fetch) -> str:
    monkeypatch.setattr(connector_module, "_fetch_completion", fetch)
    # WHY the cast: the loop never touches the client once `_fetch_completion` is stubbed — the
    # client exists only to be forwarded to the stub. F2: the per-request values travel in the
    # scope, so an anonymous scope is exactly the pre-F2 `profile=None, identity_headers=None`.
    return await _chat_completion_loop(
        http_client=cast(httpx.AsyncClient, None),
        cfg=AigatewayConfig(default_model=_MODEL, models=(ModelSpec(id=_MODEL),)),
        scope=RequestScope(origin="run"),
        messages=[{"role": "user", "content": _PROMPT}],
        params={},
        spec=ModelSpec(id=_MODEL),
        tavily_http=None,
        tavily_api_key=None,
        retrieval_policy=None,
    )


async def test_a_completed_call_logs_model_duration_and_finish_reason(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def fetch(client, *, headers, body, cache):
        return _Resp(_completion()), None

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await _run_loop(monkeypatch, fetch)
    records = [r for r in caplog.records if "completed" in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert _MODEL in message
    assert "finish_reason=stop" in message
    assert "s" in message  # a duration is named


async def test_a_failed_call_logs_the_error_code_before_raising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def fetch(client, *, headers, body, cache):
        return _Resp({"error": {"message": "boom"}}), None

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        with pytest.raises(RunnerRequestError):
            await _run_loop(monkeypatch, fetch)
    records = [r for r in caplog.records if "failed" in r.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert _MODEL in message
    assert "aigateway_bad_response" in message


async def test_a_slow_call_heartbeats_until_it_resolves(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(connector_module, "_IN_FLIGHT_HEARTBEAT_S", 0.05)

    async def fetch(client, *, headers, body, cache):
        await asyncio.sleep(0.18)
        return _Resp(_completion()), None

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await _run_loop(monkeypatch, fetch)
    beats = [r for r in caplog.records if "in flight" in r.getMessage()]
    assert len(beats) >= 2, "a stalled call must keep announcing itself"
    assert _MODEL in beats[0].getMessage()
    # WHY: the heartbeat must STOP with the call — a beat after completion would be a
    # leaked task announcing a call that no longer exists.
    await asyncio.sleep(0.12)
    assert len([r for r in caplog.records if "in flight" in r.getMessage()]) == len(beats)


async def test_lifecycle_records_never_carry_prompt_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """INVARIANT (OME-990): the runtime log is world-readable operational history — the
    prompt must never reach it through lifecycle lines."""
    monkeypatch.setattr(connector_module, "_IN_FLIGHT_HEARTBEAT_S", 0.05)

    async def fetch(client, *, headers, body, cache):
        await asyncio.sleep(0.08)
        return _Resp(_completion("SECRET-ANSWER-TEXT")), None

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await _run_loop(monkeypatch, fetch)
    for record in caplog.records:
        assert "SECRET-PROMPT-TEXT" not in record.getMessage()
        assert "SECRET-ANSWER-TEXT" not in record.getMessage()


def test_the_local_composition_root_attaches_exactly_one_engine_handler() -> None:
    """WHY: without a handler the package logger's INFO lines are dropped by Python's
    last-resort handler and none of the lifecycle lines above ever reach runtime.log;
    idempotence keeps repeated `create_local_app` calls from duplicating every line."""
    from screamingface_engine.local import _configure_engine_logging, _EngineRuntimeLogHandler

    package_logger = logging.getLogger("screamingface_engine")
    before = [h for h in package_logger.handlers if isinstance(h, _EngineRuntimeLogHandler)]
    try:
        _configure_engine_logging()
        _configure_engine_logging()
        added = [h for h in package_logger.handlers if isinstance(h, _EngineRuntimeLogHandler)]
        assert len(added) == 1
        assert package_logger.level == logging.INFO
    finally:
        for handler in package_logger.handlers[:]:
            if isinstance(handler, _EngineRuntimeLogHandler) and handler not in before:
                package_logger.removeHandler(handler)


async def test_heartbeats_back_off_instead_of_spamming(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """WHY: a 20-minute reasoning marathon at a fixed interval is 20 log lines saying
    the same thing — doubling waits keep a long call to a handful of beats while a
    fixed cadence would flood the log."""
    monkeypatch.setattr(connector_module, "_IN_FLIGHT_HEARTBEAT_S", 0.04)
    monkeypatch.setattr(connector_module, "_IN_FLIGHT_HEARTBEAT_MAX_S", 10.0)

    async def fetch(client, *, headers, body, cache):
        await asyncio.sleep(0.4)
        return _Resp(_completion()), None

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await _run_loop(monkeypatch, fetch)
    beats = len([r for r in caplog.records if "in flight" in r.getMessage()])
    # Fixed 0.04s cadence over 0.4s would be ~10 beats; doubling (0.04+0.08+0.16+0.32)
    # yields 3-4. The band is wide because CI clocks jitter.
    assert 2 <= beats <= 5, beats


class _FlakyTransport:
    """An `httpx.MockTransport` handler that fails transiently a fixed number of times.

    WHY a real `httpx.MockTransport` rather than a stub coroutine: the fact under test —
    which tuple slot `_post_completion` puts the retry bit in — lives INSIDE that function's
    own retry loop, so the probe has to go through `http_client.post` and a genuine
    `httpx.TransportError`, not around them.
    """

    def __init__(self, fail_times: int) -> None:
        self.calls = 0
        self._fail_times = fail_times

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise httpx.ReadError("synthetic transport failure", request=request)
        return httpx.Response(200, json={"ok": True})


async def test_post_completion_reports_no_retry_when_the_first_attempt_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for OME-1203 finding 3: a mutant `attempt >= 0` would mark this call
    retried too, and every cache hit downstream would be withdrawn forever with the suite
    still green. Asserted positionally so swapping the tuple's two elements also fails."""
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0)
    flaky = _FlakyTransport(fail_times=0)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(flaky.handler), base_url="http://aigateway.test"
    ) as client:
        result = await connector_module._post_completion(client, headers={}, body={})

    assert isinstance(result[0], httpx.Response)
    assert result[1] is False
    assert flaky.calls == 1


async def test_post_completion_reports_a_retry_when_the_first_attempt_fails_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The companion case: a transport failure followed by a success must report `True` —
    the fact `avoided_usd_for_outcome` relies on to withdraw a hit's saved cost. Asserted
    positionally so swapping the tuple's two elements also fails."""
    monkeypatch.setattr(connector_module, "_transport_backoff", lambda _: 0)
    flaky = _FlakyTransport(fail_times=1)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(flaky.handler), base_url="http://aigateway.test"
    ) as client:
        result = await connector_module._post_completion(client, headers={}, body={})

    assert isinstance(result[0], httpx.Response)
    assert result[1] is True
    assert flaky.calls == 2


async def test_a_cancelled_call_logs_cancelled_and_reraises_without_failing_the_observation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """FX-18 (NT-L9): a sync timeout cancels the call; before this the log said nothing."""
    from screamingface_engine.observations import ModelCall

    failed: list[str] = []
    monkeypatch.setattr(ModelCall, "failed", lambda self, code: failed.append(code))
    entered = asyncio.Event()

    async def fetch(client, *, headers, body, cache):
        entered.set()
        await asyncio.Event().wait()

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        task = asyncio.create_task(_run_loop(monkeypatch, fetch))
        await asyncio.wait_for(entered.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    records = [r for r in caplog.records if "cancelled" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].name == _LOGGER
    message = records[0].getMessage()
    assert message.startswith(f"model call cancelled model={_MODEL} duration=")
    assert message.endswith("s")
    assert failed == []
    assert not [r for r in caplog.records if "failed" in r.getMessage()]

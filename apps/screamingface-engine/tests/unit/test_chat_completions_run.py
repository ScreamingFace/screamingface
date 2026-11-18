"""Tests for the schedule stage of POST /v1/chat/completions (prd/chat-completion.md).

CC-10, CC-11, CC-17, CC-20, CC-26, CC-37, CC-46, CC-47, CC-48 and Q8 (the outcome and duration
metrics). The App runs in process over a scripted runner, so each test reads what was scheduled,
what the chat-input store held at schedule time, and what the App left behind.
"""

import hashlib
import json
from typing import Any

import pytest
from _chat_app import (
    EMAIL,
    answered,
    body,
    chat_app,
    error,
    post,
    stored_bytes,
    stored_record,
)

from screamingface_engine.artifacts.blob_schema import BlobError
from screamingface_engine.artifacts.s3 import S3StorageError
from screamingface_engine.chat.input import (
    ChatInputTooLarge,
    chat_input_from_request,
    encode_chat_input,
)
from screamingface_engine.chat.wire import ChatCompletionRequest

pytestmark = pytest.mark.asyncio


async def test_request_schedules_chat_shape_with_blob_ref_and_deadline() -> None:
    ca = chat_app(answered(), chat_max_wait_s=5.0)
    resp = await post(ca.app, body(), headers={**EMAIL, "X-Profile": "p1", "X-Capture": "true"})
    assert resp.status_code == 200
    run = ca.runner.scheduled[0]
    assert run["shape"] == "chat"
    assert run["deadline_s"] == 10
    assert run["capture"] is False
    assert run.get("replay_frozen_copy") is None
    assert run["identity"] == EMAIL
    assert len(run["topic"]) == 64
    assert run["topic"].isalnum()
    data = stored_bytes(ca.runner.inputs[0])
    assert run["chat_input"] == "blob:sha256/" + hashlib.sha256(data).hexdigest()
    assert stored_record(ca.runner.inputs[0])["schema"] == "screamingface.chat-input.v1"


async def test_blob_is_written_before_schedule_and_deleted_after_success() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body())
    assert resp.status_code == 200
    assert stored_record(ca.runner.inputs[0])["schema"] == "screamingface.chat-input.v1"
    assert ca.objects.objects == {}


@pytest.mark.parametrize("flags", [{"full": True}, {"conflict": True}])
async def test_blob_is_written_before_schedule_and_deleted_on_schedule_failure(
    flags: dict[str, Any],
) -> None:
    ca = chat_app(answered(), **flags)
    resp = await post(ca.app, body())
    assert resp.status_code in (429, 409)
    assert ca.objects.objects == {}
    assert ca.runner.stopped == []
    assert ca.runner.scheduled == []


async def test_a_start_that_is_not_confirmed_stops_the_run_and_deletes_the_blob() -> None:
    """Review F6: the broker can still hold the message of a queue_unavailable start."""
    ca = chat_app(answered(), queue_down=True)
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert error(resp)["code"] == "queue_unavailable"
    assert len(ca.runner.attempted) == 1
    assert ca.runner.stopped == ca.runner.attempted
    assert ca.objects.objects == {}


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(BlobError("refused"), id="blob-error"),
        pytest.param(S3StorageError("unreachable"), id="s3-error"),
        pytest.param(OSError("disk full"), id="os-error"),
    ],
)
async def test_an_input_write_failure_is_503_chat_unavailable_and_schedules_nothing(
    failure: Exception,
) -> None:
    ca = chat_app(answered())

    def ingest(*args: Any) -> Any:
        raise failure

    ca.app.state.chat_input_store.ingest = ingest
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert error(resp)["code"] == "chat_unavailable"
    assert error(resp)["type"] == "server_error"
    assert "retry-after" not in resp.headers
    assert resp.headers["x-should-retry"] == "false"
    assert ca.runner.attempted == []
    assert ca.runner.stopped == []


async def test_inflight_cap_is_429_with_retry_after() -> None:
    ca = chat_app(full=True, retry_after_s=42)
    resp = await post(ca.app, body())
    assert resp.status_code == 429
    assert error(resp)["code"] == "overloaded"
    assert error(resp)["type"] == "rate_limit_error"
    assert resp.headers["retry-after"] == "42"
    assert resp.headers["x-should-retry"] == "true"

    ca_no_estimate = chat_app(full=True, retry_after_s=None)
    resp = await post(ca_no_estimate.app, body())
    assert resp.headers["retry-after"] == "1"


async def test_cache_participates_by_default_and_no_store_turns_it_off() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body())
    assert resp.status_code == 200
    assert ca.runner.scheduled[0]["cache"].participate is True

    ca_no_store = chat_app(answered())
    resp = await post(ca_no_store.app, body(), headers={**EMAIL, "Cache-Control": "no-store"})
    assert resp.status_code == 200
    assert ca_no_store.runner.scheduled[0]["cache"].participate is False


async def test_missing_blob_store_is_503_chat_unavailable() -> None:
    ca = chat_app(answered(), blob_store=False)
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert error(resp)["code"] == "chat_unavailable"
    assert error(resp)["type"] == "server_error"
    assert "retry-after" not in resp.headers
    assert resp.headers["x-should-retry"] == "false"
    assert ca.runner.scheduled == []
    assert ca.source is not None
    assert ca.source.calls == []


@pytest.mark.parametrize(
    ("flags", "status", "code", "should_retry"),
    [
        ({"full": True}, 429, "overloaded", "true"),
        ({"queue_down": True}, 503, "queue_unavailable", "true"),
        ({"conflict": True}, 409, "internal_error", "false"),
        ({"job_runner": False}, 503, "internal_error", "false"),
    ],
)
async def test_problem_exceptions_are_re_enveloped_in_openai_shape(
    flags: dict[str, Any], status: int, code: str, should_retry: str
) -> None:
    ca = chat_app(answered(), **flags)
    resp = await post(ca.app, body())
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/json")
    assert set(error(resp)) == {"message", "type", "param", "code"}
    assert "detail" not in resp.json()
    assert error(resp)["code"] == code
    assert resp.headers["x-should-retry"] == should_retry
    if flags.get("conflict"):
        assert error(resp)["message"] == "the request failed"


async def test_missing_blob_store_is_permanent_and_queue_down_is_retryable() -> None:
    ca_no_store = chat_app(answered(), blob_store=False)
    resp = await post(ca_no_store.app, body())
    assert resp.status_code == 503
    assert "retry-after" not in resp.headers
    assert resp.headers["x-should-retry"] == "false"

    ca_queue_down = chat_app(answered(), queue_down=True)
    resp = await post(ca_queue_down.app, body())
    assert resp.status_code == 503
    assert error(resp)["code"] == "queue_unavailable"
    assert resp.headers["retry-after"] == "5"
    assert resp.headers["x-should-retry"] == "true"


async def test_encoded_record_over_cap_is_413() -> None:
    empty = json.dumps(body(messages=[{"role": "user", "content": ""}]), separators=(",", ":"))
    content = "x" * (8_000_000 - len(empty.encode()))
    payload = body(messages=[{"role": "user", "content": content}])
    raw = json.dumps(payload, separators=(",", ":")).encode()
    assert len(raw) == 8_000_000
    with pytest.raises(ChatInputTooLarge):
        encode_chat_input(chat_input_from_request(ChatCompletionRequest.model_validate_json(raw)))

    ca = chat_app(answered())
    resp = await post(ca.app, raw)
    assert resp.status_code == 413
    assert error(resp)["code"] == "request_too_large"
    assert ca.runner.scheduled == []
    assert ca.objects.objects == {}


async def test_request_after_drain_event_is_503_before_schedule() -> None:
    ca = chat_app(answered())
    ca.app.state.chat_drain.request()
    resp = await post(ca.app, body())
    assert resp.status_code == 503
    assert error(resp)["code"] == "server_restarting"
    assert error(resp)["type"] == "server_error"
    assert resp.headers["x-should-retry"] == "true"
    assert "retry-after" not in resp.headers
    assert ca.runner.scheduled == []
    assert ca.objects.objects == {}
    assert ca.source is not None
    assert ca.source.calls == []


async def test_chat_requests_are_counted_by_outcome_and_timed() -> None:
    ca = chat_app(answered())
    resp = await post(ca.app, body())
    assert resp.status_code == 200
    resp = await post(ca.app, body(), headers={"Content-Type": "application/json"})
    assert resp.status_code == 401
    registry = ca.app.state.metrics.registry
    assert (
        registry.get_sample_value("screamingface_engine_chat_requests_total", {"outcome": "ok"})
        == 1.0
    )
    assert (
        registry.get_sample_value(
            "screamingface_engine_chat_requests_total", {"outcome": "identity_required"}
        )
        == 1.0
    )
    assert (
        registry.get_sample_value("screamingface_engine_chat_request_duration_seconds_count") == 2.0
    )

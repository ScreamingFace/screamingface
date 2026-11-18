"""Tests of the answer stage of POST /v1/chat/completions (prd/chat-completion.md section 3.2).

CC-12, CC-13, CC-14, CC-21, CC-27, CC-28, CC-36, CC-38, CC-44 and CC-45 of the TDD table, the
terminal table of section 3.2, and the Q7 default: a run with no root cost-usage frame answers
with zero usage, a null cost and one warning line that names the trace id. Also the final-step
report of the CHAT_RESULT.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from _chat_app import (
    MODEL,
    TRACE_ID,
    answered,
    body,
    chat_app,
    chat_result,
    cost_frame,
    ended,
    error,
    post,
    result_frame,
    terminated_frame,
)

from screamingface_engine.artifacts.ports import LocalFile, RemoteStream
from screamingface_engine.chat.result import FinalStep, encode_chat_result
from url4.streaming.protocol.signals import ResultArtifact

pytestmark = pytest.mark.asyncio

ANSWER_LOGGER = "screamingface_engine.rest.chat_answer"
ARTIFACT = ResultArtifact(id="ab" * 32, size_bytes=10, sha256="ab" * 32)

# (run status, terminal code, permanent, HTTP status, error code, x-should-retry)
TERMINAL_ROWS = [
    ("failed", "fail_closed", True, 422, "fail_closed", "false"),
    ("failed", "chat_input_unavailable", False, 500, "chat_input_unavailable", "false"),
    ("failed", "chat_input_invalid", True, 500, "chat_input_invalid", "false"),
    ("failed", "final_step_ambiguous", True, 502, "final_step_ambiguous", "false"),
    ("failed", "quorum_not_met", True, 502, "quorum_not_met", "false"),
    ("failed", "unbound_reference", False, 502, "unbound_reference", "true"),
    ("failed", "queue_expired", False, 502, "queue_expired", "true"),
    ("failed", "provider_secret_code", True, 502, "internal_error", "false"),
    ("failed", "memory_budget_exceeded", True, 503, "run_failed", "false"),
    ("failed", "oom_killed", False, 503, "run_failed", "true"),
    ("failed", "killed", False, 503, "run_failed", "true"),
    ("failed", "child_exited", False, 503, "run_failed", "true"),
    ("stopped", "worker_draining", False, 503, "worker_draining", "true"),
    ("stopped", "cancelled", False, 503, "run_failed", "true"),
    ("timed_out", "deadline_exceeded", False, 504, "timeout", "false"),
]

# (name, script, HTTP status, error code): a succeeded run that has no usable result.
SUCCESS_ROWS = [
    ("no-result", lambda t: [terminated_frame(t)], 502, "result_unavailable"),
    (
        "wrong-media-type",
        lambda t: [result_frame(t, media_type="application/json"), terminated_frame(t)],
        502,
        "result_invalid",
    ),
    (
        "bad-body",
        lambda t: [result_frame(t, body="not a chat result"), terminated_frame(t)],
        502,
        "result_invalid",
    ),
    (
        "artifact-missing",
        lambda t: [result_frame(t, artifact=ARTIFACT), terminated_frame(t)],
        502,
        "result_unavailable",
    ),
]


def _error_type(status: int) -> str:
    """The OpenAI type of an error status: 429, other 4xx, then 5xx."""
    if status == 429:
        return "rate_limit_error"
    if status < 500:
        return "invalid_request_error"
    return "server_error"


def _subtree(topic: str, input_tokens: int, n: int) -> Any:
    """A root cost-usage frame with the given input tokens."""
    return cost_frame(topic, input_tokens=input_tokens, n=n)


async def test_usage_and_cost_come_from_the_root_cost_usage_frame() -> None:
    def frames(topic: str) -> list[Any]:
        return [
            cost_frame(topic, scope="self", input_tokens=1, output_tokens=1, total_usd="0.5", n=1),
            cost_frame(topic, input_tokens=30, output_tokens=12, total_usd="0.003", n=2),
            result_frame(topic),
            terminated_frame(topic),
        ]

    ca = chat_app(frames)
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"].startswith("chatcmpl-")
    assert data["object"] == "chat.completion"
    assert data["model"] == MODEL
    choice = data["choices"][0]
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == "Paris"
    assert data["usage"] == {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}
    assert data["screamingface"]["cost_usd"] == "0.003"
    assert data["screamingface"]["trace_id"] == TRACE_ID


async def test_the_last_subtree_frame_is_the_root_frame() -> None:
    def frames(topic: str) -> list[Any]:
        return [
            _subtree(topic, input_tokens=5, n=1),
            _subtree(topic, input_tokens=30, n=2),
            result_frame(topic),
            terminated_frame(topic),
        ]

    ca = chat_app(frames)
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    assert resp.json()["usage"]["prompt_tokens"] == 30


async def test_abstained_result_is_200_empty_content_with_status() -> None:
    result = chat_result(
        status="abstained", content="", finish_reason="stop", abstain_reason="budget_refused"
    )
    ca = chat_app(answered(result))
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["choices"][0]["message"]["content"] == ""
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["screamingface"]["status"] == "abstained"
    assert data["screamingface"]["abstain_reason"] == "budget_refused"


@pytest.mark.parametrize(
    ("status", "code", "permanent", "http_status", "error_code", "retry"), TERMINAL_ROWS
)
async def test_each_row_of_the_terminal_table_gives_its_status_code_and_retry_header(
    status: Any,
    code: str,
    permanent: bool,
    http_status: int,
    error_code: str,
    retry: str,
) -> None:
    ca = chat_app(ended(status, code, permanent=permanent))
    resp = await post(ca.app, body())

    assert resp.status_code == http_status
    assert error(resp)["code"] == error_code
    assert error(resp)["type"] == _error_type(http_status)
    assert resp.headers["x-should-retry"] == retry
    assert "retry-after" not in resp.headers


@pytest.mark.parametrize(("name", "script", "http_status", "error_code"), SUCCESS_ROWS)
async def test_success_rows_of_the_terminal_table(
    name: str, script: Any, http_status: int, error_code: str
) -> None:
    ca = chat_app(script)
    ca.app.state.artifact_store.content = lambda artifact_id: None
    resp = await post(ca.app, body())

    assert resp.status_code == http_status, name
    assert error(resp)["code"] == error_code
    assert resp.headers["x-should-retry"] == "false"
    assert "retry-after" not in resp.headers


async def test_response_never_contains_the_topic() -> None:
    for script in (answered(), ended("failed", "fail_closed", permanent=True)):
        ca = chat_app(script)
        resp = await post(ca.app, body())
        topic = ca.runner.scheduled[0]["topic"]

        assert topic not in resp.text
        assert all(topic not in value for value in resp.headers.values())
        assert "x-url4-run" not in resp.headers


async def test_refused_result_maps_to_refusal_message_and_content_filter() -> None:
    result = chat_result(
        status="refused",
        content="",
        refusal="I cannot help with that",
        finish_reason="content_filter",
    )
    ca = chat_app(answered(result))
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    data = resp.json()
    message = data["choices"][0]["message"]
    assert message["content"] is None
    assert message["refusal"] == "I cannot help with that"
    assert data["choices"][0]["finish_reason"] == "content_filter"
    assert data["screamingface"]["status"] == "refused"


@pytest.mark.parametrize(
    ("code", "permanent", "retry"),
    [("oom_killed", False, "true"), ("memory_budget_exceeded", True, "false")],
)
async def test_worker_loss_or_memory_breach_is_503_run_failed(
    code: str, permanent: bool, retry: str
) -> None:
    ca = chat_app(ended("failed", code, permanent=permanent))
    resp = await post(ca.app, body())

    assert resp.status_code == 503
    assert error(resp)["code"] == "run_failed"
    assert resp.headers["x-should-retry"] == retry


async def test_timeout_and_permanent_failures_send_x_should_retry_false() -> None:
    ca = chat_app(ended("timed_out", "deadline_exceeded"))
    resp = await post(ca.app, body())
    assert resp.status_code == 504
    assert error(resp)["code"] == "timeout"
    assert resp.headers["x-should-retry"] == "false"

    ca = chat_app(None, chat_max_wait_s=0.2)
    resp = await post(ca.app, body())
    assert resp.status_code == 504
    assert error(resp)["code"] == "timeout"
    assert resp.headers["x-should-retry"] == "false"
    assert ca.runner.stopped == [ca.runner.scheduled[0]["topic"]]

    ca = chat_app(ended("failed", "fail_closed", permanent=True))
    resp = await post(ca.app, body())
    assert resp.status_code == 422
    assert resp.headers["x-should-retry"] == "false"

    ca = chat_app(lambda t: [result_frame(t, body="not a chat result"), terminated_frame(t)])
    resp = await post(ca.app, body())
    assert resp.status_code == 502
    assert resp.headers["x-should-retry"] == "false"


async def test_failure_code_and_message_come_from_sanitized_error() -> None:
    ca = chat_app(ended("failed", "provider_error_x", message="sk-live-123 secret provider text"))
    resp = await post(ca.app, body())
    assert resp.status_code == 502
    assert error(resp)["code"] == "internal_error"
    assert "sk-live" not in resp.text
    assert "secret provider text" not in resp.text

    ca = chat_app(ended("failed", "fail_closed", message="gate 1 failed closed", permanent=True))
    resp = await post(ca.app, body())
    assert error(resp)["message"] == "gate 1 failed closed"

    trace = "Traceback (most recent call last): /Users/x/secret.py"
    ca = chat_app(ended("failed", "fail_closed", message=trace, permanent=True))
    resp = await post(ca.app, body())
    assert "/Users/x/secret.py" not in resp.text
    assert isinstance(error(resp)["message"], str)
    assert error(resp)["message"]


async def test_unpriced_run_reports_cost_null_not_zero() -> None:
    def frames(topic: str) -> list[Any]:
        return [
            cost_frame(topic, pricing_version="unpriced", total_usd="0"),
            result_frame(topic),
            terminated_frame(topic),
        ]

    ca = chat_app(frames)
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["screamingface"]["cost_usd"] is None
    assert data["usage"] == {"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42}


async def test_fully_cached_turn_reports_zero_usage() -> None:
    def frames(topic: str) -> list[Any]:
        return [
            cost_frame(topic, input_tokens=0, output_tokens=0, total_usd="0"),
            result_frame(topic),
            terminated_frame(topic),
        ]

    ca = chat_app(frames)
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert data["screamingface"]["cost_usd"] == "0"


async def test_a_run_with_no_cost_usage_frame_answers_with_zero_usage_and_null_cost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ca = chat_app(answered(cost=False))
    caplog.set_level(logging.WARNING, logger=ANSWER_LOGGER)
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    data = resp.json()
    assert data["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    assert data["screamingface"]["cost_usd"] is None
    warnings = [r for r in caplog.records if r.name == ANSWER_LOGGER]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert TRACE_ID in warnings[0].getMessage()


async def test_final_step_is_reported_from_the_chat_result() -> None:
    final = FinalStep(
        binding="synthesis_1",
        model="prov/b",
        usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    )
    ca = chat_app(answered(chat_result(final_step=final)))
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    assert resp.json()["screamingface"]["final_step"] == {
        "binding": "synthesis_1",
        "model": "prov/b",
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    }


def _artifact_script(media_type: str | None = None) -> Any:
    """A succeeded run whose CHAT_RESULT is an artifact claim ticket."""

    def frames(topic: str) -> list[Any]:
        if media_type is None:
            head = result_frame(topic, artifact=ARTIFACT)
        else:
            head = result_frame(topic, artifact=ARTIFACT, media_type=media_type)
        return [cost_frame(topic), head, terminated_frame(topic)]

    return frames


async def test_a_result_in_a_local_artifact_file_answers_200(tmp_path: Path) -> None:
    """Contracts C9: the CHAT_RESULT read from a local file of the artifact store."""
    stored = tmp_path / "result"
    stored.write_bytes(encode_chat_result(chat_result(content="Lyon")))
    ca = chat_app(_artifact_script())
    asked: list[str] = []

    def content(artifact_id: str) -> LocalFile:
        asked.append(artifact_id)
        return LocalFile(path=stored)

    ca.app.state.artifact_store.content = content
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Lyon"
    assert asked == [ARTIFACT.id]


async def test_a_result_in_a_remote_artifact_stream_answers_200() -> None:
    """Contracts C9: the CHAT_RESULT read in chunks from a remote stream of the artifact store."""
    encoded = encode_chat_result(chat_result(content="Nice"))

    async def chunks() -> AsyncIterator[bytes]:
        yield encoded[:5]
        yield encoded[5:]

    ca = chat_app(_artifact_script())
    ca.app.state.artifact_store.content = lambda artifact_id: RemoteStream(
        stream=chunks(), size_bytes=len(encoded)
    )
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Nice"


async def test_an_artifact_result_with_a_wrong_media_type_is_502_result_invalid() -> None:
    ca = chat_app(_artifact_script(media_type="application/json"))
    read: list[str] = []
    ca.app.state.artifact_store.content = lambda artifact_id: read.append(artifact_id)
    resp = await post(ca.app, body())

    assert resp.status_code == 502
    assert error(resp)["code"] == "result_invalid"
    assert resp.headers["x-should-retry"] == "false"
    assert read == []

"""Tests of the result delivery of POST /v1/chat/completions (review round 2, RR-S6 to RR-S9).

RR-6 to RR-10 of the TDD table in docs/spec/2026-11-17-engine-openai-chat-endpoint/prd/
review-round-2.md: the size limit of a result, a store error that answers result_unavailable, the
keep-alive lines while a slow result is read, and a transient input outage that can be retried.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from _chat_app import (
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
from _chat_stream import data_payloads, stream_body

from screamingface_engine.artifacts.ports import LocalFile, RemoteStream
from screamingface_engine.artifacts.s3 import S3StorageError
from screamingface_engine.chat.result import encode_chat_result
from screamingface_engine.rest import chat_answer
from url4.streaming.protocol.signals import ResultArtifact

pytestmark = pytest.mark.asyncio

ARTIFACT = ResultArtifact(id="ab" * 32, size_bytes=10, sha256="ab" * 32)


def _artifact_script() -> Any:
    """A succeeded run whose CHAT_RESULT is an artifact claim ticket."""

    def frames(topic: str) -> list[Any]:
        return [cost_frame(topic), result_frame(topic, artifact=ARTIFACT), terminated_frame(topic)]

    return frames


def _error_object(payloads: list[dict[str, Any] | str]) -> dict[str, Any]:
    """The error object of the last event of a stream."""
    last = payloads[-1]
    assert isinstance(last, dict)
    error_obj = last["error"]
    assert isinstance(error_obj, dict)
    return error_obj


async def test_local_result_file_above_the_limit_is_refused_before_the_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root reads a file whatever its mode")
    path = tmp_path / "result"
    path.write_bytes(b"x" * 65)
    os.chmod(path, 0)
    try:
        monkeypatch.setattr(chat_answer, "CHAT_RESULT_MAX_BYTES", 64)
        ca = chat_app(_artifact_script())
        ca.app.state.artifact_store.content = lambda artifact_id: LocalFile(path=path)
        resp = await post(ca.app, body())

        assert resp.status_code == 502
        assert error(resp)["code"] == "result_too_large"
        assert resp.headers["x-should-retry"] == "false"
        assert "retry-after" not in resp.headers
    finally:
        os.chmod(path, 0o600)

    encoded = encode_chat_result(chat_result(content="Lyon"))
    stored = tmp_path / "lyon"
    stored.write_bytes(encoded)
    monkeypatch.setattr(chat_answer, "CHAT_RESULT_MAX_BYTES", len(encoded))
    ca = chat_app(_artifact_script())
    ca.app.state.artifact_store.content = lambda artifact_id: LocalFile(path=stored)
    resp = await post(ca.app, body())

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Lyon"


async def test_remote_result_stream_stops_at_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_answer, "CHAT_RESULT_MAX_BYTES", 64)
    pulled: list[bytes] = []
    closed = [False]

    async def chunks() -> AsyncIterator[bytes]:
        try:
            for _ in range(5):
                pulled.append(b"x" * 40)
                yield b"x" * 40
        finally:
            closed[0] = True

    ca = chat_app(_artifact_script())
    ca.app.state.artifact_store.content = lambda artifact_id: RemoteStream(
        stream=chunks(), size_bytes=200
    )
    resp = await post(ca.app, body())

    assert resp.status_code == 502
    assert error(resp)["code"] == "result_too_large"
    assert len(pulled) == 2
    assert closed == [True]


def _open_os_error(artifact_id: str) -> None:
    raise OSError("x")


def _open_s3_error(artifact_id: str) -> None:
    raise S3StorageError("x")


async def _broken_stream() -> AsyncIterator[bytes]:
    yield b"{"
    raise S3StorageError("x")


def _stream_s3_error(artifact_id: str) -> RemoteStream:
    return RemoteStream(stream=_broken_stream(), size_bytes=10)


@pytest.mark.parametrize(
    "content",
    [_open_os_error, _open_s3_error, _stream_s3_error],
    ids=["open-oserror", "open-s3-error", "stream-s3-error"],
)
async def test_store_error_at_open_and_in_stream_is_result_unavailable(
    content: Any,
) -> None:
    ca = chat_app(_artifact_script())
    ca.app.state.artifact_store.content = content
    resp = await post(ca.app, body())

    assert resp.status_code == 502
    assert error(resp)["code"] == "result_unavailable"
    assert resp.headers["x-should-retry"] == "false"

    ca = chat_app(_artifact_script())
    ca.app.state.artifact_store.content = content
    resp = await post(ca.app, stream_body())

    payloads = data_payloads(resp.content)
    error_obj = _error_object(payloads)
    assert error_obj["code"] == "result_unavailable"
    assert error_obj["should_retry"] is False
    assert "[DONE]" not in payloads


async def test_keep_alive_lines_continue_during_a_slow_result_read() -> None:
    encoded = encode_chat_result(chat_result(content="Lyon"))

    async def slow() -> AsyncIterator[bytes]:
        await asyncio.sleep(0.3)
        yield encoded

    ca = chat_app(_artifact_script(), chat_keepalive_s=0.02)
    ca.app.state.artifact_store.content = lambda artifact_id: RemoteStream(
        stream=slow(), size_bytes=len(encoded)
    )
    resp = await post(ca.app, stream_body())

    payloads = data_payloads(resp.content)
    assert payloads.count("keep-alive") >= 3
    assert payloads[-1] == "[DONE]"
    chunks = [p for p in payloads if isinstance(p, dict)]
    assert any(chunk["choices"][0]["delta"].get("content") == "Lyon" for chunk in chunks)


@pytest.mark.parametrize(
    ("permanent", "http_status", "retry", "retry_after"),
    [(False, 503, "true", "5"), (True, 500, "false", None)],
)
async def test_transient_input_outage_is_503_with_retry(
    permanent: bool, http_status: int, retry: str, retry_after: str | None
) -> None:
    ca = chat_app(ended("failed", "chat_input_unavailable", permanent=permanent))
    resp = await post(ca.app, body())

    assert resp.status_code == http_status
    assert error(resp)["code"] == "chat_input_unavailable"
    assert resp.headers["x-should-retry"] == retry
    assert resp.headers.get("retry-after") == retry_after


async def test_transient_input_outage_stream_error_event_can_be_retried() -> None:
    ca = chat_app(ended("failed", "chat_input_unavailable", permanent=False))
    resp = await post(ca.app, stream_body())

    error_obj = _error_object(data_payloads(resp.content))
    assert error_obj["code"] == "chat_input_unavailable"
    assert error_obj["should_retry"] is True
    assert error_obj["retry_after"] == 5

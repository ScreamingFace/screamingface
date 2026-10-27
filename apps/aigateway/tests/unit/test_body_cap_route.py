"""The body cap as wired into the real app and its setting (OME-1542).

# FEATURE: image and file input across the gateway (OME-1529).
# INVARIANT: the cap is app-wide, configurable through `AIGW_MAX_REQUEST_BYTES`, 8 MiB by default
# (MMMU's largest Case is 3.78 MB inline — Khoa, OME-1542), and refuses inside the call-id layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aigateway.config import Settings


def test_the_default_limit_is_eight_mebibytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIGW_MAX_REQUEST_BYTES", raising=False)
    assert Settings().max_request_bytes == 8 * 1024 * 1024


def test_the_limit_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_MAX_REQUEST_BYTES", "1234")
    assert Settings().max_request_bytes == 1234


@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_non_positive_limit_is_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("AIGW_MAX_REQUEST_BYTES", value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.fixture
def small_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIGW_MAX_REQUEST_BYTES", "2048")


def test_an_oversized_chat_body_gets_413_with_the_call_id(small_cap, authenticated_client) -> None:
    payload = (
        b'{"model":"anthropic/claude-haiku-4-5","messages":[{"role":"user","content":"'
        + (b"x" * 4096)
        + b'"}]}'
    )

    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=payload,
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 413, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "request_too_large"
    assert detail["limit_bytes"] == 2048
    assert "2048 bytes" in detail["message"]
    # WHY: the cap sits inside CallIdMiddleware, so even a refusal is correlatable.
    assert resp.headers.get("x-aigw-trace-id")


def test_a_chunked_oversized_body_gets_413(small_cap, authenticated_client) -> None:
    def chunks():
        for _ in range(8):
            yield b"y" * 512

    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=chunks(),
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 413, resp.text
    assert resp.json()["detail"]["code"] == "request_too_large"


def test_a_body_under_the_cap_reaches_the_route(small_cap, authenticated_client) -> None:
    resp = authenticated_client.post(
        "/v1/chat/completions",
        content=b"not json",
        headers={"content-type": "application/json"},
    )

    # the route's own refusal, not the cap's
    assert resp.status_code == 400, resp.text

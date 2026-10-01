"""Every terminal chat-dispatch failure emits exactly one attributable record (OME-968).

Empirically observed before this: a litellm `APIConnectionError` mapped to `provider_unavailable`
returned a 5xx and emitted ZERO WARNING+ records — the mapped branches never reached a log call —
and a failed stream logged only class names at HTTP 200, unattributable under concurrency.

# STORY: as an operator alerting on WARNING+, every failing gateway call shows up as one line I
# can grep by `gateway_call_id`, telling me the provider, the failure class and the status.
# INVARIANT: class-name-only on the dispatch path — provider text, prompts and tracebacks never
# reach the record (`routes/chat_dispatch.py`).

Driven through the real app stack so the call id asserted is the one the record factory actually
stamped inside `CallIdMiddleware`'s scope, not one a test handed in.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from functools import partial
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from litellm.exceptions import APIConnectionError

from aigateway.call_context import record_call_id, record_trace_id
from aigateway.core.oauth.store import OAuthConnectionStore, credential_key_for
from aigateway.plugins.anthropic_provider.auth import credential_service_for

_CHAT = "/v1/chat/completions"
_DISPATCH = "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion"
_STREAM = (
    "aigateway.plugins.anthropic_provider.plugin.AnthropicProviderPlugin.chat_completion_stream"
)
CALL_ID = "call_" + "9" * 32
PROVIDER_TEXT = "upstream body: sk-ant-SECRET-968 and the user's prompt"


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def failures(self) -> list[logging.LogRecord]:
        return [r for r in self.records if r.levelno >= logging.WARNING]


@pytest.fixture
def captured() -> Iterator[_Capture]:
    # WHY on the `aigateway` logger: `logs.configure` disables propagation, so caplog's root
    # handler never sees these records and a `not in caplog.text` assertion passes vacuously.
    handler = _Capture()
    logger = logging.getLogger("aigateway")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


async def _active_connection(account_id: str):
    store = OAuthConnectionStore()
    connection = await store.create_pending(
        account_id=account_id, provider="anthropic", label="default", connection_id=uuid4()
    )
    return await store.complete(connection, label="default", identity=None)


@pytest.fixture
def chat_client(authenticated_client: TestClient, credential_blobs) -> Iterator[TestClient]:
    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    portal = authenticated_client.portal
    assert portal is not None
    connection = portal.call(partial(_active_connection, account_id))
    credential_blobs.write(
        credential_service_for(credential_key_for(account_id, connection.id)),
        "default",
        json.dumps(
            {
                "access_token": "tok",
                "refresh_token": "rt",
                "expires_at_ms": int(time.time() * 1000) + 3_600_000,
                "token_type": "Bearer",
            }
        ),
    )
    with patch("aigateway.middleware.call_id.new_gateway_call_id", return_value=CALL_ID):
        yield authenticated_client


def _body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "anthropic/claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hi"}],
        **extra,
    }


def _raising(exc: Exception):
    async def dispatch(_self, _body):
        raise exc

    return dispatch


def _only_failure(captured: _Capture) -> logging.LogRecord:
    failures = captured.failures()
    assert len(failures) == 1, [r.getMessage() for r in failures]
    record = failures[0]
    # INVARIANT: class-name-only — no provider text, no traceback.
    assert PROVIDER_TEXT not in record.getMessage()
    assert record.exc_info is None
    assert record.exc_text is None
    return record


def test_a_mapped_connection_error_logs_one_error_record_with_the_call_id(
    chat_client, captured
) -> None:
    exc = APIConnectionError(message=PROVIDER_TEXT, llm_provider="anthropic", model="m")
    with patch(_DISPATCH, _raising(exc)):
        response = chat_client.post(_CHAT, json=_body())

    assert response.status_code >= 500
    assert response.json()["detail"]["code"] == "provider_unavailable"
    record = _only_failure(captured)
    assert record.levelno == logging.ERROR
    assert record_call_id(record) == CALL_ID
    message = record.getMessage()
    assert "provider=anthropic" in message
    assert "classification=provider_unavailable" in message
    assert f"status={response.status_code}" in message
    assert "type=APIConnectionError" in message


def test_a_plugin_http_exception_4xx_logs_one_warning(chat_client, captured) -> None:
    # WHY 403 and not 429: a 429 is retried, and each retry legitimately logs its own WARNING —
    # this test is about the TERMINAL record, so it uses a status the retry loop never touches.
    exc = HTTPException(status_code=403, detail={"code": "forbidden", "message": "no"})
    with patch(_DISPATCH, _raising(exc)):
        response = chat_client.post(_CHAT, json=_body())

    assert response.status_code == 403
    record = _only_failure(captured)
    assert record.levelno == logging.WARNING
    assert record_call_id(record) == CALL_ID
    assert "classification=forbidden" in record.getMessage()
    assert "status=403" in record.getMessage()


def test_a_string_detail_is_classified_without_echoing_it(chat_client, captured) -> None:
    exc = HTTPException(status_code=400, detail=PROVIDER_TEXT)
    with patch(_DISPATCH, _raising(exc)):
        chat_client.post(_CHAT, json=_body())

    record = _only_failure(captured)
    assert "classification=unclassified" in record.getMessage()


def test_an_unclassified_exception_still_yields_exactly_one_record(chat_client, captured) -> None:
    with patch(_DISPATCH, _raising(RuntimeError(PROVIDER_TEXT))):
        response = chat_client.post(_CHAT, json=_body())

    assert response.status_code == 502
    record = _only_failure(captured)
    assert record_call_id(record) == CALL_ID
    message = record.getMessage()
    assert "type=RuntimeError" in message
    assert "classification=provider_error" in message
    assert "status=502" in message
    assert "provider=anthropic" in message


def test_a_response_conversion_failure_names_provider_and_status(chat_client, captured) -> None:
    class _Unrenderable:
        def model_dump(self) -> Any:
            raise ValueError(PROVIDER_TEXT)

    async def dispatch(_self, _body):
        return _Unrenderable()

    with patch(_DISPATCH, dispatch):
        response = chat_client.post(_CHAT, json=_body())

    assert response.status_code == 502
    record = _only_failure(captured)
    assert record_call_id(record) == CALL_ID
    message = record.getMessage()
    assert "provider=anthropic" in message
    assert "classification=provider_error" in message
    assert "status=502" in message


def test_a_failed_stream_logs_one_attributable_record(chat_client, captured) -> None:
    async def stream(_self, _body):
        yield {"choices": [{"delta": {"content": "ok"}}]}
        raise RuntimeError(PROVIDER_TEXT)

    with patch(_STREAM, stream):
        response = chat_client.post(_CHAT, json=_body(stream=True))

    # The status was committed before the failure; the record says so honestly.
    assert response.status_code == 200
    assert PROVIDER_TEXT not in response.text
    record = _only_failure(captured)
    assert record_call_id(record) == CALL_ID
    assert record_trace_id(record) == response.headers["x-aigw-trace-id"]
    message = record.getMessage()
    assert "stream failed" in message
    assert "provider=anthropic" in message
    assert "classification=provider_error" in message
    assert "status=200" in message

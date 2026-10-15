"""One terminal record per dispatch failure, even when the failure handler raises (OME-1461).

OME-968 promised exactly one record per failing call. The secondary path broke it: when
`_dispatch_failure_response` itself raised (e.g. marking the credential failed), the request
logged "dispatch failure handling error" AND "dispatch failed" — two ERROR records.

# STORY: as an operator alerting on WARNING+, one failing call is one line, and that line tells me
# when the gateway's own failure handling broke (`outcome=handler_error`) without a second record.
# INVARIANT: class-name-only — the handler's exception text never reaches the record.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from aigateway.call_context import record_call_id
from aigateway.routes.chat_dispatch import log_dispatch_failure

from .test_dispatch_failure_records import (  # noqa: F401 — fixtures shared with OME-968's suite
    _CHAT,
    _DISPATCH,
    CALL_ID,
    PROVIDER_TEXT,
    _body,
    _only_failure,
    _raising,
    captured,
    chat_client,
)

_HANDLER = "aigateway.routes.chat_dispatch._dispatch_failure_response"


async def _handler_raises(*_args, **_kwargs):
    raise RuntimeError(PROVIDER_TEXT)


def test_a_raising_failure_handler_still_yields_exactly_one_record(
    chat_client,  # noqa: F811
    captured,  # noqa: F811
) -> None:
    exc = HTTPException(status_code=401, detail={"code": "auth_required", "message": "no"})
    with patch(_DISPATCH, _raising(exc)), patch(_HANDLER, _handler_raises):
        response = chat_client.post(_CHAT, json=_body())

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "provider_error"
    record = _only_failure(captured)
    assert record.levelno == logging.ERROR
    assert record_call_id(record) == CALL_ID
    message = record.getMessage()
    assert message.startswith("dispatch failed ")
    assert "outcome=handler_error" in message
    assert "handler_type=RuntimeError" in message
    assert "status=502" in message
    assert "classification=provider_error" in message
    assert "provider=anthropic" in message


def test_a_normally_handled_failure_is_marked_mapped(
    chat_client,  # noqa: F811
    captured,  # noqa: F811
) -> None:
    exc = HTTPException(status_code=403, detail={"code": "forbidden", "message": "no"})
    with patch(_DISPATCH, _raising(exc)):
        chat_client.post(_CHAT, json=_body())

    message = _only_failure(captured).getMessage()
    assert "outcome=mapped" in message
    assert "handler_type" not in message


def test_a_client_disconnect_is_recorded_below_warning(
    chat_client,  # noqa: F811
    captured,  # noqa: F811
) -> None:
    # WHY end-to-end: #1153 (OME-1162) raises this exact 499 from the dispatch path; the
    # client is gone, so the record must not count as a failure an operator alerts on.
    exc = HTTPException(
        status_code=499,
        detail={"code": "client_disconnected", "message": "The client disconnected."},
    )
    with patch(_DISPATCH, _raising(exc)):
        chat_client.post(_CHAT, json=_body())

    assert captured.failures() == []
    infos = [r for r in captured.records if r.getMessage().startswith("dispatch failed ")]
    assert len(infos) == 1
    assert infos[0].levelno == logging.INFO
    assert "status=499" in infos[0].getMessage()
    assert "classification=client_disconnected" in infos[0].getMessage()


@pytest.mark.parametrize(
    ("status", "level"),
    [
        (499, logging.INFO),  # the client left — not an operator-actionable failure
        (429, logging.WARNING),  # back-pressure, not breakage
        (503, logging.ERROR),  # unknown-origin 503 stays alertable
        (400, logging.WARNING),  # unchanged: the caller's own bad request
        (403, logging.WARNING),
        (500, logging.ERROR),  # unchanged: gateway/provider breakage
        (502, logging.ERROR),
        (504, logging.ERROR),
        (529, logging.ERROR),  # out of scope for OME-1461's policy — stays ERROR
    ],
)
def test_the_terminal_record_level_follows_the_ome_1461_policy(
    status: int,
    level: int,
    captured,  # noqa: F811
) -> None:
    log_dispatch_failure(
        HTTPException(status_code=status, detail={"code": "x", "message": "y"}),
        provider="anthropic",
        error_type=None,
        account_id="acct",
        profile_name="default",
    )

    records = [r for r in captured.records if r.getMessage().startswith("dispatch failed ")]
    assert len(records) == 1
    assert records[0].levelno == level
    assert f"status={status}" in records[0].getMessage()


@pytest.mark.parametrize(
    ("detail", "level"),
    [
        # The gateway's own back-pressure (#1153 / OME-1162 admission shedding): expected volume
        # under overload, so WARNING.
        ({"code": "provider_queue_timeout", "message": "m"}, logging.WARNING),
        # An upstream provider 503 that survived the retry loop: an outage, so it stays alertable.
        ({"code": "provider_unavailable", "message": "m"}, logging.ERROR),
        # Unknown origin fails loud: only a named gateway back-pressure code earns WARNING.
        ("free text from somewhere", logging.ERROR),
    ],
)
def test_a_503_is_levelled_by_its_origin_not_its_status(
    detail: object,
    level: int,
    captured,  # noqa: F811
) -> None:
    log_dispatch_failure(
        HTTPException(status_code=503, detail=detail),
        provider="anthropic",
        error_type=None,
        account_id="acct",
        profile_name="default",
    )

    records = [r for r in captured.records if r.getMessage().startswith("dispatch failed ")]
    assert len(records) == 1
    assert records[0].levelno == level

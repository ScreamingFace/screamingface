"""Boundary tests of review round 2 (PR #1937): the body read deadline, n >= 1 and the
screamingface.ignored_parameters signal.

RR-S10 to RR-S12 of prd/review-round-2.md (tests RR-11 to RR-16). The App is the real create_app
with a scripted runner and an in-memory chat-input store.
"""

import asyncio
import json
import logging
from typing import Any

import pytest
from _chat_app import (
    answered,
    asgi_call,
    asgi_scope,
    body,
    body_then,
    chat_app,
    error,
    post,
    sent_body,
    sent_status,
    stored_bytes,
)
from _chat_stream import data_payloads, stream_body

from screamingface_engine.rest import chat_body

pytestmark = pytest.mark.asyncio


def _info(resp_json: dict[str, Any]) -> dict[str, Any]:
    return resp_json["screamingface"]


def _stream_infos(raw: bytes) -> list[dict[str, Any]]:
    payloads = data_payloads(raw)
    return [p["screamingface"] for p in payloads if isinstance(p, dict) and "screamingface" in p]


async def test_small_body_that_stalls_gets_408(monkeypatch: pytest.MonkeyPatch) -> None:
    """RR-11 (RR-S10): a small body that stops arriving gets 408 at the total read limit."""
    monkeypatch.setattr(chat_body, "BODY_READ_TIMEOUT_S", 0.1)
    ca = chat_app(answered())
    raw = json.dumps(body()).encode()
    gone = asyncio.Event()
    sent = await asyncio.wait_for(
        asgi_call(ca.app, asgi_scope(len(raw)), body_then(raw[:10], gone, more_body=True)), 5.0
    )
    assert sent_status(sent) == 408
    assert sent_body(sent)["error"]["code"] == "request_timeout"
    assert ca.runner.scheduled == []


@pytest.mark.parametrize(
    ("n", "status", "code"),
    [
        (0, 400, "invalid_request"),
        (-1, 400, "invalid_request"),
        (1, 200, None),
        (2, 400, "unsupported_parameter"),
    ],
)
async def test_n_below_one_is_invalid(n: int, status: int, code: str | None) -> None:
    """RR-12 (RR-S11): n below 1 is 400 invalid_request; n of 1 passes; n above 1 is refused."""
    ca = chat_app(answered())
    resp = await post(ca.app, body(n=n))
    assert resp.status_code == status
    if code is None:
        assert ca.runner.scheduled != []
        return
    assert error(resp)["code"] == code
    assert error(resp)["param"] == "n"
    assert ca.runner.scheduled == []


async def test_reply_lists_ignored_fields_sorted_and_absent_when_none() -> None:
    """RR-13 (RR-S12): the reply names the ignored fields, sorted; the key is absent when none."""
    ca = chat_app(answered())
    resp = await post(ca.app, body(temperature=0.2, user="u", max_tokens=5, stream_options=None))
    assert resp.status_code == 200
    assert _info(resp.json())["ignored_parameters"] == ["max_tokens", "temperature", "user"]

    plain = chat_app(answered())
    resp = await post(plain.app, body())
    assert resp.status_code == 200
    assert "ignored_parameters" not in _info(resp.json())


@pytest.mark.parametrize("include_usage", [True, False])
async def test_stream_info_chunk_lists_ignored_fields(include_usage: bool) -> None:
    """RR-14 (RR-S12): the chunk that holds the screamingface object names the ignored fields."""
    extra: dict[str, Any] = {"stream_options": {"include_usage": True}} if include_usage else {}
    ca = chat_app(answered())
    resp = await post(ca.app, stream_body(temperature=0.2, **extra))
    infos = _stream_infos(resp.content)
    assert len(infos) == 1
    assert infos[0]["ignored_parameters"] == ["temperature"]

    plain = chat_app(answered())
    resp = await post(plain.app, stream_body(**extra))
    infos = _stream_infos(resp.content)
    assert len(infos) == 1
    assert "ignored_parameters" not in infos[0]


async def test_null_values_long_names_and_the_cap() -> None:
    """RR-15 (RR-S12): null values and names over 64 characters are left out; at most 32 names."""
    names = [f"x{i:02d}" for i in range(40)]
    extra: dict[str, Any] = {"temperature": None, "k" * 64: 1, "k" * 65: 1}
    extra.update({name: 1 for name in names})
    ca = chat_app(answered())
    resp = await post(ca.app, body(**extra))
    assert resp.status_code == 200
    listed = _info(resp.json())["ignored_parameters"]
    assert listed == sorted(["k" * 64] + names)[:32]
    assert "temperature" not in listed
    assert "k" * 65 not in listed
    assert len(listed) == 32


async def test_no_log_line_holds_an_ignored_name(caplog: pytest.LogCaptureFixture) -> None:
    """RR-16 (RR-S12 INVARIANT): no log line, schedule or stored record holds an ignored name."""
    caplog.set_level(logging.DEBUG)
    name = "zq_private_field_7c1e"
    extra: dict[str, Any] = {name: "v"}

    plain = chat_app(answered())
    resp = await post(plain.app, body(**extra))
    assert resp.status_code == 200

    streamed = chat_app(answered())
    stream_resp = await post(streamed.app, stream_body(**extra))
    assert stream_resp.status_code == 200

    assert name not in caplog.text
    assert all(name not in record.getMessage() for record in caplog.records)
    assert name not in repr(plain.runner.scheduled)
    assert name not in repr(streamed.runner.scheduled)
    assert name.encode() not in stored_bytes(plain.runner.inputs[0])
    assert name in _info(resp.json())["ignored_parameters"]
    assert name in _stream_infos(stream_resp.content)[0]["ignored_parameters"]

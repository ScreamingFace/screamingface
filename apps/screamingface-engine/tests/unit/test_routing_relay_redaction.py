"""A relayed classifier or branch failure speaks only in the Engine's words (OME-1822 review).

FEATURE: BYOM routing pilot (spec 3.5). A classifier or branch call has been sent by the time its
failure comes back, and the Gateway, or a proxy in front of it, wrote that failure's body. The
routed answer relays the failure's status and permanence, never its text: the message is one
fixed Engine sentence, and a Gateway refusal's code is always `aigateway_http_<status>`. Only the
Engine's own code for a sent call (`aigateway_bad_response`, `model_token_cap`) is kept.

STORY: as the owner of a BYOM endpoint, a failure of my private model never shows a caller, or
the run's logs, my key, my origin, a path or my private model ID.

INVARIANT: the rewrite happens in the routing relay, before the error becomes the run's terminal
error, so the public envelope, the run's events and the runner's log read the same fixed text.

WHY no log claim for a branch code: the connector's own `model call failed ... code=` line reads
the lifted `detail.code` inside the branch's chat call, before the relay. Closing that line is
the separate connector unit (`gateway-code-provenance`, spec 9); until it lands this module
asserts the log for every message marker and for the classifier's codes only.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from routing_support import (
    CHAT_PATH,
    CLASSIFICATIONS_PATH,
    CLASSIFIER,
    MODELS,
    Gateway,
    call,
    context,
    engine,
    query,
    run_direct,
    write_world,
)

from screamingface_engine.world.gateway_endpoints import ROUTED_CALL_FAILED_MESSAGE

pytestmark = pytest.mark.no_default_scope

_SITES = {
    "classifier": ((CLASSIFICATIONS_PATH, CLASSIFIER), 1, 0),
    "branch": ((CHAT_PATH, MODELS["code"]), 1, 1),
}
"""Where the failure is answered, and the classifier and chat POSTs sent by then."""

_PRIVATE_MODEL = "byom_" + "f" * 32 + "/secret_model"

_MESSAGES = {
    "bearer": "Authorization: Bearer sk-secret123456",
    "api_key": "upstream rejected api_key=sk-live-abcdef123456",
    "absolute_path": "weights missing at /private/origin/models/weights.bin",
    "relative_path": "config missing at ../relative/secret_dir/config.toml",
    "origin": "upstream https://byom-origin.internal.test:8443 refused the call",
    "private_model": f"model {_PRIVATE_MODEL} is overloaded",
    # WHY a plain phrase too: the screen in `error_text.public_message` would pass it, and a
    # private model ID can read exactly like one; only a fixed message withholds it.
    "plain_private_text": "byom-secret-deployment-alpha is overloaded",
}
"""Upstream messages, each a marker that must reach neither the caller nor the log."""

_CODES = {
    "path_code": "/private/origin",
    "key_code": "sk-secret123456",
    "model_code": _PRIVATE_MODEL,
    "header_code": "Authorization: Bearer sk-secret123456",
    "gateway_code": "provider_error",
}
"""Upstream codes outside the relay vocabulary, the last one a real Gateway code."""

_MARKERS = (
    "sk-secret123456",
    "sk-live-abcdef123456",
    "/private/origin",
    "../relative/secret_dir",
    "byom-origin.internal.test",
    _PRIVATE_MODEL,
    "byom-secret-deployment-alpha",
)


def _body(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": {"code": code, "message": message}})


def _assert_no_marker(text: str) -> None:
    leaked = [marker for marker in _MARKERS if marker in text]
    assert not leaked, leaked


# --- the run's own error: what becomes the terminal frame --------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("name", _MESSAGES)
async def test_a_relayed_message_is_the_fixed_engine_message(site: str, name: str) -> None:
    target, classifications, chats = _SITES[site]
    gateway = Gateway(top="code", script={target: _body(502, "provider_error", _MESSAGES[name])})

    outcome = await run_direct(gateway)

    assert outcome.code() == "aigateway_http_502"
    assert str(outcome.error) == ROUTED_CALL_FAILED_MESSAGE
    _assert_no_marker(repr(outcome.error))
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == classifications
    assert len(gateway.posts(CHAT_PATH)) == chats


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("name", _CODES)
async def test_a_code_outside_the_relay_vocabulary_takes_the_status_code(
    site: str, name: str
) -> None:
    target, _, _ = _SITES[site]
    gateway = Gateway(top="code", script={target: _body(502, _CODES[name], "after-send failure")})

    outcome = await run_direct(gateway)

    assert outcome.code() == "aigateway_http_502"
    assert str(outcome.error) == ROUTED_CALL_FAILED_MESSAGE


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize(("status", "permanent"), [(400, True), (429, False), (503, False)])
async def test_a_relayed_failure_keeps_its_status_and_permanence(
    site: str, status: int, permanent: bool
) -> None:
    target, _, _ = _SITES[site]
    gateway = Gateway(top="code", script={target: _body(status, "provider_error", "x")})

    outcome = await run_direct(gateway)

    assert (outcome.code(), outcome.permanent()) == (f"aigateway_http_{status}", permanent)


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
@pytest.mark.parametrize("code", ["model_token_cap", "aigateway_bad_response", "provider_refusal"])
async def test_a_gateway_body_never_speaks_an_engine_diagnosis(site: str, code: str) -> None:
    """WHY: the Engine raises these after reading an answer; a refusal body cannot carry one."""
    target, _, _ = _SITES[site]
    gateway = Gateway(top="code", script={target: _body(400, code, _MESSAGES["bearer"])})

    outcome = await run_direct(gateway)

    assert outcome.code() == "aigateway_http_400"
    assert str(outcome.error) == ROUTED_CALL_FAILED_MESSAGE


@pytest.mark.asyncio
async def test_the_engines_own_token_cap_is_kept_with_the_fixed_message() -> None:
    """The branch's answer ran out of tokens: the Engine's diagnosis, not the Gateway's."""
    capped = {
        "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 2048},
    }
    gateway = Gateway(top="code", script={(CHAT_PATH, MODELS["code"]): lambda _: capped})

    outcome = await run_direct(gateway)

    assert (outcome.code(), str(outcome.error)) == ("model_token_cap", ROUTED_CALL_FAILED_MESSAGE)


@pytest.mark.asyncio
@pytest.mark.parametrize("site", _SITES)
async def test_an_engine_failure_of_the_call_keeps_its_code_with_the_fixed_message(
    site: str,
) -> None:
    """WHY: the Engine's own failure of a sent call can quote the answer that caused it."""
    target, _, _ = _SITES[site]
    page = httpx.Response(200, text=f"<html>{_MESSAGES['origin']}</html>")
    gateway = Gateway(top="code", script={target: page})

    outcome = await run_direct(gateway)

    assert (outcome.code(), str(outcome.error)) == (
        "aigateway_bad_response",
        ROUTED_CALL_FAILED_MESSAGE,
    )


def test_the_fixed_message_names_no_route() -> None:
    assert "/" not in ROUTED_CALL_FAILED_MESSAGE
    assert "byom" not in ROUTED_CALL_FAILED_MESSAGE


# --- through the App: the envelope the caller reads and the log the operator reads -------------


_APP_CASES = [(site, "message", name) for site in _SITES for name in _MESSAGES] + [
    (site, "code", name) for site in _SITES for name in _CODES
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("site", "kind", "name"), _APP_CASES)
async def test_the_app_answer_and_log_carry_no_upstream_marker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, site: str, kind: str, name: str
) -> None:
    target, classifications, chats = _SITES[site]
    code, message = (
        ("provider_error", _MESSAGES[name])
        if kind == "message"
        else (_CODES[name], _MESSAGES["bearer"])
    )
    gateway = Gateway(top="code", script={target: _body(502, code, message)})
    caplog.set_level(logging.DEBUG)

    async with engine(gateway, write_world(tmp_path)) as (app, _):
        resp = await call(app, query(context()))

    assert resp.status_code == 502
    assert resp.json()["error"] == {
        "code": "aigateway_http_502",
        "message": ROUTED_CALL_FAILED_MESSAGE,
    }
    _assert_no_marker(resp.text)
    if (site, kind) != ("branch", "code"):
        # WHY: see the module docstring; the connector unit closes the branch code's log line.
        _assert_no_marker(caplog.text)
    assert len(gateway.posts(CLASSIFICATIONS_PATH)) == classifications
    assert len(gateway.posts(CHAT_PATH)) == chats

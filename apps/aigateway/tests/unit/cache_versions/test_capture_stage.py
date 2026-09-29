"""The kill switch and the inbound-trace rule of `begin_capture` (OME-1307, GW-capture).

FEATURE: OME-1307 (E14) - `AIGW_CACHE_VERSIONS_ENABLED` decides whether capture exists at all.
INVARIANT (OD-1): with the switch off, a valid ``traceparent`` still yields no capture context, so
no prompt is persisted.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request

from aigateway.plugins.anthropic_provider.plugin import PLUGIN as ANTHROPIC
from aigateway.routes.chat_capture_stage import begin_capture
from tests.unit.cache_versions.conftest import traceparent

_TRACE = "d4" * 16
_BODY: dict[str, Any] = {
    "model": "anthropic/claude-haiku-4-5",
    "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
}


def _request(*, enabled: bool, header: str | None) -> Request:
    headers = {} if header is None else {"traceparent": header}
    app = SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(cache_versions_enabled=enabled))
    )
    return cast(Request, SimpleNamespace(app=app, headers=headers))


def test_begin_capture_returns_none_when_the_switch_is_off() -> None:
    request = _request(enabled=False, header=traceparent(_TRACE))

    assert begin_capture(request, account_id="acct", body=_BODY, plugin=ANTHROPIC) is None


def test_begin_capture_returns_a_keyed_context_when_the_switch_is_on() -> None:
    # Positive control for the case above: only the switch differs.
    request = _request(enabled=True, header=traceparent(_TRACE))

    ctx = begin_capture(request, account_id="acct", body=_BODY, plugin=ANTHROPIC)

    assert ctx is not None
    assert ctx.trace_id == _TRACE
    assert ctx.account_id == "acct"
    assert ctx.key is not None


@pytest.mark.parametrize("header", [None, "garbage"])
def test_begin_capture_returns_none_without_a_valid_inbound_traceparent(header: str | None) -> None:
    request = _request(enabled=True, header=header)

    assert begin_capture(request, account_id="acct", body=_BODY, plugin=ANTHROPIC) is None

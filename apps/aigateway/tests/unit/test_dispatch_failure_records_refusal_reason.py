"""The terminal record of a provider 402/403 says why the provider refused (OME-1989).

On 2026-11-19 one account drew 7,056 provider 403s. The record said `status=403 type=APIError`
and nothing else, so on-call could not tell a disabled key from a model the key may not use.

# STORY: as an on-call engineer, the one line a refused call already logs tells me the provider's
# own reason, so I know whether to top up a key, re-enable it, or tell the user the model is off.
# INVARIANT: the reason is the screened text the caller's body already carries, never the raw
# provider text, and never the key.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from aigateway.core.provider_error_text import relayed_detail, sanitize_upstream_text
from aigateway.routes.chat_dispatch import log_dispatch_failure

from .test_dispatch_failure_records import (  # noqa: F401 — fixtures shared with OME-968's suite
    _only_failure,
    captured,
)

_KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"  # noqa: S105 - not a real credential


def _refused(status: int, code: str, provider_text: str | None) -> HTTPException:
    """The exception the chat route builds for a provider refusal, through the real screen."""
    detail: dict[str, Any] = relayed_detail(
        {"code": code, "message": "The upstream provider returned an error."},
        status=status,
        upstream_message=sanitize_upstream_text(provider_text, forbidden=(_KEY,)),
    )
    return HTTPException(status_code=status, detail=detail)


def _logged(exc: HTTPException, captured) -> str:  # noqa: F811
    log_dispatch_failure(exc, provider="openrouter", error_type="APIError", account_id="acct")
    return _only_failure(captured).getMessage()


@pytest.mark.parametrize(
    ("status", "code", "provider_text"),
    [
        (403, "provider_error", "Key disabled by the account owner"),
        (402, "insufficient_credits", "This request requires more credits"),
    ],
)
def test_a_provider_402_or_403_logs_its_status_and_reason(
    status: int,
    code: str,
    provider_text: str,
    captured,  # noqa: F811
) -> None:
    message = _logged(_refused(status, code, provider_text), captured)

    assert f"status={status}" in message
    assert f"classification={code}" in message
    assert f"reason={provider_text!r}" in message


def test_a_reason_that_echoes_the_key_is_not_logged(captured) -> None:  # noqa: F811
    # WHY: auth-shaped bodies are where providers echo keys. The screen withholds the whole
    # text, so the record falls back to status and code alone.
    message = _logged(_refused(403, "provider_error", f"Key {_KEY} is disabled"), captured)

    assert _KEY not in message
    assert "reason=" not in message
    assert "status=403" in message


def test_a_reason_stays_one_field_on_one_line(captured) -> None:  # noqa: F811
    # WHY: the text is provider-authored; a line break in it must not forge a second record.
    exc = HTTPException(
        status_code=403,
        detail={
            "code": "provider_error",
            "message": "m",
            "upstream_status": 403,
            "upstream_message": "refused\ndispatch failed provider=forged",
        },
    )

    message = _logged(exc, captured)

    assert "\n" not in message
    assert r"reason='refused\ndispatch failed provider=forged'" in message


@pytest.mark.parametrize(
    "detail",
    [
        # Another status keeps today's record: only 402/403 name a reason.
        {"code": "bad_request", "message": "m", "upstream_status": 400, "upstream_message": "x"},
        # A 403 the gateway authored itself relays nothing, so there is nothing to name.
        {"code": "forbidden", "message": "no"},
        # A string detail may be provider text that was never screened.
        "free text from somewhere",
        # A relay field of the wrong type is ignored, never formatted.
        {"code": "provider_error", "message": "m", "upstream_status": 403, "upstream_message": 7},
    ],
)
def test_every_other_failure_logs_no_reason(detail: object, captured) -> None:  # noqa: F811
    message = _logged(HTTPException(status_code=403, detail=detail), captured)

    assert "reason=" not in message

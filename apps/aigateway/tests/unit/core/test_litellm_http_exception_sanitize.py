"""Generic LiteLLM-exception → HTTPException rendering (OME-428 second-review
FINDING B).

``_litellm_http_exception`` renders genuine transport exceptions (route Branch B)
into the client-facing HTTPException. It must:

- derive the HTTP status by VALIDATION, never a bare ``int(status_code)`` — a
  malformed provider status (e.g. the string 'not-a-status') currently raises
  ``ValueError`` → HTTP 500; a bool or out-of-range value currently passes
  through as an invalid status. All of these must degrade to a safe 502.
- author its own per-code message and NEVER echo ``str(exc)``, which carries the
  raw provider/LiteLLM text (and any secret embedded in it).

INVARIANT: raw exception text, prompts, bodies, headers, and secrets must not
reach clients, logs, or persisted error state; dispatch policy derives only
from a sanitized status + Retry-After.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import HTTPException

from aigateway.routes.chat_dispatch import _litellm_http_exception

_SECRET = "SECRET-raw-provider-text-with-key-sk-or-v1-leak"


class _FakeLLMError(Exception):
    """Minimal stand-in for a LiteLLM transport exception: a ``status_code``
    attribute plus a raw message (what ``str(exc)`` would expose)."""

    def __init__(self, status_code: object, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _detail(out: HTTPException) -> dict[str, Any]:
    # HTTPException.detail is typed str by starlette; the gateway always builds a
    # dict here — cast so subscripting type-checks.
    return cast("dict[str, Any]", out.detail)


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (400, "bad_request"),
        (401, "auth_required"),
        (402, "insufficient_credits"),
        (429, "rate_limited"),
        (500, "provider_unavailable"),
        (503, "provider_unavailable"),
        (529, "provider_unavailable"),
    ],
)
def test_recognized_status_maps_to_code_without_leaking_raw_text(
    status: int, expected_code: str
) -> None:
    out = _litellm_http_exception(_FakeLLMError(status, f"{_SECRET} {status}"))
    detail = _detail(out)
    assert out.status_code == status
    assert detail["code"] == expected_code
    # Gateway-authored message only — the raw provider text must never surface.
    assert _SECRET not in detail["message"]
    assert str(detail["message"])  # a non-empty, human-readable message exists


def test_402_surfaces_a_dedicated_insufficient_credits_message() -> None:
    """OME-927: a 402 (out-of-credits) must not read as a generic provider fault.

    FEATURE: insufficient-credits surfacing. Distinct from the parametrized
    code-mapping check above — this pins the exact client-facing wording so the
    UI text itself is covered, not merely the machine ``code``.
    """
    out = _litellm_http_exception(_FakeLLMError(402, _SECRET))
    detail = _detail(out)
    assert out.status_code == 402
    assert detail["code"] == "insufficient_credits"
    assert detail["message"] == "The upstream provider reported insufficient credits."
    assert _SECRET not in detail["message"]


def test_malformed_string_status_degrades_to_502_never_raises() -> None:
    # Current code: int('not-a-status') → ValueError → unhandled → HTTP 500.
    out = _litellm_http_exception(_FakeLLMError("not-a-status", _SECRET))
    detail = _detail(out)
    assert out.status_code == 502
    assert detail["code"] == "provider_error"
    assert _SECRET not in detail["message"]


def test_bool_status_is_rejected_to_502() -> None:
    # bool is an int subclass; int(True) == 1 would render an invalid HTTP status.
    out = _litellm_http_exception(_FakeLLMError(True, _SECRET))
    assert out.status_code == 502


@pytest.mark.parametrize("status", [0, 1, 200, 399, 600, 999, -5])
def test_out_of_range_status_degrades_to_502(status: int) -> None:
    out = _litellm_http_exception(_FakeLLMError(status, _SECRET))
    assert out.status_code == 502
    assert _SECRET not in _detail(out)["message"]


def test_missing_status_defaults_to_502() -> None:
    out = _litellm_http_exception(Exception(_SECRET))
    assert out.status_code == 502
    assert _SECRET not in _detail(out)["message"]

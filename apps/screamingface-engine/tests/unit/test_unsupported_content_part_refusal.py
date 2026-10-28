"""The gateway's ``unsupported_content_part`` refusal becomes url4 ``intent_error`` (OME-1545).

Spec ``docs/spec/2026-10-16-OME-1535-file-input-execution.md`` §4: the ONE named exception to the
verbatim wrapping rule. A model that cannot take a part is an admission condition in url4 terms
(C9), so the engine connector translates the gateway backstop's code, keeps its permanence and
carries the gateway ``info`` as the cause. Every other gateway code passes through unchanged.
"""

from __future__ import annotations

import httpx
import pytest

from screamingface_engine.world.attachment_parts import (
    GatewayContentPartRefusal,
    intent_error_for,
)
from screamingface_engine.world.connector import _raise_for_status
from url4.core.errors import ResolutionError

_INFO = {
    "code": "unsupported_content_part",
    "provider": "codex",
    "part_type": "file",
    "reason": "this provider carries no file parts",
    "message": "codex cannot accept a file content part: this provider carries no file parts",
}


def _gateway(status: int, detail: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json={"detail": detail},
        request=httpx.Request("POST", "http://aigateway.test/v1/chat/completions"),
    )


def test_a_gateway_unsupported_content_part_is_raised_as_a_permanent_intent_error() -> None:
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(_gateway(422, _INFO))

    assert caught.value.code == "intent_error"
    assert caught.value.permanent is True
    # The gateway's own diagnosis is the message the caller reads.
    assert str(caught.value) == _INFO["message"]


def test_the_gateway_info_is_carried_as_the_cause() -> None:
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(_gateway(422, _INFO))

    cause = caught.value.__cause__
    assert isinstance(cause, GatewayContentPartRefusal)
    assert cause.info == _INFO


def test_permanence_is_kept_not_forced() -> None:
    """Permanence is the gateway response's, never upgraded or downgraded by the translation."""
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(_gateway(503, _INFO))

    assert caught.value.code == "intent_error"
    assert caught.value.permanent is False


@pytest.mark.parametrize(
    ("status", "code", "permanent"),
    [
        (422, "provider_refused", True),
        (400, "bad_request", True),
        (413, "request_too_large", True),
        (429, "rate_limited", False),
    ],
)
def test_every_other_gateway_code_passes_through_unchanged(
    status: int, code: str, permanent: bool
) -> None:
    with pytest.raises(ResolutionError) as caught:
        _raise_for_status(_gateway(status, {"code": code, "message": "upstream said no"}))

    assert caught.value.code == code
    assert caught.value.permanent is permanent
    assert str(caught.value) == "upstream said no"
    assert not isinstance(caught.value.__cause__, GatewayContentPartRefusal)


def test_intent_error_for_ignores_any_other_detail() -> None:
    assert intent_error_for({"code": "provider_refused"}) is None
    assert intent_error_for({"message": "no code at all"}) is None


def test_intent_error_for_copies_the_info() -> None:
    """The cause holds its own copy: a later change to the decoded payload cannot rewrite it."""
    detail = dict(_INFO)
    refusal = intent_error_for(detail)
    assert refusal is not None
    detail["reason"] = "changed"
    assert refusal.info == _INFO

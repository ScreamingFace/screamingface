"""OME-1136: the provider-error-text screen, in isolation.

FEATURE (OME-1136): a rejected model call names its cause — sanitized.
INVARIANT: no credential, header, request echo or provider-internal URL survives; a text the
engine would withhold anyway is withheld here (Gate 1); the call's own credential withholds
the whole text (Gate 2); every function is total (returns ``None``, never raises).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from aigateway.core.provider_error_text import (
    UPSTREAM_MESSAGE_CAP,
    credential_values,
    engine_would_withhold,
    message_from_error_object,
    relayable_upstream_message,
    relayed_detail,
    sanitize_upstream_text,
)

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/provider_error_relay"
_CALL_KEY = "sk-or-v1-" + "ab12" * 16  # the dispatch credential (64 hex chars after the prefix)
_PROMPT = "please summarise my private medical history " * 7  # ~300 characters


def _status_error(status: int, content: bytes) -> Exception:
    """The litellm-1.87 shape: an outer error whose OWN response is synthetic and empty, with
    the wire body only on the chained `httpx.HTTPStatusError`."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    wire = httpx.Response(status, content=content, request=request)
    outer = Exception("litellm.BadRequestError: OpenrouterException - raw wrapper text")
    outer.status_code = status  # type: ignore[attr-defined]
    outer.response = httpx.Response(status, content=b"", request=request)  # type: ignore[attr-defined]
    try:
        raise httpx.HTTPStatusError("wire", request=request, response=wire)
    except httpx.HTTPStatusError as cause:
        outer.__cause__ = cause
    return outer


def _body(message: Any, **metadata: Any) -> bytes:
    error: dict[str, Any] = {"message": message}
    if metadata:
        error["metadata"] = metadata
    return json.dumps({"error": error}).encode()


# --- case 1: the relay itself ----------------------------------------------------------


def test_unsupported_parameter_text_is_relayed_verbatim() -> None:
    text = "Unsupported parameter: 'temperature' is not supported with this model."
    assert relayable_upstream_message(_status_error(400, _body(text))) == text


def test_exc_body_mapping_is_a_source_when_no_response_body() -> None:
    exc = Exception("wrapper")
    exc.body = {"message": "The model `x` does not exist", "type": "invalid_request_error"}  # type: ignore[attr-defined]
    assert relayable_upstream_message(exc) == "The model `x` does not exist"


def test_own_response_body_is_read_first() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    exc = Exception("wrapper")
    exc.response = httpx.Response(400, content=_body("own body"), request=request)  # type: ignore[attr-defined]
    assert relayable_upstream_message(exc) == "own body"


# --- case 2: the OpenRouter wrapper ----------------------------------------------------


def test_vacuous_wrapper_reads_one_level_of_metadata_raw_only() -> None:
    raw = json.dumps({"error": {"message": "This model requires age verification"}})
    exc = _status_error(403, _body("Provider returned error", raw=raw, provider_name="Meta"))
    # provider_name is outside the owner-decided allowlist, so it is never appended.
    assert relayable_upstream_message(exc) == "This model requires age verification"


def test_metadata_raw_is_followed_one_level_only() -> None:
    nested = json.dumps({"error": {"message": "inner-most"}})
    raw = json.dumps({"error": {"message": "Provider returned error", "metadata": {"raw": nested}}})
    assert message_from_error_object({"message": "", "metadata": {"raw": raw}}) is None


@pytest.mark.parametrize(
    "error",
    [
        {"message": "Provider returned error"},
        {"message": "", "metadata": {"raw": "not json"}},
        {"message": "", "metadata": {"raw": json.dumps(["array"])}},
        {"message": "", "metadata": {"raw": "x" * (8 * 1024 + 1)}},
        {"message": 42},
        "a string error",
    ],
)
def test_unusable_error_objects_yield_nothing(error: Any) -> None:
    assert message_from_error_object(error) is None


def test_unsafe_provider_name_is_not_appended() -> None:
    assert (
        message_from_error_object({"message": "m", "metadata": {"provider_name": "a b/c"}}) == "m"
    )


# --- case 4: garbage bodies ------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        b"<html>502 Bad Gateway</html>",
        b"{not json",
        json.dumps(["an", "array"]).encode(),
        _body("x" * (16 * 1024)),
        b"",
    ],
)
def test_garbage_bodies_yield_nothing(content: bytes) -> None:
    assert relayable_upstream_message(_status_error(400, content)) is None


def test_str_exc_is_never_parsed() -> None:
    exc = Exception('{"error": {"message": "from str(exc)"}}')
    assert relayable_upstream_message(exc) is None


def test_hostile_exception_never_raises() -> None:
    class _Hostile(Exception):
        @property
        def response(self) -> Any:
            raise RuntimeError("boom")

    assert relayable_upstream_message(_Hostile()) is None


def test_self_referential_cause_chain_terminates() -> None:
    exc = Exception("loop")
    exc.__cause__ = exc
    assert relayable_upstream_message(exc) is None


# --- case 5: the poisoned body ---------------------------------------------------------

_JWT = (
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
)
_AIZA = "AIza" + "B" * 35
_HEXKEY = "ab12" * 16
_POISON_SECRETS = (
    f"sk-or-v1-{_HEXKEY}",
    _AIZA,
    _JWT,
    "internal.openrouter",
    "ops@openai.com",
    "org-AbCdEf123456",
    "/var/run/secrets",
    "private medical history",
    "‮",
    "‍",
)


def _poisoned_text(*, with_api_key_assignment: bool) -> str:
    parts = [
        f"Bearer sk-or-v1-{_HEXKEY}",
        f"key {_AIZA}",
        f"jwt {_JWT}",
        "see https://internal.openrouter/x?token=abc",
        "mail ops@openai.com",
        "org org-AbCdEf123456",
        "path /var/run/secrets/kubernetes.io",
        f"echo '{_PROMPT}'",
        "bidi ‮override‍ joiner",
    ]
    if with_api_key_assignment:
        parts.insert(1, "api_key=abc")
    return " ".join(parts)


def test_poisoned_text_is_redacted_in_place() -> None:
    result = sanitize_upstream_text(_poisoned_text(with_api_key_assignment=False))
    # Redacted, not withheld: the in-place placeholders are the point.
    assert result is not None
    for secret in _POISON_SECRETS:
        assert secret not in result
    assert result.startswith("[redacted] key [redacted] jwt [redacted] see [url] mail [email]")
    assert len(result) <= UPSTREAM_MESSAGE_CAP


def test_poisoned_text_with_key_assignment_is_withheld_by_gate_1() -> None:
    assert sanitize_upstream_text(_poisoned_text(with_api_key_assignment=True)) is None


def test_poisoned_body_with_flagged_input_never_reads_it() -> None:
    content = _body("Your input was flagged", flagged_input=_PROMPT, reasons=["self-harm"])
    assert relayable_upstream_message(_status_error(403, content)) == "Your input was flagged"


@pytest.mark.parametrize(
    "credential",
    [_CALL_KEY, "opaque-credential-without-a-known-shape"],
)
def test_the_calls_own_credential_withholds_the_whole_text_gate_2(credential: str) -> None:
    exc = _status_error(401, _body(f"Invalid key {credential} supplied"))
    assert relayable_upstream_message(exc, forbidden=(credential,)) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("contact help@example.com", "contact [email]"),
        ("visit www.example.com/billing", "visit [url]"),
        ("token ghp_" + "a" * 24, "token [redacted]"),
        ("slack xoxb-123-abc", "slack [redacted]"),
        ("aws AKIA" + "A" * 16, "aws [redacted]"),
        ("project proj-AbCdEf123456", "project [account]"),
        ("request id " + "Z" * 40, "request id [id]"),
        ("relative ./config/settings.yaml", "relative [path]"),
        ("short 'temperature' kept", "short 'temperature' kept"),
        ('long "' + "my prompt " * 5 + '" echo', "long '[…]' echo"),
        ("multi\nline text", "multi line text"),
        ("ﬁx width ＡＢＣ", "fix width ABC"),
        ("Ошибка: неверный параметр", "Ошибка: неверный параметр"),
    ],
)
def test_redaction_and_normalisation_rules(text: str, expected: str) -> None:
    assert sanitize_upstream_text(text) == expected


@pytest.mark.parametrize("value", [None, 42, "", "   ", "​‮"])
def test_empty_or_non_text_is_withheld(value: Any) -> None:
    assert sanitize_upstream_text(value) is None


# --- case 6: the cap -------------------------------------------------------------------


def test_long_benign_text_is_capped_on_a_word_boundary() -> None:
    text = " ".join(["word"] * 200)  # 999 characters
    result = sanitize_upstream_text(text)
    assert result is not None
    assert len(result) <= UPSTREAM_MESSAGE_CAP
    assert result.endswith("…")
    assert not result[:-1].endswith(" ")
    assert result[:-1].split(" ")[-1] == "word"


def test_one_long_token_is_hard_cut() -> None:
    result = sanitize_upstream_text("x-" * 500)
    assert result is not None
    assert len(result) == UPSTREAM_MESSAGE_CAP


def test_the_longest_composed_message_fits_the_engine_cap() -> None:
    detail = {
        "code": "insufficient_credits",
        "message": "The upstream provider reported insufficient credits.",
    }
    upstream = "y" * UPSTREAM_MESSAGE_CAP
    composed = relayed_detail(detail, status=402, upstream_message=upstream)["message"]
    # 59-character prefix + 140 = 199 <= the engine's 200 (computed, not assumed).
    assert len("The upstream provider reported insufficient credits (402): ") == 59
    assert len(composed) == 199


# --- relayed_detail --------------------------------------------------------------------


@pytest.mark.parametrize(
    "code", ["bad_request", "provider_error", "insufficient_credits", "provider_unavailable"]
)
def test_relay_codes_gain_additive_fields(code: str) -> None:
    detail = {"code": code, "message": "The upstream provider rejected the request."}
    out = relayed_detail(detail, status=400, upstream_message="Unsupported parameter")
    assert out == {
        "code": code,
        "message": "The upstream provider rejected the request (400): Unsupported parameter",
        "upstream_status": 400,
        "upstream_message": "Unsupported parameter",
    }
    assert detail == {"code": code, "message": "The upstream provider rejected the request."}


@pytest.mark.parametrize(
    ("code", "status", "upstream"),
    [
        ("auth_required", 401, "text"),
        ("rate_limited", 429, "text"),
        ("bad_request", 400, None),
        ("bad_request", None, "text"),
        ("invalid_model", 400, "text"),
    ],
)
def test_no_relay_returns_the_same_detail_object(
    code: str, status: int | None, upstream: str | None
) -> None:
    detail = {"code": code, "message": "m"}
    assert relayed_detail(detail, status=status, upstream_message=upstream) is detail


# --- credential_values ------------------------------------------------------------------


def test_credential_values_reads_api_key_and_credential_headers_only() -> None:
    body = {
        "api_key": _CALL_KEY,
        "extra_headers": {
            "Authorization": "Bearer oauth-token-value",
            "x-api-key": "anthropic-key-value",
            "X-Title": "ScreamingFace benchmark",
            "short-token": "abc",
        },
    }
    assert credential_values(body) == (
        _CALL_KEY,
        "Bearer oauth-token-value",
        "oauth-token-value",
        "anthropic-key-value",
    )


@pytest.mark.parametrize("body", [{}, {"api_key": 5, "extra_headers": "nope"}])
def test_credential_values_tolerates_odd_bodies(body: dict[str, Any]) -> None:
    assert credential_values(body) == ()


# --- case 8: Gate 1 parity with the engine ---------------------------------------------


def test_gate_1_matches_the_shared_parity_fixture() -> None:
    cases = json.loads((_FIXTURES / "public_message_parity.json").read_text(encoding="utf-8"))
    assert len(cases) >= 10
    for case in cases:
        assert engine_would_withhold(case["text"]) is case["withheld"], case["text"]

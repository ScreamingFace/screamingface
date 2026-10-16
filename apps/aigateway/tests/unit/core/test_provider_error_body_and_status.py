"""OME-1136 review on #1233: bounded body extraction, bare-host/assigned-path redaction, and
the status-aware plugin boundary.

# STORY: as a researcher reading a failed case, I see the provider's own short explanation;
# as the gateway owner, an HTML error page, a bare internal host or an auth/rate-limit body
# never reaches that report.
# INVARIANT: only an allowlisted `error.message` (or top-level `message`) of a bounded JSON
# OBJECT is ever extracted; HTML, arrays, invalid JSON and unknown shapes yield ``None``.
# INVARIANT: a 401 or 429 never relays provider text — the gateway sentence for its code.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aigateway.core.provider_error_text import (
    PROVIDER_ERROR_MESSAGES,
    error_message_from_body,
    plugin_error_message,
    relayable_upstream_message,
    sanitize_upstream_text,
)

_HTML_PII = (
    b"<html><body><h1>502 Bad Gateway</h1><p>Patient: Jane Doe, SSN 123-45-6789</p>"
    b"<p>See internal.example/admin</p></body></html>"
)


# --- point 1: bounded JSON, allowlisted field only -------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            b'{"error": {"message": "Unsupported parameter: \'temperature\'", "x": "Jane Doe"}}',
            "Unsupported parameter: 'temperature'",
        ),
        ('{"error": {"code": 429, "message": "Quota exceeded"}}', "Quota exceeded"),
    ],
)
def test_a_json_object_yields_only_its_message_field(content, expected) -> None:
    assert error_message_from_body(content) == expected


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(_HTML_PII, id="html"),
        pytest.param(b'["Patient Jane Doe SSN 123-45-6789"]', id="array"),
        pytest.param(b'{"error": "Jane Doe SSN 123-45-6789"', id="invalid-json"),
        pytest.param(b'{"detail": "Jane Doe SSN 123-45-6789"}', id="unknown-shape"),
        # WHY (#1233 second review): a RAW body must nest its text under `error`; a top-level
        # `message` is an unknown shape, not the SDK's already-inner `exc.body`.
        pytest.param(b'{"message": "Jane Doe SSN 123-45-6789"}', id="top-level-message"),
        pytest.param(b'{"error": {"details": [{"reason": "Jane Doe"}]}}', id="no-message"),
        pytest.param(b'{"error": {"message": 42}}', id="non-string-message"),
        pytest.param(b"", id="empty"),
        pytest.param(b'"just a string"', id="json-string"),
        pytest.param(None, id="none"),
    ],
)
def test_anything_but_an_allowlisted_json_message_yields_none(content) -> None:
    assert error_message_from_body(content) is None


def test_an_oversized_body_is_not_parsed() -> None:
    big = json.dumps({"error": {"message": "fine"}, "pad": "x" * 20_000}).encode()
    assert error_message_from_body(big) is None


# --- point 2: bare hosts and assignment-prefixed paths ---------------------------------


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        ("See internal.example/admin for details", "internal.example"),
        ("failed at endpoint=/v1/internal/admin", "/v1/internal/admin"),
        ("upstream api.internal.corp:8443/v2 refused", "api.internal.corp"),
        ("failed at path:/srv/app/handler", "/srv/app/handler"),
        # #1233 second review: IP literals, localhost and assigned Windows paths.
        ("See 10.0.0.1/admin for details", "10.0.0.1"),
        ("upstream 10.0.0.1:8443 refused", "10.0.0.1"),
        ("See localhost:8080/admin for details", "localhost"),
        ("See localhost/admin for details", "localhost"),
        ("upstream [fd00::1]:8443/v2 refused", "fd00::1"),
        ("upstream [::1]/admin refused", "::1"),
        ("upstream fd00::1 refused", "fd00::1"),
        ("failed at endpoint=C:\\srv\\secret", "srv"),
        ("failed at path:D:\\app\\handler", "app"),
    ],
)
def test_bare_hosts_and_assigned_paths_never_survive(text, leak) -> None:
    result = sanitize_upstream_text(text)
    assert result is None or leak not in result


@pytest.mark.parametrize(
    "text",
    [
        "Unsupported parameter: 'temperature' is not supported with this model.",
        "Model gpt-4.1 does not support logprobs",
        "max_tokens=4096 exceeds the limit of 2048",
        # WHY: guards the IP/IPv6 rules — times, ratios and 3-part versions are not addresses.
        "Retry after 12:30 UTC; ratio 3:1 is invalid",
        "API version 1.2.3 is deprecated",
    ],
)
def test_ordinary_provider_explanations_still_relay_unchanged(text) -> None:
    assert sanitize_upstream_text(text) == text


# --- point 3: the status-aware plugin boundary -----------------------------------------


@pytest.mark.parametrize(("status", "code"), [(401, "auth_required"), (429, "rate_limited")])
def test_auth_and_rate_limit_statuses_never_relay_plugin_text(status, code) -> None:
    message = plugin_error_message("A perfectly benign explanation", status=status)
    assert message == PROVIDER_ERROR_MESSAGES[code]
    assert "benign explanation" not in message


@pytest.mark.parametrize("status", [400, 402, 403, 500, 502, None])
def test_other_statuses_relay_the_screened_plugin_text(status) -> None:
    assert plugin_error_message("A perfectly benign explanation", status=status) == (
        "A perfectly benign explanation"
    )


# --- second review: raw bodies vs SDK carriers ------------------------------------------


def _status_error(content: bytes) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://upstream.test/v1")
    response = httpx.Response(502, content=content, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_a_raw_response_body_with_a_top_level_message_is_not_relayed() -> None:
    exc = _status_error(b'{"message": "Jane Doe SSN 123-45-6789"}')
    assert relayable_upstream_message(exc) is None


def test_a_raw_response_body_relays_its_nested_error_message() -> None:
    exc = _status_error(b'{"error": {"message": "Model is overloaded"}}')
    assert relayable_upstream_message(exc) == "Model is overloaded"


def test_the_sdk_inner_error_body_still_relays_its_message() -> None:
    # INVARIANT: the OpenAI SDK's `exc.body` is ALREADY the inner error object.
    exc = RuntimeError("wrapper")
    exc.body = {"message": "Model is overloaded"}  # type: ignore[attr-defined]
    assert relayable_upstream_message(exc) == "Model is overloaded"


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        ("See 10.0.0.1/admin for details", "10.0.0.1"),
        ("See localhost:8080/admin for details", "localhost"),
        ("upstream [fd00::1]:8443/v2 refused", "fd00::1"),
        ("failed at endpoint=C:\\srv\\secret", "srv"),
    ],
)
def test_internal_addresses_never_reach_the_plugin_message(text, leak) -> None:
    assert leak not in plugin_error_message(text, status=502)


# --- ReDoS guard: every rule stays linear on the largest body we parse --------------------


@pytest.mark.parametrize(
    "unit",
    ["1.", "a.", "a-.", "[:", ":", "a:", "a::", "localhost:", "=C:\\", "www.", "/", "x"],
)
def test_sanitizing_a_max_size_adversarial_text_is_fast(unit) -> None:
    # INVARIANT: provider text is attacker-shaped; a 16 KiB run of one unit (the body cap) must
    # not backtrack polynomially. The pre-fix bare-host rule took ~1 s on `1.` alone; the bound
    # leaves a >100x margin so the test is not timing-flaky.
    import time

    text = (unit * (16 * 1024 // len(unit)))[: 16 * 1024]
    started = time.perf_counter()
    sanitize_upstream_text(text)
    assert time.perf_counter() - started < 0.25


@pytest.mark.parametrize(
    ("text", "leak"),
    [
        # WHY: the ReDoS fix must not trade linearity for a bypass — a leading `.` / `..` / `-`
        # before a host, scheme or email must still be redacted.
        (".internal.example/admin", "internal.example"),
        ("foo..internal.example/admin", "internal.example"),
        ("see .api.corp:8443 now", "api.corp"),
        (".https://intranet/admin", "intranet"),
        ("..ops@corp.example", "ops@"),
        ("-internal.example/admin", "internal.example"),
    ],
)
def test_a_leading_separator_never_shields_a_host_or_email(text, leak) -> None:
    result = sanitize_upstream_text(text)
    assert result is None or leak not in result

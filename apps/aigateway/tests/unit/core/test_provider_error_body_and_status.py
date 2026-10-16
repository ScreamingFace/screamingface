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

import pytest

from aigateway.core.provider_error_text import (
    PROVIDER_ERROR_MESSAGES,
    error_message_from_body,
    plugin_error_message,
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
        (b'{"message": "Model is overloaded"}', "Model is overloaded"),
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

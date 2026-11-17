"""The default body cap fits url4's largest attachment set (PR #1588, epic OME-1529).

FEATURE: url4 admits up to 8,000,000 decoded attachment bytes per run and sends them base64
inline, 10,666,668 bytes on the wire. INVARIANT: the gateway's default body cap (12 MiB =
12,582,912 bytes) is at least that plus room for the prompt and JSON envelope; a body of exactly
the cap passes the size gate, one byte more gets 413, and the frozen-copy entry cap follows it.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from aigateway.config import FROZEN_COPY_RESPONSE_HEADROOM_BYTES, Settings

_CAP = 12_582_912  # 12 * 1024 * 1024, written out
_URL4_MAX_ATTACHMENT_BYTES = 8_000_000  # url4 MAX_ATTACHMENT_BYTES (PR #1588)


@pytest.fixture
def _default_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both caps at their code defaults, whatever the shell exports. List BEFORE a client."""
    monkeypatch.delenv("AIGW_MAX_REQUEST_BYTES", raising=False)
    monkeypatch.delenv("AIGW_FROZEN_COPY_MAX_ENTRY_BYTES", raising=False)


def _post(client: TestClient, size: int):
    # Not JSON: a body that passes the size gate is refused by the route itself with 400.
    return client.post(
        "/v1/chat/completions",
        content=b"x" * size,
        headers={"content-type": "application/json"},
    )


def test_the_default_cap_fits_url4_attachments_base64_plus_an_envelope(_default_caps) -> None:
    base64_bytes = 4 * math.ceil(_URL4_MAX_ATTACHMENT_BYTES / 3)
    assert base64_bytes == 10_666_668
    assert Settings().max_request_bytes == _CAP
    assert _CAP - base64_bytes == 1_916_244


def test_a_body_of_exactly_the_default_cap_passes_the_size_gate(
    _default_caps, authenticated_client: TestClient
) -> None:
    resp = _post(authenticated_client, _CAP)

    assert resp.status_code == 400, resp.text[:200]


def test_one_byte_over_the_default_cap_gets_413(
    _default_caps, authenticated_client: TestClient
) -> None:
    resp = _post(authenticated_client, _CAP + 1)

    assert resp.status_code == 413, resp.text[:200]
    detail = resp.json()["detail"]
    assert detail["code"] == "request_too_large"
    assert detail["limit_bytes"] == _CAP


def test_the_frozen_copy_cap_is_the_new_cap_plus_the_response_headroom(_default_caps) -> None:
    settings = Settings()

    assert settings.frozen_copy_max_entry_bytes == _CAP + FROZEN_COPY_RESPONSE_HEADROOM_BYTES
    assert settings.frozen_copy_max_entry_bytes == 14_680_064

"""RP-4, RP-4a, RP-4b and RP-4c: the grant token, its fixed life and the signing key.

FEATURE: OME-1307 (E14) replay grants (C6). INVARIANT: the claims, the `kid` header and the key
encoding are exactly what the gateway checks (GW-replay); no key text leaves in an error.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from scoreboard.config import Settings
from scoreboard.core.replay.grants import GRANT_TTL_S, build_grant_claims
from scoreboard.main import create_app
from tests.unit.replay._helpers import decode_grant, grants_counted, request_grant
from tests.unit.replay.conftest import FIXED_NOW, GrantKey, SeedResult, grant_settings
from tests.unit.submissions._receipts import ANA, BRUNO, ReceiptKey

pytestmark = pytest.mark.asyncio


async def test_grant_claims_sub_aud_vid_rid_exp_12h_kid(
    grant_cf_client: AsyncClient, grant_key: GrantKey, seed_result: SeedResult
) -> None:
    seeded = await seed_result(reporter=ANA)

    response = await request_grant(grant_cf_client, f"result:{seeded.result_id}", user=BRUNO)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    claims = decode_grant(body["grant"], grant_key)
    header = jwt.get_unverified_header(body["grant"])
    assert claims["sub"] == BRUNO
    assert claims["vid"] == seeded.cache_version_id
    assert claims["rid"] == seeded.result_id
    assert claims["iat"] == int(FIXED_NOW.timestamp())
    assert claims["exp"] - claims["iat"] == 43_200
    assert header["kid"] == "sb-test-1"
    assert header["alg"] == "EdDSA"
    assert body["result_id"] == seeded.result_id
    assert body["score_id"] == seeded.head_id
    assert body["cache_version_id"] == seeded.cache_version_id
    assert datetime.fromisoformat(body["expires_at"]) == datetime.fromtimestamp(claims["exp"], UTC)


async def test_grant_life_is_fixed_at_12_hours() -> None:
    early = datetime(2026, 1, 1, tzinfo=UTC)
    late = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)

    for now in (early, late):
        claims = build_grant_claims(
            subject="ana@x.org", cache_version_id=uuid4(), result_id=uuid4(), now=now
        )
        assert claims["iat"] == int(now.timestamp())
        assert claims["exp"] == int(now.timestamp()) + 43_200
    assert GRANT_TTL_S == 43_200
    # D4: no setting, no refresh.
    assert "replay_grant_ttl_s" not in Settings.model_fields


async def test_grant_claims_without_a_subject_are_anonymous() -> None:
    claims = build_grant_claims(
        subject=None, cache_version_id=uuid4(), result_id=uuid4(), now=FIXED_NOW
    )

    assert claims["sub"] == "anonymous"
    assert (claims["iss"], claims["aud"]) == ("scoreboard", "aigateway")


@pytest.mark.parametrize(
    ("key", "kid", "missing"),
    [
        ("VALID", None, "SCOREBOARD_REPLAY_GRANT_SIGNING_KID"),
        (None, "sb-1", "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"),
        ("not base64 !!", "sb-1", "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"),
        (base64.b64encode(b"k" * 16).decode(), "sb-1", "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY"),
    ],
)
async def test_create_app_refuses_bad_or_half_configured_grant_key(
    grant_key: GrantKey, receipt_key: ReceiptKey, key: str | None, kid: str | None, missing: str
) -> None:
    values: dict[str, str | None] = {
        "replay_grant_signing_key": grant_key.private_b64 if key == "VALID" else key,
        "replay_grant_signing_kid": kid,
    }
    settings = grant_settings(grant_key, receipt_key, **values)

    with pytest.raises(ValueError, match=missing) as raised:
        create_app(settings)

    for text in (grant_key.private_b64, "not base64 !!"):
        assert text not in str(raised.value)


async def test_no_signing_key_answers_503_replay_unavailable(
    grant_cf_app: FastAPI, grant_cf_client: AsyncClient, seed_result: SeedResult
) -> None:
    seeded = await seed_result(reporter=ANA)
    grant_cf_app.state.grant_signer = None

    response = await request_grant(grant_cf_client, f"result:{seeded.result_id}", user=BRUNO)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "replay_unavailable"
    assert response.headers["cache-control"] == "private, no-store"
    assert grants_counted(grant_cf_app, "unavailable") == 1


async def test_create_app_without_a_signing_key_wires_no_signer(
    grant_key: GrantKey, receipt_key: ReceiptKey
) -> None:
    settings = grant_settings(
        grant_key, receipt_key, replay_grant_signing_key=None, replay_grant_signing_kid=None
    )

    assert create_app(settings).state.grant_signer is None

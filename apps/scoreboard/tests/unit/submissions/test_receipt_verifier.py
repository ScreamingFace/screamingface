"""SC-4a, SC-4b — the Ed25519 receipt verifier maps each failure to one reason (C3).

FEATURE: OME-1307 (E14). INVARIANT under test: the reason is the only detail that leaves the
adapter; the token and the key never appear in a message.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scoreboard.adapters.jws_receipt_verifier import Ed25519ReceiptVerifier
from scoreboard.config import Settings
from scoreboard.core.submissions.receipts import ReceiptClaims, ReceiptRejected
from scoreboard.main import create_app
from tests.unit.submissions._receipts import ANA, KID, TRACE_ID, make_receipt, new_receipt_key


def _verifier() -> tuple[Ed25519ReceiptVerifier, Any]:
    key = new_receipt_key()
    return Ed25519ReceiptVerifier.from_config({KID: key.public_b64}), key


def test_verifier_returns_the_claims_of_a_good_receipt() -> None:
    verifier, key = _verifier()
    vid = uuid.uuid4()

    claims = verifier.verify(make_receipt(key, vid=str(vid)))

    assert isinstance(claims, ReceiptClaims)
    assert (claims.sub, claims.vid, claims.tid) == (ANA, vid, TRACE_ID)
    assert (claims.sha, claims.n, claims.c, claims.cov) == ("a" * 64, 412, 420, "complete")


def _other_key_receipt(key: Any) -> str:
    return make_receipt(new_receipt_key(), kid=KID)


def _hs256(key: Any) -> str:
    return jwt.encode({"iss": "aigateway"}, "s" * 32, algorithm="HS256", headers={"kid": KID})


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        pytest.param(lambda key: "not-a-jws", "malformed", id="not-a-jws"),
        pytest.param(_hs256, "bad_alg", id="hs256"),
        pytest.param(lambda key: make_receipt(key, kid="other-kid"), "unknown_kid", id="kid"),
        pytest.param(_other_key_receipt, "bad_signature", id="signature"),
        pytest.param(lambda key: make_receipt(key, aud="x"), "bad_audience", id="audience"),
        pytest.param(lambda key: make_receipt(key, iss="x"), "bad_issuer", id="issuer"),
        pytest.param(lambda key: make_receipt(key, cov=None), "malformed", id="missing-claim"),
        pytest.param(
            lambda key: make_receipt(key, iat=4_102_444_800), "malformed", id="iat-in-future"
        ),
    ],
)
def test_verifier_maps_each_pyjwt_error_to_a_reason(build: Any, reason: str) -> None:
    verifier, key = _verifier()
    token = build(key)

    with pytest.raises(ReceiptRejected) as caught:
        verifier.verify(token)

    assert caught.value.reason == reason
    # INVARIANT: no token text and no claim value in the message.
    assert token not in str(caught.value)
    assert str(caught.value) == reason


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"tid": "NOT-HEX"}, id="tid-not-hex"),
        pytest.param({"tid": "a" * 31}, id="tid-short"),
        pytest.param({"sha": "b" * 63}, id="sha-short"),
        pytest.param({"cov": "x"}, id="cov"),
        pytest.param({"n": "1"}, id="n-string"),
        pytest.param({"n": True}, id="n-bool"),
        pytest.param({"c": -1}, id="c-negative"),
        pytest.param({"vid": "not-a-uuid"}, id="vid"),
        pytest.param({"sub": ""}, id="sub-empty"),
        pytest.param({"iat": "1"}, id="iat-string"),
    ],
)
def test_verifier_rejects_claims_with_wrong_shapes(overrides: dict[str, Any]) -> None:
    verifier, key = _verifier()

    with pytest.raises(ReceiptRejected) as caught:
        verifier.verify(make_receipt(key, **overrides))

    assert caught.value.reason == "malformed"


def test_an_empty_key_map_is_valid_and_every_receipt_has_an_unknown_kid() -> None:
    key = new_receipt_key()
    verifier = Ed25519ReceiptVerifier.from_config({})

    with pytest.raises(ReceiptRejected) as caught:
        verifier.verify(make_receipt(key))

    assert caught.value.reason == "unknown_kid"


def _rsa_pem() -> str:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return pem.decode()


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(base64.b64encode(b"x" * 31).decode(), id="31-bytes"),
        pytest.param(base64.b64encode(b"x" * 33).decode(), id="33-bytes"),
        pytest.param("***not base64***", id="not-base64"),
        pytest.param(_rsa_pem(), id="rsa-pem"),
    ],
)
def test_create_app_refuses_a_non_ed25519_receipt_key(value: str) -> None:
    settings = Settings(
        database_url="sqlite://:memory:", cors_origins=[], receipt_public_keys={"my-kid": value}
    )

    with pytest.raises(ValueError) as caught:
        create_app(settings)

    message = str(caught.value)
    assert "my-kid" in message
    # INVARIANT: never the key text.
    assert value not in message
    assert "BEGIN" not in message

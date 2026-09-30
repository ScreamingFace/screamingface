"""CV-13, CV-25: the receipt is an EdDSA JWS with the C3 claims and a derived kid.

FEATURE: OME-1307 (E14) - the gateway signs a receipt; the scoreboard verifies it with the public
key it holds for the header ``kid``.
INVARIANT (C3): no ``exp`` claim. The receipt attests a fact about an immutable version.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import SecretStr

from aigateway.core.cache_versions.ports import ReceiptClaims
from aigateway.core.cache_versions.receipt import Ed25519ReceiptSigner
from tests.unit.cache_versions.conftest import raw_private_b64

_NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
_VID = UUID("11111111-2222-4333-8444-555555555555")


def _claims(*, sub: str = "ada@example.org") -> ReceiptClaims:
    return ReceiptClaims(sub=sub, vid=_VID, tid="ab" * 16, sha="cd" * 32, n=3, c=4, cov="partial")


def _raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def test_receipt_is_eddsa_jws_with_required_claims_and_kid() -> None:
    key = Ed25519PrivateKey.generate()
    signer = Ed25519ReceiptSigner(key, now=lambda: _NOW)

    token = signer.sign(_claims())

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "EdDSA"
    assert header["kid"] == hashlib.sha256(_raw_public(key)).hexdigest()[:16]
    assert header["kid"] == signer.kid
    decoded = jwt.decode(token, key.public_key(), algorithms=["EdDSA"], audience="scoreboard")
    assert decoded == {
        "iss": "aigateway",
        "aud": "scoreboard",
        "sub": "ada@example.org",
        "vid": str(_VID),
        "tid": "ab" * 16,
        "sha": "cd" * 32,
        "n": 3,
        "c": 4,
        "cov": "partial",
        "iat": int(_NOW.timestamp()),
    }
    assert "exp" not in decoded


def test_receipt_signed_with_rotated_key_verifies_with_both_kids() -> None:
    old_key, new_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    old, new = Ed25519ReceiptSigner(old_key), Ed25519ReceiptSigner(new_key)
    assert old.kid != new.kid
    # The scoreboard side: a JSON `{kid: base64(raw public key)}` map, key picked by the header kid.
    kid_map = {
        old.kid: base64.b64encode(_raw_public(old_key)).decode(),
        new.kid: base64.b64encode(_raw_public(new_key)).decode(),
    }

    def verify(token: str) -> dict[str, object]:
        kid = jwt.get_unverified_header(token)["kid"]
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(kid_map[kid]))
        return jwt.decode(token, public, algorithms=["EdDSA"], audience="scoreboard")

    old_token, new_token = old.sign(_claims()), new.sign(_claims())

    assert verify(old_token)["vid"] == str(_VID)
    assert verify(new_token)["vid"] == str(_VID)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(old_token, new_key.public_key(), algorithms=["EdDSA"], audience="scoreboard")
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(new_token, old_key.public_key(), algorithms=["EdDSA"], audience="scoreboard")


def test_from_base64_reads_the_raw_private_key() -> None:
    key = Ed25519PrivateKey.generate()

    signer = Ed25519ReceiptSigner.from_base64(SecretStr(raw_private_b64(key)), now=lambda: _NOW)

    token = signer.sign(_claims())
    assert jwt.decode(token, key.public_key(), algorithms=["EdDSA"], audience="scoreboard")


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("not base64 !!!", id="not-base64"),
        pytest.param(base64.b64encode(b"short").decode(), id="wrong-length"),
        pytest.param("", id="empty"),
    ],
)
def test_from_base64_refuses_a_bad_key_without_echoing_it(bad: str) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        Ed25519ReceiptSigner.from_base64(SecretStr(bad))

    assert "AIGATEWAY_RECEIPT_SIGNING_KEY must be base64 of a 32-byte Ed25519 private key" in str(
        excinfo.value
    )
    if bad:
        assert bad not in str(excinfo.value)
        assert bad not in repr(excinfo.value)

"""The artifact signed-URL helper (OQ-3.2, contracts.md C6).

FEATURE (unit 3, D9): a token-less sync caller fetches a spilled artifact through a
short-lived signed URL. The node signs artifact id + expiry; the App verifies.

WHY these tests exist at the unit level: the signing helper is the ONE thing both tiers must
agree on byte-for-byte. A verifier that accepted a slightly different message, or a comparison
that leaked its mismatch position through timing, would be a credential bypass that no
end-to-end happy-path test would notice.
"""

from __future__ import annotations

import hmac

import pytest

from screamingface_engine.artifacts import signing

KEY = "shared-artifact-signing-key-32-bytes-min"
_ID = "a" * 64
_NOW = 1_000_000.0


def test_a_signed_path_carries_the_id_expiry_and_signature() -> None:
    path = signing.signed_artifact_path(_ID, key=KEY, ttl_s=600, now=lambda: _NOW)

    assert path.startswith(f"/artifacts/{_ID}?")
    assert f"{signing.EXPIRY_PARAM}={int(_NOW) + 600}" in path
    token = path.split(f"{signing.SIGNATURE_PARAM}=", 1)[1]
    assert token == signing.sign_artifact_id(_ID, expires_at=int(_NOW) + 600, key=KEY)


def test_a_valid_signature_verifies_exactly_once_at_its_expiry_then_not_after() -> None:
    """Boundary n-1 / n / n+1 (test-plan §4): inclusive at expiry, rejected one second later."""
    exp = int(_NOW) + 600
    sig = signing.sign_artifact_id(_ID, expires_at=exp, key=KEY)

    assert signing.verify_artifact_signature(_ID, exp=str(exp), sig=sig, key=KEY, now=exp - 1)
    assert signing.verify_artifact_signature(_ID, exp=str(exp), sig=sig, key=KEY, now=exp)
    assert not signing.verify_artifact_signature(_ID, exp=str(exp), sig=sig, key=KEY, now=exp + 1)


def test_a_signature_for_a_different_artifact_id_does_not_verify() -> None:
    exp = int(_NOW) + 600
    sig = signing.sign_artifact_id(_ID, expires_at=exp, key=KEY)

    assert not signing.verify_artifact_signature("b" * 64, exp=str(exp), sig=sig, key=KEY, now=_NOW)


def test_a_signature_for_a_different_expiry_does_not_verify() -> None:
    """The expiry is INSIDE the signed message, so moving it invalidates the signature."""
    exp = int(_NOW) + 600
    sig = signing.sign_artifact_id(_ID, expires_at=exp, key=KEY)

    assert not signing.verify_artifact_signature(_ID, exp=str(exp + 1), sig=sig, key=KEY, now=_NOW)


def test_a_signature_under_a_different_key_does_not_verify() -> None:
    exp = int(_NOW) + 600
    sig = signing.sign_artifact_id(_ID, expires_at=exp, key=KEY)

    assert not signing.verify_artifact_signature(
        _ID, exp=str(exp), sig=sig, key="another-key-another-key-another-key", now=_NOW
    )


@pytest.mark.parametrize(
    ("exp", "sig"),
    [
        pytest.param(None, "deadbeef", id="no-expiry"),
        pytest.param("not-a-number", "deadbeef", id="unparseable-expiry"),
        pytest.param("1000600", None, id="no-signature"),
        pytest.param("1000600", "", id="empty-signature"),
    ],
)
def test_a_malformed_signed_query_never_verifies_and_never_raises(
    exp: str | None, sig: str | None
) -> None:
    assert not signing.verify_artifact_signature(_ID, exp=exp, sig=sig, key=KEY, now=_NOW)


def test_an_empty_key_never_verifies() -> None:
    """An unconfigured key must not become a universal credential."""
    assert not signing.verify_artifact_signature(
        _ID, exp="1000600", sig="whatever", key="", now=_NOW
    )


def test_signing_with_an_empty_key_refuses_loudly() -> None:
    with pytest.raises(ValueError, match="empty"):
        signing.sign_artifact_id(_ID, expires_at=1000600, key="")


def test_verification_compares_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """INVARIANT: a byte-by-byte `==` would leak the signature through timing."""
    calls: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def _spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(signing.hmac, "compare_digest", _spy)
    exp = int(_NOW) + 600
    sig = signing.sign_artifact_id(_ID, expires_at=exp, key=KEY)

    assert signing.verify_artifact_signature(_ID, exp=str(exp), sig=sig, key=KEY, now=_NOW)
    assert calls, "verification did not use hmac.compare_digest"


@pytest.mark.parametrize(
    "sig",
    [
        pytest.param("é" * 64, id="non-ascii"),
        pytest.param("Z" * 64, id="non-hex-ascii"),
        pytest.param(" ", id="line-separator"),
    ],
)
def test_a_non_ascii_or_non_hex_signature_answers_false_and_never_raises(sig: str) -> None:
    """FX-10 (NT-M6): `hmac.compare_digest` raises TypeError on a non-ASCII str.

    A query string is caller-controlled, so a crafted `sig` must mean "not signed", never a 500.
    """
    exp = int(_NOW) + 600
    assert not signing.verify_artifact_signature(_ID, exp=str(exp), sig=sig, key=KEY, now=_NOW)

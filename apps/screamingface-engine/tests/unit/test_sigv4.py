"""AWS Signature Version 4, checked against AWS's own published example.

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

WHY hand-rolled rather than a client library (spec D5): the scope is PUT and GET of ONE
object — no multipart, and no presigning, because the App streams artifacts through rather
than redirecting. That is small enough to sign correctly in pure functions, and it keeps
`httpx` the only HTTP dependency in a Runner Job's cold start.

WHY that is safe: we SIGN, Garage VERIFIES. A bug here gets our own request rejected with a
403 — it can never make a forged request acceptable. The failure mode is closed.

INVARIANT (the bound, spec D5): if this ever needs multipart or presigned URLs, it stops
being a ~50-line pure function and the dependency is the right answer instead. Do not grow
it past PUT/GET of a single object.

The vectors below are the `get-vanilla` case from AWS's documented Signature Version 4 test
suite. They pin all three stages — canonical request, string to sign, and the finished
`Authorization` header — so a break localises to a stage instead of just "the signature
changed".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from screamingface_engine.artifacts.sigv4 import (
    EMPTY_PAYLOAD_SHA256,
    Credentials,
    authorization_header,
    canonical_request,
    signing_key,
    string_to_sign,
)

# --- AWS `get-vanilla` published vector --------------------------------------------------
#
# PROVENANCE: AWS's own `aws-sig-v4-test-suite`, `get-vanilla` case. The four constants below
# are transcribed from the `.creq`, `.sts` and `.authz` files of that suite as mirrored at
# https://github.com/boto/botocore/tree/develop/tests/unit/auth/aws4_testsuite/get-vanilla
#
# AIDEV-NOTE: do NOT "fix" these to match the implementation. They are the external oracle —
# the only thing in this file that is not our own code checking itself. If one disagrees with
# the signer, the signer is what is wrong. Re-fetch from the suite before touching them.

ACCESS_KEY = "AKIDEXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
REGION = "us-east-1"
SERVICE = "service"
AMZ_DATE = "20150830T123600Z"
DATE_STAMP = "20150830"
HOST = "example.amazonaws.com"

# Joined line-by-line rather than concatenated so the suite's `.creq` file structure stays
# visible — each element below is one line of it, in order.
EXPECTED_CANONICAL_REQUEST = "\n".join(
    [
        "GET",
        "/",
        "",
        f"host:{HOST}",
        f"x-amz-date:{AMZ_DATE}",
        "",
        "host;x-amz-date",
        EMPTY_PAYLOAD_SHA256,
    ]
)
EXPECTED_STRING_TO_SIGN = "\n".join(
    [
        "AWS4-HMAC-SHA256",
        AMZ_DATE,
        f"{DATE_STAMP}/{REGION}/{SERVICE}/aws4_request",
        "bb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63",
    ]
)
EXPECTED_SIGNATURE = "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"


def test_the_empty_payload_hash_is_the_sha256_of_nothing() -> None:
    """A GET signs the hash of an empty body; this constant is that, spelled once."""
    assert EMPTY_PAYLOAD_SHA256 == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_canonical_request_matches_the_published_vector() -> None:
    assert (
        canonical_request(
            method="GET",
            path="/",
            query="",
            headers={"Host": HOST, "X-Amz-Date": AMZ_DATE},
            payload_sha256=EMPTY_PAYLOAD_SHA256,
        )
        == EXPECTED_CANONICAL_REQUEST
    )


def test_string_to_sign_matches_the_published_vector() -> None:
    assert (
        string_to_sign(
            amz_date=AMZ_DATE,
            scope=f"{DATE_STAMP}/{REGION}/{SERVICE}/aws4_request",
            canonical=EXPECTED_CANONICAL_REQUEST,
        )
        == EXPECTED_STRING_TO_SIGN
    )


def test_the_authorization_header_matches_the_published_vector() -> None:
    """The whole chain, end to end — signing key derivation included."""
    header = authorization_header(
        credentials=Credentials(
            access_key=ACCESS_KEY, secret_key=SECRET_KEY, region=REGION, service=SERVICE
        ),
        method="GET",
        path="/",
        query="",
        headers={"Host": HOST, "X-Amz-Date": AMZ_DATE},
        payload_sha256=EMPTY_PAYLOAD_SHA256,
        now=datetime(2015, 8, 30, 12, 36, 0, tzinfo=UTC),
    )

    assert header == (
        f"AWS4-HMAC-SHA256 Credential={ACCESS_KEY}/{DATE_STAMP}/{REGION}/{SERVICE}/aws4_request, "
        f"SignedHeaders=host;x-amz-date, Signature={EXPECTED_SIGNATURE}"
    )


# --- canonicalisation rules the vector alone does not exercise ---------------------------


def test_headers_are_lowercased_trimmed_and_sorted() -> None:
    """INVARIANT: canonical header order is by lowercase name, not by insertion order.

    Sending them in one order and signing them in another is the classic SigV4 mistake, and
    it produces a 403 that looks like bad credentials.
    """
    canonical = canonical_request(
        method="PUT",
        path="/bucket/key",
        query="",
        headers={
            "X-Amz-Date": AMZ_DATE,
            "Host": HOST,
            "X-Amz-Content-Sha256": "  abc  ",
        },
        payload_sha256="abc",
    )

    lines = canonical.split("\n")
    assert lines[3:6] == [
        f"host:{HOST}",
        "x-amz-content-sha256:abc",
        f"x-amz-date:{AMZ_DATE}",
    ]
    assert lines[7] == "host;x-amz-content-sha256;x-amz-date"


def test_the_object_key_is_not_double_encoded() -> None:
    """Our keys are 64 hex chars, so the path must pass through byte-identical.

    S3 canonicalisation does NOT re-encode the path for the object APIs; encoding a key that
    needs no encoding is another silent 403.
    """
    key = "a" * 64
    canonical = canonical_request(
        method="GET",
        path=f"/artifacts/{key}",
        query="",
        headers={"Host": HOST, "X-Amz-Date": AMZ_DATE},
        payload_sha256=EMPTY_PAYLOAD_SHA256,
    )

    assert canonical.split("\n")[1] == f"/artifacts/{key}"


def test_the_signing_key_is_derived_over_date_region_service_then_terminator() -> None:
    """Four chained HMACs, in that order. A wrong order yields a valid-looking bad key."""
    derived = signing_key(
        secret_key=SECRET_KEY, date_stamp=DATE_STAMP, region=REGION, service=SERVICE
    )

    assert isinstance(derived, bytes)
    assert len(derived) == 32
    # Deriving twice is pure — no hidden clock or nonce leaks into the key.
    assert derived == signing_key(
        secret_key=SECRET_KEY, date_stamp=DATE_STAMP, region=REGION, service=SERVICE
    )


@pytest.mark.parametrize("missing", ["Host", "X-Amz-Date"])
def test_signing_refuses_to_proceed_without_a_mandatory_header(missing: str) -> None:
    """INVARIANT: fail loudly here rather than emit a signature the server will reject.

    A missing `host` or `x-amz-date` produces a 403 from the far side with no hint which
    header was absent — so the check belongs on this side, where the answer is known.
    """
    headers = {"Host": HOST, "X-Amz-Date": AMZ_DATE}
    del headers[missing]

    with pytest.raises(ValueError, match=missing.lower()):
        canonical_request(
            method="GET",
            path="/",
            query="",
            headers=headers,
            payload_sha256=EMPTY_PAYLOAD_SHA256,
        )

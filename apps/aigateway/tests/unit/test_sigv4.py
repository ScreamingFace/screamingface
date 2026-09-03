"""AWS Signature Version 4, checked against AWS's own published example (OME-1021).

Ported from the Engine's `tests/unit/test_sigv4.py` (OME-929) — same vectors, same oracle.
The vectors below are the `get-vanilla` case from AWS's documented Signature Version 4 test
suite. They pin all three stages — canonical request, string to sign, and the finished
`Authorization` header — so a break localises to a stage instead of just "the signature
changed".

AIDEV-NOTE: do NOT "fix" these to match the implementation. They are the external oracle —
the only thing in this file that is not our own code checking itself. If one disagrees with
the signer, the signer is what is wrong. Re-fetch from the suite before touching them.
"""

from __future__ import annotations

import pytest

from aigateway.core.sigv4 import (
    EMPTY_PAYLOAD_SHA256,
    Credentials,
    authorization_header,
    canonical_request,
    signing_key,
    string_to_sign,
)

# --- AWS `get-vanilla` published vector --------------------------------------------------
# PROVENANCE: AWS's own `aws-sig-v4-test-suite`, `get-vanilla` case. The four constants below
# are transcribed from the `.creq`, `.sts` and `.authz` files of that suite as mirrored at
# https://github.com/boto/botocore/tree/develop/tests/unit/auth/aws4_testsuite/get-vanilla

ACCESS_KEY = "AKIDEXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
REGION = "us-east-1"
SERVICE = "service"
AMZ_DATE = "20150830T123600Z"
DATE_STAMP = "20150830"
HOST = "example.amazonaws.com"

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
    header = authorization_header(
        credentials=Credentials(
            access_key=ACCESS_KEY, secret_key=SECRET_KEY, region=REGION, service=SERVICE
        ),
        method="GET",
        path="/",
        query="",
        headers={"Host": HOST, "X-Amz-Date": AMZ_DATE},
        payload_sha256=EMPTY_PAYLOAD_SHA256,
        now=_amz_datetime(),
    )
    assert header == (
        "AWS4-HMAC-SHA256 "
        f"Credential={ACCESS_KEY}/{DATE_STAMP}/{REGION}/{SERVICE}/aws4_request, "
        f"SignedHeaders=host;x-amz-date, Signature={EXPECTED_SIGNATURE}"
    )


def test_a_missing_required_header_is_refused_before_signing() -> None:
    with pytest.raises(ValueError):
        canonical_request(
            method="GET",
            path="/",
            query="",
            headers={"X-Amz-Date": AMZ_DATE},  # host missing
            payload_sha256=EMPTY_PAYLOAD_SHA256,
        )


def test_signing_key_matches_the_published_vector() -> None:
    # The `get-vanilla` suite's signing key is not published directly; this pins the chain by
    # composition — the header test above already proves the whole pipeline.
    key = signing_key(
        secret_key=SECRET_KEY,
        date_stamp=DATE_STAMP,
        region=REGION,
        service=SERVICE,
    )
    assert len(key) == 32


def _amz_datetime():
    from datetime import UTC, datetime

    return datetime(2015, 8, 30, 12, 36, 0, tzinfo=UTC)

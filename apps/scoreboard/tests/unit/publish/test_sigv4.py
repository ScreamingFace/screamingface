"""The SigV4 copy (`adapters/sigv4.py`) against the published AWS GET Object example.

FEATURE: OME-1307 (E14). WHY: the file is a copy of `apps/aigateway/src/aigateway/core/sigv4.py`
(OD-5), so nothing else here pins its math. The vector is the "GET Object" example of the AWS
Signature Version 4 documentation (bucket `examplebucket`, key `test.txt`, a Range header).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scoreboard.adapters.sigv4 import (
    EMPTY_PAYLOAD_SHA256,
    Credentials,
    authorization_header,
    canonical_request,
)

_CREDENTIALS = Credentials(
    access_key="AKIAIOSFODNN7EXAMPLE",
    secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    region="us-east-1",
)
_HEADERS = {
    "Host": "examplebucket.s3.amazonaws.com",
    "Range": "bytes=0-9",
    "X-Amz-Content-Sha256": EMPTY_PAYLOAD_SHA256,
    "X-Amz-Date": "20130524T000000Z",
}


def test_the_copy_reproduces_the_aws_get_object_signature() -> None:
    header = authorization_header(
        credentials=_CREDENTIALS,
        method="GET",
        path="/test.txt",
        query="",
        headers=_HEADERS,
        payload_sha256=EMPTY_PAYLOAD_SHA256,
        now=datetime(2013, 5, 24, tzinfo=UTC),
    )

    assert header == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request,"
        " SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,"
        " Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


@pytest.mark.parametrize("missing", ["Host", "X-Amz-Date"])
def test_a_request_without_host_or_date_is_refused_before_it_is_signed(missing: str) -> None:
    headers = {name: value for name, value in _HEADERS.items() if name != missing}

    with pytest.raises(ValueError, match=missing.lower()):
        canonical_request(
            method="GET", path="/", query="", headers=headers, payload_sha256=EMPTY_PAYLOAD_SHA256
        )

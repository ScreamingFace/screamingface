"""AWS Signature Version 4 — the narrow slice needed to PUT and GET one object.

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment (OME-929).

WHY hand-rolled (spec D5): the whole requirement is two unsigned-query requests against our
own S3-compatible endpoint. No multipart, and no presigning — the App streams artifacts
through rather than redirecting a client at storage. That fits in pure functions and keeps
`httpx` the only HTTP dependency a Runner Job loads.

WHY that is safe: we SIGN and the server VERIFIES. A defect here makes our own request fail
with 403; it cannot make a forged request acceptable. The failure mode is closed, which is
the property that makes hand-rolling defensible at all.

INVARIANT (the bound): this stays PUT/GET of a single object. Multipart, presigned URLs, or
chunked payload signing are the signal to take a real S3 client instead of growing this.

Everything here is pure — no I/O, no ambient clock. `now` is a parameter so the signature is
reproducible in a test, which is what lets it be checked against AWS's published vectors.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

ALGORITHM = "AWS4-HMAC-SHA256"

EMPTY_PAYLOAD_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
"""sha256 of the empty byte string — what a GET or HEAD signs as its payload hash."""

# INVARIANT: both must be signed. `host` binds the signature to this endpoint and `x-amz-date`
# bounds its lifetime; without either, a captured signature is replayable somewhere or
# forever. The server rejects their absence with an opaque 403, so we refuse earlier, where
# we can say which one is missing.
_REQUIRED_HEADERS = ("host", "x-amz-date")

_TERMINATOR = "aws4_request"


@dataclass(frozen=True)
class Credentials:
    """One S3-compatible endpoint's signing identity.

    AIDEV-NOTE: `secret_key` is credential material. It is never logged and never rendered —
    `dataclass(frozen=True)` gives this a `__repr__` that WOULD print it, so do not put an
    instance into a log line or an exception message.
    """

    access_key: str
    secret_key: str
    region: str
    service: str = "s3"


def canonical_request(
    *,
    method: str,
    path: str,
    query: str,
    headers: Mapping[str, str],
    payload_sha256: str,
) -> str:
    """The canonical request: the exact bytes whose hash goes into the string to sign.

    `path` passes through unencoded. S3's object APIs do NOT re-encode the key, and our keys
    are 64 lowercase hex characters, so there is nothing to encode — re-encoding a key that
    needs none is a silent 403.
    """
    lowered = {name.lower(): value.strip() for name, value in headers.items()}
    for required in _REQUIRED_HEADERS:
        if required not in lowered:
            raise ValueError(f"SigV4 requires the {required} header to be signed")
    names = sorted(lowered)
    canonical_headers = "".join(f"{name}:{lowered[name]}\n" for name in names)
    signed_headers = ";".join(names)
    return "\n".join(
        [method, path, query, canonical_headers + "\n" + signed_headers, payload_sha256]
    )


def signed_headers_of(headers: Mapping[str, str]) -> str:
    """The `SignedHeaders` list — the same names, in the same order, as the canonical block.

    Derived from one place so the header list sent and the header list signed cannot drift;
    computing them separately is the classic way to produce a 403 that reads as bad keys.
    """
    return ";".join(sorted(name.lower() for name in headers))


def string_to_sign(*, amz_date: str, scope: str, canonical: str) -> str:
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "\n".join([ALGORITHM, amz_date, scope, digest])


def signing_key(*, secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """Four chained HMACs: date, region, service, terminator. Order is part of the spec."""
    key = f"AWS4{secret_key}".encode()
    for part in (date_stamp, region, service, _TERMINATOR):
        key = hmac.new(key, part.encode("utf-8"), hashlib.sha256).digest()
    return key


def authorization_header(
    *,
    credentials: Credentials,
    method: str,
    path: str,
    query: str,
    headers: Mapping[str, str],
    payload_sha256: str,
    now: datetime,
) -> str:
    """The finished `Authorization` value for one request."""
    date_stamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{date_stamp}/{credentials.region}/{credentials.service}/{_TERMINATOR}"
    canonical = canonical_request(
        method=method,
        path=path,
        query=query,
        headers=headers,
        payload_sha256=payload_sha256,
    )
    signature = hmac.new(
        signing_key(
            secret_key=credentials.secret_key,
            date_stamp=date_stamp,
            region=credentials.region,
            service=credentials.service,
        ),
        string_to_sign(amz_date=amz_date, scope=scope, canonical=canonical).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return (
        f"{ALGORITHM} Credential={credentials.access_key}/{scope}, "
        f"SignedHeaders={signed_headers_of(headers)}, Signature={signature}"
    )


__all__ = [
    "ALGORITHM",
    "EMPTY_PAYLOAD_SHA256",
    "Credentials",
    "authorization_header",
    "canonical_request",
    "signed_headers_of",
    "signing_key",
    "string_to_sign",
]

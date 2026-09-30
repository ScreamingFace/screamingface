"""Plain helpers of the SB-submit tests: receipts, identities and url4 constants.

FEATURE: OME-1307 (E14). SB-grants and SB-publish import this module
(`from tests.unit.submissions._receipts import ...`), so the names are stable.

These are functions and constants, not fixtures, so a test outside this directory can use them.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any, NamedTuple

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from httpx import AsyncClient, Response

# WHY these two texts: the route runs the real `Url4Fingerprinter` (SB-registry), and a text such as
# `url4://bench/cand-a` does not parse. Both parse, and they give two different fingerprints
# (checked with the merged `url4.fingerprint`).
URL4_A = "(https://model.test/cand-a)!'answer'"
URL4_B = "(https://model.test/cand-b)!'answer'"

ANA = "ana@x.org"
BRUNO = "bruno@y.org"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
KID = "gw-test-1"


def as_user(email: str) -> dict[str, str]:
    """The header the mesh injects after it verifies Cloudflare Access."""
    return {"X-User-Email": email}


class ReceiptKey(NamedTuple):
    kid: str
    private_key: Ed25519PrivateKey
    public_b64: str


def new_receipt_key(kid: str = KID) -> ReceiptKey:
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return ReceiptKey(kid, private_key, base64.b64encode(raw).decode())


def default_claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": "aigateway",
        "aud": "scoreboard",
        "sub": ANA,
        "vid": str(uuid.uuid4()),
        "tid": TRACE_ID,
        "sha": "a" * 64,
        "n": 412,
        "c": 420,
        "cov": "complete",
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return claims


def make_receipt(key: ReceiptKey, *, kid: str | None = None, **overrides: Any) -> str:
    """A receipt signed with `key`. An override set to `None` drops that claim."""
    claims = {k: v for k, v in default_claims(**overrides).items() if v is not None}
    return jwt.encode(
        claims,
        key.private_key,
        algorithm="EdDSA",
        headers={"kid": kid if kid is not None else key.kid},
    )


def payload(**overrides: Any) -> dict[str, Any]:
    """A valid `POST /v1/scores` body, like `_valid_payload` of `test_scores_routes.py`."""
    body: dict[str, Any] = {
        "benchmark_id": "pub",
        "spec_id": "kevins-best",
        "url4_expression": URL4_A,
        "submitted_by": "tester",
        "trace_id": TRACE_ID,
        "score": 0.75,
        "total_questions": 4,
        "correct_questions": 3,
        "ran_with_providers": ["openai"],
        "run_cost_usd": "1.250000",
        "run_cost_status": "complete",
        "ran_at_local": "2026-05-21T12:00:00+00:00",
        "client": {"name": "scoreboard-test", "version": "0.1.0", "platform": "test"},
        "metadata": {"source": "unit"},
    }
    body.update(overrides)
    return body


async def post_score(
    client: AsyncClient,
    *,
    user: str | None = ANA,
    key: str | None = None,
    receipt: str | None = None,
    **overrides: Any,
) -> Response:
    """`POST /v1/scores` as `user` (the mesh header), with an optional run id and receipt."""
    headers = as_user(user) if user is not None else {}
    if key is not None:
        headers["Idempotency-Key"] = key
    body = payload(**overrides)
    if receipt is not None:
        body["cache_version_receipt"] = receipt
    return await client.post("/v1/scores", json=body, headers=headers)

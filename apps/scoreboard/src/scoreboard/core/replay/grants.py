"""The replay grant (C6): the claims, the signer port and the errors of a resolved pin.

FEATURE: OME-1307 (E14) replay grants.
INVARIANT: standard library only. `jwt` stays in `adapters/`; this module owns the port.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

GRANT_ISSUER = "scoreboard"
GRANT_AUDIENCE = "aigateway"
# AIDEV-NOTE (D5): only the `disabled` dev/local fallback issues this subject. In
# cloudflare_headers (production) the route refuses a caller with no verified identity.
ANONYMOUS_SUBJECT = "anonymous"
GRANT_TTL_S = 43_200
"""INVARIANT (C6, D4): exp = iat + 43,200 s (12 h). No setting and no refresh.
WHY this is a known limit: the engine job deadline is 57,600 s
(apps/screamingface-engine/src/screamingface_engine/config.py:148-151) and a queued job can
also wait before it starts (worker/supervisor.py:833-858). So a grant can expire during a
run. Then the gateway refuses the grant and that run fails with the typed replay error (the
RP-14 path, ENG-replay). The user starts a new run with a new grant.
"""


class GrantSigner(Protocol):
    def sign(self, claims: Mapping[str, object]) -> str: ...


def build_grant_claims(
    *, subject: str | None, cache_version_id: UUID, result_id: UUID, now: datetime
) -> dict[str, object]:
    """The C6 claims, exactly. `subject` is the verified email in cloudflare_headers; None only in
    the `disabled` fallback, which gets `ANONYMOUS_SUBJECT`.
    """
    issued_at = int(now.timestamp())
    return {
        "iss": GRANT_ISSUER,
        "aud": GRANT_AUDIENCE,
        "sub": subject or ANONYMOUS_SUBJECT,
        "vid": str(cache_version_id),
        "rid": str(result_id),
        "iat": issued_at,
        "exp": issued_at + GRANT_TTL_S,
    }


# PinNotFound and InvalidPin are the SB-registry errors (scoreboard.core.registry).
class PinWithdrawn(Exception):
    """The pinned result is withdrawn and the caller is not its owner (-> 410)."""


class PinBenchmarkMismatch(Exception):
    """The pinned result belongs to another benchmark than the request names (-> 422)."""


@dataclass(frozen=True, slots=True)
class ResolvedReplay:
    result_id: UUID
    score_id: UUID
    cache_version_id: UUID
    # WHY: an owner may replay her own run on a private board; every other caller's answer rests on
    # a public board, which the route must re-prove before it signs (OME-894).
    via_owner: bool

"""The order the checks run in, which is the policy (spec §7).

```
mesh identity?  ->  yes: admitted, gate skipped, address bound to the report
                    no : rate limit  ->  bot gate  ->  admitted anonymously
```

Three things about that order are decisions rather than convenience:

**Identity short-circuits the gate.** Spec §7: a mesh-verified caller never sees a `403`. The
Turnstile widget is a browser affordance and a verified caller has already proved more than it
asks; requiring both would make the SDK's best-authenticated path its most awkward one.

**The rate limit runs before the bot gate.** Verifying a token is an outbound HTTP request this
service makes on an anonymous caller's say-so. Checking the budget first means a flood costs one
dictionary lookup rather than one round trip to Cloudflare per request — otherwise the gate meant
to absorb abuse would amplify it.

**The gate runs at the route, not as middleware.** Middleware would have to carry a path
exemption list to keep `/healthz` and `/readyz` answering, and an exemption list is a thing that
goes stale. Only `POST /v1/reports` is gated because only `POST /v1/reports` writes.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ..config import Settings
from ..core.problem_catalogue import rate_limited
from . import turnstile
from .mesh_identity import mesh_caller_email
from .rate_limit import TokenBucketLimiter, rate_limit_key


@dataclass(frozen=True, slots=True)
class Admission:
    """What the gate decided about one caller: who they are, and what "the same caller" means.

    The two are not the same question, which is why they are two fields. `caller_email` is
    identity and is written to a row and rendered into a ticket; `dedup_scope` is only ever
    hashed, and exists so a `Idempotency-Key` one caller chose cannot resolve another caller's
    report (spec §5's replay is per submitter, not per string).
    """

    caller_email: str | None
    """The mesh-verified address, or ``None`` for an admitted anonymous caller — which is exactly
    :attr:`Submission.caller_email`'s type, because "no verified identity" is a caller class here
    and not a failure."""

    dedup_scope: str
    """The namespace this caller's `Idempotency-Key` is resolved inside.

    The strongest value this service can honestly produce, which differs by caller class: a
    mesh-verified caller is scoped by the address the mesh verified, and an anonymous one by the
    same value the rate limiter counts against. Read the anonymous case for what it is — in a
    deployment the mesh proxy is the peer on every request, so anonymous callers share one scope
    unless the edge is trusted for a client address. It is not weaker than today's behaviour
    (which had no scope at all), and it removes the cross-caller leak entirely for the class this
    service can actually tell apart.
    """


async def admit(request: Request) -> Admission:
    """Decide whether this request may file a report, and who it is from.

    Raises the catalogued `429` or `403`/`503` when it may not; nothing has been stored at that
    point and the details say so.
    """
    settings: Settings = request.app.state.settings
    peer = request.client.host if request.client is not None else None
    if settings.auth_mode == "disabled":
        # No gate, and no identity either: `disabled` is bound to loopback by
        # `LoopbackOnlyMiddleware`, so there is no mesh to have injected an address and any
        # header claiming one came from the caller themselves. The peer is still a scope: every
        # caller in this mode is on the loopback interface, which is the honest ceiling.
        return Admission(caller_email=None, dedup_scope=peer or "")

    email = mesh_caller_email(request.headers, peer, settings.allowed_networks)
    if email is not None:
        return Admission(caller_email=email, dedup_scope=email)

    key = _spend_anonymous_budget(request, peer)
    await turnstile.enforce(request.headers, request.app.state.turnstile_verifier)
    return Admission(caller_email=None, dedup_scope=key)


def _spend_anonymous_budget(request: Request, peer: str | None) -> str:
    """Charge this request to its bucket, and answer with the key it was charged to."""
    settings: Settings = request.app.state.settings
    limiter: TokenBucketLimiter = request.app.state.anon_rate_limiter
    key = rate_limit_key(
        request.headers,
        peer,
        settings.allowed_networks,
        trust_client_ip_header=settings.trust_client_ip_header,
    )
    if key is None:
        # No visible peer means no way to attribute the request, and an unattributable
        # unauthenticated write is refused rather than admitted under a bucket every other
        # unattributable request would share. Unreachable under uvicorn, which always sets it.
        raise rate_limited(settings.anon_rate_window_s)
    decision = limiter.check(key)
    if not decision.allowed:
        raise rate_limited(decision.retry_after_s)
    return key

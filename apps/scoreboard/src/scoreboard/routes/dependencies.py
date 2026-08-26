"""Shared route dependencies.

FEATURE: OME-894 — private leaderboards need the caller's identity on GET paths that never had
one, across four routes. `_resolve_submitter` in `routes/scores.py` carries an AIDEV-NOTE saying
a second authenticated route does NOT inherit its check and that the next one should either
extract a proper `Depends()` or copy the call verbatim. This is that extraction, for reads.

WHY the decision itself lives in `core.auth.cloudflare_identity.optional_identity` and not here:
that module is the port and stays free of FastAPI and of Settings, so the whole trust decision is
testable without constructing a request. This file is only the adapter that pulls the four inputs
off the request.

AIDEV-NOTE: this is the READ dependency. It returns None instead of raising. Do NOT reuse it on a
write path — `_resolve_submitter` must keep 401-ing there, because a write with no verified
identity is a misconfigured mesh, not an anonymous visitor.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from scoreboard.config import Settings
from scoreboard.core.auth.cloudflare_identity import HEADER_USER_EMAIL, optional_identity


async def read_identity(request: Request) -> str | None:
    """The caller's verified email, or None when the request carries no usable identity."""
    settings = cast(Settings, request.app.state.settings)
    return optional_identity(
        header_auth_enabled=settings.auth_mode != "disabled",
        peer_host=request.client.host if request.client is not None else None,
        headers=request.headers,
        networks=settings.allowed_networks,
    )


ReadIdentity = Annotated[str | None, Depends(read_identity)]


# INVARIANT (OME-894): a response scoped to one caller must never be reused for another. Private
# responses vary by identity at a fixed URL, so a shared cache holding one participant's and
# replaying it is a direct leak. The refusals carry it too — they are identity-dependent as well,
# and replaying alice's 404 to bob would deny bob his own history.
# Applied at the privacy boundary rather than relying on the current proxy not caching, so a
# future proxy or configuration change cannot turn this into a data leak (review of PR #719).
PRIVATE_CACHE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Vary": f"{HEADER_USER_EMAIL}, Origin",
}

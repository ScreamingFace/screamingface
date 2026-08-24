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
from scoreboard.core.auth.cloudflare_identity import optional_identity


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

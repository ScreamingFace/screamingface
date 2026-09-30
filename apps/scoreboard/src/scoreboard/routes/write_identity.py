"""The verified caller of a write route (E14, D5).

FEATURE: OME-1307 (E14a) — `_resolve_submitter` in `routes/scores.py` carries an AIDEV-NOTE asking
for this extraction: a second authenticated write route must not skip the peer check and the
header check. This is that `Depends()`, for every new write route (metadata edit, later grants and
publish).

WHY a module of its own and not `routes/dependencies.py`: `routes/scores.py` imports
`routes/dependencies.py`, and this module imports `routes/scores.py` (for the verified-mode
allowlist and the untrusted-peer string), so putting it there would be an import cycle.

AIDEV-NOTE: `_resolve_submitter` is untouched. The legacy submit route keeps its body fallback
and its plain-string 401, which append-only tests pin.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status

from scoreboard.config import Settings
from scoreboard.core.auth.cloudflare_identity import (
    HEADER_USER_EMAIL,
    identity_from_headers,
    peer_in_networks,
)
from scoreboard.routes.scores import UNTRUSTED_PEER_DETAIL, identity_is_verified


async def write_identity(request: Request) -> str | None:
    """The verified caller of a write route (D5).

    cloudflare_headers: untrusted peer -> 403 UNTRUSTED_PEER_DETAIL (plain string); no
    X-User-Email -> 401 {"detail": {"code": "identity_not_verified", "message": ...}};
    else the verified email. disabled: None (dev/local fallback only; no header is read).

    INVARIANT: the peer check comes BEFORE the header read (cloudflare_identity.py), so an
    untrusted peer is refused without its identity claim ever being consulted.

    INVARIANT: no identity is a 401, never a silent fallback to anonymous — a misconfigured mesh
    must not turn into a service that lets a caller act without being verified.
    """
    settings = cast(Settings, request.app.state.settings)
    if not identity_is_verified(settings.auth_mode):
        return None
    if not peer_in_networks(
        request.client.host if request.client is not None else None,
        settings.allowed_networks,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=UNTRUSTED_PEER_DETAIL)
    email = identity_from_headers(request.headers)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "identity_not_verified",
                "message": (
                    f"Missing {HEADER_USER_EMAIL}: this service resolves the caller from the "
                    "identity header the mesh gateway injects after verifying Cloudflare Access."
                ),
            },
        )
    return email


WriteIdentity = Annotated[str | None, Depends(write_identity)]

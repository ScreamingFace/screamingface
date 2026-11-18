"""Who may claim a frozen copy (OME-1947, contracts K4).

The scoreboard claims the frozen copy of each Score, so that the expiry rule keeps the copy. A
claim changes the retention of a copy that a different account owns. Thus the claim is a separate
permission: only the addresses in `AIGW_FROZEN_COPY_CLAIM_EMAILS` have it.

INVARIANT: the claim list and the admin list are separate. An address on one list gets no access
through the other list.

INVARIANT: the guard makes no account row. It does not call `account_for_identity`, and it does
not write to the database.

INVARIANT: the guard checks the peer network before it reads the identity header, as
`require_admin` does.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .admin import email_is_admin as email_in_allowlist
from .cloudflare_identity import HEADER_USER_EMAIL, identity_from_headers, peer_in_networks

_WRONG_MODE = (
    "The claim route needs AIGW_AUTH_MODE=cloudflare_headers: a bearer token carries no address "
    "to compare with the claim list."
)
_NO_CLAIMERS = (
    "The claim route is disabled: no claim addresses are set. Set "
    "AIGW_FROZEN_COPY_CLAIM_EMAILS to enable it."
)
_UNTRUSTED_PEER = (
    "This gateway accepts header identity only from the networks it was configured to trust."
)
_NO_IDENTITY = (
    f"Missing {HEADER_USER_EMAIL}: the claim route identifies the caller from the identity "
    "header that the mesh gateway injects."
)
_NOT_A_CLAIMER = "This caller may not claim a frozen copy."


async def require_copy_claimer(request: Request) -> None:
    """Accept the caller of the claim route, or raise an `HTTPException`.

    The order of the checks is the order of contracts K4: `jwt` mode (503), `disabled` mode
    (accept), an empty claim list (503), an untrusted peer (403), no identity (401), an address
    that is not in the claim list (403). The messages do not name the caller or the networks.
    """
    settings = request.app.state.settings
    if settings.auth_mode == "jwt":
        raise HTTPException(status_code=503, detail=_WRONG_MODE)
    # WHY no list in `disabled` mode: that mode is loopback only (AuthDisabledLocalOnlyMiddleware).
    if settings.auth_mode == "disabled":
        return
    if not settings.frozen_copy_claim_emails:
        raise HTTPException(status_code=503, detail=_NO_CLAIMERS)
    peer = request.client.host if request.client is not None else None
    if not peer_in_networks(peer, settings.allowed_networks):
        raise HTTPException(status_code=403, detail=_UNTRUSTED_PEER)
    identity = identity_from_headers(request.headers)
    if identity is None:
        raise HTTPException(status_code=401, detail=_NO_IDENTITY)
    if not email_in_allowlist(identity.email, settings.frozen_copy_claim_emails):
        raise HTTPException(status_code=403, detail=_NOT_A_CLAIMER)

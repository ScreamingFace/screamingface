"""Who may claim a frozen copy (OME-1947, contracts K4).

The scoreboard claims the frozen copy of each Score, so that the expiry rule keeps the copy.

WHY the guard checks the peer only (owner decision 2026-11-25): in `cloudflare_headers` mode the
users do not reach the gateway. Only the services in the cluster reach it, and the NetworkPolicy is
the boundary. A list of addresses protects nothing here: each pod in the cluster can send the same
fixed address in a header. Thus the claim route accepts each peer in `AIGW_ALLOWED_NETWORKS` or in
`AIGW_FROZEN_COPY_CLAIM_NETWORKS`, with no identity header and no address list.

INVARIANT: the guard reads no request header, makes no account row and writes nothing. It does not
call `account_for_identity`.

INVARIANT: a peer on `AIGW_FROZEN_COPY_CLAIM_NETWORKS` is trusted here and nowhere else. The
scoreboard pods go on that list, not on `AIGW_ALLOWED_NETWORKS`: a peer on the second list may name
any user on every authenticated route.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from .cloudflare_identity import peer_in_networks

_WRONG_MODE = (
    "The claim route needs AIGW_AUTH_MODE=cloudflare_headers: it trusts the peer network of the "
    "caller, and jwt mode has no peer network list."
)
_UNTRUSTED_PEER = "This gateway accepts a claim only from the networks it was configured to trust."


async def require_copy_claimer(request: Request) -> None:
    """Accept the caller of the claim route, or raise an `HTTPException`.

    The order of the checks: `jwt` mode (503), `disabled` mode (accept), an untrusted peer (403).
    The messages do not name the caller or the networks.

    A trusted peer is in `allowed_networks` (the mesh gateway) or in `frozen_copy_claim_networks`
    (the scoreboard pods).
    """
    settings = request.app.state.settings
    if settings.auth_mode == "jwt":
        raise HTTPException(status_code=503, detail=_WRONG_MODE)
    # WHY no peer check in `disabled` mode: that mode is loopback only
    # (AuthDisabledLocalOnlyMiddleware).
    if settings.auth_mode == "disabled":
        return
    peer = request.client.host if request.client is not None else None
    trusted = (*settings.allowed_networks, *settings.frozen_copy_claim_networks)
    if not peer_in_networks(peer, trusted):
        raise HTTPException(status_code=403, detail=_UNTRUSTED_PEER)

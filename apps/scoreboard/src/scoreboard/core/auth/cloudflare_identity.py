"""Resolving the submitter from the identity header the mesh gateway injects.

https://pulse.dev.openmined.org/docs/products/gateway-identity-flow/ — Cloudflare Access
authenticates the caller at the edge and issues a signed assertion; the request reaches the
cluster through a `cloudflared` tunnel, where Envoy **re-verifies that assertion against
Cloudflare's JWKS** and translates the verified claims into plain HTTP headers. Envoy also clears
any client-supplied copy of those headers first, so a caller cannot forge one.

This service therefore does no token work of its own: identity arrives as `X-User-Email`, already
verified. Mirrors `apps/aigateway/src/aigateway/core/auth/cloudflare_identity.py`, simplified —
scoreboard has no accounts table, so the submitter is stored as a plain string, not looked up
against an `Account` model.

INVARIANT: the trust is a property of the NETWORK, not of this module. It holds only while this
service is unreachable except through that chain. Expose this port directly and anyone can claim
any identity with one header — see `peer_in_networks`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from ipaddress import IPv4Network, IPv6Address, IPv6Network, ip_address

HEADER_USER_EMAIL = "X-User-Email"
"""The one identity header this service reads.

A caller presenting no email is rejected rather than guessed at — see `identity_from_headers`.
"""


def peer_in_networks(host: str | None, networks: Sequence[IPv4Network | IPv6Network]) -> bool:
    """Whether the connecting peer falls inside one of ``networks``.

    ``host`` is the TCP peer (`request.client.host`).

    INVARIANT: never `X-Forwarded-For`, and never any other header. This check exists because
    `X-User-Email` is forgeable by anyone who can reach the port; deciding whether to trust it
    from a second header that is forgeable in exactly the same way would be circular. A
    deployment behind a proxy must declare the PROXY's address here.

    Fails closed on every uncertainty: no peer, an unparseable peer, or no declared networks all
    return False.
    """
    if host is None or not networks:
        return False
    try:
        peer = ip_address(host)
    except ValueError:
        return False
    # A dual-stack cluster reports an IPv4 peer as `::ffff:10.1.2.3`. Comparing that against an
    # IPv4 network returns False (`__contains__` short-circuits on version), so without this the
    # service would refuse every legitimate caller on such a cluster.
    if isinstance(peer, IPv6Address) and peer.ipv4_mapped is not None:
        peer = peer.ipv4_mapped
    return any(peer in network for network in networks)


def identity_from_headers(headers: Mapping[str, str]) -> str | None:
    """The caller's verified email, or ``None`` when the header carries none.

    ``headers`` must look up case-insensitively (Starlette's ``Headers`` does); header names are
    case-insensitive on the wire.

    ``None`` means "no identity present", NOT "anonymous" — the caller decides what to do with
    that. A present-but-blank header counts as absent: it carries no identity, and treating it as
    one would let a reader conclude a caller was authenticated when nothing said so.
    """
    email = (headers.get(HEADER_USER_EMAIL) or "").strip()
    return email or None


def optional_identity(
    *,
    header_auth_enabled: bool,
    peer_host: str | None,
    headers: Mapping[str, str],
    networks: Sequence[IPv4Network | IPv6Network],
) -> str | None:
    """The caller's verified email on a READ path, or ``None`` when there is none.

    FEATURE: OME-894 — private leaderboards. A private benchmark scopes every score-bearing read
    to the caller, which needs an identity on GET requests that never had one.

    WHY this does not raise, unlike `_resolve_submitter` on the write path: a PUBLIC board must
    stay anonymously readable, so "no identity" is an ordinary outcome here rather than a
    misconfiguration. The caller decides what absence means — for a public board, everything; for
    a private one, nothing.

    INVARIANT: the peer network is checked BEFORE the header is read, exactly as on the write
    path, so an untrusted peer never has its identity claim consulted.

    INVARIANT: with ``header_auth_enabled`` false there is no verified identity to be had, and a
    header present in that mode is an unverified claim. Honouring it would let anyone read a
    private board by setting one, so it is ignored rather than trusted. The practical consequence
    is deliberate and recorded in the OME-894 spec: while the deployment runs `auth_mode:
    disabled`, a private board is readable by nobody through the API and staff read it out of band.

    Kept free of FastAPI and of Settings on purpose — this module is the port, so the whole
    decision is testable without a request or an app.
    """
    if not header_auth_enabled:
        return None
    if not peer_in_networks(peer_host, networks):
        return None
    return identity_from_headers(headers)

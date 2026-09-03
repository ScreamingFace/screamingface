"""The caller's address, as the mesh verified it — and the only module that names the header.

https://pulse.dev.openmined.org/docs/products/gateway-identity-flow/ — Cloudflare Access
authenticates the caller at the edge and issues a signed assertion; the request reaches the
cluster through a `cloudflared` tunnel, where Envoy **re-verifies that assertion against
Cloudflare's JWKS** and translates the verified claims into plain HTTP headers. Envoy clears any
client-supplied copy of those headers first, so a caller cannot forge one. This service therefore
does no token work of its own, exactly as `apps/aigateway` does not.

INVARIANT — the trust is a property of the NETWORK, not of this module. `X-User-Email` is a plain
header: anyone who can reach this port can send one. It means something only while this service
is unreachable except through that chain, which is what :func:`peer_in_networks` checks and why
the peer is checked BEFORE the header is read. Nothing here can detect a misconfigured topology.

INVARIANT — this file is the one place in `src/report_intake` allowed to name the header.
`tests/unit/test_mesh_header_containment.py` asserts it by scanning the source tree, because
every additional reader is another place that has to repeat both conditions and the one that
forgets is indistinguishable from the ones that do not. `core/headers.read_allowed()` must never
return it.

INVARIANT — `reply_to` is not this. It is self-asserted by the reporter, it is never identity,
and it lives in the report body rather than anywhere near this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from ipaddress import IPv4Network, IPv6Address, IPv6Network, ip_address

MESH_IDENTITY_HEADER = "X-User-Email"
"""The one identity header this service reads.

Deliberately the only one. The flow also carries a tenant and, for automation, a Cloudflare
service token's `common_name`; both are dropped here. A report needs an address a human can be
answered at, and nothing in this service is authorized on identity at all — `caller_email` is a
column and a line in a ticket, never a permission.
"""

MAX_EMAIL_LENGTH = 254
"""RFC 5321's ceiling on an address. Longer than this is not an address.

Belt and braces on top of the peer check: this value is written to a row and rendered into a
ticket body, and a bound on it means a header cannot become an unbounded string downstream. An
over-long value is treated as ABSENT, which makes the caller anonymous and sends them to the bot
gate — the fail-closed direction.
"""


def peer_in_networks(host: str | None, networks: Sequence[IPv4Network | IPv6Network]) -> bool:
    """Whether the connecting peer falls inside one of ``networks``.

    ``host`` is the TCP peer (`request.client.host`).

    INVARIANT: never `X-Forwarded-For`, and never any other header. This check exists because
    `X-User-Email` is forgeable by anyone who can reach the port; deciding whether to trust it
    from a second header forgeable in exactly the same way would be circular and would restore
    the hole it closes. A deployment behind a proxy declares the PROXY's address here — and
    `create_app` refuses to start when uvicorn's `FORWARDED_ALLOW_IPS` would let a client rewrite
    that peer out from under this function.

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


def mesh_caller_email(
    headers: Mapping[str, str],
    peer: str | None,
    networks: Sequence[IPv4Network | IPv6Network],
) -> str | None:
    """The verified caller's address, or ``None`` when this request carries none.

    ``headers`` must look up case-insensitively (starlette's ``Headers`` does); header names are
    case-insensitive on the wire.

    The order is load-bearing and is the whole function: the peer is checked FIRST, so a request
    from outside the mesh never has its claim read at all. ``None`` means "no verified identity",
    which spec §7 calls an *anonymous* caller — a real caller class here, not a rejection.

    A present-but-blank header counts as absent: it carries no identity, and treating it as one
    would let a reader conclude a caller was authenticated when nothing said so.
    """
    if not peer_in_networks(peer, networks):
        return None
    # NOTE the ordering: nothing above this line reads the header.
    email = (headers.get(MESH_IDENTITY_HEADER) or "").strip()
    if not email or len(email) > MAX_EMAIL_LENGTH:
        return None
    return email

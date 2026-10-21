"""The destination policy of the url4 HTTP source guard (spec F1b, ``OME-1544``).

Standard library only: this module decides *whether* a destination may be fetched; the
httpx transport in :mod:`url4.io._guarded_transport` enforces it on every connection, and
:class:`~url4.io.http.HttpIOLayer` applies it before the first request.

FEATURE: url4 source fetch destination guard (OME-1544, fixes OME-1704).
STORY: as an operator running the engine, I let an expression name ``https://`` sources
without letting it reach my loopback, cluster network or cloud metadata endpoint.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from url4.core.errors import ErrorCode, ResolutionError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# WHY: RFC 6052's well-known NAT64 prefix embeds an IPv4 address in its last 32 bits, and
# `ipaddress` reports 64:ff9b::7f00:1 as global although it reaches 127.0.0.1 through NAT64.
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")

# WHY: the IPv4-compatible ``::/96`` (deprecated, RFC 4291) and SIIT ``::ffff:0:0:0/96``
# (obsolete, RFC 6145) forms embed an IPv4 address too, but no legitimate source uses them, and
# what a host stack does with one varies. They are refused OUTRIGHT, whatever they embed; the one
# exception is the loopback escape hatch, which still admits their loopback embeddings.
_DEPRECATED = (ipaddress.IPv6Network("::/96"), ipaddress.IPv6Network("::ffff:0:0:0/96"))
_EMBEDS_IPV4 = (_NAT64, *_DEPRECATED)

# WHY: ``ipaddress`` reports these as global although no source fetch may target them.
_ALSO_REFUSED = (ipaddress.IPv4Network("192.88.99.0/24"),)  # deprecated 6to4 relay (RFC 7526)

# ``::`` and ``::1`` sit inside ``::/96`` but are IPv6's own unspecified and loopback addresses.
_NOT_EMBEDDED = (ipaddress.IPv6Address("::"), ipaddress.IPv6Address("::1"))

# One inet_aton part: hex (``0x``, digits optional), octal (leading ``0``) or decimal. ASCII only.
_ATON_PART = re.compile(r"0[xX][0-9a-fA-F]*|0[0-7]*|[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class SourceGuard:
    """Operator configuration of the destination guard on :class:`~url4.io.http.HttpIOLayer`.

    Every field defaults to the strict value spec F1b names. ``peer_hosts`` is the
    operator-configured allowlist of ``url4://`` peer host names (case-insensitive, no
    port); empty means no remote-node calls at all. ``allow_loopback`` is the test/dev escape
    hatch: it admits loopback addresses only, never private or link-local ones.
    """

    allow_http: bool = False
    allow_loopback: bool = False
    peer_hosts: frozenset[str] = field(default_factory=frozenset)
    max_redirects: int = 3
    max_bytes: int = 20 * 1024 * 1024
    connect_timeout: float = 10.0
    total_timeout: float = 60.0

    def __post_init__(self) -> None:
        normalized = frozenset(_normal_host(host) for host in self.peer_hosts)
        object.__setattr__(self, "peer_hosts", normalized)


def destination_blocked(message: str) -> ResolutionError:
    return ResolutionError(message, code=ErrorCode.SOURCE_DESTINATION_BLOCKED, permanent=True)


def redirect_limit(message: str) -> ResolutionError:
    return ResolutionError(message, code=ErrorCode.SOURCE_REDIRECT_LIMIT, permanent=True)


def too_large(limit: int) -> ResolutionError:
    return ResolutionError(
        f"source body exceeds the {limit}-byte cap", code=ErrorCode.SOURCE_TOO_LARGE, permanent=True
    )


def source_timeout(message: str) -> ResolutionError:
    return ResolutionError(message, code=ErrorCode.SOURCE_TIMEOUT, permanent=False)


def check_destination(
    scheme: str,
    host: str,
    guard: SourceGuard,
    *,
    peer: bool = False,
    previous_scheme: str | None = None,
) -> IPAddress | None:
    """Refuse a hop by scheme, downgrade, peer allowlist or literal address.

    Returns the vetted address when ``host`` is an IP literal (in any form a resolver
    would accept), else ``None`` — a DNS name is vetted after resolution by the transport.
    """
    allowed = ("https", "http") if guard.allow_http else ("https",)
    if scheme not in allowed:
        raise destination_blocked(f"scheme {scheme!r} is not allowed for a source fetch")
    if previous_scheme == "https" and scheme == "http":
        raise destination_blocked("a redirect from https to http is refused")
    name = _normal_host(host)
    if peer and name not in guard.peer_hosts:
        raise destination_blocked(f"url4 peer {name!r} is not on the peer allowlist")
    address = literal_ip(name)
    if address is not None:
        vet_address(address, guard)
    return address


def check_url(url: str, guard: SourceGuard, *, peer: bool = False) -> None:
    """:func:`check_destination` on a URL string, before any request is built.

    WHY a stdlib parse: httpx rejects ``https://0177.0.0.1/`` as an invalid URL, so only a
    pre-check can report that loopback spelling as the blocked destination it is.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return  # malformed: the transport layer reports it as it always has
    check_destination(parts.scheme.lower(), host, guard, peer=peer)


def vet_address(address: IPAddress, guard: SourceGuard) -> None:
    """Refuse loopback, private, link-local, CGNAT, unspecified, multicast and reserved.

    INVARIANT: an IPv4 address embedded in IPv6 (mapped ``::ffff:a.b.c.d`` or NAT64) is judged
    as the IPv4 address it reaches. The deprecated IPv4-compatible ``::a.b.c.d`` and SIIT
    ``::ffff:0:a.b.c.d`` forms are refused whatever they embed (only the loopback escape hatch
    admits their loopback embeddings); ``::`` and ``::1`` keep IPv6's own rules.
    """
    effective = _unwrap(address)
    if guard.allow_loopback and effective.is_loopback:
        return
    if _refused(effective) or _deprecated(address):
        raise destination_blocked(f"address {address} is in a refused range")


def literal_ip(host: str) -> IPAddress | None:
    """``host`` as an IP address when it is one in any resolver-accepted spelling, else ``None``.

    Covers the plain forms plus the ``inet_aton`` ones (``2130706433``, ``0177.0.0.1``,
    ``0x7f.1``), which a libc resolver turns into an address without any DNS lookup.
    """
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return _inet_aton(host)


def _inet_aton(host: str) -> ipaddress.IPv4Address | None:
    values = _aton_parts(host)
    if values is None:
        return None
    *head, last = values
    tail_bits = 8 * (5 - len(values))  # the last part fills every byte the others leave
    if any(value > 0xFF for value in head) or last >= 1 << tail_bits:
        return None
    packed = 0
    for value in head:
        packed = packed << 8 | value
    return ipaddress.IPv4Address(packed << tail_bits | last)


def _aton_parts(host: str) -> list[int] | None:
    parts = host.split(".")
    if not 1 <= len(parts) <= 4 or not all(_ATON_PART.fullmatch(part) for part in parts):
        return None
    return [_aton_value(part) for part in parts]


def _aton_value(part: str) -> int:
    if part[:2].lower() == "0x":
        return int(part[2:] or "0", 16)
    return int(part, 8) if part.startswith("0") else int(part)


def _refused(address: IPAddress) -> bool:
    return (
        address.is_multicast
        or address.is_reserved
        or not address.is_global
        or any(address in network for network in _ALSO_REFUSED)
    )


def _deprecated(address: IPAddress) -> bool:
    return address not in _NOT_EMBEDDED and any(address in net for net in _DEPRECATED)


def _unwrap(address: IPAddress) -> IPAddress:
    if not isinstance(address, ipaddress.IPv6Address) or address in _NOT_EMBEDDED:
        return address
    embeds = address.ipv4_mapped is not None or any(address in net for net in _EMBEDS_IPV4)
    return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF) if embeds else address


def _normal_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


__all__ = [
    "SourceGuard",
    "check_destination",
    "check_url",
    "destination_blocked",
    "literal_ip",
    "redirect_limit",
    "source_timeout",
    "too_large",
    "vet_address",
]

"""The destination policy of the url4 source guard, without any transport (spec F1b, OME-1544).

FEATURE: url4 source fetch destination guard (OME-1544).
INVARIANT: every refused range is refused in every spelling a resolver would accept.
"""

from __future__ import annotations

import ipaddress

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.io._source_policy import (
    SourceGuard,
    check_destination,
    check_url,
    literal_ip,
    vet_address,
)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("2130706433", "127.0.0.1"),  # one decimal part
        ("0177.0.0.1", "127.0.0.1"),  # octal part
        ("0x7f.1", "127.0.0.1"),  # hex part + 24-bit tail
        ("0x7F.0.0.1", "127.0.0.1"),
        ("127.1", "127.0.0.1"),
        ("10.0.1", "10.0.0.1"),  # three parts: 16-bit tail
        ("0x", "0.0.0.0"),
        ("::1", "::1"),
        ("[::ffff:127.0.0.1]", "::ffff:7f00:1"),
    ],
)
def test_literal_ip_reads_every_resolver_spelling(host: str, expected: str) -> None:
    assert literal_ip(host) == ipaddress.ip_address(expected)


@pytest.mark.parametrize(
    "host",
    ["example.com", "1.2.3.4.5", "256.1.1.1", "1.2.3.example", "0x1g", "09.1.1.1", "１.2.3.4", ""],
)
def test_names_and_malformed_numbers_are_not_literals(host: str) -> None:
    assert literal_ip(host) is None


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "::1",
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",
        "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1, which ipaddress calls global
        "fc00::1",
        "fe80::1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "::",
        "224.0.0.1",  # multicast that ipaddress calls global
        "ff02::1",
        "240.0.0.1",  # reserved
        "2001:db8::1",  # documentation
    ],
)
def test_refused_ranges(address: str) -> None:
    with pytest.raises(ResolutionError) as caught:
        vet_address(ipaddress.ip_address(address), SourceGuard())
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED
    assert caught.value.permanent is True


@pytest.mark.parametrize("address", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_public_addresses_pass(address: str) -> None:
    vet_address(ipaddress.ip_address(address), SourceGuard())


def test_loopback_escape_hatch_admits_loopback_only() -> None:
    hatch = SourceGuard(allow_loopback=True)
    vet_address(ipaddress.ip_address("127.0.0.1"), hatch)
    vet_address(ipaddress.ip_address("::ffff:127.0.0.1"), hatch)
    with pytest.raises(ResolutionError):
        vet_address(ipaddress.ip_address("10.0.0.1"), hatch)
    with pytest.raises(ResolutionError):
        vet_address(ipaddress.ip_address("169.254.169.254"), hatch)


def test_defaults_are_the_strict_f1b_values() -> None:
    guard = SourceGuard()
    assert (guard.allow_http, guard.allow_loopback, guard.peer_hosts) == (False, False, frozenset())
    assert guard.max_redirects == 3


def test_peer_hosts_are_normalized() -> None:
    assert SourceGuard(peer_hosts=frozenset({" Node.Example. "})).peer_hosts == {"node.example"}


def test_scheme_policy() -> None:
    with pytest.raises(ResolutionError, match="scheme 'http'"):
        check_destination("http", "example.com", SourceGuard())
    assert check_destination("http", "example.com", SourceGuard(allow_http=True)) is None
    with pytest.raises(ResolutionError, match="scheme 'ftp'"):
        check_destination("ftp", "example.com", SourceGuard(allow_http=True))


def test_downgrade_is_refused_even_when_http_is_allowed() -> None:
    guard = SourceGuard(allow_http=True)
    with pytest.raises(ResolutionError, match="https to http"):
        check_destination("http", "example.com", guard, previous_scheme="https")
    check_destination("http", "example.com", guard, previous_scheme="http")


def test_peer_must_be_allowlisted() -> None:
    guard = SourceGuard(peer_hosts=frozenset({"node.example"}))
    with pytest.raises(ResolutionError, match="peer allowlist"):
        check_destination("https", "other.example", guard, peer=True)
    assert check_destination("https", "NODE.example.", guard, peer=True) is None
    check_destination("https", "other.example", guard)  # not a peer call: no allowlist


def test_check_url_refuses_a_spelling_httpx_cannot_parse() -> None:
    with pytest.raises(ResolutionError) as caught:
        check_url("https://0177.0.0.1/", SourceGuard())
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED


def test_check_url_leaves_malformed_urls_to_the_transport() -> None:
    check_url("https://[::1/", SourceGuard())  # urlsplit raises; not this layer's report


# --- review hardening: reserved IPv6 and embedded IPv4 forms (OME-1544) ----------------------


@pytest.mark.parametrize(
    "address",
    [
        "::7f00:1",  # IPv4-compatible ::/96 form of 127.0.0.1; ipaddress calls it global
        "::a9fe:a9fe",  # IPv4-compatible form of the 169.254.169.254 metadata address
        "::a00:1",  # IPv4-compatible form of 10.0.0.1
        "::ffff:0:7f00:1",  # SIIT ::ffff:0:0/96 form of 127.0.0.1
        "::ffff:0:a9fe:a9fe",  # SIIT form of the metadata address
        "::c058:6301",  # IPv4-compatible form of a 6to4 relay address
        "192.88.99.1",  # deprecated 6to4 relay anycast (RFC 7526); ipaddress calls it global
        "100::1",  # RFC 6666 discard-only prefix
    ],
)
def test_reserved_and_embedded_ipv4_forms_are_refused(address: str) -> None:
    with pytest.raises(ResolutionError) as caught:
        vet_address(ipaddress.ip_address(address), SourceGuard())
    assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED


def test_embedded_loopback_forms_follow_the_escape_hatch() -> None:
    hatch = SourceGuard(allow_loopback=True)
    vet_address(ipaddress.ip_address("::7f00:1"), hatch)
    vet_address(ipaddress.ip_address("::ffff:0:7f00:1"), hatch)
    vet_address(ipaddress.ip_address("::1"), hatch)  # plain IPv6 loopback is not unwrapped
    with pytest.raises(ResolutionError):
        vet_address(ipaddress.ip_address("::a9fe:a9fe"), hatch)


# --- review hardening 2: deprecated embedded forms refused outright (OME-1544) ----------------


@pytest.mark.parametrize(
    "address",
    [
        "::8.8.8.8",  # IPv4-compatible ::/96 (RFC 4291 deprecated), public embedded address
        "::ffff:0:808:808",  # SIIT ::ffff:0:0/96 (RFC 6145 obsolete), public embedded address
        "::1:0:0",  # just outside ::/96, inside the reserved ::/8: refused by the reserved rule
    ],
)
def test_deprecated_embedded_forms_are_refused_whatever_they_embed(address: str) -> None:
    for guard in (SourceGuard(), SourceGuard(allow_loopback=True)):
        with pytest.raises(ResolutionError) as caught:
            vet_address(ipaddress.ip_address(address), guard)
        assert caught.value.code == ErrorCode.SOURCE_DESTINATION_BLOCKED


def test_unspecified_and_ipv6_loopback_keep_their_own_rules() -> None:
    with pytest.raises(ResolutionError):
        vet_address(ipaddress.ip_address("::"), SourceGuard(allow_loopback=True))
    with pytest.raises(ResolutionError):
        vet_address(ipaddress.ip_address("::1"), SourceGuard())
    vet_address(ipaddress.ip_address("::1"), SourceGuard(allow_loopback=True))

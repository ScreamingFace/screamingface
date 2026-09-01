"""Scoreboard resolves the submitter from the identity header the mesh gateway injects.

The trust model is the deployment's, not this module's: Cloudflare Access authenticates at the
edge and Envoy re-verifies that assertion before injecting `X-User-Email`, so in
`cloudflare_headers` mode this service reads the header directly. Mirrors
apps/aigateway/tests/unit/auth/test_cloudflare_identity.py, simplified for a plain-string
submitter identity rather than an Account lookup.
"""

from __future__ import annotations

from ipaddress import ip_network

from starlette.datastructures import Headers

from scoreboard.core.auth.cloudflare_identity import (
    HEADER_USER_EMAIL,
    identity_from_headers,
    optional_identity,
)

EMAIL = "someone@openmined.org"


def test_a_caller_is_identified_by_their_verified_email() -> None:
    assert identity_from_headers({"X-User-Email": EMAIL}) == EMAIL


def test_no_identity_header_is_no_identity() -> None:
    """`None` means "nothing presented", which the route turns into a 401 — never anonymous."""
    assert identity_from_headers({}) is None


def test_a_blank_header_is_treated_as_absent() -> None:
    """Blank carries no identity; treating it as one would let a reader think a caller was known."""
    assert identity_from_headers({"X-User-Email": "   "}) is None


def test_the_header_is_read_case_insensitively() -> None:
    """Header names are case-insensitive on the wire, whatever casing the mesh emits.

    Exercised through Starlette's `Headers`, not a plain dict: the case-insensitivity is the
    mapping's, which is exactly the contract `identity_from_headers` documents for its argument.
    """
    assert identity_from_headers(Headers({"x-user-email": EMAIL})) == EMAIL


def test_surrounding_whitespace_is_stripped() -> None:
    assert identity_from_headers({"X-User-Email": f"  {EMAIL}  "}) == EMAIL


# --- OME-894: optional identity on READ paths ------------------------------------------------
# The write path (routes/scores.py) 401s when identity is absent. Reads cannot: a public board
# must stay anonymously readable, so absence is a normal state and resolves to None. What the
# two paths MUST share is the ordering — peer network first, header second.

_NETWORKS = (ip_network("10.0.0.0/8"),)


def test_header_auth_disabled_yields_no_identity_even_with_a_header() -> None:
    # INVARIANT: in `disabled` mode there is no verified identity to be had, so a private board
    # is readable by nobody (OME-894 D2). A header present in this mode is an unverified claim
    # and must never be honoured — that would make the entry challenge readable by anyone who
    # sets one.
    assert (
        optional_identity(
            header_auth_enabled=False,
            peer_host="10.0.0.5",
            headers={HEADER_USER_EMAIL: "attacker@evil.example"},
            networks=_NETWORKS,
        )
        is None
    )


def test_an_untrusted_peer_gets_no_identity_even_with_a_header() -> None:
    # INVARIANT: the peer network is checked BEFORE the header is read, carried over verbatim
    # from _resolve_submitter. An untrusted peer never has its claim consulted.
    assert (
        optional_identity(
            header_auth_enabled=True,
            peer_host="203.0.113.9",
            headers={HEADER_USER_EMAIL: "attacker@evil.example"},
            networks=_NETWORKS,
        )
        is None
    )


def test_a_trusted_peer_without_a_header_is_anonymous_not_an_error() -> None:
    assert (
        optional_identity(
            header_auth_enabled=True,
            peer_host="10.0.0.5",
            headers={},
            networks=_NETWORKS,
        )
        is None
    )


def test_a_trusted_peer_with_a_verified_header_is_identified() -> None:
    assert (
        optional_identity(
            header_auth_enabled=True,
            peer_host="10.0.0.5",
            headers={HEADER_USER_EMAIL: "alice@example.test"},
            networks=_NETWORKS,
        )
        == "alice@example.test"
    )


def test_no_declared_networks_yields_no_identity() -> None:
    # Fails closed on the misconfiguration, matching peer_in_networks.
    assert (
        optional_identity(
            header_auth_enabled=True,
            peer_host="10.0.0.5",
            headers={HEADER_USER_EMAIL: "alice@example.test"},
            networks=(),
        )
        is None
    )

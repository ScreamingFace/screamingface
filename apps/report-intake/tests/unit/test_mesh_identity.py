"""`X-User-Email` is a plain header, so the peer is what makes it mean anything.

Every case here is one of the two conditions failing on its own, because the failure this module
exists to prevent is a request that satisfies one and is believed anyway.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from ipaddress import ip_network

from starlette.datastructures import Headers

from report_intake.identity.mesh_identity import (
    MAX_EMAIL_LENGTH,
    MESH_IDENTITY_HEADER,
    mesh_caller_email,
    peer_in_networks,
)

_MESH = (ip_network("10.0.0.0/8"),)


def _headers(email: str | None = "reporter@example.org") -> dict[str, str]:
    return {} if email is None else {MESH_IDENTITY_HEADER: email}


def test_a_forged_identity_header_from_outside_the_mesh_is_not_honoured() -> None:
    """Spec §10's first identity assertion. The header is forgeable by anyone who can reach the
    port; the peer is what the deployment vouches for."""
    assert mesh_caller_email(_headers(), "203.0.113.9", _MESH) is None


def test_the_mesh_injected_address_is_honoured_from_inside_the_declared_networks() -> None:
    assert mesh_caller_email(_headers(), "10.1.2.3", _MESH) == "reporter@example.org"


def test_an_ipv4_peer_reported_in_ipv4_mapped_form_resolves_against_an_ipv4_network() -> None:
    """A dual-stack cluster reports an IPv4 peer as `::ffff:10.1.2.3`, and `in` short-circuits on
    version — so without the normalization this refuses every legitimate caller."""
    assert mesh_caller_email(_headers(), "::ffff:10.1.2.3", _MESH) == "reporter@example.org"


def test_declaring_no_networks_means_no_header_is_ever_honoured() -> None:
    """The fail-closed default. `create_app` refuses to build a `mesh_or_turnstile` app without
    networks precisely so this state is unreachable in a deployment."""
    assert mesh_caller_email(_headers(), "10.1.2.3", ()) is None


def test_a_request_with_no_peer_is_not_believed() -> None:
    assert mesh_caller_email(_headers(), None, _MESH) is None


def test_an_unparseable_peer_is_not_believed() -> None:
    """Uvicorn always supplies an address, but starlette's TestClient defaults to the string
    `testclient` — and anything this cannot parse is refused rather than guessed at."""
    assert mesh_caller_email(_headers(), "testclient", _MESH) is None


def test_a_blank_header_carries_no_identity() -> None:
    """Present-but-empty is absent. Treating it as identity would let a reader conclude a caller
    was authenticated when nothing said so."""
    assert mesh_caller_email(_headers("   "), "10.1.2.3", _MESH) is None


def test_a_missing_header_from_inside_the_mesh_is_an_anonymous_caller() -> None:
    """`None` is a caller class here (spec §7), not a rejection — the gate decides what happens
    next."""
    assert mesh_caller_email(_headers(None), "10.1.2.3", _MESH) is None


def test_the_header_is_found_under_the_wire_spelling_a_real_request_carries() -> None:
    """Header names are case-insensitive on the wire and starlette lowercases them, so the lookup
    has to go through a case-insensitive mapping — asserted with the real one rather than with a
    dict, which would pass for the wrong reason."""
    headers = Headers(raw=[(b"x-user-email", b"reporter@example.org")])

    assert mesh_caller_email(headers, "10.1.2.3", _MESH) == "reporter@example.org"


def test_surrounding_whitespace_is_stripped_but_the_address_is_otherwise_untouched() -> None:
    """Not lowercased: this value is written to a row and rendered into a ticket a human reads,
    and the address as it actually arrived is the one to answer."""
    assert mesh_caller_email(_headers("  Reporter@Example.org "), "10.1.2.3", _MESH) == (
        "Reporter@Example.org"
    )


def test_an_implausibly_long_address_is_treated_as_absent() -> None:
    """Fail closed: an over-long value makes the caller anonymous and sends them to the bot gate,
    rather than becoming an unbounded string in a row and a ticket body."""
    too_long = "a" * MAX_EMAIL_LENGTH + "@example.org"

    assert mesh_caller_email(_headers(too_long), "10.1.2.3", _MESH) is None


def test_the_peer_check_answers_before_the_header_is_read() -> None:
    """The ordering is the whole function, so it is asserted directly rather than only through
    its consequences: a mapping that raises on lookup proves nothing read it."""

    class _Explodes(Mapping[str, str]):
        def __getitem__(self, key: str) -> str:  # pragma: no cover - must not run
            raise AssertionError("the identity header was read for an untrusted peer")

        def __iter__(self) -> Iterator[str]:
            return iter(())

        def __len__(self) -> int:
            return 0

    assert mesh_caller_email(_Explodes(), "203.0.113.9", _MESH) is None


def test_peer_in_networks_matches_only_the_networks_it_was_given() -> None:
    assert peer_in_networks("10.1.2.3", _MESH)
    assert not peer_in_networks("192.168.1.1", _MESH)
    assert not peer_in_networks("10.1.2.3", ())

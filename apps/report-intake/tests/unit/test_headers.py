"""The general request-header allowlist.

The interesting assertions here are about what is *not* returned. An allowlist's failure mode is
that it quietly grows, and the header it must never grow is the one identity rests on.
"""

from __future__ import annotations

from report_intake.core.headers import ALLOWED_REQUEST_HEADERS, read_allowed


def test_an_allowlisted_header_is_read() -> None:
    assert read_allowed({"Idempotency-Key": "abc"}) == {"idempotency-key": "abc"}


def test_header_names_are_matched_without_regard_to_case() -> None:
    """HTTP field names are case-insensitive, and a client that sends `IDEMPOTENCY-KEY` is not
    opting out of deduplication."""
    assert read_allowed({"IDEMPOTENCY-KEY": "abc"})["idempotency-key"] == "abc"


def test_a_header_nobody_asked_for_is_dropped_without_comment() -> None:
    """Not an error: a caller sending an unknown header is simply not listened to."""
    assert read_allowed({"X-Whatever": "1"}) == {}


def test_the_mesh_identity_header_is_never_returned() -> None:
    """INVARIANT. `X-User-Email` is honoured only when the mesh injected it, only after the peer
    check, and only in `OME-1011`'s one module. A general reader that returns it is how a
    client-supplied copy reaches code that believes it — the edge strips inbound copies, but the
    edge is one hop."""
    assert read_allowed({"X-User-Email": "attacker@example.org"}) == {}
    assert "x-user-email" not in ALLOWED_REQUEST_HEADERS


def test_the_bot_gate_header_is_not_in_the_general_allowlist_either() -> None:
    """Like the identity header, it is read once by the one module that evaluates it, rather than
    handed around by a general-purpose reader."""
    assert read_allowed({"Cf-Turnstile-Response": "token"}) == {}


def test_absent_headers_are_absent_rather_than_empty() -> None:
    """A caller that sent no `Idempotency-Key` cannot be deduplicated; an empty string would look
    like a key and collide with every other caller that sent none."""
    assert "idempotency-key" not in read_allowed({"Content-Type": "application/json"})

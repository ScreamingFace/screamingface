"""The no_network fixture: a grading test that reaches the internet fails here, not in prod.

INVARIANT (spec R16, R17): Grading downloads nothing. Loopback stays open because the
grading tests drive a url4 node over it.
"""

from __future__ import annotations

import socket

import pytest


def test_an_outbound_connection_is_refused(no_network: None) -> None:
    with pytest.raises(RuntimeError, match="outbound network is blocked"):
        socket.create_connection(("example.com", 443), timeout=1)


def test_a_connection_to_a_literal_address_is_refused(no_network: None) -> None:
    """WHY: a hard-coded IP skips DNS, so the connect itself must refuse too."""

    with socket.socket() as client:
        with pytest.raises(RuntimeError, match="outbound network is blocked"):
            client.connect(("93.184.216.34", 443))


def test_dns_is_refused_too(no_network: None) -> None:
    with pytest.raises(RuntimeError, match="outbound network is blocked"):
        socket.getaddrinfo("example.com", 443)


def test_loopback_still_works(no_network: None) -> None:
    server: socket.socket = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client: socket.socket = socket.create_connection(server.getsockname(), timeout=1)
        client.close()
    finally:
        server.close()

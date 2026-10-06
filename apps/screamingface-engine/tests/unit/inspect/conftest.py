"""Fixtures for the inspect lane.

FEATURE: Task-replay Imported Benchmarks (OME-1273). `no_network` is spec R17's tool: a
Benchmark's grading test runs under it, so a scorer that downloads fails in CI instead of in
a run pod that has no egress.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

#: Hosts a test may still reach: the grading tests drive a url4 node over loopback.
_LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost", ""})


def _refuse(host: Any) -> None:
    """Raise unless the host is loopback."""

    if str(host) not in _LOOPBACK:
        raise RuntimeError(f"outbound network is blocked in this test (spec R17): {host!r}")


def _refuse_address(address: Any) -> None:
    """Refuse an internet address; a Unix socket path is local and passes."""

    # WHY only tuples: AF_INET/AF_INET6 addresses are (host, port, ...); an AF_UNIX address
    # is a filesystem path, which never leaves the machine.
    if isinstance(address, tuple):
        _refuse(address[0])


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Block every socket connection and DNS lookup that is not loopback."""

    original_connect: Any = socket.socket.connect
    original_connect_ex: Any = socket.socket.connect_ex
    original_getaddrinfo: Any = socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> None:
        """socket.connect, refusing an internet address first."""

        _refuse_address(address)
        original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        """socket.connect_ex, refusing an internet address first."""

        _refuse_address(address)
        return original_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        """socket.getaddrinfo, refusing any name that is not loopback."""

        _refuse(host)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield

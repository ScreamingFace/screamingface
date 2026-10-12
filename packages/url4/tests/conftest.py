"""Shared test fixtures and helpers."""

from __future__ import annotations

import asyncio
import importlib
import socket
from types import ModuleType

import pytest

from url4 import IOLayer, StaticIOLayer
from url4.core.errors import ResolutionError
from url4.dag.nodes import guard as guard_module


@pytest.fixture
def hide_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import uvicorn`` fail, so the missing-``[server]``-extra branch is testable.

    # AIDEV-NOTE: a test must CREATE the condition it asserts. The two
    # missing-uvicorn branches (`cli._serve_forever`, `Url4Node.serve`) used to be
    # asserted by relying on the dev venv happening to lack the optional extra.
    # Once anyone ran `uv sync --extra server` — which the README tells them to —
    # the import succeeded, both tests fell through to the REAL `uvicorn.run()`,
    # bound 127.0.0.1:4404 and served forever: the suite hung with no failure and
    # no timeout. Only `uvicorn` is hidden, so unrelated imports still resolve.
    """
    real_import = importlib.import_module

    def without_uvicorn(name: str, package: str | None = None) -> ModuleType:
        if name == "uvicorn":
            raise ModuleNotFoundError("No module named 'uvicorn'")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", without_uvicorn)


@pytest.fixture(autouse=True)
def _no_real_listen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn any attempt to listen on a real port into a loud failure.

    # AIDEV-NOTE: defense in depth for the hang above. A unit test that binds a
    # port either hangs (port free) or fails with a confusing errno (port taken),
    # and which one you get depends on unrelated processes — the reason that bug
    # survived so long. Binding stays legal (ephemeral sockets, socketpair);
    # LISTENING does not, since that is what makes a test serve forever.
    """

    def guarded(self: socket.socket, *args: object) -> None:
        raise RuntimeError(
            f"unit test tried to listen on {self.getsockname()!r} — unit tests must not "
            "serve on a real port (it hangs the suite). Simulate the dependency instead; "
            "see the `hide_uvicorn` fixture."
        )

    monkeypatch.setattr(socket.socket, "listen", guarded)


@pytest.fixture(autouse=True)
def _instant_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real Spec C §13.3 backoff (0.5 s and more per retry) in every test.

    A retry test asserts how many attempts ran, not how long they waited; the
    schedule itself is pinned in tests/regressions/test_guard.py, which patches the
    same seam to record the delays.
    """

    async def no_wait(_delay: float) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(guard_module, "_sleep", no_wait)


class RecordingIOLayer:
    """An :class:`~url4.IOLayer` that records and serves every fetch (no network).

    Delegates to a :class:`~url4.StaticIOLayer` (``fetch_map`` for static reads,
    ``routes`` for localhost ``?q=`` expression endpoints), echoes ``"<target>"``
    for anything unmapped, and appends every fetched ``target`` to :attr:`fetches`
    so tests can assert dispatch order and the encoded ``?q=`` payloads.
    """

    def __init__(self, fetch_map: dict[str, str] | None = None, routes: dict | None = None) -> None:
        self._static = StaticIOLayer(fetch_map, routes)
        self.fetches: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.fetches.append(target)
        try:
            return await self._static.fetch(target, relative=relative)
        except ResolutionError:
            return f"<{target}>"

    def default_route(self) -> str | None:
        """Delegate SupportsDefaultRoute — first declared route, like the static layer."""
        return self._static.default_route()


# Structural check that the helper satisfies the port.
_: IOLayer = RecordingIOLayer()

"""The no-network tripwire shared by the remote-node refusal tests (OME-1811).

WHY one helper: each test proves a refused run makes zero requests by swapping the guarded
transport's inner transport for an ``httpx.MockTransport``. That needs url4's private
``_guarded_transport`` module; importing it here once keeps the engine's private-url4-import
ratchet (``test_url4_private_import_ratchet.py``) at one crossing for all of them.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

import url4.io._guarded_transport as gt


def install_tripwire(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    """Route every guarded outbound request to ``handler`` instead of the network."""
    monkeypatch.setattr(gt, "_inner_transport", lambda: httpx.MockTransport(handler))

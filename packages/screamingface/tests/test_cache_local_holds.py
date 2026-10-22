"""Whether the local gateway still holds a key (epic OME-1311, PR #1446 review round 3).

FEATURE: community cache, available to a local engine (epic OME-1311).

Pinned here: `LocalGateway.holds` asks the gateway's own loader, and a database that cannot be
read answers "no", so a resumed pull starts over rather than skip pages it cannot vouch for.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest

from screamingface._cache.local import LocalGateway
from screamingface.cache import PullResult


class _Rejected(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


def _gateway(monkeypatch: pytest.MonkeyPatch, answer: object) -> LocalGateway:
    loader = ModuleType("aigateway.core.request_cache.sqlite_loader")
    loader.PageRejected = _Rejected  # type: ignore[attr-defined]

    def holds(_database: Path, key_hash: str) -> bool:
        if isinstance(answer, BaseException):
            raise answer
        return key_hash in answer  # type: ignore[operator]

    loader.holds = holds  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aigateway.core.request_cache.sqlite_loader", loader)
    return LocalGateway(Path("aigateway.sqlite3"), empty=PullResult(0, 0, 0, False, False))


def test_holds_asks_the_gateways_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = _gateway(monkeypatch, {"a" * 64})

    assert gateway.holds("a" * 64) is True
    assert gateway.holds("b" * 64) is False


@pytest.mark.parametrize(
    "failure",
    [_Rejected("not_a_gateway_database", "gone"), sqlite3.OperationalError("locked")],
    ids=["refused", "unreadable"],
)
def test_a_database_that_cannot_be_read_holds_nothing(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    assert _gateway(monkeypatch, failure).holds("a" * 64) is False

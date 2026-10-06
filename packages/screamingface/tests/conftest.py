"""Shared fixtures for the Client SDK test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_PAID_FLAG = "SCREAMINGFACE_TEST_PAID"
_PAID_LANE: Path = Path(__file__).resolve().parent / "paid"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Drop every paid-lane test unless the paid button opened the fence.

    INVARIANT (OME-1275, owner rule): `tests/paid/` runs ONLY when someone presses the
    paid button — the `workflow_dispatch` workflow or the `test-paid-benchmarks` just
    recipe, both of which set SCREAMINGFACE_TEST_PAID=1. Merge CI runs plain `pytest`.
    WHY deselect instead of `collect_ignore`: the ignore list does not apply to a path
    named on the command line, so `pytest tests/paid` would slip through; deselection
    fences both, and pytest's summary still counts what it dropped. Pinned by
    `test_paid_lane_isolation.py`.
    """
    if os.environ.get(_PAID_FLAG) == "1":
        return
    fenced: list[pytest.Item] = [item for item in items if _PAID_LANE in item.path.parents]
    if not fenced:
        return
    config.hook.pytest_deselected(items=fenced)
    items[:] = [item for item in items if _PAID_LANE not in item.path.parents]


@pytest.fixture(autouse=True)
def _isolated_screamingface_data_dir(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: the suite never reads the developer's real `~/.screamingface`.
    # Since OME-998 the default client discovers a running `screamingface up` stack
    # from that data dir, so without this isolation any test building a default
    # client would change behavior based on whether the dev's local stack is up.
    # Tests that need populated local state set SCREAMINGFACE_DATA_DIR themselves.
    monkeypatch.setenv(
        "SCREAMINGFACE_DATA_DIR",
        str(tmp_path_factory.mktemp("screamingface-data")),
    )
    # INVARIANT (OME-1169): `up`/`restart` refuse to boot while AIGATEWAY_DATABASE_URL is
    # set, reading live os.environ — on a dev machine that exports it (exactly the
    # gateway-with-Postgres dev the refusal protects), every runtime test would fail with
    # the refusal instead of exercising its own contract. Tests that need the variable
    # set it themselves via monkeypatch.
    monkeypatch.delenv("AIGATEWAY_DATABASE_URL", raising=False)


__all__: list[str] = []

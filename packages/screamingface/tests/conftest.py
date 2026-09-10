"""Shared fixtures for the Client SDK test suite."""

from __future__ import annotations

import pytest


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

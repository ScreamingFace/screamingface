"""Keyless boot of the workbench ``local`` target: un-stubbed, spends nothing.

WHY: the notebook run is paid-gated, so without this the local target's wiring is only ever
checked against stubs — which is how a target serving only the built-in boards (no ifeval)
went unnoticed. This boots the real ``screamingface up`` + inspect-capable Engine and asks the
Engine what it lists. No BYOK key is connected, so no provider is ever called.

Gate: ``SCREAMINGFACE_TEST_E2E=1`` only — the local target needs no Docker (unlike the replay
lane's Postgres testcontainer).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from harness._gating import E2E_ENV

from workbench.targets import _listed_benchmarks, _prepared_ifeval_assets, local_stack


@pytest.mark.e2e
def test_local_target_boots_and_its_engine_lists_ifeval(tmp_path: Path) -> None:
    if os.environ.get(E2E_ENV) != "1":
        pytest.skip(f"{E2E_ENV}=1 not set (the local boot check is opt-in)")
    with local_stack(tmp_path, _prepared_ifeval_assets()) as target:
        assert "ifeval" in _listed_benchmarks(target.engine_url)
        assert target.scoreboard_url is not None

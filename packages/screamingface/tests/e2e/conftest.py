"""Shared fixtures for the OME-961 e2e replay lane.

Gating lives in ``harness._gating`` (marker ``e2e`` + ``SCREAMINGFACE_TEST_E2E=1`` +
a reachable Docker daemon); the fixtures here always route through it, so any test
depending on them skips loudly — naming the reason — instead of erroring.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from harness._gating import GOLDENS_DIR, SNAPSHOTS_DIR, require_e2e_stack
from harness.cache_seeded import CacheSeededGateway
from harness.e14_stack import E14Stack, e14_stack
from harness.goldens import GoldenReport, load_golden
from harness.tape import LoadedTape, load_tape


@pytest.fixture(scope="session")
def synthetic_tape() -> LoadedTape:
    return load_tape(SNAPSHOTS_DIR / "synthetic.tape.json")


@pytest.fixture(scope="session")
def synthetic_gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The cache-seeded gateway loaded with the SYNTHETIC (authored) snapshot.

    Session-scoped: one Postgres container + one gateway boot serve every plumbing
    test. Yields the gateway base URL.
    """
    require_e2e_stack()
    backend = CacheSeededGateway(
        snapshot=SNAPSHOTS_DIR / "synthetic.snapshot.gz",
        manifest=SNAPSHOTS_DIR / "synthetic.manifest.json",
        work_dir=tmp_path_factory.mktemp("synthetic-gateway"),
    )
    base_url = backend.start_sync()
    try:
        yield base_url
    finally:
        backend.stop_sync()


@pytest.fixture(scope="session")
def e14_assets() -> Path:
    """The prepared ``ifeval`` assets, or a loud skip. Same rule as ``test_boards._assets_root``."""
    from screamingface._runtime.config import default_data_dir

    configured = os.environ.get("SCREAMINGFACE_E2E_ASSETS")
    root = Path(configured) if configured else default_data_dir() / "benchmark-assets"
    if not (root / "ifeval").is_dir():
        pytest.skip(
            f"E14 spines need prepared ifeval assets at {root / 'ifeval'} "
            "(run `screamingface prepare ifeval`, or point SCREAMINGFACE_E2E_ASSETS at them)"
        )
    return root


@pytest.fixture(scope="session")
def e14_golden() -> GoldenReport:
    return load_golden(GOLDENS_DIR / "ifeval.golden.json")


@pytest.fixture
def e14(tmp_path: Path, e14_assets: Path) -> Iterator[E14Stack]:
    """One full E14 stack for ONE test (function scope, ``tmp_path`` as the work dir).

    WHY function scope: SC-23 and RP-21 use the same recipe, so on a shared
    stack one test's head would absorb the next test's submit (it would cluster, or get
    ``system_already_named``) and the result would depend on the test order.
    INVARIANT: no test reads rows that another test wrote.
    """
    require_e2e_stack()
    with e14_stack(work_dir=tmp_path, assets_dir=e14_assets) as stack:
        yield stack

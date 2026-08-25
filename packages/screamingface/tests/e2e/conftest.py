"""Shared fixtures for the OME-961 e2e replay lane.

Gating lives in ``harness._gating`` (marker ``e2e`` + ``SCREAMINGFACE_TEST_E2E=1`` +
a reachable Docker daemon); the fixtures here always route through it, so any test
depending on them skips loudly — naming the reason — instead of erroring.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from harness._gating import SNAPSHOTS_DIR, require_e2e_stack
from harness.cache_seeded import CacheSeededGateway
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

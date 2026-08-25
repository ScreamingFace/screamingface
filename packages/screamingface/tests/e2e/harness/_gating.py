"""Gating + fixture locations for the e2e replay lane (OME-961, internal).

Double gate, mirroring aigateway's ``needs_postgres`` convention (marker +
``AIGW_TEST_PG=1``): the ``e2e`` marker keeps the lane out of ``-m "not e2e"`` runs,
and ``SCREAMINGFACE_TEST_E2E=1`` + a reachable Docker daemon are checked at runtime so
an ungated environment SKIPS with the exact reason instead of erroring or fake-passing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

E2E_ENV: Final = "SCREAMINGFACE_TEST_E2E"

FIXTURES_DIR: Final = Path(__file__).resolve().parents[1] / "fixtures"
SNAPSHOTS_DIR: Final = FIXTURES_DIR / "snapshots"
GOLDENS_DIR: Final = FIXTURES_DIR / "goldens"


def e2e_unavailable_reason() -> str | None:
    """Why the e2e stack cannot run here, or ``None`` when it can."""
    reason = None
    if os.environ.get(E2E_ENV) != "1":
        reason = f"{E2E_ENV}=1 not set (the e2e replay lane is opt-in, like AIGW_TEST_PG)"
    elif shutil.which("docker") is None:
        reason = "docker CLI not on PATH (Postgres testcontainer needs it)"
    elif subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        reason = "docker daemon unreachable (Postgres testcontainer needs it)"
    return reason


def require_e2e_stack() -> None:
    """Skip — loudly, with the reason — when the e2e stack cannot run here."""
    reason = e2e_unavailable_reason()
    if reason is not None:
        pytest.skip(f"e2e replay stack unavailable: {reason}")

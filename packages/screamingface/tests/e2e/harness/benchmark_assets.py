"""Where the prepared benchmark assets are, for the replay lanes that need an imported board.

``screamingface prepare`` writes them under the data dir, and ``SCREAMINGFACE_E2E_ASSETS`` moves
them. Both replay test modules (``test_reducer_replay.py``, ``test_fusion_replay.py``) read it here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

ASSETS_ENV: Final = "SCREAMINGFACE_E2E_ASSETS"


def assets_root() -> Path:
    """The env override, else where `screamingface prepare` writes (as test_boards does)."""
    from screamingface._runtime.config import default_data_dir

    configured = os.environ.get(ASSETS_ENV)
    if configured:
        return Path(configured)
    return default_data_dir() / "benchmark-assets"

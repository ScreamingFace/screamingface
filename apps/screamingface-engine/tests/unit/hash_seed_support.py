"""Run a scenario under many PYTHONHASHSEED values (OME-1289, E4a; FW-3 harness).

Test-only. A scenario is a function in an importable support module that returns one string; the
helper runs ``print(<call>)`` in a fresh interpreter for each seed and returns every stdout.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def stdout_for_seed(script: str, seed: int) -> str:
    """The stdout of ``python -c script`` with this hash seed and this directory on the path."""
    here = str(Path(__file__).parent)
    env = {
        **os.environ,
        "PYTHONHASHSEED": str(seed),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": os.pathsep.join(filter(None, [here, os.environ.get("PYTHONPATH")])),
    }
    done = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=120,
    )
    return done.stdout


def stdout_across_seeds(script: str, seeds: Iterable[int], *, workers: int = 5) -> list[str]:
    """``stdout_for_seed`` for every seed, run ``workers`` at a time."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda seed: stdout_for_seed(script, seed), seeds))


__all__ = ["stdout_across_seeds", "stdout_for_seed"]

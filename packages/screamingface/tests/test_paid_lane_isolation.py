"""The paid lane is invisible to every automatic run (OME-1275).

INVARIANT (owner rule): nothing under `tests/paid/` — not the paid smoke, not its free
gate tests — is collected unless the paid button sets `SCREAMINGFACE_TEST_PAID=1`.
The button is the `workflow_dispatch` workflow or the `test-paid-benchmarks` just recipe;
merge CI runs plain `pytest`, so collection itself is the fence, not a per-test skip.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

_PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
_PAID_FLAG: Final = "SCREAMINGFACE_TEST_PAID"
# pytest's "no tests collected" exit code.
_NO_TESTS_COLLECTED: Final = 5


def _collect_paid_lane(flag: str | None) -> subprocess.CompletedProcess[str]:
    """Ask a fresh pytest which tests it would collect from `tests/paid/`."""
    env: dict[str, str] = {k: v for k, v in os.environ.items() if k != _PAID_FLAG}
    if flag is not None:
        env[_PAID_FLAG] = flag
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
        + ["tests/paid"],
        cwd=_PACKAGE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_paid_lane_is_not_collected_without_the_paid_flag() -> None:
    """Merge CI never sets the flag, so even naming the directory collects nothing."""
    result = _collect_paid_lane(flag=None)

    assert result.returncode == _NO_TESTS_COLLECTED, result.stdout + result.stderr


def test_paid_lane_is_collected_when_the_button_sets_the_flag() -> None:
    """The fence must open for the button — otherwise the lane silently runs nothing."""
    result = _collect_paid_lane(flag="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_every_benchmark_runs_end_to_end" in result.stdout
    assert "test_gate_fails_instead_of_skipping_when_required" in result.stdout

"""Exercise the new conditional browser command without production requests."""

import subprocess
from pathlib import Path


def test_browser_enrollment_command():
    result = subprocess.run(
        ["node", "--test", "tests/browser/bridge-enrollment.test.cjs"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr

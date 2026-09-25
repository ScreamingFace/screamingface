"""Exercise the shipped iframe script's message boundary without browser mocks in production."""

import subprocess
from pathlib import Path


def test_bridge_message_protocol():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "--test", "tests/browser/bridge.test.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

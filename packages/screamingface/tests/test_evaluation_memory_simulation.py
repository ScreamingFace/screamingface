"""The development harness must traverse the real transport, not an SDK mock."""

import json
import subprocess
import sys
from pathlib import Path


def test_memory_simulation_recovery_without_restarting_runs(tmp_path):
    script = Path(__file__).parents[1] / "scripts/check_evaluation_memory.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--directory",
            str(tmp_path),
            "--candidates",
            "2",
            "--cases",
            "30",
            "--prompt-bytes",
            "200",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads((tmp_path / "validation.json").read_text())
    assert evidence["normal"]["candidates"] == 2
    assert evidence["normal"]["cases"] == 60
    assert evidence["local_recovery"]["cases"] == 60
    assert evidence["export_exit_code"] == 74
    assert evidence["decode_exit_code"] == 73
    assert evidence["run_starts_before_recovery"] == evidence["run_starts_after_recovery"]
    assert evidence["remote_recovery"]["cases"] == 60
    assert (
        evidence["offline_recovery"]["export_sha256"]
        == evidence["remote_recovery"]["export_sha256"]
    )
    assert evidence["artifact_downloads"] == 6

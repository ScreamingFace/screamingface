"""The CI lane writes JUnit into the workbench evidence dir and uploads it (review finding 5)."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Final

import yaml

from workbench.conftest import OUT_ENV

_WORKFLOW: Final = (
    Path(__file__).resolve().parents[5] / ".github" / "workflows" / "screamingface-e2e-replay.yml"
)


def _steps() -> dict[str, dict[str, Any]]:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return {step.get("name", ""): step for step in workflow["jobs"]["golden-replay"]["steps"]}


def _pytest_step() -> dict[str, Any]:
    (step,) = [s for s in _steps().values() if "pytest tests/e2e" in str(s.get("run", ""))]
    return step


def test_the_replay_lane_writes_junit_inside_the_evidence_dir() -> None:
    step = _pytest_step()
    args = shlex.split(step["run"])
    junit = [a.removeprefix("--junitxml=") for a in args if a.startswith("--junitxml=")]
    assert junit == [f"${OUT_ENV}/junit.xml"], args
    # The shell expands it from the step env, so it lands where the bundles are written.
    assert step["env"][OUT_ENV] == "${{ runner.temp }}/workbench-out"


def test_the_evidence_upload_carries_the_junit_on_pass_and_fail() -> None:
    upload = _steps()["Upload workbench evidence"]
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == _pytest_step()["env"][OUT_ENV]

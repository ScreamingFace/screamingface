"""Deployment composition still works with the activity package/registration removed."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_local_composition_survives_removing_activity_package_and_registration(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src/screamingface_engine"
    target = tmp_path / "screamingface_engine"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "activity"))
    # WHY: removal changes registration only; existing execution-removal tests cover requests.
    (target / "observation_plugins.py").write_text(
        "def observation_factories(env):\n    return ()\n"
    )
    script = r"""
import asyncio
import importlib.util
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.world.config import WorldConfig
assert importlib.util.find_spec('screamingface_engine.activity') is None
app = create_local_app(settings=Settings(activity_level='full'), env={})
executor = app.state.job_runner._factory({}, config=WorldConfig())
async def main():
    frames = [frame async for frame in executor.execute('42')]
    assert frames
    assert 'sf.activity.' not in str(frames)
    await app.state.job_runner.aclose()
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr

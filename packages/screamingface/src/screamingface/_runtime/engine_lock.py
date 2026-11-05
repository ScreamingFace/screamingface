"""The Engine's pinned dependency world, read from its lock when it is needed (OME-1620).

`screamingface up` builds an Engine environment from these pins so the local Engine runs the
versions the deployed Engine runs: both come from `apps/screamingface-engine/uv.lock`, the lock
the deployed image is built from. Nothing is committed that could go stale. A release wheel
gets the pins when it is BUILT (`scripts/runtime_build_hook.py` calls this module); a checkout
exports them from its live lock when `up` builds its environment.

INVARIANT: standard library only. The build hook loads this file by path in hatchling's
isolated build environment, where the SDK itself is not installed.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

#: Where the Engine app (its `pyproject.toml` and `uv.lock`) sits in the monorepo.
ENGINE_APP = Path("apps") / "screamingface-engine"
#: The name the pins travel under: in the wheel's `_runtime/resources/`, and in an sdist.
REQUIREMENTS_NAME = "engine-requirements.txt"

# WHY these flags: `--extra benchmarks` is what Dockerfile.benchmark syncs (the preparers' PDF
# readers included, so a local `prepare` can build every bundle); `--frozen` reads the lock as
# it is and never re-resolves; `--no-emit-project` and `--no-emit-package url4` leave out the
# two projects the environment installs from its own copies; no hashes because the installer
# may be pip or uv, and the lock, not this list, is the authority.
_EXPORT_ARGS: tuple[str, ...] = (
    "export",
    "--frozen",
    "--no-dev",
    "--extra",
    "benchmarks",
    "--no-emit-project",
    "--no-emit-package",
    "url4",
    "--no-hashes",
    "--no-header",
    "--no-annotate",
)
# WHY 15: enough of uv's stderr to carry its reason into the error.
_ERROR_TAIL_LINES = 15


def export_engine_requirements(
    engine_app: Path,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """The Engine lock's `benchmarks` world as `name==version` lines, straight from `uv export`.

    Raises RuntimeError naming the fix when uv is missing, and carrying uv's own reason when
    the export fails (a lock out of step with its pyproject, for example).
    """

    uv: str | None = which("uv")
    if uv is None:
        raise RuntimeError(
            f"reading the Engine's pinned packages needs uv on PATH (it is the only reader of "
            f"{ENGINE_APP / 'uv.lock'}); install it from https://docs.astral.sh/uv/"
        )
    try:
        completed = run(
            [uv, *_EXPORT_ARGS], cwd=engine_app, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise RuntimeError(f"could not run uv to export the Engine's lock: {exc}") from None
    if completed.returncode != 0:
        tail: str = "\n".join(completed.stderr.strip().splitlines()[-_ERROR_TAIL_LINES:])
        raise RuntimeError(
            f"exporting the Engine's lock failed (exit {completed.returncode}):\n{tail}"
        )
    return completed.stdout


__all__ = ["ENGINE_APP", "REQUIREMENTS_NAME", "export_engine_requirements"]

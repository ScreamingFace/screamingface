"""Write the Engine's pinned `benchmarks` world into the SDK's resources (OME-1620).

`screamingface up` builds a pip user's Engine environment from this file, so the local Engine
runs the SAME dependency versions as the deployed one — `inspect-ai` and `inspect-evals` above
all, which are revision identity for every imported board. The file is committed (the wheel
must carry it, and a build must not depend on the lock being next to it);
`tests/test_runtime_engine_env_builder.py` fails when it drifts from the lock.

    uv run python scripts/export_engine_requirements.py   # from packages/screamingface
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PACKAGE_ROOT: Path = Path(__file__).resolve().parents[1]
ENGINE_ROOT: Path = PACKAGE_ROOT.parents[1] / "apps" / "screamingface-engine"
REQUIREMENTS: Path = PACKAGE_ROOT / "src" / "screamingface" / "_runtime" / "resources"
REQUIREMENTS = REQUIREMENTS / "engine-requirements.txt"

# WHY these flags: `--extra benchmarks` is what Dockerfile.benchmark syncs (the preparers' PDF
# readers included, so a local `prepare` can build every bundle); `--no-emit-project` and
# `--no-emit-package url4` leave out the two projects the wheel installs from its own copies;
# no hashes because the installer may be pip or uv and the lock, not this file, is the authority.
_EXPORT: tuple[str, ...] = (
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


def exported_requirements() -> str:
    """The Engine lock's `benchmarks` world as pip-style pins, straight from `uv export`."""

    uv: str | None = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is not on PATH; it is the only reader of the Engine's lock")
    completed = subprocess.run(
        [uv, *_EXPORT], cwd=ENGINE_ROOT, capture_output=True, text=True, check=True
    )
    return completed.stdout


def main() -> None:
    REQUIREMENTS.write_text(exported_requirements(), encoding="utf-8")
    print(f"wrote {REQUIREMENTS}")


if __name__ == "__main__":
    main()

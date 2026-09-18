"""Verify built ScreamingFace distributions contain only releaseable package material."""

from __future__ import annotations

import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


def main() -> None:
    root = Path(__file__).parents[1]
    version = _version(root / "pyproject.toml")
    wheel = root / "dist" / f"screamingface-{version}-py3-none-any.whl"
    source = root / "dist" / f"screamingface-{version}.tar.gz"
    _require_files(wheel, source)
    with zipfile.ZipFile(wheel) as archive:
        _validate(tuple(PurePosixPath(name) for name in archive.namelist()), source=False)
    with tarfile.open(source, "r:gz") as archive:
        _validate(tuple(PurePosixPath(name) for name in archive.getnames()), source=True)


def _version(path: Path) -> str:
    with path.open("rb") as stream:
        value = tomllib.load(stream)["project"]["version"]
    if not isinstance(value, str) or not value:
        raise SystemExit("project version is missing")
    return value


def _require_files(*paths: Path) -> None:
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"build distributions before verification: missing={missing}")


def _validate(paths: tuple[PurePosixPath, ...], *, source: bool) -> None:
    forbidden_parts = {
        ".ipynb_checkpoints",
        "__pycache__",
    }
    leaked = sorted(
        str(path)
        for path in paths
        if forbidden_parts.intersection(path.parts) or path.suffix == ".pyc"
    )
    if leaked:
        kind = "source distribution" if source else "wheel"
        raise SystemExit(f"{kind} contains forbidden release material: {leaked}")
    if not source and any("apps" in path.parts or "tests" in path.parts for path in paths):
        raise SystemExit("wheel contains application or test code")
    if not source and PurePosixPath("screamingface/py.typed") not in paths:
        raise SystemExit("wheel does not declare its inline types with screamingface/py.typed")
    if not source:
        required_runtime_files = {
            PurePosixPath("aigateway/__init__.py"),
            PurePosixPath("scoreboard/__init__.py"),
            PurePosixPath("url4/__init__.py"),
            PurePosixPath("screamingface_engine/__init__.py"),
            PurePosixPath("screamingface/_runtime/resources/url4.json"),
            PurePosixPath("screamingface/_runtime/scoreboard_portal/index.html"),
        }
        missing_runtime = sorted(map(str, required_runtime_files - set(paths)))
        if missing_runtime:
            raise SystemExit(f"wheel is missing bundled runtime material: {missing_runtime}")
    # WHY: Apache-2.0 section 4(a) requires the licence to travel with every redistribution.
    # A packaging change can drop it silently, and the failure is legal rather than functional
    # — nothing breaks at runtime, so only an assertion catches it.
    if not _declares_license(paths, source=source):
        raise SystemExit("distribution does not carry its Apache-2.0 LICENSE")


def _declares_license(paths: tuple[PurePosixPath, ...], *, source: bool) -> bool:
    if source:
        return any(path.name == "LICENSE" for path in paths)
    # Hatchling records wheel licence files under `<name>-<version>.dist-info/licenses/`.
    return any("licenses" in path.parts and path.name == "LICENSE" for path in paths)


if __name__ == "__main__":
    main()

"""The tortoise-orm pins that one local process must agree on (E5 P1, OME-1785).

WHY: the SDK's `runtime` extra installs the Engine and aigateway into one environment, so its
tortoise-orm pin is the version local users run, and it must equal both apps' pins. CI is
path-filtered and Dependabot groups per directory, so a bump in one project can merge green
alone. A twin of this test runs in the Engine lane too, so whichever side drifts, the lane
that carried the drift goes red. Both read the other projects' files as text.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT: Path = Path(__file__).resolve().parents[4]
_PINNED: str = "tortoise-orm"
_PROJECTS: dict[str, tuple[Path, str | None]] = {
    "Engine": (_REPO_ROOT / "apps" / "screamingface-engine", None),
    "aigateway": (_REPO_ROOT / "apps" / "aigateway", None),
    "SDK runtime extra": (_REPO_ROOT / "packages" / "screamingface", "runtime"),
}


def _pin(project: Path, extra: str | None) -> str:
    """The exact version project pins tortoise-orm to, in its dependencies or extra."""
    config: dict[str, Any] = tomllib.loads((project / "pyproject.toml").read_text("utf-8"))
    table = config["project"]
    requirements: list[str] = (
        table["dependencies"] if extra is None else table["optional-dependencies"][extra]
    )
    pins = [r for r in requirements if r.split("[", 1)[0].split("=", 1)[0] == _PINNED]
    assert len(pins) == 1, f"{project}: expected one {_PINNED} requirement, found {pins}"
    name, operator, version = pins[0].partition("==")
    assert operator, f"{project}: {pins[0]!r} is not an exact == pin"
    return version


def _locked(project: Path) -> str:
    lock: dict[str, Any] = tomllib.loads((project / "uv.lock").read_text("utf-8"))
    versions = [str(p["version"]) for p in lock["package"] if p["name"] == _PINNED]
    assert len(versions) == 1, f"{project}/uv.lock: expected one {_PINNED}, found {versions}"
    return versions[0]


@pytest.mark.skipif(
    not all(path.exists() for path, _ in _PROJECTS.values()), reason="monorepo not present"
)
def test_every_project_one_process_loads_pins_one_tortoise_orm() -> None:
    pins = {name: _pin(path, extra) for name, (path, extra) in _PROJECTS.items()}
    assert len(set(pins.values())) == 1, (
        f"{_PINNED} pins disagree: {pins}. The SDK runtime extra runs the Engine and aigateway "
        "in one process, so move all three together"
    )


@pytest.mark.skipif(
    not all(path.exists() for path, _ in _PROJECTS.values()), reason="monorepo not present"
)
def test_every_lockfile_installs_the_pinned_tortoise_orm() -> None:
    pinned = _pin(*_PROJECTS["Engine"])
    locked = {name: _locked(path) for name, (path, _) in _PROJECTS.items()}
    assert set(locked.values()) == {pinned}, (
        f"the lockfiles resolve {_PINNED} to {locked}, but the pins say =={pinned}: re-run "
        "`uv lock` where they disagree"
    )

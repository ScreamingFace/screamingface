"""Engine-side twin of the SDK's inspect-ai pin conformance bind.

FEATURE: export a Report in inspect's .eval log format (OME-1117).
STORY: as a researcher, the .eval log the SDK writes for me comes from the same inspect
version the Engine prepared the Imported Benchmark with, never a newer one nobody checked.
WHY a twin in each package: CI is path-filtered, so an SDK-only Dependabot PR never runs
the Engine's tests. That is how #1119 and #1135 moved the SDK to 0.3.270 while the Engine
stayed on 0.3.263. This copy runs in the SDK lane and the Engine's copy in the Engine lane,
so whichever side drifts, the lane that carried the drift goes red. This copy also catches
an Engine-only pin change the SDK was never moved with. Both read the other side's files as
text; neither imports the other.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

# parents[3] = apps/, so its parent is the monorepo root
_REPO_ROOT: Path = Path(__file__).resolve().parents[3].parent
_ENGINE_APP: Path = _REPO_ROOT / "apps" / "screamingface-engine"
_SDK_PACKAGE: Path = _REPO_ROOT / "packages" / "screamingface"
_PINNED_PACKAGE: str = "inspect-ai"
_EXTRA: str = "inspect"
# WHY: split a requirement string at the first character that can end a package name.
_REQUIREMENT_NAME_END: re.Pattern[str] = re.compile(r"[=<>!~\[; ]")
_EXACT_VERSION: re.Pattern[str] = re.compile(r"[0-9][0-9A-Za-z.]*")


def _extra_pin(pyproject: Path) -> str:
    """The exact version a project's ``inspect`` extra pins inspect-ai to; refuses a range."""

    assert pyproject.exists(), f"{pyproject} moved: update the inspect pin bind"
    config: dict[str, Any] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    extra: list[str] = config["project"]["optional-dependencies"][_EXTRA]
    specs: list[str] = [
        spec for spec in extra if _REQUIREMENT_NAME_END.split(spec, 1)[0] == _PINNED_PACKAGE
    ]
    assert len(specs) == 1, (
        f"{pyproject}: expected one {_PINNED_PACKAGE} entry in the {_EXTRA!r} extra, found {specs}"
    )
    name, operator, version = specs[0].partition("==")
    # INVARIANT: only an exact == pin can be "the same version" as another pin.
    assert operator and name == _PINNED_PACKAGE and _EXACT_VERSION.fullmatch(version), (
        f"{pyproject}: {specs[0]!r} is not an exact == pin, so no other pin can match it"
    )
    return version


def _locked_version(lockfile: Path) -> str:
    """The inspect-ai version a uv lockfile actually resolved, i.e. what installs."""

    assert lockfile.exists(), f"{lockfile} moved: update the inspect pin bind"
    lock: dict[str, Any] = tomllib.loads(lockfile.read_text(encoding="utf-8"))
    versions: list[str] = [
        str(package["version"]) for package in lock["package"] if package["name"] == _PINNED_PACKAGE
    ]
    assert len(versions) == 1, f"{lockfile}: expected one {_PINNED_PACKAGE}, found {versions}"
    return versions[0]


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_the_sdk_pins_the_engines_inspect_ai_version() -> None:
    """The SDK's inspect extra pins exactly the inspect-ai version the Engine pins."""

    engine: str = _extra_pin(_ENGINE_APP / "pyproject.toml")
    sdk: str = _extra_pin(_SDK_PACKAGE / "pyproject.toml")
    # INVARIANT: the Engine's pin is the single source of truth. It is hashed into every
    # Imported Benchmark's Benchmark Revision, so the SDK follows it, never the reverse.
    assert sdk == engine, (
        f"the SDK pins {_PINNED_PACKAGE}=={sdk} but the Engine pins =={engine}. The Engine's "
        "pin is the source of truth (every Imported Benchmark's Benchmark Revision hashes it): "
        "set packages/screamingface to match, and move both together only through OME-1410's "
        "bump check"
    )


@pytest.mark.skipif(not _SDK_PACKAGE.exists(), reason="SDK package not present")
def test_both_lockfiles_install_the_engines_inspect_ai_version() -> None:
    """Each lockfile resolves inspect-ai to the Engine's pin, so what installs is what is pinned."""

    engine: str = _extra_pin(_ENGINE_APP / "pyproject.toml")
    # WHY: a hand-edited pin with a stale lockfile would still install the old version.
    locked: dict[str, str] = {
        "Engine": _locked_version(_ENGINE_APP / "uv.lock"),
        "SDK": _locked_version(_SDK_PACKAGE / "uv.lock"),
    }
    assert locked == {"Engine": engine, "SDK": engine}, (
        f"the lockfiles resolve {_PINNED_PACKAGE} to {locked}, but the Engine pins =={engine}: "
        "re-run `uv lock` in the project whose lockfile disagrees"
    )


@pytest.mark.parametrize(
    "requirement",
    ["inspect-ai>=0.3.263", "inspect-ai~=0.3.263", "inspect-ai", "inspect-ai==0.3.*"],
)
def test_a_range_pin_is_refused_because_it_cannot_equal_another_pin(
    tmp_path: Path, requirement: str
) -> None:
    """A range or bare requirement fails the bind instead of comparing as a version."""

    pyproject: Path = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[project.optional-dependencies]\ninspect = ["{requirement}"]\n', encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="not an exact == pin"):
        _extra_pin(pyproject)


def test_an_exact_pin_reads_back_as_its_version(tmp_path: Path) -> None:
    """The exact pin 0.3.263 reads back as the version string the other side must equal."""

    pyproject: Path = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project.optional-dependencies]\ninspect = ["inspect-ai==0.3.263", "datasets==5.0.1"]\n',
        encoding="utf-8",
    )
    assert _extra_pin(pyproject) == "0.3.263"

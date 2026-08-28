"""`sf.__version__` reports the installed distribution, so it cannot drift from pyproject.

Mental model: the version number is written in exactly ONE place, `pyproject.toml`. At import
time the package asks the installer "what did you actually put on disk?" instead of carrying a
second copy in the source. These tests pin both ends of that chain — the attribute equals what
the package manager recorded, and what the package manager recorded equals what `pyproject.toml`
declares. Break either link and the number a user reads stops describing the code they are running,
which is the one question `sf.__version__` exists to answer.

STORY: as someone who just ran `pip install screamingface` and hit a surprise, I type
`sf.__version__` to find out what I am actually running — and get an answer, not an
`AttributeError`.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path

import pytest

import screamingface as sf
from screamingface import _version

PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _declared_version() -> str:
    """The `[project] version` literal, read straight out of `pyproject.toml`."""

    with PYPROJECT_PATH.open("rb") as stream:
        declared = tomllib.load(stream)["project"]["version"]
    assert isinstance(declared, str)
    return declared


def test_version_reports_the_installed_distribution_version() -> None:
    """The first thing a user types after an install must answer, not raise."""

    assert sf.__version__ == distribution_version("screamingface")


def test_version_matches_the_version_declared_in_pyproject() -> None:
    """INVARIANT: `pyproject.toml` is the only place the version is written.

    A hand-maintained `__version__ = "..."` literal is exactly the thing that goes stale one
    release after someone forgets it; this asserts the attribute is derived, not duplicated.
    """

    assert sf.__version__ == _declared_version()


def test_version_is_exported_from_the_package_surface() -> None:
    """It is a documented attribute, so `from screamingface import *` must carry it."""

    assert "__version__" in sf.__all__


def test_version_falls_back_when_no_distribution_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INVARIANT: a missing version label never breaks `import screamingface`.

    Importing off a bare source tree with nothing installed raises `PackageNotFoundError` from
    `importlib.metadata`. Letting that escape would turn "I cannot read the version" into "the
    library will not import at all" — a fail-closed on a purely informational attribute.
    """

    def _no_such_distribution(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(_version, "distribution_version", _no_such_distribution)

    assert _version.resolve_version() == _version.SOURCE_TREE_VERSION


def test_source_tree_marker_is_never_mistaken_for_a_release() -> None:
    """INVARIANT: the fallback must not look like a version anyone could have shipped.

    A bug report quoting a release-shaped fallback would send a maintainer hunting for a tag
    that was never cut, so the marker stays a local-version label pinned at `0.0.0`.
    """

    assert _version.SOURCE_TREE_VERSION.startswith("0.0.0+")
    assert _version.SOURCE_TREE_VERSION != _declared_version()

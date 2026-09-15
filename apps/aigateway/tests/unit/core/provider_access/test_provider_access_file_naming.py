"""File-naming policy of the provider-access unit (OME-1204, follow-up to OME-1200).

# INVARIANT (owner decision, OME-1204): no file introduced by the provider-access unit has a name
# beginning with `_`; `__init__.py` is the required Python exception; underscores BETWEEN words in
# ordinary snake_case names are allowed. The policy is checked on the filenames themselves — a
# module that merely imports fine under a `_`-prefixed name would still violate it.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import aigateway.core.provider_access as provider_access

_PACKAGE_DIR = Path(inspect.getfile(provider_access)).resolve().parent
_TESTS_DIR = Path(__file__).resolve().parent
# WHY a one-element set and not a prefix rule: `__init__.py` is the ONLY name Python requires to
# start with an underscore; pinning the exact set keeps a future `_helpers.py` from being waved
# through by a "dunder files are fine" generalisation.
_ALLOWED_UNDERSCORE_NAMES = frozenset({"__init__.py"})


def _python_files(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*.py") if path.is_file())


def _underscore_prefixed(directory: Path) -> list[str]:
    return [
        name
        for name in _python_files(directory)
        if name.startswith("_") and name not in _ALLOWED_UNDERSCORE_NAMES
    ]


@pytest.mark.parametrize(
    ("label", "directory"),
    [("package", _PACKAGE_DIR), ("tests", _TESTS_DIR)],
    ids=["core/provider_access", "tests/unit/core/provider_access"],
)
def test_no_provider_access_file_begins_with_an_underscore(label: str, directory: Path) -> None:
    assert _python_files(directory), f"the {label} directory must contain Python files"

    assert _underscore_prefixed(directory) == []


def test_the_policy_exempts_only_the_package_initialiser() -> None:
    assert _ALLOWED_UNDERSCORE_NAMES == {"__init__.py"}
    assert (_PACKAGE_DIR / "__init__.py").is_file()

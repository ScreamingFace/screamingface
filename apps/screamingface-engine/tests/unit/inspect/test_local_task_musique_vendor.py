"""The copied MuSiQue scorer IS the paper's scorer — byte for byte, but for one import line.

WHY this file exists: the spec's rule is "our number means what the paper's number means" (D8).
That holds only while the files under `local_tasks/musique/vendor/` are the ones published at
StonyBrookNLP/musique@922ac98f. A well-meaning tidy-up (a type hint, a ruff autofix, a "bug fix"
to the duplicated `f1, em = 1.0, 1.0` line) would move every MuSiQue score off the paper's with
every other gate green. Nothing else would notice, so this test does.

The one permitted edit: `from metrics.metric import Metric` became `from .metric import Metric`
so the copy imports inside this package. The test reverses exactly that line and demands the
upstream sha256, so any SECOND edit fails it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import screamingface_engine_inspect.local_tasks.musique.vendor as vendor

_VENDOR_DIR: Path = Path(vendor.__file__).parent

#: Upstream sha256 of each copied file at StonyBrookNLP/musique@922ac98f, read from the clone.
_UPSTREAM_SHA256: dict[str, str] = {
    "answer.py": "10368f619b4d5ef5d83748c05a96c0afd332a14ab5c010740c98d58dfaefe974",
    "support.py": "ac16c0daf458a6a4d6db97682c2340fe5b5936a947bf32c04dc3bf16406077c6",
    "metric.py": "c858d1bfda2f0b005065e87a402cd2f82154eb7eed5916845ae130759cc3a299",
}

_OUR_IMPORT = b"from .metric import Metric\n"
_UPSTREAM_IMPORT = b"from metrics.metric import Metric\n"


def _upstream_bytes(name: str) -> bytes:
    """Undo our one permitted edit, giving back what upstream published."""

    return (_VENDOR_DIR / name).read_bytes().replace(_OUR_IMPORT, _UPSTREAM_IMPORT)


@pytest.mark.parametrize("name", sorted(_UPSTREAM_SHA256))
def test_each_copied_file_is_the_upstream_file_with_only_its_import_made_relative(
    name: str,
) -> None:
    """INVARIANT: reversing the one import edit reproduces the upstream bytes exactly."""

    digest: str = hashlib.sha256(_upstream_bytes(name)).hexdigest()

    assert digest == _UPSTREAM_SHA256[name]


@pytest.mark.parametrize("name", ["answer.py", "support.py"])
def test_the_scorers_import_their_base_from_inside_this_package(name: str) -> None:
    """The edit we DID make is present exactly once — an absolute `metrics.` import would only
    resolve if some unrelated top-level `metrics` package happened to be installed."""

    source: bytes = (_VENDOR_DIR / name).read_bytes()

    assert source.count(_OUR_IMPORT) == 1
    assert _UPSTREAM_IMPORT not in source


def test_the_licence_ships_beside_the_copied_code() -> None:
    """CC BY 4.0 requires attribution; the licence text travels with the copy."""

    licence: str = (_VENDOR_DIR / "LICENSE").read_text(encoding="utf-8")

    assert "Attribution 4.0 International" in licence


def test_the_provenance_names_the_pinned_commit_and_every_upstream_hash() -> None:
    """A reader of the package docstring can re-fetch and re-check the copy without this test."""

    docstring: str = vendor.__doc__ or ""

    assert "922ac98f19a201998dbdae6d7f2887a5258dbdeb" in docstring
    for digest in _UPSTREAM_SHA256.values():
        assert digest in docstring

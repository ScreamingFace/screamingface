"""The copied MuSiQue scorer IS the paper's scorer — byte for byte below our own header.

WHY this file exists: the spec's rule is "our number means what the paper's number means" (D8).
That holds only while the code under `local_tasks/musique/vendor/` is the code published at
StonyBrookNLP/musique@922ac98f. A well-meaning tidy-up (a type hint, a ruff autofix, a "bug fix"
to the duplicated `f1, em = 1.0, 1.0` line) would move every MuSiQue score off the paper's with
every other gate green. Nothing else would notice, so this test does.

Two edits are ours and nothing else is: (1) each file's module docstring is our header, which
links to the upstream blob at the pinned commit instead of repeating the authors' docstring (owner
rule, 2026-10-08); (2) `from metrics.metric import Metric` became `from .metric import Metric` so
the copy imports inside this package. The test drops the docstring, reverses the import, and
demands the sha256 of upstream's code after ITS docstring, so any third edit fails it.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

import screamingface_engine_inspect.local_tasks.musique.vendor as vendor

_VENDOR_DIR: Path = Path(vendor.__file__).parent

_UPSTREAM_BLOB = "https://github.com/StonyBrookNLP/musique/blob/922ac98f19a201998dbdae6d7f2887a5258dbdeb/metrics/"

#: sha256 of each upstream file's code AFTER its module docstring, StonyBrookNLP/musique@922ac98f.
#: Computed from the raw files at that commit with `_code_after_docstring` below.
_UPSTREAM_CODE_SHA256: dict[str, str] = {
    "answer.py": "36e249e93436617dd9bbbced66a36167b285bfe612ffad9fafc6ad5a5e0843be",
    "support.py": "aff8cf854483627edc7e777f6dd996255671e3590140574909e1b10c84232dc3",
    "metric.py": "caef22392788f4dc03719df96e1872b2900f1e4774e2e951533c9a17d0dc69f9",
}

_OUR_IMPORT = b"from .metric import Metric\n"
_UPSTREAM_IMPORT = b"from metrics.metric import Metric\n"


def _code_after_docstring(source: bytes) -> bytes:
    """Everything after the module docstring — the same cut on our copy and on upstream."""

    first: ast.stmt = ast.parse(source).body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant), (
        "a vendored file must open with our header docstring"
    )
    assert first.end_lineno is not None
    return b"".join(source.splitlines(keepends=True)[first.end_lineno :])


def _upstream_code(name: str) -> bytes:
    """Undo our two permitted edits, giving back the code upstream published."""

    code: bytes = _code_after_docstring((_VENDOR_DIR / name).read_bytes())
    return code.replace(_OUR_IMPORT, _UPSTREAM_IMPORT)


@pytest.mark.parametrize("name", sorted(_UPSTREAM_CODE_SHA256))
def test_each_copied_file_is_the_upstream_code_below_our_header(name: str) -> None:
    """INVARIANT: dropping our header and reversing the import reproduces upstream's code."""

    digest: str = hashlib.sha256(_upstream_code(name)).hexdigest()

    assert digest == _UPSTREAM_CODE_SHA256[name]


@pytest.mark.parametrize("name", sorted(_UPSTREAM_CODE_SHA256))
def test_each_header_links_to_its_own_upstream_blob_at_the_pinned_commit(name: str) -> None:
    """A reader opens the file and reaches the exact upstream bytes in one click — the link is
    per file and per commit, never a branch, so it cannot drift under them."""

    module = ast.parse((_VENDOR_DIR / name).read_bytes())
    docstring: str = ast.get_docstring(module) or ""

    assert f"{_UPSTREAM_BLOB}{name}" in docstring


@pytest.mark.parametrize("name", ["answer.py", "support.py"])
def test_the_scorers_import_their_base_from_inside_this_package(name: str) -> None:
    """The import edit we DID make is present exactly once — an absolute `metrics.` import would
    only resolve if some unrelated top-level `metrics` package happened to be installed."""

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
    for digest in _UPSTREAM_CODE_SHA256.values():
        assert digest in docstring

"""The copied ARC Prize parser IS the harness's parser — byte for byte below our own header.

WHY this file exists: the spec's rule is "our number means the harness's number" (OME-1476, D4).
That holds only while ``local_tasks/arc_agi_2/vendor/parsing.py`` is the code published at
arcprize/arc-agi-benchmarking@9e2828fb. A well-meaning tidy-up (a type hint, a ruff autofix, a
"fix" to the quirk where a reply ending in ``}`` gives up) would move ARC scores off the
harness's with every other gate green. Nothing else would notice, so this test does.

One edit is ours and nothing else is: the module docstring is our header, linking to the
upstream blob at the pinned commit (upstream's file has no docstring). The test drops it and
demands the sha256 of upstream's file, so any second edit fails it.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import screamingface_engine_inspect.local_tasks.arc_agi_2.vendor as vendor

_VENDOR_DIR: Path = Path(vendor.__file__).parent

_COMMIT = "9e2828fb5bd3ab43f6b9fc545595b82b67473b93"
_UPSTREAM_BLOB = (
    f"https://github.com/arcprize/arc-agi-benchmarking/blob/{_COMMIT}"
    "/src/arc_agi_benchmarking/utils/parsing.py"
)

#: sha256 of upstream's ``src/arc_agi_benchmarking/utils/parsing.py`` at that commit (the whole
#: file: it opens with ``import json``, no docstring).
_UPSTREAM_SHA256 = "67f6be50f339537bacac646f290cd782c47eb5fc4ccd4900a5b8bf9a4389917a"


def _code_after_docstring(source: bytes) -> bytes:
    """Everything after our header docstring."""

    first: ast.stmt = ast.parse(source).body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant), (
        "a vendored file must open with our header docstring"
    )
    assert first.end_lineno is not None
    return b"".join(source.splitlines(keepends=True)[first.end_lineno :])


def test_the_copied_parser_is_the_upstream_file_below_our_header() -> None:
    """INVARIANT: dropping our header reproduces upstream's file exactly."""

    code: bytes = _code_after_docstring((_VENDOR_DIR / "parsing.py").read_bytes())

    assert hashlib.sha256(code).hexdigest() == _UPSTREAM_SHA256


def test_the_header_links_to_the_upstream_blob_at_the_pinned_commit() -> None:
    """A reader reaches the exact upstream bytes in one click — a commit, never a branch."""

    module = ast.parse((_VENDOR_DIR / "parsing.py").read_bytes())

    assert _UPSTREAM_BLOB in (ast.get_docstring(module) or "")


def test_the_licence_ships_beside_the_copied_code() -> None:
    """MIT requires the copyright notice to travel with the copy."""

    licence: str = (_VENDOR_DIR / "LICENSE").read_text(encoding="utf-8")

    assert "MIT License" in licence
    assert "Copyright (c) 2025 ARC Prize Foundation" in licence


def test_the_provenance_names_the_pinned_commit_and_the_upstream_hash() -> None:
    """A reader of the package docstring can re-fetch and re-check the copy without this test."""

    docstring: str = vendor.__doc__ or ""

    assert _COMMIT in docstring
    assert _UPSTREAM_SHA256 in docstring

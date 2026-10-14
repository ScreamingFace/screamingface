"""The url4 of every README and public-docs Fusion example, frozen before the recipe rewrite.

CHAR (FR#1): these goldens pass on the compiler as it was BEFORE the Fusion recipe rewrite
(unit 10S, Commit G). The rewrite must keep every byte, so a later change to this file or to
``data/fusion_docs`` is a leaderboard-risk change and needs a reviewer.

To write the goldens (only when an example is added), run
``uv run python tests/test_fusion_doc_goldens.py`` from ``packages/screamingface``; it calls
``write_goldens()``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from _fusion_doc_examples import EXAMPLES, DocExample, compile_example

_GOLDEN_DIR = Path(__file__).parent / "data" / "fusion_docs"


def golden_path(example: DocExample) -> Path:
    return _GOLDEN_DIR / f"{example.slug}.url4"


def write_goldens() -> None:
    """Write one golden per example. Run it ONLY with the compiler that is to be characterized."""

    _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for example in EXAMPLES:
        golden_path(example).write_text(compile_example(example) + "\n", encoding="utf-8")


def test_every_example_has_a_distinct_slug_and_a_golden_file() -> None:
    slugs = [example.slug for example in EXAMPLES]

    assert len(slugs) == len(set(slugs))
    assert {path.name for path in _GOLDEN_DIR.glob("*.url4")} == {f"{slug}.url4" for slug in slugs}


@pytest.mark.parametrize("example", EXAMPLES, ids=[example.slug for example in EXAMPLES])
def test_fusion_doc_example_url4_is_unchanged(example: DocExample) -> None:
    # WHY removesuffix: the repo's end-of-file-fixer hook appends one newline to data files;
    # the compiler output has none.
    expected = golden_path(example).read_text(encoding="utf-8").removesuffix("\n")

    assert compile_example(example) == expected


if __name__ == "__main__":
    write_goldens()
    sys.stdout.write(f"wrote {len(EXAMPLES)} goldens to {_GOLDEN_DIR}\n")

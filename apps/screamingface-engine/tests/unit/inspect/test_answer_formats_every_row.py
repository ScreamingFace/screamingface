# pyright: reportMissingImports=false
# WHY file-level: the catalogue assembles through inspect_ai and inspect_evals, absent in the
# extra-less typecheck install.
"""No Benchmark page goes without its answer format (OME-1906, PR 2 of 2).

FEATURE: answer format on the Benchmark page. `test_answer_formats.py` proves each answer
format is true; this file proves no imported row is left out, so an imported row added later
fails here until its page says how its replies are read. AIDEV-NOTE: a hand-built core
Benchmark (medxpert) is not in this catalogue; its sentence is pinned by its own test.

Runs only with the `inspect` extra installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from screamingface_engine_inspect.answer_formats import (  # noqa: E402
    ANSWER_FORMATS,
    answer_format_for,
)
from screamingface_engine_inspect.benchmarks import BENCHMARKS  # noqa: E402


def test_every_catalogue_row_has_an_answer_format() -> None:
    """INVARIANT: a new row fails here until its answer format is written and proved."""

    missing: list[str] = [
        spec.key for spec in BENCHMARKS if answer_format_for(spec.key, spec.scorer) is None
    ]

    assert missing == []


def test_every_answer_format_serves_at_least_one_row() -> None:
    """An answer format whose row and scorer left the catalogue is dead text; drop it."""

    served: set[str] = {key for spec in BENCHMARKS for key in (spec.key, spec.scorer)}

    assert sorted(set(ANSWER_FORMATS) - served) == []

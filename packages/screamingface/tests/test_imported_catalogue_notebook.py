"""The imported-catalogue notebook is the front door to the imported boards.

INVARIANT under test (OME-1202): the examples suite carries one notebook that walks the
imported catalogue — it lists benchmarks (where provenance renders as one group per
origin), fetches a real imported board by its catalogue id, and evaluates a fusion
against it — using only the public SDK surface and never enabling a paid run by default.
The notebook gate checks regeneration, not content, so this contract lives here.
"""

from __future__ import annotations

import runpy
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_NOTEBOOK_NAME = "12_imported_benchmarks.ipynb"

# WHY hardcoded: the SDK cannot import the Engine's board table (separate deployable);
# this is the catalogue id the Engine publishes for the imported GSM8K board
# (`inspect-<key>`, apps/screamingface-engine .../screamingface_engine_inspect/boards.py).
_IMPORTED_BOARD_ID = "inspect-gsm8k"


def _cells() -> list:
    """Build the imported-catalogue notebook fresh from the deterministic builder."""
    builder = runpy.run_path(str(_ROOT / "scripts/build_notebooks.py"))["notebooks"]
    notebooks = builder()
    assert _NOTEBOOK_NAME in notebooks, "the imported-catalogue notebook is not registered"
    return notebooks[_NOTEBOOK_NAME].cells


def test_notebook_walks_listing_then_imported_board_then_fusion_evaluate() -> None:
    # STORY: as a researcher, I open one notebook and go catalogue → imported board →
    # fusion run without reverse-engineering SDK calls from tickets.
    source = "\n".join(cell.source for cell in _cells())
    assert "sf.benchmarks.list()" in source
    assert f'sf.benchmarks.get("{_IMPORTED_BOARD_ID}")' in source
    assert "sf.Fusion(" in source
    assert f'benchmark="{_IMPORTED_BOARD_ID}"' in source


def test_notebook_stays_on_the_public_surface_and_never_pays_by_default() -> None:
    code = "\n".join(cell.source for cell in _cells() if cell.cell_type == "code")
    # INVARIANT: the notebook consumes the public SDK only — no engine internals,
    # no private modules, no inspect runner.
    assert "screamingface._" not in code
    assert "screamingface_engine" not in code
    assert "inspect_ai" not in code
    # INVARIANT: Run All must never spend by default (paid-runs rule).
    assert not any(line.strip() == "RUN_EVALUATION = True" for line in code.splitlines()), (
        "public notebooks must not enable paid evaluation by default"
    )

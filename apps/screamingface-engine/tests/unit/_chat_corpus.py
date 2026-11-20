"""The recipe corpus of the chat recipe tests: the SDK surface corpus and the Gate contract
corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).parents[4]
GATE_CONTRACT = Path(__file__).parent / "data" / "gate_contract"
SURFACE_PARITY = REPO / "packages/screamingface/tests/data/surface_parity.json"


def corpus() -> dict[str, str]:
    """Every corpus recipe by name: the SDK surface corpus, then the Gate contract corpus."""

    surface = json.loads(SURFACE_PARITY.read_text())
    recipes = {str(name): str(text) for name, text in surface.items()}
    for path in sorted(GATE_CONTRACT.glob("*.url4")):
        recipes[path.name] = path.read_text().strip()
    return recipes

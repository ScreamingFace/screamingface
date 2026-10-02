"""The public surface gains only the block names (OME-1289 gap, BK#11).

GUARD: passes at once. It pins that unit 4 exports the five block names and nothing else of the
reducer machinery (no Reducer, Signal, Matches or Filter at the top level).
"""

from __future__ import annotations

import json
from pathlib import Path

import screamingface as sf

_SNAPSHOT = Path(__file__).parent / "public_surface_snapshot.json"


def test_public_surface_adds_only_block_names() -> None:
    assert {"Extract", "Reduce", "signal", "matches", "Answer"} <= set(sf.__all__)
    for hidden in ("Filter", "Reducer", "Signal", "Matches"):
        assert hidden not in sf.__all__
    assert not hasattr(sf, "Reducer")
    assert not hasattr(sf, "reducers")

    snapshot = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["screamingface"]["__all__"] == sorted(sf.__all__)
    assert "TraceEntry" in snapshot["screamingface.report"]["__all__"]

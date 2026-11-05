"""The SDK reads the rank and the cut that the Engine wrote for a rank run (E4b part 2 unit 3).

The Engine test ``test_combine_evidence_contract_fixture.py`` runs the real combine core for the
PRD scenario RK-1 (``sf.Rank(2, by_signal=sf.signal("cost_usd"), order="min")``, costs 0.03, 0.01,
0.02, 0.01) and pins it as ``rank_min_cost`` in ``evidence_cases.json``. This test only READS it.
The expected ranks are computed by hand: cheapest first, equal costs in author order.
"""

from __future__ import annotations

import json
from typing import Any

from _combine_contract import COMBINE_CONTRACT, requires_engine_app

from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface.combine_evidence import CombineEvidence
from screamingface.report import CombineCut

_CASES = COMBINE_CONTRACT / "evidence_cases.json"


@requires_engine_app
def test_sdk_reads_rank_and_cut_from_a_rank_run() -> None:
    cases: dict[str, Any] = json.loads(_CASES.read_text(encoding="utf-8"))
    assert "rank_min_cost" in cases, "regenerate evidence_cases.json (E4b part 2 unit 3)"
    wire = cases["rank_min_cost"]

    decoded = decode_combine_evidence(wire, "Engine evidence rank_min_cost")

    assert isinstance(decoded, CombineEvidence)
    assert [row.rank for row in decoded.members] == [4, 1, 3, 2]
    assert decoded.chosen == ("member_2", "member_4")
    assert isinstance(decoded.cut, CombineCut)
    assert (decoded.cut.k, decoded.cut.order) == (2, "min")
    assert decoded.to_dict() == wire

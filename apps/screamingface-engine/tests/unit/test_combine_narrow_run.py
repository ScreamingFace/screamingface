"""SDK-compiled narrow recipes run in the Engine (E4b map-reduce surface unit 5, NC-5).

FEATURE: the url4 files ``narrow_filter_mean_candidate.url4`` and
``narrow_rank_vote_candidate.url4`` under ``data/combine_contract/`` are what the SDK compiles from
``Fanout >> Filter >> Mean`` and ``Fanout >> Judge >> Rank >> Vote(weights="score:judge")`` (the
SDK drift guard ``ST/test_narrow_contract_fixtures.py`` keeps them byte-equal). This test runs each
one through the mocked gateway of ``_signal_world.run_candidate``.
STORY: as a researcher, the narrow step and the reduce run in ONE combine call, and the evidence
says which members the narrow step left out.
INVARIANT defended: the evidence of a real run equals the contract cases of
``narrow_evidence_cases.json`` (``filter_mean``, ``judge_rank_weighted_vote``) on the narrow
record, the member rows and the result; the judge is called once for its two readers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _signal_world import operation, run_candidate

_DATA = Path(__file__).parent / "data" / "combine_contract"
_CASES = _DATA / "narrow_evidence_cases.json"


def _fixture(name: str) -> str:
    # WHY read inside the test: a missing fixture fails this test, not the module's collection
    return (_DATA / name).read_text(encoding="utf-8").removesuffix("\n")


def _case(name: str) -> dict[str, Any]:
    cases: dict[str, Any] = json.loads(_CASES.read_text(encoding="utf-8"))
    return cases[name]


def _rows(combine: dict[str, Any]) -> list[tuple[str, str | None]]:
    return [(row["status"], row["reason"]) for row in combine["members"]]


@pytest.mark.asyncio
async def test_engine_runs_the_sdk_filter_then_mean() -> None:
    # The values and confidences of the filter_mean contract case; delta has no confidence.
    models = {
        "prov/alpha": ('{"answer": 10, "confidence": 0.9}', "0.001"),
        "prov/beta": ('{"answer": 100, "confidence": 0.2}', "0.001"),
        "prov/gamma": ('{"answer": 20, "confidence": 0.8}', "0.001"),
        "prov/delta": ('{"answer": 7}', "0.001"),
    }
    seen: list[dict[str, Any]] = []

    record = await run_candidate(
        _fixture("narrow_filter_mean_candidate.url4"), models, "miss", on_request=seen.append
    )

    case = _case("filter_mean")
    assert record["status"] == "completed"
    # Oracle: (10 + 20) / 2 = 15; with every member the mean would be (10 + 100 + 20 + 7) / 4.
    assert record["output"] == "15"
    assert len(seen) == 4  # the members only: the narrow step is in the combine call
    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("answer", "mean")
    assert combine["operators"] == case["operators"]
    assert combine["narrow"] == case["narrow"]
    assert _rows(combine) == _rows(case)
    assert [row["value"] for row in combine["members"]] == ["10", "100", "20", "7"]
    assert [row["signals"] for row in combine["members"]] == [
        row["signals"] for row in case["members"]
    ]
    assert combine["mean"] == case["mean"]
    assert combine["result"] == case["result"]
    assert combine["dropped"] == 0


@pytest.mark.asyncio
async def test_engine_runs_the_sdk_judge_rank_then_weighted_vote() -> None:
    # The texts and judge scores of the judge_rank_weighted_vote contract case.
    models = {
        "prov/alpha": ("A", "0.001"),
        "prov/beta": ("B", "0.001"),
        "prov/gamma": ("C", "0.001"),
        "prov/delta": ("C", "0.001"),
        "prov/judge": ('{"member_1": 2, "member_2": 9, "member_3": 8, "member_4": 7}', "0.001"),
    }
    seen: list[dict[str, Any]] = []

    record = await run_candidate(
        _fixture("narrow_rank_vote_candidate.url4"), models, "miss", on_request=seen.append
    )

    case = _case("judge_rank_weighted_vote")
    assert record["status"] == "completed"
    # Oracle: the top two by the judge are beta (b, 9) and gamma (c, 8): b wins 9 to 8. Over all
    # four members, c would win 8 + 7 = 15.
    assert record["output"] == "B"
    # four members and ONE judge call for its two readers (the narrow rank and the weights)
    assert len(seen) == 5
    assert sum(call["model"] == "prov/judge" for call in seen) == 1
    combine = operation(record, "op_synthesis_1")["combine"]
    assert (combine["kind"], combine["reducer"]) == ("answer", "vote")
    assert combine["narrow"] == case["narrow"]
    assert _rows(combine) == _rows(case)
    assert [row["weight"] for row in combine["members"]] == [2.0, 9.0, 8.0, 7.0]
    assert [row["signals"] for row in combine["members"]] == [
        row["signals"] for row in case["members"]
    ]
    assert combine["tally"] == case["tally"]
    assert combine["chosen"] == case["chosen"]
    assert combine["agreement"] == case["agreement"]
    assert combine["signal"] == case["signal"]
    assert combine["result"] == case["result"]

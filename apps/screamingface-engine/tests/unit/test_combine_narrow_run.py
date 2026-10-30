"""SDK-compiled narrow recipes run in the Engine (E4b map-reduce surface unit 5, NC-5).

FEATURE: the url4 files ``narrow_filter_mean_candidate.url4`` and
``narrow_rank_vote_candidate.url4`` and ``narrow_judge_rank_vote_candidate.url4`` under
``data/combine_contract/`` are what the SDK compiles from ``Fanout >> Filter >> Mean``,
``Fanout >> Judge >> Rank >> Vote(weights="score:judge")`` and ``Fanout >> Judge >> Rank >>
Vote()`` (the SDK drift guard ``ST/test_narrow_contract_fixtures.py`` keeps them byte-equal). This
test runs each one through the mocked gateway of ``_signal_world.run_candidate``.
STORY: as a researcher, the narrow step and the reduce run in ONE combine call, and the evidence
says which members the narrow step left out.
INVARIANT defended: the whole combine record of a real run equals the contract case of
``narrow_evidence_cases.json`` (``filter_mean``, ``judge_rank_weighted_vote``), except a short
named list of keys where the SDK recipe differs from the case's hand-written spec; the judge is
called once, also when only a narrow step reads it.
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


# The texts and judge scores of the judge_rank_weighted_vote contract case.
_JUDGED_PANEL = {
    "prov/alpha": ("A", "0.001"),
    "prov/beta": ("B", "0.001"),
    "prov/gamma": ("C", "0.001"),
    "prov/delta": ("C", "0.001"),
    "prov/judge": ('{"member_1": 2, "member_2": 9, "member_3": 8, "member_4": 7}', "0.001"),
}


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

    assert record["status"] == "completed"
    # Oracle: (10 + 20) / 2 = 15; with every member the mean would be (10 + 100 + 20 + 7) / 4.
    assert record["output"] == "15"
    assert len(seen) == 4  # the members only: the narrow step is in the combine call
    assert operation(record, "op_synthesis_1")["combine"] == _case("filter_mean")


@pytest.mark.asyncio
async def test_engine_runs_the_sdk_judge_rank_then_weighted_vote() -> None:
    seen: list[dict[str, Any]] = []

    record = await run_candidate(
        _fixture("narrow_rank_vote_candidate.url4"), _JUDGED_PANEL, "miss", on_request=seen.append
    )

    assert record["status"] == "completed"
    # Oracle: the top two by the judge are beta (b, 9) and gamma (c, 8): b wins 9 to 8. Over all
    # four members, c would win 8 + 7 = 15.
    assert record["output"] == "B"
    # four members and ONE judge call for its two readers (the narrow rank and the weights)
    assert len(seen) == 5
    assert sum(call["model"] == "prov/judge" for call in seen) == 1
    case = _case("judge_rank_weighted_vote")
    # WHY the one override: the case's hand-written spec selects with first_holder@1, and the SDK's
    # weighted vote with max_weight_holder@1; both choose member_2 here.
    expected = {**case, "operators": [*case["operators"][:3], "max_weight_holder@1"]}
    assert operation(record, "op_synthesis_1")["combine"] == expected


@pytest.mark.asyncio
async def test_engine_runs_the_sdk_judge_rank_then_plain_vote() -> None:
    seen: list[dict[str, Any]] = []

    record = await run_candidate(
        _fixture("narrow_judge_rank_vote_candidate.url4"),
        _JUDGED_PANEL,
        "miss",
        on_request=seen.append,
    )

    assert record["status"] == "completed"
    # Oracle: the judge keeps beta (b) and gamma (c); the plain vote ties 1 to 1, and the first
    # holder in author order is beta. Over all four members, c would win 2 to 1.
    assert record["output"] == "B"
    # only the narrow rank reads the judge, and it is still ONE call
    assert len(seen) == 5
    assert sum(call["model"] == "prov/judge" for call in seen) == 1
    case = _case("judge_rank_weighted_vote")
    # WHY these overrides: the main vote has no weights, so it is mode@1 with no weight per row,
    # each holder counts 1, the tie is 1 to 1 (agreement 1/2), and the evidence ``signal`` (the
    # main step's key) is absent. The narrow record, the rows and the result are the case's.
    expected = {
        **case,
        "operators": ["last_line@1", "text@1", "mode@1", "first_holder@1"],
        "members": [{**row, "weight": None} for row in case["members"]],
        "tally": [{**entry, "score": 1.0} for entry in case["tally"]],
        "agreement": 0.5,
        "tie": True,
        "signal": None,
    }
    assert operation(record, "op_synthesis_1")["combine"] == expected

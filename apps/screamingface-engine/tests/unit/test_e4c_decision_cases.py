r"""The E4c decision records of real Engine runs: the contract fixture both packages read.

FEATURE: E4c (OME-1291) C9 ``data/gate_contract/decision_cases.json``; branch-core #21, docs #3,
#4, #16; report #3.
STORY: as a maintainer, the Engine writes one GateDecision per scenario and the SDK decodes and
renders the same records, so a drift on either side fails a test.
The url4 files are the SDK compile (``packages/screamingface/tests/test_e4c_gate_fixtures.py``).
A missing or stale fixture FAILS here. A deliberate change is made by running this file as a
script (``write_cases()``), and the change needs an owner-approved manifest (C9)::

    uv run python tests/unit/test_e4c_decision_cases.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, get_args

import pytest
from _gate_world import FAIL, REFUSE, Gateway, fixture, operations, run_gate
from test_e4c_budget_runs import _priced

from screamingface_engine.combine.decision import (
    BudgetUnit,
    GateDecision,
    GateKind,
    GateResultStatus,
    NotRunReason,
    PanelBranch,
    SelectorKind,
)
from screamingface_engine.combine.ports import AbstainReason

DATA = Path(__file__).parent / "data"
_CASES = DATA / "gate_contract" / "decision_cases.json"

_ROUTER = {"prov/math": "M", "prov/coder": "C", "prov/general": "G"}
_GUARD = {"prov/clf": "safe", "prov/med": "MED", **_ROUTER}
_PANEL = {"prov/alpha": "A", "prov/beta": "A", "prov/gamma": "A"}
_AGREE = {**_PANEL, "prov/judge": "member_3"}
_SPLIT = {"prov/alpha": "A", "prov/beta": "A", "prov/gamma": "B", "prov/judge": "member_3"}
_NO_VOTE = {"prov/alpha": " ", "prov/beta": " ", "prov/gamma": " ", "prov/judge": "x"}
# _replies(("A", "B"), ("C", "D")) of test_e4c_cascade_runs.py
_CASCADE = {"prov/a": "A", "prov/b": "B", "prov/c": "C", "prov/d": "D", "prov/large": "L"}
_MEMBERS = {"prov/math": "A", "prov/code": "C", "prov/web": "A"}
_LABEL_ROUTER = {**_PANEL, "prov/router": "code", "prov/coder": "C", "prov/general": "G"}

# scenario -> (fixture file, gateway replies, question)
_SCENARIOS: dict[str, tuple[str, dict[str, Any], str]] = {
    "keyword_router_selected": ("keyword_router.url4", _ROUTER, "an integral please"),
    # test_e4c_gate_runs.py: a refusing body ends the run "refused"; its decision has no result
    "keyword_router_body_refused": (
        "keyword_router.url4",
        {**_ROUTER, "prov/math": REFUSE},
        "an integral",
    ),
    # test_e4c_gate_runs.py: the classifier fails, the selector is "failed" and the default runs
    "guard_tree_failed_selector": ("guard_tree.url4", {**_GUARD, "prov/clf": FAIL}, "an integral"),
    "label_router_code": ("d2_label_router.url4", _LABEL_ROUTER, "what is 2 + 2?"),
    "lazy_judge_gate_passes": ("lazy_judge.url4", _AGREE, "what is 2 + 2?"),
    "lazy_judge_gate_fails": ("lazy_judge.url4", _SPLIT, "what is 2 + 2?"),
    "lazy_judge_no_voters": ("lazy_judge.url4", _NO_VOTE, "what is 2 + 2?"),
    "lazy_writer_in_band": (
        "lazy_writer.url4",
        {
            "prov/alpha": "Confidence: 50\nA",
            "prov/beta": "Confidence: 50\nA",
            "prov/gamma": "Confidence: 50\nA",
        },
        "what is 2 + 2?",
    ),
    "cascade_escalates": ("cascade_three.url4", _CASCADE, "the question"),
    "cascade_abstains_gate_not_met": ("cascade_abstain.url4", _CASCADE, "what is 2 + 2?"),
    "budget_choice_runs_then": (
        "budget_choice.url4",
        {"prov/big": "B", "prov/small": "S"},
        "what is 2 + 2?",
    ),
    "budget_tokens_refused": (
        "budget_tokens.url4",
        {"prov/big": "B", "prov/small": "S"},
        "what is 2 + 2?",
    ),
    # test_e4c_budget_runs.py: a reply with no price and no usage leaves the spend unpriced
    "budget_two_units_unpriced": (
        "budget_two_units.url4",
        {"prov/prep": "P", "prov/big": "B"},
        "what is 2 + 2?",
    ),
    "budget_lazy_judge_refused_answers_majority": (
        "budget_lazy_judge.url4",
        _SPLIT,
        "what is 2 + 2?",
    ),
    "skip_vote_members": (
        "skip_vote.url4",
        {"prov/sel": "math, web", **_MEMBERS},
        "what is 2 + 2?",
    ),
    "word_abstain": ("word_abstain.url4", {"prov/general": "G"}, "write python"),
}


def _gateway(name: str) -> Gateway:
    _, replies, _ = _SCENARIOS[name]
    if name == "budget_two_units_unpriced":
        return _priced(replies, drop=("usd", "usage"))
    return Gateway(replies)


async def _decisions(name: str) -> dict[str, Any]:
    fixture_name, _, question = _SCENARIOS[name]
    record = await run_gate(fixture(fixture_name), _gateway(name), question)
    return {op_id: op["decision"] for op_id, op in operations(record).items() if "decision" in op}


def write_cases() -> None:
    """Run every scenario on the fake gateway and write the decision records (see the docstring)."""
    cases = {name: asyncio.run(_decisions(name)) for name in sorted(_SCENARIOS)}
    _CASES.write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")


def _fixture() -> dict[str, dict[str, Any]]:
    assert _CASES.is_file(), f"missing gate contract fixture {_CASES}; run this file as a script"
    loaded = json.loads(_CASES.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(_SCENARIOS))
async def test_decision_cases_fixture_matches_the_engine_runs(name: str) -> None:
    # C9: the committed record is byte for byte what the Engine writes today (int and float apart).
    entry = _fixture()[name]
    assert entry
    assert json.dumps(entry) == json.dumps(await _decisions(name))


def test_every_scenario_has_a_fixture_entry() -> None:
    assert set(_fixture()) == set(_SCENARIOS)


def test_every_fixture_record_round_trips_through_the_engine_model() -> None:
    # The Engine publishes the record with model_dump_json(by_alias=True), null fields included.
    for scenario, decisions in _fixture().items():
        for op_id, record in decisions.items():
            dumped = GateDecision.model_validate(record).model_dump(mode="json", by_alias=True)
            assert json.dumps(dumped) == json.dumps(record), f"{scenario} {op_id}"


def test_the_scenarios_cover_the_decision_shapes() -> None:
    records = [record for decisions in _fixture().values() for record in decisions.values()]
    results = [record["result"] for record in records if record["result"] is not None]
    views = [view for record in records for view in record["budget"] or ()]
    links = [record["panel"] for record in records if record["panel"] is not None]
    selectors = [selector for record in records for selector in record["selectors"]]

    assert {record["kind"] for record in records} == set(get_args(GateKind))
    # fail_closed is not here: a run that fails closed raises and keeps no operations.
    assert {result["status"] for result in results} == set(get_args(GateResultStatus)) - {
        "fail_closed"
    }
    assert any(record["result"] is None for record in records)
    # cut_not_met and output_missing are combine-step reasons; no Gate result writes them.
    assert {result["reason"] for result in results if result["status"] == "abstain"} == set(
        get_args(AbstainReason)
    ) - {"cut_not_met", "output_missing"}
    assert {entry["reason"] for record in records for entry in record["not_run"]} == set(
        get_args(NotRunReason)
    )
    assert {link["branch"] for link in links} == set(get_args(PanelBranch)) | {None}
    assert {selector["kind"] for selector in selectors} == set(get_args(SelectorKind))
    assert {selector["status"] for selector in selectors} >= {"computed", "failed"}
    assert {view["unit"] for view in views} == set(get_args(BudgetUnit))
    assert any(view["refused"] for view in views)
    assert any(view["unpriced"] > 0 for view in views)
    assert any(record["budget"] is None for record in records)


if __name__ == "__main__":
    write_cases()

"""The Engine's decision records decode and render in the SDK (E4c, C9 contract fixture).

FEATURE: E4c (OME-1291) C9 ``gate_contract/decision_cases.json``; report #3 (RP-1, RP-2, RP-20).
STORY: as a maintainer, every record the Engine writes is one the SDK decodes and renders, so a
drift on either side fails here, not in a saved Report.
The Engine side is ``apps/screamingface-engine/tests/unit/test_e4c_decision_cases.py``, which
writes the fixture from real Engine runs; this module reads it. A missing or stale fixture FAILS
here: regenerate it from the Engine side.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from _combine_contract import ENGINE_APP, engine_operators, requires_engine_app
from test_e4c_budget_fixtures import (
    budget_choice,
    budget_lazy_judge,
    budget_tokens,
    budget_two_units,
)
from test_e4c_docs_fixtures import d2_label_router
from test_e4c_gate_fixtures import (
    cascade_abstain,
    cascade_three,
    guard_tree,
    keyword_router,
    lazy_judge,
    lazy_writer,
    skip_vote,
    word_abstain,
)
from test_e4c_report import case, operation
from test_report import benchmark

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.gate_decision import decode_gate_decision
from screamingface._ui.branch_view import GateSummary, branch_sections_html

GATE_CONTRACT = ENGINE_APP / "tests" / "unit" / "data" / "gate_contract"
CASES_PATH = GATE_CONTRACT / "decision_cases.json"
MIN_SCENARIOS = 12

# scenario -> (fixture file, the SDK recipe the Engine ran). The fixture file is the recipe's own
# compile, so the render reads the same topology the Engine decided on.
_RECIPES: dict[str, tuple[str, Callable[[], object]]] = {
    "keyword_router_selected": ("keyword_router.url4", keyword_router),
    "keyword_router_body_refused": ("keyword_router.url4", keyword_router),
    "guard_tree_failed_selector": ("guard_tree.url4", guard_tree),
    "label_router_code": ("d2_label_router.url4", d2_label_router),
    "lazy_judge_gate_passes": ("lazy_judge.url4", lazy_judge),
    "lazy_judge_gate_fails": ("lazy_judge.url4", lazy_judge),
    "lazy_judge_no_voters": ("lazy_judge.url4", lazy_judge),
    "lazy_writer_in_band": ("lazy_writer.url4", lazy_writer),
    "cascade_escalates": ("cascade_three.url4", cascade_three),
    "cascade_abstains_gate_not_met": ("cascade_abstain.url4", cascade_abstain),
    "budget_choice_runs_then": ("budget_choice.url4", budget_choice),
    "budget_tokens_refused": ("budget_tokens.url4", budget_tokens),
    "budget_two_units_unpriced": ("budget_two_units.url4", budget_two_units),
    "budget_lazy_judge_refused_answers_majority": ("budget_lazy_judge.url4", budget_lazy_judge),
    "skip_vote_members": ("skip_vote.url4", skip_vote),
    "word_abstain": ("word_abstain.url4", word_abstain),
}
# The direct members of the fanout block of skip_vote (report.py needs at least one): one per skip
# Gate, each routed to its model.
_SKIP_MEMBERS = tuple(
    sf.MemberResult(
        operation_id=f"op_gate_{index}",
        name=f"member_{index}",
        kind="gate",
        models=[model],
        failures=None,
        duration_ms=None,
        usage=None,
    )
    for index, model in enumerate(("prov/math", "prov/code", "prov/web"), start=1)
)
_MEMBERS: dict[str, tuple[sf.MemberResult, ...]] = {"skip_vote_members": _SKIP_MEMBERS}
# The text each (scenario, op_id) shows in its Case pane or run summary (branch_view.py).
_LINES: dict[tuple[str, str], str] = {
    (
        "keyword_router_selected",
        "op_gate_1",
    ): "not run · otherwise · not selected · avoided 1 model call",
    ("keyword_router_body_refused", "op_gate_1"): "result · —",
    ("guard_tree_failed_selector", "op_gate_1"): "ran · otherwise",
    ("guard_tree_failed_selector", "op_gate_2"): "failed · the default branch ran",
    ("guard_tree_failed_selector", "op_gate_3"): "failed · the default branch ran",
    ("guard_tree_failed_selector", "op_gate_4"): "ran · then",
    ("label_router_code", "op_gate_1"): "not run · then · not selected · avoided 3 model calls",
    ("label_router_code", "op_gate_2"): "not run · otherwise · not selected · avoided 1 model call",
    (
        "lazy_judge_gate_passes",
        "op_gate_1",
    ): "not run · otherwise · not selected · avoided 1 model call",
    ("lazy_judge_gate_fails", "op_gate_1"): "not run · then · not selected · avoided 0 model calls",
    ("lazy_judge_no_voters", "op_gate_1"): "result · abstained · no_votes",
    ("lazy_writer_in_band", "op_gate_1"): "result · abstained · in_band",
    ("cascade_escalates", "op_gate_1"): "ran · otherwise",
    ("cascade_escalates", "op_gate_2"): "ran · otherwise",
    ("cascade_escalates", "op_gate_3"): "result · answered",
    ("cascade_abstains_gate_not_met", "op_gate_1"): "result · abstained · gate_not_met",
    (
        "budget_choice_runs_then",
        "op_gate_1",
    ): "not run · otherwise · not selected · avoided 1 model call",
    (
        "budget_tokens_refused",
        "op_gate_1",
    ): "not run · then · refused by the budget · avoided 1 model call",
    ("budget_two_units_unpriced", "op_gate_1"): "1 call with unknown cost counted as $0",
    (
        "budget_lazy_judge_refused_answers_majority",
        "op_gate_1",
    ): "not run · otherwise · refused by the budget · avoided 1 model call",
    ("skip_vote_members", "op_gate_1"): "ran · then",
    ("skip_vote_members", "op_gate_2"): "result · —",
    ("skip_vote_members", "op_gate_3"): "ran · then",
    ("word_abstain", "op_gate_1"): "result · abstained · gate_not_met",
}
_TAG = re.compile(r"<[^>]+>")


def _cases() -> dict[str, dict[str, dict[str, Any]]]:
    assert CASES_PATH.is_file(), f"missing gate contract fixture {CASES_PATH}; run the Engine side"
    loaded = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


_PAIRS = (
    [
        (scenario, op_id, record)
        for scenario, decisions in sorted(_cases().items())
        for op_id, record in sorted(decisions.items())
    ]
    if ENGINE_APP.exists()
    else []
)
_IDS = [f"{scenario}-{op_id}" for scenario, op_id, _ in _PAIRS]


def _candidate(
    build: Callable[[], object], result: sf.CaseResult, members: tuple[sf.MemberResult, ...]
) -> sf.CandidateResult:
    """The one-Case Candidate of test_e4c_report.gate_candidate, with direct members."""

    compiled = compile_candidate(build(), operators=engine_operators())  # type: ignore[arg-type]
    return sf.CandidateResult(
        benchmark=benchmark(),
        run_id="run_gate",
        started_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
        completed_at=datetime(2026, 10, 22, 12, 0, 1, tzinfo=UTC),
        name="router",
        kind=compiled.kind,
        url4=compiled.url4,
        models=compiled.models,
        operations=compiled.operations,
        score=0.5,
        coverage=1.0,
        metrics={},
        cases=(result,),
        members=members,
        failures=(),
        usage=sf.Usage(input_tokens=10, output_tokens=4, cost_usd="0.01"),
    )


@requires_engine_app
def test_fixture_holds_at_least_the_minimum_scenarios() -> None:
    # A fixture emptied on the Engine side fails here too.
    assert len(_cases()) >= MIN_SCENARIOS


@requires_engine_app
def test_every_fixture_scenario_has_a_recipe_and_the_recipe_is_the_fixture() -> None:
    assert set(_cases()) == set(_RECIPES)
    for scenario, (file_name, build) in _RECIPES.items():
        fixture_text = (GATE_CONTRACT / file_name).read_text(encoding="utf-8").removesuffix("\n")
        compiled = compile_candidate(build(), operators=engine_operators())  # type: ignore[arg-type]
        assert compiled.url4 == fixture_text, scenario


@requires_engine_app
@pytest.mark.parametrize(("scenario", "op_id", "record"), _PAIRS, ids=_IDS)
def test_sdk_decodes_every_engine_decision_record(
    scenario: str, op_id: str, record: dict[str, Any]
) -> None:
    # C8 / RP-1: the strict decoder accepts the Engine's record and writes back the same bytes.
    decoded = decode_gate_decision(record, f"{scenario} {op_id}")

    assert decoded is not None
    assert json.dumps(decoded.to_dict()) == json.dumps(record)


@requires_engine_app
@pytest.mark.parametrize(("scenario", "op_id", "record"), _PAIRS, ids=_IDS)
def test_sdk_report_renders_every_engine_decision_record(
    scenario: str, op_id: str, record: dict[str, Any]
) -> None:
    # C8 / RP-2: the Case pane and the run summary render the record with its own recipe, name the
    # Gate, and show the line that depends on this record.
    result = case(1, (operation(op_id.removeprefix("op_"), record),))
    build = _RECIPES[scenario][1]
    candidate = _candidate(build, result, _MEMBERS.get(scenario, ()))
    summary = GateSummary()
    summary.add(result)

    summary_html = summary.html(candidate)
    text = _TAG.sub("", branch_sections_html(candidate, result) + summary_html)

    assert summary_html
    assert record["gate_id"] in text
    assert _LINES[(scenario, op_id)] in text

"""The judge link of a combine step in the trace (E4b part 2, judge-model PRD, JM#1-12).

FEATURE: the trace ``reduce`` entry of a step that reads a judge names the judge's own operation
(``judge_operation_id``) and the model of that call (``judge_model``).
STORY: as a researcher who reads the trace of a judge step, I can check that the model that scored
the members is not the model that wrote the answer after the cut.
INVARIANT defended: the link is an SDK view, not a wire key (ans:Q4, P8). It reads the evidence
(rule J1-J3, P9), the bound operation graph and the judge operation's own accounting. It never
guesses: no graph, no unique ``"judge"`` dependency or no accounting gives null. The url4 of every
judge recipe keeps its bytes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from _answer_fixtures import bound
from _combine_contract import COMBINE_CONTRACT, read_contract, requires_engine_app
from _combine_recipes import compile_recipe
from _reducer_fixtures import evidence_wire
from test_combine_evidence import _fields_variant, _judge_variant
from test_engine_url4_contract_fixtures import judge_vote_url4
from test_filter_judge_url4_fixture import filter_judge_url4
from test_judge_order_url4_contract_fixtures import judge_order_min_url4
from test_quorum_url4_contract_fixtures import quorum_judge_vote_url4
from test_reducer_url4_round_trip import _linked
from test_report_trace import _accounting, _case, _evidence, _info

import screamingface as sf
from screamingface._evaluation.url4 import _candidate_from_url4
from screamingface.case_result import CaseOperation
from screamingface.operation import OperationInfo
from screamingface.operation_accounting import OperationAccounting, OperationCache
from screamingface.report_trace import TRACE_FIELDS

_SCHEMAS = Path(__file__).parent / "data" / "schemas"
_KEYS = ("judge_operation_id", "judge_model")
_JUDGE_MODEL = "provider/judge-x"
_LINKED = {"judge_operation_id": "op_judge_1", "judge_model": _JUDGE_MODEL}
_UNLINKED: dict[str, str | None] = {"judge_operation_id": None, "judge_model": None}
_MEMBERS = ("op_model_1", "op_model_2", "op_model_3")
_SCORES = {"member_1": 0.2, "member_2": 0.9, "member_3": 0.5}
_SCORES_READING = {
    "raw": '{"member_1":0.2,"member_2":0.9,"member_3":0.5}',
    "returns": "scores",
    "parsed": _SCORES,
}
_SELECTION_RESULT = {"member_id": None, "value": None, "status": "answered", "reason": None}
_JUDGE_SIGNAL = {"key": "score:judge", "order": None}


# --- the evidence of each judge reading (wires the SDK decoder accepts) ---------------------------


def _judge_scores() -> dict[str, Any]:
    """J1: sf.Judge(returns="scores") as the synthesizer."""

    return evidence_wire(
        kind="selection",
        reducer="judge",
        operators=["scores@1", "max_score@1"],
        tally=None,
        judge=_SCORES_READING,
        presentation_order="author",
        chosen=["member_2"],
        agreement=None,
        result={"member_id": "member_2", "value": "12", "status": "answered", "reason": None},
    )


def _rank_by_judge(*, reading: bool = True) -> dict[str, Any]:
    """J2: sf.Rank(2, by=sf.Judge(...)); without a reading it is the JM-D4 abstain."""

    if not reading:
        return evidence_wire(
            kind="selection",
            reducer="rank",
            operators=["scores@1", "top_k@1"],
            tally=None,
            judge=None,
            presentation_order="author",
            chosen=[],
            built=False,
            agreement=None,
            result={"member_id": None, "value": None, "status": "abstain", "reason": "cut_not_met"},
        )
    return evidence_wire(
        kind="selection",
        reducer="rank",
        operators=["scores@1", "top_k@1"],
        tally=None,
        judge=_SCORES_READING,
        presentation_order="author",
        chosen=["member_2", "member_3"],
        built=True,
        agreement=None,
        result=_SELECTION_RESULT,
    )


def _filter_by_judge() -> dict[str, Any]:
    """J3: sf.Filter(where=sf.signal("score:judge") >= 7, judge=...)."""

    return evidence_wire(
        kind="selection",
        reducer="filter",
        operators=["filter@1", "kept@1"],
        tally=None,
        judge=None,
        presentation_order="author",
        signal=_JUDGE_SIGNAL,
        chosen=["member_1", "member_3"],
        built=True,
        agreement=None,
        result=_SELECTION_RESULT,
    )


def _vote_by_judge() -> dict[str, Any]:
    """J3: sf.Vote(weights=sf.signal("score:judge"), judge=...)."""

    return evidence_wire(
        operators=["last_number@1", "numeric@1", "weighted_mode@1", "max_weight_holder@1"],
        presentation_order="author",
        signal=_JUDGE_SIGNAL,
    )


def _pick_by_judge() -> dict[str, Any]:
    """J3: sf.Pick(by_signal=sf.signal("score:judge"), ...)."""

    return evidence_wire(
        kind="answer",
        reducer="pick",
        operators=["by_signal@1", "best_holder@1"],
        tally=None,
        agreement=None,
        presentation_order="author",
        signal={"key": "score:judge", "order": "max"},
    )


def _rank_by_values() -> dict[str, Any]:
    """JM-D2: scores@1 with source="values" (Rank by a numeric field) writes no judge reading."""

    return evidence_wire(
        kind="selection",
        reducer="rank",
        operators=["json_field@1", "numeric@1", "scores@1", "top_k@1"],
        tally=None,
        judge=None,
        chosen=["member_1", "member_2"],
        built=True,
        agreement=None,
        result=_SELECTION_RESULT,
    )


# --- the Case: three members, the extra operations, and one combine step --------------------------


def _judge_accounting(model: str | None = _JUDGE_MODEL) -> OperationAccounting:
    # WHY another response model: the link shows the request model, as the model_call entry does.
    return OperationAccounting(
        provider="provider",
        request_model=model,
        response_model="provider/judge-x-2026-10-01",
        usage=sf.Usage(input_tokens=10, output_tokens=4, cost_usd="0.002"),
        provider_latency_ms=30,
        provider_attempts=1,
        cache=OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
    )


def _extra_operation(info: OperationInfo, accounting: OperationAccounting | None) -> CaseOperation:
    """A judge or writer call; with no accounting it is an unattributed call (no output)."""

    if accounting is None:
        return CaseOperation(info.id, None, None, None)
    return CaseOperation(info.id, '{"member_1": 9}', "stop", accounting)


def _linked_case(
    wire: dict[str, Any],
    extras: Sequence[OperationInfo] = (_info("op_judge_1", "judge", *_MEMBERS),),
    *,
    model: str | None = _JUDGE_MODEL,
    accounted: bool = True,
    traced: Sequence[str] | None = None,
) -> sf.CaseResult:
    """op_model_1..3, the extra operations (judge or writer), then op_synthesis_1.

    The combine node depends on the members, then on every extra operation (the compile order,
    S/_case_views.py:213-226). ``traced`` names the extra operations the Case holds (default:
    all of them). Each one has the accounting of ``model``, or none when ``accounted`` is False.
    """

    held = [info for info in extras if traced is None or info.id in traced]
    calls = _judge_accounting(model) if accounted else None
    operations = [
        *(CaseOperation(member, f"text of {member}", "stop", _accounting()) for member in _MEMBERS),
        *(_extra_operation(info, calls) for info in held),
        CaseOperation("op_synthesis_1", "12", "stop", combine=_evidence(wire)),
    ]
    graph = (
        *(_info(member, "model") for member in _MEMBERS),
        *extras,
        _info("op_synthesis_1", "combine", *_MEMBERS, *(info.id for info in extras)),
    )
    return bound(_case(operations), graph)


def _reduce(case: sf.CaseResult) -> dict[str, Any]:
    entries = [entry.to_dict() for entry in case.trace() if entry.kind == "reduce"]
    assert len(entries) == 1
    return entries[0]


def _link(case: sf.CaseResult) -> dict[str, Any]:
    """The two link keys of the one reduce entry; a missing key is missing here too."""

    entry = _reduce(case)
    return {key: entry[key] for key in _KEYS if key in entry}


# --- JM#1, JM#2: CHAR ---------------------------------------------------------------------------

# sha256 of each judge url4 fixture (file text minus its last newline): the part base 0f4b9e292,
# then the judge-template@2 bytes of unit 7b (overview §4.3).
_JUDGE_URL4: list[tuple[str, Callable[[], str], str]] = [
    (
        "recipe_s10.url4",
        lambda: compile_recipe("recipe_s10.url4"),
        "d66e02f8838c46d0f4d1d9305ea6e4891777c188f1409dfccaf985517e7711e4",
    ),
    (
        "recipe_s11_max.url4",
        lambda: compile_recipe("recipe_s11_max.url4"),
        "7edd0c1dde469b72c3623c5280175dd9366e3cf81a826c9e19cd98e5fdc39f43",
    ),
    (
        "judge_vote_candidate.url4",
        judge_vote_url4,
        "b6273d0b30369d224efa04497907fd16273a8c86a4a882b8c56ec96d309be308",
    ),
    (
        "filter_judge_candidate.url4",
        filter_judge_url4,
        "58378dd3f08f126d5b074bd855d7025f97c0e7566cdd944c87e1e2e53572439e",
    ),
    (
        "judge_order_min_candidate.url4",
        judge_order_min_url4,
        "bfee9ed7b4d10851890adb2ac1134054206a5b703c20b58f6a574a3aa5c360a1",
    ),
    (
        "quorum_judge_vote_candidate.url4",
        quorum_judge_vote_url4,
        "a3317a46ff7fbb53917f5bcf78d1a7c7d80126efdd55eebeb45581bfa01ff0c4",
    ),
]


@requires_engine_app
@pytest.mark.parametrize(
    ("name", "build", "sha256"), _JUDGE_URL4, ids=[name for name, _, _ in _JUDGE_URL4]
)
def test_judge_recipe_url4_bytes_do_not_change(
    name: str, build: Callable[[], str], sha256: str
) -> None:
    """JM#1 (JM-4, ans:Q4): no combine spec change, so every judge url4 keeps its bytes."""

    compiled = build()

    assert hashlib.sha256(compiled.encode("utf-8")).hexdigest() == sha256
    assert (COMBINE_CONTRACT / name).is_file()
    assert read_contract(name) == compiled


def test_judge_call_model_call_entry_shows_its_model() -> None:
    """JM#2: the judge's own model_call entry already holds the model (S/_case_views.py:180-200)."""

    case = _linked_case(_judge_variant())

    calls = [entry.to_dict() for entry in case.trace() if entry.kind == "model_call"]
    judge = [call for call in calls if call["operation_id"] == "op_judge_1"]
    assert len(judge) == 1
    assert (judge[0]["member_id"], judge[0]["model"]) == (None, "provider/judge-x")


# --- JM#3 .. JM#12 ------------------------------------------------------------------------------


@pytest.mark.parametrize("wire", [_judge_variant, _judge_scores], ids=["label", "scores"])
def test_judge_reducer_trace_links_the_judge_operation_and_model(
    wire: Callable[[], dict[str, Any]],
) -> None:
    """JM#3 (JM-1, rule J1): the judge reducer links its one "judge" dependency."""

    case = _linked_case(wire())

    assert _link(case) == _LINKED
    calls = [entry.to_dict() for entry in case.trace() if entry.kind == "model_call"]
    judge_call = next(call for call in calls if call["operation_id"] == "op_judge_1")
    assert _reduce(case)["judge_model"] == judge_call["model"]


@pytest.mark.parametrize(
    "wire",
    [_rank_by_judge, _filter_by_judge, _vote_by_judge, _pick_by_judge],
    ids=["rank-J2", "filter-J3", "vote-J3", "pick-J3"],
)
def test_rank_filter_and_vote_by_judge_link_the_judge(wire: Callable[[], dict[str, Any]]) -> None:
    """JM#4 (JM-2, rules J2 and J3)."""

    assert _link(_linked_case(wire())) == _LINKED


@pytest.mark.parametrize(
    "extras",
    [(), (_info("op_judge_1", "judge", *_MEMBERS),)],
    ids=["no-judge-call", "judge-call-in-graph"],
)
def test_step_without_a_judge_has_null_judge_keys(extras: tuple[OperationInfo, ...]) -> None:
    """JM#5 (JM-3): a plain vote reads no judge, even when a judge call is in the graph."""

    assert _link(_linked_case(evidence_wire(), extras)) == _UNLINKED


def test_unattributed_judge_call_gives_null_model() -> None:
    """JM#6 (JM-E1): the id is set; the model is null when the call has no accounting."""

    unattributed = _linked_case(_judge_variant(), accounted=False)
    not_held = _linked_case(_judge_variant(), traced=())
    no_request_model = _linked_case(_judge_variant(), model=None)

    expected = {"judge_operation_id": "op_judge_1", "judge_model": None}
    assert _link(unattributed) == expected
    assert _link(not_held) == expected
    assert _link(no_request_model) == expected


def test_case_without_graph_gives_null_judge_keys() -> None:
    """JM#7 (JM-E2): an old result with no bound graph, or a graph without the combine node."""

    operations = [
        *(CaseOperation(member, f"text of {member}", "stop", _accounting()) for member in _MEMBERS),
        CaseOperation("op_judge_1", "{}", "stop", _judge_accounting()),
        CaseOperation("op_synthesis_1", "12", "stop", combine=_evidence(_judge_variant())),
    ]
    unbound = _case(operations)
    other_graph = bound(_case(operations), (_info("op_model_1", "model"),))

    assert _link(unbound) == _UNLINKED
    assert _link(other_graph) == _UNLINKED


@pytest.mark.parametrize(
    "extras",
    [
        (),
        (
            _info("op_judge_1", "judge", *_MEMBERS),
            _info("op_judge_2", "judge", *_MEMBERS),
        ),
    ],
    ids=["zero", "two"],
)
def test_zero_or_two_judge_dependencies_give_null_keys(extras: tuple[OperationInfo, ...]) -> None:
    """JM#8 (JM-E3): the rule holds, but there is no unique "judge" dependency."""

    assert _link(_linked_case(_judge_variant(), extras)) == _UNLINKED


@requires_engine_app
@pytest.mark.parametrize(
    ("name", "wire"),
    [("recipe_s11_max.url4", _judge_scores), ("recipe_s10.url4", _rank_by_judge)],
    ids=["s11-judge", "s10-rank-by-judge"],
)
def test_old_judge_url4_rebuilds_and_links_the_judge(
    name: str, wire: Callable[[], dict[str, Any]]
) -> None:
    """JM#9 (JM-D1): a url4 compiled before part 2 replays to the same graph, and links."""

    replayed = _candidate_from_url4(_linked(read_contract(name)))
    graph = {operation.id: operation for operation in replayed.operations}

    assert (graph["op_judge_1"].kind, graph["op_judge_1"].depends_on) == ("judge", _MEMBERS)
    assert graph["op_synthesis_1"].depends_on == (*_MEMBERS, "op_judge_1")
    operations = [
        CaseOperation(operation.id, f"text of {operation.id}", "stop", _accounting())
        for operation in replayed.operations
        if operation.kind == "model"
    ]
    operations.append(
        CaseOperation("op_judge_1", "{}", "stop", _judge_accounting("provider/judge"))
    )
    operations.append(CaseOperation("op_synthesis_1", "12", "stop", combine=_evidence(wire())))
    case = bound(_case(operations), replayed.operations)

    assert _link(case) == {"judge_operation_id": "op_judge_1", "judge_model": "provider/judge"}


@pytest.mark.parametrize(
    "wire",
    [_rank_by_values, lambda: _rank_by_judge(reading=False)],
    ids=["values-source", "judge-reading-null"],
)
def test_values_scores_rank_links_no_judge(wire: Callable[[], dict[str, Any]]) -> None:
    """JM#10 (JM-D2, JM-D4): scores@1 without a judge reading fails J2, even with a judge call."""

    assert _link(_linked_case(wire())) == _UNLINKED


def test_merge_writer_is_not_linked_as_judge() -> None:
    """JM#11 (JM-D3): a writer call has the kind "writer"; it is never the judge."""

    writer = _info("op_writer_summary_1", "writer", *_MEMBERS)
    judge = _info("op_judge_1", "judge", *_MEMBERS)

    assert _link(_linked_case(_fields_variant(), (writer,))) == _UNLINKED
    assert _link(_linked_case(_judge_variant(), (writer, judge))) == _LINKED


def test_trace_reduce_field_set_matches_report_trace_v1() -> None:
    """JM#12 (PRD §4): the two keys close the reduce kind, in code and in the approved snapshot."""

    expected = [
        "operation_id",
        "op",
        "rule",
        "mode",
        "tally",
        "chosen",
        "signal",
        "result",
        "dropped",
        "judge_operation_id",
        "judge_model",
    ]
    snapshot = json.loads(
        (_SCHEMAS / "screamingface.report-trace.v1.json").read_text(encoding="utf-8")
    )

    assert list(TRACE_FIELDS["reduce"]) == expected
    assert snapshot["kinds"]["reduce"] == expected

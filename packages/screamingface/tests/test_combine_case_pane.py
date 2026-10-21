"""The Combine section of the Case pane (E4b part 4 unit 3, PRD case-pane, CP#1-18).

FEATURE: the "Answer & grading" view of a Case pane shows one Combine section per reducer step of
the Case, between the failures and the criteria: the step facts as chips, one table row per member
(status, value, weight, score, rank, every recorded signal, chosen) and the vote tally.
STORY: as a researcher who opens a Case in the HTML report, I see what each member gave, which
members were left out and why, and how the step decided, without writing Python.
INVARIANT defended: every reducer step gets a section, a plain majority vote and a step with no
evidence included (ans:Q2, P19); a Case with no combine step renders as before (P18); every text
from data is escaped (P8); numbers show 4 significant digits with the exact value as the title,
and a missing value is an em dash with its reason (ans:Q3). Every expected string is written by
hand from the PRD scenarios CP-1..CP-D7, never copied from the code's output.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from typing import Any

from _answer_fixtures import evidence_cases, evidence_wires, fixture_case, fixture_graph
from test_criterion_chip_passfail import _check
from test_judge_link_trace import _judge_accounting, _judge_scores
from test_report import candidate as _base_candidate
from test_report_trace import _case, _evidence

import screamingface as sf
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._ui.report_view import _pane_html, bounded_pane
from screamingface.case_result import CaseOperation, Check
from screamingface.combine_evidence import CombineEvidence
from screamingface.operation import OperationInfo

_MEMBER_OPS = ("op_model_1", "op_model_2", "op_model_3")
_JUDGE_MODEL = "provider/judge-x"
_SECTION = "<div class='sf-cmb'>"
_TABLE = "<table class='sf-cmb__t'>"
_CRITERIA_HEAD = "<div class='sf-detail__k'>criteria · the judge's verdict and reasoning</div>"
_ANSWER_HEAD = "<div class='sf-detail__k'>answer</div>"
_ANSWER_VIEW = "<div class='sf-answer-view'>"
_COST_VIEW = "<div class='sf-cost-view'"
_N = "<span class='sf-cmb__n' title='{title}'>{text}</span>"
_NA = "<span class='sf-cmb__na' title='{title}'>—</span>"

# CP-5: the Engine fixture ET/data/combine_contract/evidence_cases.json "rank_cut_not_met" (E4b
# part 2), copied here so this SDK test needs no Engine checkout.
_RANK_CUT_NOT_MET: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "selection",
    "reducer": "rank",
    "operators": ["by_signal@1", "top_k@1"],
    "members": [
        {
            "member_id": "member_1",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"field:score": 0.3},
            "weight": None,
            "score": 0.3,
            "rank": 2,
        },
        {
            "member_id": "member_2",
            "raw": None,
            "value": None,
            "status": "excluded",
            "reason": "no_signal",
            "signals": {"field:score": None},
            "weight": None,
            "score": None,
        },
        {
            "member_id": "member_3",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"field:score": 0.6},
            "weight": None,
            "score": 0.6,
            "rank": 1,
        },
    ],
    "tally": None,
    "judge": None,
    "fields": None,
    "chosen": [],
    "built": False,
    "agreement": None,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": {"key": "field:score", "order": "max"},
    "cut": {"k": 3, "order": "max"},
    "result": {"member_id": None, "value": None, "status": "abstain", "reason": "cut_not_met"},
    "dropped": 0,
    "finish_reason": "stop",
}


# --- builders ------------------------------------------------------------------------------------


def _candidate(
    operations: Sequence[OperationInfo], cases: Sequence[sf.CaseResult]
) -> sf.CandidateResult:
    """A copy of test_report_trace._candidate that takes the graph and the Cases."""

    base = _base_candidate("opus")
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id="run_opus",
        started_at=base.started_at,
        completed_at=base.completed_at,
        name="opus",
        kind=base.kind,
        url4=base.url4,
        models=base.models,
        operations=tuple(operations),
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=tuple(cases),
        members=(),
        failures=(),
        usage=base.usage,
    )


def _pane(operations: Sequence[OperationInfo], case: sf.CaseResult) -> str:
    """The live pane of the one Case. The Candidate binds its graph; the test never binds."""

    owner = _candidate(operations, (case,))
    return _pane_html(owner, owner.cases[0], "")


def _evidence_case(
    evidence: CombineEvidence, *, output: str = "x", checks: Sequence[Check] = ()
) -> sf.CaseResult:
    """op_model_1..n then op_synthesis_1 with the evidence (as fixture_case), with criteria."""

    count = len(evidence.members)
    operations = [
        CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in range(1, count + 1)
    ]
    operations.append(CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence))
    return sf.CaseResult(
        case_id=1,
        input="Question 1",
        output=output,
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=tuple(checks)),
        failures=(),
        metadata={},
        operations=operations,
    )


def _declared_wire() -> dict[str, Any]:
    """CP-4: the vote_field_signal wire, reading the declared name conf (as DS#15)."""

    wire = evidence_wires()["vote_field_signal"]
    for member, value in zip(wire["members"], (90.0, 30.0, 40.0), strict=True):
        member["signals"] = {"conf": value}
    wire["signal"] = {"key": "conf", "order": None}
    wire["declared"] = {"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}
    return wire


def _judge_graph(label: str = "synthesis") -> tuple[OperationInfo, ...]:
    """op_model_1..3, op_judge_1 (judge), op_synthesis_1 (combine, members then the judge)."""

    return (
        *(OperationInfo(id=op, kind="model", label=op) for op in _MEMBER_OPS),
        OperationInfo(id="op_judge_1", kind="judge", label="judge", depends_on=_MEMBER_OPS),
        OperationInfo(
            id="op_synthesis_1",
            kind="combine",
            label=label,
            depends_on=(*_MEMBER_OPS, "op_judge_1"),
        ),
    )


def _judge_case(
    wire: dict[str, Any], model: str | None, *, accounted: bool = True
) -> sf.CaseResult:
    """The Case of test_judge_link_trace._linked_case, not bound (the Candidate binds it)."""

    judge = (
        CaseOperation("op_judge_1", '{"member_1": 9}', "stop", _judge_accounting(model))
        if accounted
        else CaseOperation("op_judge_1", None, None, None)
    )
    return _case(
        [
            *(CaseOperation(op, f"text of {op}", "stop", None) for op in _MEMBER_OPS),
            judge,
            CaseOperation("op_synthesis_1", "12", "stop", None, combine=_evidence(wire)),
        ]
    )


def _wide_vote_wire(count: int = 256) -> dict[str, Any]:
    ids = [f"member_{k}" for k in range(1, count + 1)]
    value = "x" * 50
    wire = evidence_wires()["vote_one_failed"]  # the other keys as a plain vote
    wire["members"] = [
        {
            "member_id": member_id,
            "raw": value,
            "value": value,
            "status": "answered",
            "reason": None,
            "signals": {},
            "weight": None,
            "score": None,
        }
        for member_id in ids
    ]
    wire["tally"] = [{"value": value, "score": float(count), "holders": ids}]
    wire["chosen"] = ["member_1"]
    wire["agreement"] = 1.0
    wire["result"] = {"member_id": "member_1", "value": value, "status": "answered", "reason": None}
    wire["dropped"] = 0
    return wire


def _chips(*texts: str) -> str:
    return (
        "<div class='sf-chips'>"
        + "".join(f"<span class='sf-chip'>{t}</span>" for t in texts)
        + "</div>"
    )


def _head(*cells: str) -> str:
    return "<thead><tr>" + "".join(cells) + "</tr></thead>"


def _th(text: str, title: str | None = None) -> str:
    return (
        f"<th scope='col'>{text}</th>"
        if title is None
        else f"<th scope='col' title='{title}'>{text}</th>"
    )


def _row(*cells: str, out: bool = False) -> str:
    opening = "<tr class='sf-cmb__out'>" if out else "<tr>"
    return opening + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


# --- CP#1, CP#2: CHAR ----------------------------------------------------------------------------


def test_pane_without_combine_evidence_has_no_combine_markup() -> None:
    # CP-D1: a graph with no combine node; a Case with no operations, then one with model calls.
    graph = fixture_graph(3)[:3]
    bare = _case([])
    bare_no_ops = sf.CaseResult(
        case_id=1,
        input="Question",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
    )
    models = _case([CaseOperation(op, f"text of {op}", "stop", None) for op in _MEMBER_OPS])

    for case in (bare_no_ops, bare, models):
        pane = _pane(graph, case)
        assert "sf-cmb" not in pane
        assert "combine ·" not in pane


def test_pane_keeps_answer_before_criteria_in_the_answer_view() -> None:
    check = _check("cites sources", "MET", {"criterion_type": "positive"})
    case = sf.CaseResult(
        case_id=1,
        input="Question",
        output="the answer",
        finish_reason="stop",
        grade=sf.CaseGrade(method="rubric", score=1.0, metrics={}, checks=(check,)),
        failures=(),
        metadata={},
    )

    pane = _pane(fixture_graph(3)[:3], case)

    view, answer = pane.index(_ANSWER_VIEW), pane.index(_ANSWER_HEAD)
    criteria, cost = pane.index(_CRITERIA_HEAD), pane.index(_COST_VIEW)
    assert view < answer < criteria < cost


# --- CP#3..CP#8: the section, the rows and the columns -----------------------------------------


def test_plain_majority_vote_shows_its_combine_section() -> None:
    # CP-1 (ans:Q2): a plain vote with no signal data still gets its whole section.
    pane = _pane(fixture_graph(3), fixture_case("vote_one_failed"))

    expected = (
        "<div class='sf-cmb'>"
        "<div class='sf-detail__k' title='op_synthesis_1'>combine · synthesis</div>"
        + _chips(
            "reducer · vote",
            "rule · last_number@1 → numeric@1 → mode@1 → first_holder@1",
            "answered · member_1",
            "agreement · " + _N.format(title="1.0", text="1"),
            "tie · no",
            "dropped · 1",
        )
        + _TABLE
        + _head(_th("member"), _th("status"), _th("value"), _th("chosen"))
        + "<tbody>"
        + _row("member_1", "answered", "42", "&check;")
        + _row("member_2", "fail · empty", _NA.format(title="member failed: empty"), "", out=True)
        + _row("member_3", "answered", "42", "")
        + "</tbody></table>"
        + _TABLE
        + _head(_th("tally value"), _th("score"), _th("holders"))
        + "<tbody>"
        + _row("42", _N.format(title="2.0", text="2"), "member_1, member_3")
        + "</tbody></table></div>"
    )
    assert pane.count(_SECTION) == 1
    assert expected in pane


def test_failed_member_row_shows_its_status_and_a_dashed_value() -> None:
    # CP-1, MR-1: the failed member's row is greyed out and its value is a dash with the reason.
    pane = _pane(fixture_graph(3), fixture_case("vote_one_failed"))

    assert (
        "<tr class='sf-cmb__out'><td>member_2</td><td>fail · empty</td>"
        "<td><span class='sf-cmb__na' title='member failed: empty'>—</span></td><td></td></tr>"
    ) in pane
    assert pane.count("<tr class='sf-cmb__out'>") == 1


def test_weighted_vote_shows_the_weight_and_signal_columns() -> None:
    # CP-2 (P11): a weight column, and one column for the signal the rule reads.
    pane = _pane(fixture_graph(3), fixture_case("vote_field_signal"))

    assert (
        _head(
            _th("member"),
            _th("status"),
            _th("value"),
            _th("weight"),
            _th("field:confidence", "read by the rule"),
            _th("chosen"),
        )
        in pane
    )
    weight = _N.format(title="0.9", text="0.9")
    assert _row("member_1", "answered", "a", weight, weight, "&check;") in pane
    assert "<span class='sf-chip'>reads · field:confidence</span>" in pane
    agreement = _N.format(title="0.5625", text="0.5625")
    assert f"<span class='sf-chip'>agreement · {agreement}</span>" in pane
    assert _row("a", _N.format(title="0.9", text="0.9"), "member_1") in pane
    assert _row("b", _N.format(title="0.7", text="0.7"), "member_2, member_3") in pane


def test_rank_step_shows_score_rank_cut_and_the_excluded_member() -> None:
    # CP-5: the cut is not met; member_2 is left out (MR-2); no member is chosen.
    pane = _pane(fixture_graph(3), _evidence_case(_evidence(copy.deepcopy(_RANK_CUT_NOT_MET))))

    out = _NA.format(title="left out by the rule: no_signal")
    no_value = _NA.format(title="no value recorded")
    assert (
        _chips(
            "reducer · rank",
            "rule · by_signal@1 → top_k@1",
            "abstain · cut_not_met",
            "cut · top 3 · max",
            "reads · field:score · max",
            "tie · no",
            "dropped · 0",
        )
        in pane
    )
    assert (
        _head(
            _th("member"),
            _th("status"),
            _th("value"),
            _th("score"),
            _th("rank"),
            _th("field:score", "read by the rule"),
            _th("chosen"),
        )
        in pane
    )
    low, high = _N.format(title="0.3", text="0.3"), _N.format(title="0.6", text="0.6")
    assert _row("member_1", "answered", no_value, low, "2", low, "") in pane
    assert _row("member_2", "excluded · no_signal", out, out, out, out, "", out=True) in pane
    assert _row("member_3", "answered", no_value, high, "1", high, "") in pane
    assert "&check;" not in pane
    assert pane.count(_TABLE) == 1  # no tally


def test_declared_signal_header_names_its_source() -> None:
    # CP-4 (epic A3): the header of a declared signal names its source.
    pane = _pane(fixture_graph(3), _evidence_case(_evidence(_declared_wire())))

    assert _th("conf", "source: verbalized; read by the rule") in pane
    weight = _N.format(title="0.9", text="0.9")
    conf = _N.format(title="90.0", text="90")
    assert _row("member_1", "answered", "a", weight, conf, "&check;") in pane


def test_declared_signal_that_no_rule_reads_keeps_its_column() -> None:
    # CP-D4 (P11): no weight, score or rank column without a value; a declared, unread name with
    # only a None value still gets its column.
    plain = _pane(fixture_graph(3), fixture_case("vote_one_failed"))
    # WHY the whole member header: the tally table has its own "score" header cell.
    assert _head(_th("member"), _th("status"), _th("value"), _th("chosen")) in plain
    assert _th("weight") not in plain
    assert _th("rank") not in plain
    assert plain.count(_th("score")) == 1  # the tally table only

    wire = _declared_wire()
    wire["members"][2]["signals"]["ent"] = None
    wire["declared"]["ent"] = {"source": "entropy", "top_logprobs": 5}
    pane = _pane(fixture_graph(3), _evidence_case(_evidence(wire)))

    assert _th("ent", "source: entropy") in pane
    weight = _N.format(title="0.4", text="0.4")
    conf = _N.format(title="40.0", text="40")
    no_ent = _NA.format(title="no ent recorded")
    assert _row("member_3", "answered", "b", weight, conf, no_ent, "") in pane


# --- CP#9..CP#12: the judge chip and escaping --------------------------------------------------


def test_judge_step_names_the_judge_model() -> None:
    # CP-3 (P12): the chip reads the trace reduce entry of the step.
    pane = _pane(_judge_graph(), _judge_case(_judge_scores(), _JUDGE_MODEL))
    assert "<span class='sf-chip'>judge · provider/judge-x</span>" in pane


def test_judge_step_without_accounting_shows_a_dash() -> None:
    # CP-E1: the judge call has no accounting, so the model is unknown; never a guess.
    pane = _pane(_judge_graph(), _judge_case(_judge_scores(), None, accounted=False))

    assert (
        "<span class='sf-chip'>judge · "
        "<span class='sf-cmb__na' title='no model recorded for the judge call'>—</span></span>"
    ) in pane


def test_step_without_a_judge_has_no_judge_chip() -> None:
    # CP-E2: vote_one_failed reads no judge.
    pane = _pane(fixture_graph(3), fixture_case("vote_one_failed"))

    assert "combine · synthesis" in pane
    assert "judge ·" not in pane


def test_member_text_label_and_judge_model_are_escaped() -> None:
    # CP-E3 (P8), part 1: a member value, an operation label and a judge model.
    wire = _judge_scores()
    wire["members"][0]["raw"] = "<img src=x onerror=evil()>"
    wire["members"][0]["value"] = "<img src=x onerror=evil()>"
    pane = _pane(_judge_graph("a<b>"), _judge_case(wire, "provider/<model>"))

    assert "&lt;img src=x onerror=evil()&gt;" in pane
    assert "combine · a&lt;b&gt;" in pane
    assert "judge · provider/&lt;model&gt;" in pane
    for raw in ("<img", "a<b>", "provider/<model>"):
        assert raw not in pane

    # Part 2: a signal key and a declared source. The SDK decoder accepts any text as a signal key
    # and as a source, but a declared NAME must be a signal name, so the source is on "conf".
    wire = evidence_wires()["vote_field_signal"]
    for member in wire["members"]:
        member["signals"]["<b>k</b>"] = 1.0
        member["signals"]["conf"] = 0.5
    wire["declared"] = {"conf": {"source": "<x>"}}
    pane = _pane(fixture_graph(3), _evidence_case(_evidence(wire)))

    assert _th("&lt;b&gt;k&lt;/b&gt;") in pane
    assert _th("conf", "source: &lt;x&gt;") in pane
    assert "<b>k" not in pane
    assert "source: <x>" not in pane


# --- CP#13..CP#18 --------------------------------------------------------------------------------


def test_two_combine_steps_show_two_sections_in_operation_order() -> None:
    # CP-D2 (ans:Q2): an inner vote and an outer median over the same four members.
    outer = OperationInfo(
        id="op_synthesis_2",
        kind="combine",
        label="outer",
        depends_on=("op_model_1", "op_model_2", "op_model_3", "op_model_4"),
    )
    cases = evidence_cases()
    case = _case(
        [
            *(CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in range(1, 5)),
            CaseOperation("op_synthesis_1", "42", "stop", None, combine=cases["vote_one_failed"]),
            CaseOperation("op_synthesis_2", "20", "stop", None, combine=cases["median_nearest"]),
        ]
    )

    pane = _pane(fixture_graph(4, extra=(outer,)), case)

    assert pane.count(_SECTION) == 2
    inner_at = pane.index("title='op_synthesis_1'>combine · synthesis</div>")
    outer_at = pane.index("title='op_synthesis_2'>combine · outer</div>")
    assert inner_at < outer_at


def test_section_sits_between_the_answer_and_the_criteria() -> None:
    # CP-D3 (P10): answer view, answer, the section, the criteria, then the cost view.
    check = _check("cites sources", "MET", {"criterion_type": "positive"})
    case = _evidence_case(evidence_cases()["vote_one_failed"], output="the answer", checks=(check,))

    pane = _pane(fixture_graph(3), case)

    assert "combine · synthesis" in pane
    view, answer = pane.index(_ANSWER_VIEW), pane.index(_ANSWER_HEAD)
    section, criteria = pane.index(_SECTION), pane.index(_CRITERIA_HEAD)
    assert view < answer < section < criteria < pane.index(_COST_VIEW)


def test_median_text_and_built_result_are_shown_as_stored() -> None:
    # CP-D5 (P16): the median is the stored text; a built answer names no member.
    built = _pane(fixture_graph(4), fixture_case("median_value"))
    assert "<span class='sf-chip'>answered · built</span>" in built
    assert "<span class='sf-chip'>median · 20</span>" in built
    assert "mean ·" not in built

    nearest = _pane(fixture_graph(4), fixture_case("median_nearest"))
    agreement = _N.format(title="0.3333333333333333", text="0.3333")
    assert f"<span class='sf-chip'>agreement · {agreement}</span>" in nearest


def test_large_section_falls_back_in_the_preview_and_shows_live() -> None:
    # CP-D6: 256 members of 50 characters; case.to_dict() passes 32,000 characters (about 51,000).
    evidence = decode_combine_evidence(_wide_vote_wire(), "ev")
    assert evidence is not None
    case = _case([CaseOperation("op_synthesis_1", "x" * 50, "stop", None, combine=evidence)])
    owner = _candidate(fixture_graph(256), (case,))
    bound_case = owner.cases[0]
    assert len(json.dumps(bound_case.to_dict(), ensure_ascii=False)) > 32_000

    preview = bounded_pane(owner, bound_case, "")
    live = _pane_html(owner, bound_case, "")

    assert "Preview · export the complete report" in preview
    assert "sf-cmb" not in preview
    assert live.count(_SECTION) == 1
    assert live.count("<tr><td>member_") == 256


def test_pane_adds_no_style_tag() -> None:
    # CP-D7 (P9): the style rules live in _STYLE; the pane itself has no <style> tag.
    pane = _pane(fixture_graph(3), fixture_case("vote_field_signal"))

    assert _SECTION in pane
    assert "<style" not in pane


def test_combine_step_without_evidence_shows_a_short_section() -> None:
    # CP-E4 (ans:Q2, P19): the combine node ran, but the Case holds no evidence for it.
    case = _case(
        [
            *(CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in (1, 2, 3)),
            CaseOperation("op_synthesis_1", "42", "stop", None),
        ]
    )

    pane = _pane(fixture_graph(3), case)

    assert (
        "<div class='sf-cmb'><div class='sf-detail__k' title='op_synthesis_1'>combine · synthesis"
        "</div><div class='sf-chips'><span class='sf-chip'>evidence · <span class='sf-cmb__na' "
        "title='no combine evidence recorded for this step'>—</span></span></div></div>"
    ) in pane
    assert _TABLE not in pane

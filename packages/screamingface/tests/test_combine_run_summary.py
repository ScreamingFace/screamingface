"""The run summary of each reducer step in the Candidate card (E4b part 4, RS#1-11).

STORY: as a researcher who compares recipes, I read in each Candidate card, for each reducer step,
how often each member was chosen and left out, and the mean of each declared signal, over the
whole run (ans:Q1 "Run-level summary"; numbers ans:Q3).
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from typing import Any

from _answer_fixtures import evidence_cases, fixture_case, fixture_graph
from test_report import candidate

import screamingface as sf
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._ui.combine_view import combine_summary_html
from screamingface._ui.report_view import _card_html
from screamingface.case_result import CaseAttempt, CaseOperation
from screamingface.combine_evidence import CombineEvidence
from screamingface.operation import OperationInfo

_DECLARED: dict[str, dict[str, Any]] = {
    "conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}
}
_HEAD = "<th scope='col'>member</th><th scope='col'>chosen</th><th scope='col'>excluded</th>"
_CONF_HEAD = "<th scope='col' title='source: verbalized'>conf mean</th>"
_BLOCK = "<div class='sf-detail__k'>combine</div>"
_HEADING = "<div class='sf-cmb__h' title='op_synthesis_1'>"


def _member(
    k: int,
    status: str,
    value: str | None,
    conf: float | None,
    reason: str | None = None,
    **more: float | None,
) -> dict[str, Any]:
    """One member row of the SDK `vote_field_signal` wire, with a declared `conf` signal."""

    return {
        "member_id": f"member_{k}",
        "raw": value,
        "value": value,
        "status": status,
        "reason": reason,
        "signals": {"conf": conf, **more},
        "weight": conf if status == "answered" else None,
        "score": None,
    }


def _wire(
    members: list[dict[str, Any]],
    chosen: str,
    declared: dict[str, dict[str, Any]] = _DECLARED,
) -> dict[str, Any]:
    """A weighted vote that reads `conf` (the `vote_field_signal` operators, run-summary §7)."""

    values = {row["member_id"]: row["value"] for row in members}
    return {
        "schema": "screamingface.combine-evidence.v1",
        "kind": "answer",
        "reducer": "vote",
        "operators": ["json_field@1", "text@1", "weighted_mode@1", "max_weight_holder@1"],
        "members": members,
        "tally": None,
        "judge": None,
        "fields": None,
        "chosen": [chosen],
        "built": False,
        "agreement": None,
        "tie": False,
        "median": None,
        "presentation_order": None,
        "separator_collision": None,
        "signal": {"key": "conf", "order": None},
        "declared": declared,
        "result": {
            "member_id": chosen,
            "value": values[chosen],
            "status": "answered",
            "reason": None,
        },
        "dropped": sum(row["status"] == "fail" for row in members),
        "finish_reason": "stop",
    }


def _evidence(wire: dict[str, Any]) -> CombineEvidence:
    decoded = decode_combine_evidence(wire, "ev")
    assert decoded is not None  # WHY: pyright narrows it
    return decoded


def _grade() -> sf.CaseGrade:
    return sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=())


def _model_operations(count: int = 3) -> list[CaseOperation]:
    return [CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in range(1, count + 1)]


def _case(
    case_id: int,
    evidence: CombineEvidence | None,
    *,
    operations: Sequence[CaseOperation] | None = None,
) -> sf.CaseResult:
    """A scored Case: the model calls, then op_synthesis_1 with this evidence (or none)."""

    selected = (
        [
            *_model_operations(),
            CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence),
        ]
        if operations is None
        else list(operations)
    )
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output="x",
        finish_reason="stop",
        grade=_grade(),
        failures=(),
        metadata={},
        operations=selected,
    )


def _candidate(
    operations: Sequence[OperationInfo],
    cases: Sequence[sf.CaseResult],
    *,
    members: Sequence[sf.MemberResult] = (),
) -> sf.CandidateResult:
    """`test_report_trace._candidate`, copied to take the graph, the Cases and the members."""

    base = candidate("opus")
    return sf.CandidateResult(
        benchmark=base.benchmark,
        run_id="run_opus",
        started_at=base.started_at,
        completed_at=base.completed_at,
        name="opus",
        kind="fusion" if members else base.kind,
        url4=base.url4,
        models=tuple(member.models[0] for member in members) if members else base.models,
        operations=tuple(operations),
        score=1.0,
        coverage=1.0,
        metrics={},
        cases=tuple(cases),
        members=tuple(members),
        failures=(),
        usage=base.usage,
    )


def _card(result: sf.CandidateResult) -> str:
    report = sf.Report(
        benchmark=result.benchmark, case_count=len(result.cases), candidates=(result,)
    )
    return _card_html(result, report)


def _rs1_cases() -> tuple[sf.CaseResult, ...]:
    """RS-1: three Cases of one weighted vote that declares `conf` (hand-computed in the PRD)."""

    wires = (
        _wire(
            [
                _member(1, "answered", "a", 90.0),
                _member(2, "answered", "b", 60.0),
                _member(3, "excluded", "b", None, "no_weight"),
            ],
            "member_1",
        ),
        _wire(
            [
                _member(1, "answered", "a", 80.0),
                _member(2, "answered", "b", 70.0),
                _member(3, "answered", "b", 50.0),
            ],
            "member_2",
        ),
        _wire(
            [
                _member(1, "answered", "a", 70.0),
                _member(2, "fail", None, None, "empty"),
                _member(3, "answered", "b", 40.0),
            ],
            "member_1",
        ),
    )
    return tuple(_case(index, _evidence(wire)) for index, wire in enumerate(wires, start=1))


# --- RS#1-2 CHAR: the card today ----------------------------------------------------------------


def test_card_without_combine_evidence_has_no_summary() -> None:
    # RS-E2: model calls only, a combine step with no evidence (P19), and a Case with no operations
    model_only = _case(1, None, operations=_model_operations())
    no_evidence = _case(2, None)
    no_operations = sf.CaseResult(
        case_id=3,
        input="Question 3",
        output="x",
        finish_reason="stop",
        grade=_grade(),
        failures=(),
        metadata={},
    )
    result = _candidate(fixture_graph(3), (model_only, no_evidence, no_operations))

    assert combine_summary_html(result) == ""
    html = _card(result)
    assert "sf-cmb" not in html
    assert _BLOCK not in html


def test_card_shows_the_grid_before_the_url4_block() -> None:
    html = _card(_candidate(fixture_graph(3), _rs1_cases()))

    assert html.index("<div class='sf-report__grid'>") < html.index("<summary>URL4</summary>")


# --- RS#3-6: counts and means -------------------------------------------------------------------


def test_summary_counts_chosen_excluded_and_means_the_declared_signal() -> None:
    # RS-1. member_1 (90+80+70)/3 = 80; member_2 (60+70)/2 = 65; member_3 (50+40)/2 = 45.
    summary = combine_summary_html(_candidate(fixture_graph(3), _rs1_cases()))

    assert summary == (
        "<div class='sf-detail__k'>combine</div><div class='sf-cmb'>"
        f"{_HEADING}synthesis · vote · 3 cases</div>"
        "<table class='sf-cmb__t'><thead><tr>"
        f"{_HEAD}{_CONF_HEAD}"
        "</tr></thead><tbody>"
        "<tr><td>member_1</td><td>2 of 3</td><td>0 of 3</td>"
        "<td><span class='sf-cmb__n' title='80.0'>80</span>"
        " <span class='sf-cmb__nn'>n=3</span></td></tr>"
        "<tr><td>member_2</td><td>1 of 3</td><td>0 of 3</td>"
        "<td><span class='sf-cmb__n' title='65.0'>65</span>"
        " <span class='sf-cmb__nn'>n=2</span></td></tr>"
        "<tr><td>member_3</td><td>0 of 3</td><td>1 of 3</td>"
        "<td><span class='sf-cmb__n' title='45.0'>45</span>"
        " <span class='sf-cmb__nn'>n=2</span></td></tr>"
        "</tbody></table></div>"
    )


def test_mean_title_shows_the_exact_value() -> None:
    # RS-2: math.fsum([0.1, 0.2]) / 2 == 0.15000000000000002; 4 significant digits show 0.15.
    assert math.fsum([0.1, 0.2]) / 2 == 0.15000000000000002
    cases = tuple(
        _case(
            index,
            _evidence(
                _wire(
                    [
                        _member(1, "answered", "a", conf),
                        _member(2, "answered", "b", 0.5),
                        _member(3, "answered", "b", 0.5),
                    ],
                    "member_1",
                )
            ),
        )
        for index, conf in enumerate((0.1, 0.2), start=1)
    )
    summary = combine_summary_html(_candidate(fixture_graph(3), cases))

    assert (
        "<tr><td>member_1</td><td>2 of 2</td><td>0 of 2</td>"
        "<td><span class='sf-cmb__n' title='0.15000000000000002'>0.15</span>"
        " <span class='sf-cmb__nn'>n=2</span></td></tr>"
    ) in summary


def test_summary_without_declared_signals_shows_chosen_and_excluded_only() -> None:
    # RS-3 (ans:Q2): a plain vote has a summary too; it has no mean column.
    cases = (
        fixture_case("vote_one_failed", case_id=1),
        fixture_case("vote_abstain", case_id=2),
    )
    summary = combine_summary_html(_candidate(fixture_graph(3), cases))

    assert f"<thead><tr>{_HEAD}</tr></thead>" in summary
    assert f"{_HEADING}synthesis · vote · 2 cases</div>" in summary
    assert (
        "<tbody>"
        "<tr><td>member_1</td><td>1 of 2</td><td>0 of 2</td></tr>"
        "<tr><td>member_2</td><td>0 of 2</td><td>0 of 2</td></tr>"
        "<tr><td>member_3</td><td>0 of 2</td><td>0 of 2</td></tr>"
        "</tbody>"
    ) in summary
    assert " mean</th>" not in summary


def test_signal_with_no_value_in_any_case_shows_a_dash_and_n_zero() -> None:
    # RS-E1: `ent` is declared, and no Case gives it a value.
    declared = {**_DECLARED, "ent": {"source": "entropy", "top_logprobs": 5}}
    cases = tuple(
        _case(
            index,
            _evidence(
                _wire(
                    [_member(k, "answered", "a", 50.0, ent=None) for k in (1, 2, 3)],
                    "member_1",
                    declared,
                )
            ),
        )
        for index in (1, 2)
    )
    summary = combine_summary_html(_candidate(fixture_graph(3), cases))

    assert f"{_CONF_HEAD}<th scope='col' title='source: entropy'>ent mean</th></tr>" in summary
    dash = (
        "<td><span class='sf-cmb__na' title='no Case gave a value'>—</span>"
        " <span class='sf-cmb__nn'>n=0</span></td></tr>"
    )
    assert summary.count(dash) == 3


# --- RS#7-11: escaping, order, scope ------------------------------------------------------------


def test_labels_and_sources_are_escaped() -> None:
    # RS-D1 (P8). WHY the heading string: the folded URL4 steps list already shows the escaped
    # label today, so `a&lt;b&gt;` alone is not new.
    graph = (
        *fixture_graph(3)[:3],
        OperationInfo(
            id="op_synthesis_1",
            kind="combine",
            label="a<b>",
            depends_on=("op_model_1", "op_model_2", "op_model_3"),
        ),
    )
    wire = _wire(
        [
            _member(1, "answered", "a", 90.0),
            _member(2, "answered", "b", 60.0),
            _member(3, "answered", "b", 50.0),
        ],
        "member_1",
        {"conf": {"source": "<x>"}},
    )
    html = _card(_candidate(graph, (_case(1, _evidence(wire)),)))

    assert f"{_HEADING}a&lt;b&gt; · vote · 1 case</div>" in html
    assert "<th scope='col' title='source: &lt;x&gt;'>conf mean</th>" in html
    assert "a<b>" not in html
    assert "<x>" not in html


def test_two_steps_give_two_blocks_in_first_seen_order() -> None:
    # RS-D2: the graph and the Case of case-pane CP-D2.
    graph = fixture_graph(
        4,
        extra=(
            OperationInfo(
                id="op_synthesis_2",
                kind="combine",
                label="outer",
                depends_on=("op_model_1", "op_model_2", "op_model_3", "op_model_4"),
            ),
        ),
    )
    evidence = evidence_cases()
    operations = [
        *_model_operations(4),
        CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence["vote_one_failed"]),
        CaseOperation("op_synthesis_2", "20", "stop", None, combine=evidence["median_nearest"]),
    ]
    summary = combine_summary_html(_candidate(graph, (_case(1, None, operations=operations),)))

    assert summary.count(_BLOCK) == 1
    assert summary.count("<div class='sf-cmb__h'") == 2
    first = summary.index(">synthesis · vote · 1 case</div>")
    second = summary.index(">outer · median · 1 case</div>")
    assert first < second
    assert summary[second:].count("<tr><td>member_") == 4  # median_nearest has 4 members
    assert "<tr><td>member_2</td><td>1 of 1</td><td>0 of 1</td></tr>" in summary[second:]


def test_cases_without_case_operations_are_ignored() -> None:
    # RS-D3 (P15): a model-only Case, an Attempts Case (operations only on its Attempts), a Case
    # with no operations, and one combine Case.
    evidence = evidence_cases()["vote_one_failed"]
    attempt_operations = (
        *_model_operations(),
        CaseOperation("op_synthesis_1", "42", "stop", None, combine=evidence),
    )
    with_attempts = sf.CaseResult(
        case_id=2,
        input="Question 2",
        output="42",
        finish_reason="stop",
        grade=_grade(),
        failures=(),
        metadata={},
        attempts=tuple(
            CaseAttempt(
                attempt=number,
                status="scored",
                output="42",
                finish_reason="stop",
                refusal=None,
                grade=_grade(),
                failures=(),
                operations=attempt_operations,
            )
            for number in (1, 2)
        ),
    )
    no_operations = sf.CaseResult(
        case_id=4,
        input="Question 4",
        output="x",
        finish_reason="stop",
        grade=_grade(),
        failures=(),
        metadata={},
    )
    cases = (
        _case(1, None, operations=_model_operations()),
        with_attempts,
        fixture_case("vote_one_failed", case_id=3),
        no_operations,
    )
    summary = combine_summary_html(_candidate(fixture_graph(3), cases))

    assert f"{_HEADING}synthesis · vote · 1 case</div>" in summary
    assert "<tr><td>member_1</td><td>1 of 1</td><td>0 of 1</td></tr>" in summary


def test_summary_sits_after_the_grid_and_before_the_url4_block() -> None:
    # RS-D4 (P13), with a members block and an accounting note in the same card.
    members = tuple(
        sf.MemberResult(
            operation_id=f"op_model_{k}",
            name=f"model {k}",
            kind="model",
            models=(f"provider/m{k}",),
            failures=None,
            duration_ms=None,
            usage=None,
        )
        for k in (1, 2, 3)
    )
    result = _candidate(fixture_graph(3), _rs1_cases(), members=members)
    summary = combine_summary_html(result)
    html = _card(result)

    assert summary.startswith(_BLOCK)
    assert html.count(summary) == 1
    assert (
        html.index("<div class='sf-report__grid'>")
        < html.index("<div class='sf-detail__k'>members</div>")
        < html.index(_BLOCK)
        < html.index('<p class="sf-run-accounting-note">')
        < html.index("<summary>URL4</summary>")
    )


def test_one_case_heading_is_singular() -> None:
    # RS-D5
    summary = combine_summary_html(
        _candidate(fixture_graph(3), (fixture_case("vote_one_failed", case_id=1),))
    )

    assert f"{_HEADING}synthesis · vote · 1 case</div>" in summary
    assert "1 cases" not in summary


# --- Review P4 #1: a sum past the float range ----------------------------------------------------


def test_mean_of_values_whose_sum_leaves_the_float_range_still_renders() -> None:
    # Review P4 #1: two Cases read conf = 1e308 (a verbalized 309-digit number); their sum is past
    # the float range, but their mean (1e308) is not, so the card shows it instead of failing.
    def wire(conf: float) -> dict[str, Any]:
        members = [_member(1, "answered", "a", conf), _member(2, "answered", "a", 1.0)]
        return _wire([*members, _member(3, "answered", "a", 1.0)], "member_1")

    cases = tuple(_case(k, _evidence(wire(1e308))) for k in (1, 2))
    result = _candidate(fixture_graph(3), cases)
    summary = combine_summary_html(result)

    cell = (
        "<td><span class='sf-cmb__n' title='1e+308'>1e+308</span>"
        " <span class='sf-cmb__nn'>n=2</span></td>"
    )
    assert f"<tr><td>member_1</td><td>2 of 2</td><td>0 of 2</td>{cell}</tr>" in summary
    assert summary in _card(result)


# --- Review P4 #2: one pass over the Cases per card ---------------------------------------------


def test_card_render_reads_the_cases_in_one_pass() -> None:
    # Review P4 #2: a saved Candidate decodes a Case on each read (DiskCases), so the abstained
    # count and the run summary share one pass over the Cases. The card bytes do not change.
    from screamingface._results.accounting import saved_accounting_context

    result = _candidate(fixture_graph(3), _rs1_cases())
    report = sf.Report(
        benchmark=result.benchmark, case_count=len(result.cases), candidates=(result,)
    )
    context = saved_accounting_context(result)  # WHY first: the accounting context is not counted
    expected = _card_html(result, report, context=context)
    passes = 0

    class _CountedCases(tuple[sf.CaseResult, ...]):
        def __iter__(self) -> Iterator[sf.CaseResult]:
            nonlocal passes
            passes += 1
            return super().__iter__()

    cases = result.cases
    object.__setattr__(cases, "_items", _CountedCases(cases._items))

    assert _card_html(result, report, context=context) == expected
    assert passes == 1

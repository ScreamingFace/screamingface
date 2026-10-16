"""The gate in the report (E4b part 5 unit 5, PRD gate-display, GS#1-12).

FEATURE: a gated vote shows its gate in the Case pane Combine section (one chip right after the
agreement chip), in the run summary of the Candidate card (one gate line per gated step), and in
the JSON export (``operations[].combine.gate``, with no export change).
STORY: as a researcher who opens a Case in the HTML report, I see the number the gate compared,
the comparison, the threshold and the branch it took; in the Candidate card I see how often the
gate kept the majority (ans:Q1 "records the comparison and the branch").
INVARIANT defended: an ungated step renders the same bytes as on the part base 4e622af75 (GS-D3);
every text from the record is escaped (part 4 P8); the judge chip and the trace name the fallback
judge only when the step read it (rule J4); the report-trace.v1 field set does not change (P16).
The wires are the five Engine gate cases of ET/data/combine_contract/evidence_cases.json
(gate-decision GD-D9), read under requires_engine_app, with a hand-built Case. Every expected
string is written by hand from the PRD scenarios GS-1..GS-D5, never copied from the code's output.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from _answer_fixtures import fixture_graph
from _combine_contract import COMBINE_CONTRACT, requires_engine_app
from test_combine_case_pane import _judge_case, _judge_graph
from test_combine_run_summary import _candidate
from test_judge_link_trace import _MEMBERS, _link, _linked_case
from test_report_trace import _info

import screamingface as sf
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._ui.combine_view import combine_sections_html, combine_summary_html
from screamingface.case_result import CaseOperation
from screamingface.combine_evidence import CombineEvidence
from screamingface.operation import OperationInfo
from screamingface.report_trace import TRACE_FIELDS

pytestmark = requires_engine_app

_CASES = COMBINE_CONTRACT / "evidence_cases.json"
_JUDGE_MODEL = "provider/judge-x"
_N = "<span class='sf-cmb__n' title='{title}'>{text}</span>"
_NA = "<span class='sf-cmb__na' title='{title}'>—</span>"
_NOT_RUN = "the vote found no answer, so the gate did not run"
_NO_NUMBER = "no number to compare, so the gate took the fallback"
_AGREEMENT = _N.format(title="0.6666666666666666", text="0.6667")
_AT_06 = _N.format(title="0.6", text="0.6")
_AT_07 = _N.format(title="0.7", text="0.7")
_TABLE = "<table class='sf-cmb__t'>"
# One gate chip: its text, and at most the inner number spans (no other markup inside a chip).
_GATE_CHIP = re.compile(r"<span class='sf-chip'>gate · (?:[^<]|<span [^>]*>[^<]*</span>)*</span>")

# GS-D3 (test-plan §6 L32): the 32 evidence cases of the part base, and for each the sha256 of
# its Combine section + "\n" + its run summary, rendered by the SDK of the part base 4e622af75.
_L32_DIGESTS: dict[str, str] = {
    "argmax_cost_min": "e60ee44ccb0783921f9f3e4aeccc0f57c57c61617a94f309966befab225291f4",
    "concat_collision": "e5891d542765d59bc14acd7553d964dfdb2899f04591445f279bba5cc7db2ee3",
    "filter_none_pass": "7c86803e517a3b022719e9d822714bcb89d3538ff5f8054d564db2cf83672304",
    "filter_pattern": "10a19dcd85d0d56d58ebc311996bc3acc25666d48ed5bc2280f59338295ebf9a",
    "filter_signal_excluded": "fea8005838742aedae34020f8c4785dca0f9ccf725cfcc5a13c1effb0d85602a",
    "filter_threshold": "fa53b3b8b360e9778b2df78d89191e44e145ef18308b8d1841e936d517c394ae",
    "judge_label": "2f07ed33f218646c0f7d4d1476e67d3ab4ccbf11808255db7fe162b5efeb6ff3",
    "judge_scores": "f1a424db4f9d1a6431a44d7381b316a65da8d19975a5919f01ed99480db5882b",
    "mean_weighted_value": "bb32f961941aa3bb9108f89c68ef340ac6cf75abca98795c8e3630c9cdb9cea7",
    "median_nearest": "4d90b81b071ddc1cc5720689207d2651b3e80b49b2c9ba40ab60a2445f98259b",
    "median_value": "4f4953db99ad0c88d13e1af275cdc5a4f6095dc9ac0dca1b208e43dbbc3eca4f",
    "merge_abstain": "741b97f1aabe7a288d2f71ae7306b008ff26643470f48eb0da4d994b2f52543c",
    "merge_model_field": "ece8e73686f702e8fcaee9d4aebeec7b0f62835eb91f32ec56020b9b3ec3e646",
    "pick": "f26fa7201e7a8194fbb8ea42987e170a34ecacc09f51967fd9e7884f60490df2",
    "pick_output": "dca2012eedb0e3742b9243f3e7f2ae206e1f7301e381754bb65eb8f7ce673acc",
    "pick_output_missing": "f2641c7561153e210468c70f78640a9e59ff619e244443ce02dc41c639aec182",
    "projection": "c0cdf277c1fe3fdc49c68540e7547c6b957e5c662291363add2d40f78d2c04b3",
    "rank_by_judge": "21afbf2044d5dfd09569178fd2a66d6d27183c43951792d224b7b507e6da14c7",
    "rank_by_signal": "bf87b029d4c40461d20a7d6abc8148f3e51626221a7c0034b23fb31c5d8750ef",
    "rank_cut_not_met": "c588d145c0ee24927ee7f856e731bfd83a226fd7a7fb0d39a544ba3cbbf77ac4",
    "rank_min_cost": "1e096283a5fdfdec21a0bd186c0dc56fed5cda2f3c12cc327a7e689fe0658203",
    "rank_reduce_abstain": "8bff23082601dfd4ddb80b0da53e27e7d85b0b7df1ab05e13bcab48858280e0f",
    "regex_no_match": "dd156ff91fef1bc28fd339eb22fffd8749c880f0c8bb35e23ceb7720164aea40",
    "set_normalized": "f096da5b9f2748f4902bed3c82bd96c69abf2f1d3a5b146ba4b5811b802ddde7",
    "vote_abstain": "ec938cfd0d429ba62b89abd8595d90c84f16c50c0bf44b166ad1dd614adb4f68",
    "vote_cost_signal": "3e51ebf0c9a851f185bf6b87478b55b3f72b737122ea7d3888c59eb92d2071a8",
    "vote_field_signal": "0015099371af921238ecd9dc02265b8563b2f86f17305c5732778a78d5d87e8c",
    "vote_judge_weights": "02172ce7161c7820c84979fa389adc3aef85af9cf46cd37056bf34338fc5b868",
    "vote_one_failed": "fab6c6c9df23dbd328b4b3ef499e5a5c25654a63104a129f94d39df72a51ed9f",
    "vote_tie": "fd6fe5f2f366879551b277d8554287e775ad6579d15a3fd08c9c46d661ad8cc3",
    "vote_weight_excluded": "6b0aa03f2a93cb59f5981e786211cdac77dee09972365a0506af03e2e6ebe91b",
    "vote_weighted": "f4f1c7083666f3a7c4244dc9c960572ec1241bd8bda1e028f12650affb636831",
}


# --- builders ------------------------------------------------------------------------------------


def _wires() -> dict[str, Any]:
    """Every Engine contract case (read once per call; the tests never loop over all of them)."""

    value: dict[str, Any] = json.loads(_CASES.read_text(encoding="utf-8"))
    return value


def _wire(name: str) -> dict[str, Any]:
    return _wires()[name]


def _evidence(wire: dict[str, Any]) -> CombineEvidence:
    value = decode_combine_evidence(wire, "Engine gate evidence")
    assert value is not None  # WHY: pyright narrows it
    return value


def _case_of(operations: list[CaseOperation], case_id: int = 1) -> sf.CaseResult:
    """A scored Case with these operations, not bound (the Candidate binds its graph)."""

    return sf.CaseResult(
        case_id=case_id,
        input="Question",
        output="x",
        finish_reason="stop",
        grade=sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=()),
        failures=(),
        metadata={},
        operations=operations,
    )


def _case(wire: dict[str, Any], case_id: int = 1) -> sf.CaseResult:
    """op_model_1..n, then op_synthesis_1 with the evidence (as _fixture_case)."""

    count = len(wire["members"])
    operations = [
        CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in range(1, count + 1)
    ]
    operations.append(CaseOperation("op_synthesis_1", "42", "stop", None, combine=_evidence(wire)))
    return _case_of(operations, case_id)


def _section(wire: dict[str, Any]) -> str:
    """The Combine section of the one Case of this wire, on the plain graph (fixture_graph)."""

    owner = _candidate(fixture_graph(len(wire["members"])), (_case(wire),))
    return combine_sections_html(owner, owner.cases[0])


def _judge_section(wire: dict[str, Any]) -> str:
    """The Combine section on the graph with one judge operation op_judge_1 (provider/judge-x)."""

    owner = _candidate(_judge_graph(), (_judge_case(wire, _JUDGE_MODEL),))
    return combine_sections_html(owner, owner.cases[0])


def _mean_conf_wire(cmp: str) -> dict[str, Any]:
    """GS-D2: vote_gate_abstain reading mean:conf, a declared name that no member gave."""

    wire = _wire("vote_gate_abstain")
    wire["declared"] = {"conf": {"source": "verbalized", "pattern": "Confidence: ([0-9]+)"}}
    for member in wire["members"]:
        member["signals"] = {"conf": None}
    wire["gate"]["observe"] = "mean:conf"
    wire["gate"]["observed"] = None
    wire["gate"]["cmp"] = cmp
    return wire


def _chip(text: str) -> str:
    return f"<span class='sf-chip'>{text}</span>"


def _fallback(otherwise: str) -> str:
    """The gate chip of the 0.7 cases (abstain, judge, writer): the gate took the fallback."""

    return _chip(
        f"gate · agreement &gt;= {_AT_07} · observed {_AGREEMENT} · fallback · {otherwise}"
    )


# --- GS#1: CHAR ----------------------------------------------------------------------------------


def test_ungated_section_and_summary_are_unchanged() -> None:
    # GS-D3: the fixed list L32, never a loop over the whole file.
    wires = _wires()

    assert len(_L32_DIGESTS) == 32
    for name, digest in _L32_DIGESTS.items():
        wire = wires[name]
        owner = _candidate(fixture_graph(len(wire["members"])), (_case(wire),))
        text = combine_sections_html(owner, owner.cases[0]) + "\n" + combine_summary_html(owner)
        assert "gate ·" not in text, name
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == digest, name


# --- GS#2..GS#8: the Case pane chip --------------------------------------------------------------


def test_case_pane_shows_the_gate_chip_after_agreement() -> None:
    # GS-1 (ans:Q1): one chip, right after the agreement chip and before the tie chip.
    section = _section(_wire("vote_gate_majority"))
    gate = _chip(f"gate · agreement &gt;= {_AT_06} · observed {_AGREEMENT} · majority")

    assert _GATE_CHIP.findall(section) == [gate]
    assert _chip("agreement · " + _AGREEMENT) + gate + _chip("tie · no") in section


def test_case_pane_shows_the_abstain_fallback() -> None:
    # GS-2 (ans:Q3): the abstain fallback and its own reason.
    section = _section(_wire("vote_gate_abstain"))

    assert _GATE_CHIP.findall(section) == [_fallback("abstain")]
    assert _chip("abstain · gate_not_met") in section


def test_case_pane_shows_the_fallback_judge_and_its_model() -> None:
    # GS-3 (rule J4): the fallback judge was read, so the judge chip names its model.
    section = _judge_section(_wire("vote_gate_judge"))

    assert _GATE_CHIP.findall(section) == [_fallback("judge")]
    assert _chip("answered · member_3") in section
    assert _chip("judge · provider/judge-x") in section


def test_case_pane_shows_the_writer_fallback_as_built() -> None:
    # GS-4 (ans:Q3): the writing model gives a built answer.
    section = _section(_wire("vote_gate_writer"))

    assert _GATE_CHIP.findall(section) == [_fallback("writer")]
    assert _chip("answered · built") in section


def test_case_pane_shows_a_gate_that_did_not_run() -> None:
    # GS-D1 (P10): the vote found no answer, so the gate did not run.
    section = _section(_wire("vote_gate_not_run"))
    observed = _NA.format(title=_NOT_RUN)

    assert _GATE_CHIP.findall(section) == [
        _chip(f"gate · agreement &gt;= {_AT_06} · observed {observed} · not run")
    ]


def test_missing_observed_number_is_a_dash_with_its_reason() -> None:
    # GS-D2 (P10): no member gave conf, so the gate took the fallback.
    section = _section(_mean_conf_wire(">="))
    observed = _NA.format(title=_NO_NUMBER)

    assert _GATE_CHIP.findall(section) == [
        _chip(f"gate · mean:conf &gt;= {_AT_07} · observed {observed} · fallback · abstain")
    ]


def test_gate_chip_escapes_the_comparison() -> None:
    # GS-E1 (part 4 P8): >= and < from the record reach the page escaped.
    majority = _GATE_CHIP.findall(_section(_wire("vote_gate_majority")))
    below = _GATE_CHIP.findall(_section(_mean_conf_wire("<")))

    assert len(majority) == 1
    assert len(below) == 1
    assert "gate · agreement &gt;= <span" in majority[0]
    assert "gate · mean:conf &lt; <span" in below[0]
    for chip in (*majority, *below):
        text = re.sub(r"<[^<>]*>", "", chip)
        assert "<" not in text
        assert ">" not in text


# --- GS#9, GS#10: the run summary ----------------------------------------------------------------


def test_run_summary_counts_majority_fallback_and_not_run() -> None:
    # GS-5: three Cases of one gated step, one per branch.
    names = ("vote_gate_majority", "vote_gate_abstain", "vote_gate_not_run")
    cases = tuple(_case(_wire(name), case_id) for case_id, name in enumerate(names, start=1))
    summary = combine_summary_html(_candidate(fixture_graph(3), cases))
    line = _chip("gate · majority 1 of 3 · fallback 1 of 3 · not run 1 of 3")
    heading = "<div class='sf-cmb__h' title='op_synthesis_1'>synthesis · vote · 3 cases</div>"

    assert heading + "<div class='sf-chips'>" + line + "</div>" + _TABLE in summary
    assert _GATE_CHIP.findall(summary) == [line]


def test_run_summary_has_no_gate_line_for_an_ungated_step() -> None:
    # GS-D3: a gated step and an ungated step in one Case; only the gated one has a line.
    gated, ungated = _evidence(_wire("vote_gate_majority")), _evidence(_wire("vote_one_failed"))
    operations = [
        *(CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in (1, 2, 3)),
        CaseOperation("op_synthesis_1", "9", "stop", None, combine=gated),
        CaseOperation("op_synthesis_2", "42", "stop", None, combine=ungated),
    ]
    second = OperationInfo(
        id="op_synthesis_2",
        kind="combine",
        label="second",
        depends_on=("op_model_1", "op_model_2", "op_model_3"),
    )
    graph = fixture_graph(3, extra=(second,))
    summary = combine_summary_html(_candidate(graph, (_case_of(operations),)))
    line = _chip("gate · majority 1 of 1 · fallback 0 of 1")
    first_heading = "<div class='sf-cmb__h' title='op_synthesis_1'>synthesis · vote · 1 case</div>"
    second_heading = "<div class='sf-cmb__h' title='op_synthesis_2'>second · vote · 1 case</div>"

    assert first_heading + "<div class='sf-chips'>" + line + "</div>" + _TABLE in summary
    assert second_heading + _TABLE in summary
    assert _GATE_CHIP.findall(summary) == [line]


# --- GS#11, GS#12: the export and the trace link -------------------------------------------------


def test_export_holds_the_gate_record_and_the_trace_fields_stay(tmp_path: Path) -> None:
    # GS-D4 (S/case_result.py combine export; P16): the record is exported, the trace keeps v1.
    result = _candidate(_judge_graph(), (_judge_case(_wire("vote_gate_judge"), _JUDGE_MODEL),))
    report = sf.Report(benchmark=result.benchmark, case_count=1, candidates=(result,))
    path = report.export(tmp_path / "report.json")
    exported: list[Any] = [report.to_dict(), json.loads(path.read_text(encoding="utf-8"))]
    expected = {
        "observe": "agreement",
        "observed": 0.6666666666666666,
        "cmp": ">=",
        "threshold": 0.7,
        "passed": False,
        "branch": "fallback",
        "otherwise": "judge",
    }

    assert len(TRACE_FIELDS["reduce"]) == 11
    for value in exported:
        (case,) = value["candidates"][0]["cases"]
        (combine,) = [op["combine"] for op in case["operations"] if "combine" in op]
        assert combine["gate"] == expected
        assert list(combine["gate"]) == list(expected)
        reduces = [entry for entry in case["trace"] if entry["kind"] == "reduce"]
        assert len(reduces) == 1
        assert list(reduces[0]) == ["kind", *TRACE_FIELDS["reduce"]]


def test_trace_links_the_fallback_judge_only_when_it_was_read() -> None:
    # GS-D5 (rule J4, N4): linked on the fallback branch; not on the majority branch; never
    # with two judge operations.
    two_judges = (_info("op_judge_1", "judge", *_MEMBERS), _info("op_judge_2", "judge", *_MEMBERS))
    unlinked = {"judge_operation_id": None, "judge_model": None}

    assert _link(_linked_case(_wire("vote_gate_judge"))) == {
        "judge_operation_id": "op_judge_1",
        "judge_model": "provider/judge-x",
    }
    assert _link(_linked_case(_wire("vote_gate_majority"))) == unlinked
    assert _link(_linked_case(_wire("vote_gate_judge"), two_judges)) == unlinked

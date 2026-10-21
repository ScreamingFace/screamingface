"""Consistency in the report (E4b part 7 unit 6, PRD consistency-display, CD#1-7).

FEATURE: a step that declares sf.Consistency shows its samples on the part 4 surfaces: one step
chip after the mean chip, each member's failed samples beside its value, the reason of a missing
value, and one run summary line per step. The JSON export holds
``operations[].combine.consistency`` with no export change.
STORY: as a researcher who reads a run report, I see when a consistency value rests on fewer
samples than I asked for (ans:Q4 "the count of failed samples is recorded").
INVARIANT defended: a step without consistency shows no sample fact (CD-D1); the chip, the note
and the line hold only numbers and the checked name; the report-trace.v1 field sets do not change
(CD-D5). The wires are the three Engine cases of
ET/data/combine_contract/consistency_evidence_cases.json (unit 2), read under requires_engine_app,
with a hand-built Case. Every expected string is written by hand from the PRD scenarios
CD-1..CD-D5 and the fixture V and W tables, never copied from the code's output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from _answer_fixtures import fixture_graph
from _combine_contract import COMBINE_CONTRACT, engine_operators, requires_engine_app
from test_combine_run_summary import _candidate

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._ui.combine_view import combine_sections_html, combine_summary_html
from screamingface.case_result import CaseOperation
from screamingface.combine_evidence import CombineEvidence
from screamingface.report_trace import TRACE_FIELDS, TRACE_SCHEMA

pytestmark = requires_engine_app

_CASES = COMBINE_CONTRACT / "consistency_evidence_cases.json"
_L37_CASES = COMBINE_CONTRACT / "evidence_cases.json"
_NAMES = ("consistency_vote", "consistency_pick_default_match", "consistency_no_votes")
# CD-D1 (test-plan §6 L37): the 37 evidence case names of the part base, written by hand.
_L37 = (
    "argmax_cost_min",
    "concat_collision",
    "filter_none_pass",
    "filter_pattern",
    "filter_signal_excluded",
    "filter_threshold",
    "judge_label",
    "judge_scores",
    "mean_weighted_value",
    "median_nearest",
    "median_value",
    "merge_abstain",
    "merge_model_field",
    "pick",
    "pick_output",
    "pick_output_missing",
    "projection",
    "rank_by_judge",
    "rank_by_signal",
    "rank_cut_not_met",
    "rank_min_cost",
    "rank_reduce_abstain",
    "regex_no_match",
    "set_normalized",
    "vote_abstain",
    "vote_cost_signal",
    "vote_field_signal",
    "vote_gate_abstain",
    "vote_gate_judge",
    "vote_gate_majority",
    "vote_gate_not_run",
    "vote_gate_writer",
    "vote_judge_weights",
    "vote_one_failed",
    "vote_tie",
    "vote_weight_excluded",
    "vote_weighted",
)
_N = "<span class='sf-cmb__n' title='{title}'>{text}</span>"
_NA = "<span class='sf-cmb__na' title='{title}'>—</span>"
_FAILED = " <span class='sf-cmb__nn'>{count} failed</span>"
_MEAN_N = " <span class='sf-cmb__nn'>n={count}</span>"
_TABLE = "<table class='sf-cmb__t'>"
_HALF = _N.format(title="0.5", text="0.5")
_ONE = _N.format(title="1.0", text="1")
# One samples chip (Case pane) or line (run summary): its text only, no markup inside.
_SAMPLES_CHIP = re.compile(r"<span class='sf-chip'>samples · [^<]*</span>")


# --- builders ------------------------------------------------------------------------------------


def _read(path: Path) -> dict[str, Any]:
    """One Engine contract file, read fresh so a test may change its copy; a missing file FAILS."""

    assert path.is_file(), f"missing Engine contract fixture {path}"
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return value


def _wire(name: str) -> dict[str, Any]:
    wire: dict[str, Any] = _read(_CASES)[name]
    return wire


def _evidence(wire: dict[str, Any]) -> CombineEvidence:
    value = decode_combine_evidence(wire, "Engine consistency evidence")
    assert value is not None  # WHY: pyright narrows it
    return value


def _models(count: int) -> list[CaseOperation]:
    return [CaseOperation(f"op_model_{k}", f"text {k}", "stop", None) for k in range(1, count + 1)]


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
    """op_model_1..n, then op_synthesis_1 with the evidence (the test_member_exclusion pattern)."""

    operations = _models(len(wire["members"]))
    operations.append(CaseOperation("op_synthesis_1", "42", "stop", None, combine=_evidence(wire)))
    return _case_of(operations, case_id)


def _section(wire: dict[str, Any]) -> str:
    """The Combine section of the one Case of this wire, on the plain graph (fixture_graph)."""

    owner = _candidate(fixture_graph(len(wire["members"])), (_case(wire),))
    return combine_sections_html(owner, owner.cases[0])


def _summary(*cases: sf.CaseResult) -> str:
    return combine_summary_html(_candidate(fixture_graph(3), cases))


def _chip(text: str) -> str:
    return f"<span class='sf-chip'>{text}</span>"


def _line(text: str) -> str:
    """One run summary line: one chip in its own chips block."""

    return f"<div class='sf-chips'>{_chip(text)}</div>"


def _row(member: str, status: str, value: str, cell: str, chosen: str = "") -> str:
    """One member row of a vote's Combine table (no weight, score or rank column; one signal)."""

    opening = "<tr>" if status == "answered" else "<tr class='sf-cmb__out'>"
    return (
        f"{opening}<td>{member}</td><td>{status}</td><td>{value}</td>"
        f"<td>{cell}</td><td>{chosen}</td></tr>"
    )


def _summary_row(member: str, chosen: str, mean: str, count: int) -> str:
    """One member row of the run summary of 2 Cases: chosen, excluded, then the cons mean."""

    return (
        f"<tr><td>{member}</td><td>{chosen}</td><td>0 of 2</td>"
        f"<td>{mean}{_MEAN_N.format(count=count)}</td></tr>"
    )


# --- CD#1: CHAR ----------------------------------------------------------------------------------


def test_existing_sections_show_no_sample_facts() -> None:
    # CD-D1: the fixed list L37, never a loop over the whole file.
    wires = _read(_L37_CASES)

    assert len(_L37) == 37
    for name in _L37:
        wire = wires[name]
        owner = _candidate(fixture_graph(len(wire["members"])), (_case(wire),))
        text = combine_sections_html(owner, owner.cases[0]) + "\n" + combine_summary_html(owner)
        assert "consistency" not in wire, name
        assert "samples · " not in text, name
        assert "failed</span>" not in text, name


# --- CD#2..CD#4: the Case pane -------------------------------------------------------------------


def test_the_step_chip_counts_the_failed_samples() -> None:
    # CD-1 (P15): fixture V, n 4, failed 0 + 2 + 4 of 4 x 3. The chip comes after the mean chip,
    # so in a vote (no median, no mean) it is the last chip, right after the dropped chip.
    vote = _section(_wire("consistency_vote"))
    chip = _chip("samples · cons · 4 per member · failed 6 of 12")

    assert _SAMPLES_CHIP.findall(vote) == [chip]
    assert _chip("dropped · 0") + chip + "</div>" + _TABLE in vote

    # CD-D2: fixture W, n 3, no failed sample: the chip, and no failed note in any cell.
    pick = _section(_wire("consistency_pick_default_match"))

    assert _SAMPLES_CHIP.findall(pick) == [_chip("samples · cons · 3 per member · failed 0 of 9")]
    assert "failed</span>" not in pick

    # CV-D5: a step with no voter still shows its samples (failed 0 + 2 + 4).
    no_votes = _section(_wire("consistency_no_votes"))

    assert _SAMPLES_CHIP.findall(no_votes) == [chip]


def test_each_member_cell_shows_its_value_and_its_failed_samples() -> None:
    # CD-2 (ans:Q4): the value, then " {f} failed" when the member has failed samples.
    section = _section(_wire("consistency_vote"))
    every_failed = _NA.format(title="every sample failed")

    assert _row("member_1", "answered", "12", _HALF, "&check;") in section
    assert _row("member_2", "answered", "12", _ONE + _FAILED.format(count=2)) in section
    assert _row("member_3", "answered", "7", every_failed + _FAILED.format(count=4)) in section
    assert "<th scope='col' title='source: consistency'>cons</th>" in section


def test_a_missing_value_names_why() -> None:
    # CD-D3: every member failed (missing); the member reason wins over the sample reason.
    section = _section(_wire("consistency_no_votes"))
    missing = _NA.format(title="member failed: missing")
    status = "fail · missing"

    assert _row("member_1", status, missing, missing) in section
    assert _row("member_2", status, missing, missing + _FAILED.format(count=2)) in section
    assert _row("member_3", status, missing, missing + _FAILED.format(count=4)) in section

    # CD-D4: fixture V where member_1 answered but has no match value (matched None; 4 and 0).
    wire = _wire("consistency_vote")
    wire["members"][0]["signals"]["cons"] = None
    wire["consistency"]["cons"][0]["matched"] = None
    no_answer = _NA.format(title="no answer to compare")

    assert _row("member_1", "answered", "12", no_answer, "&check;") in _section(wire)


# --- CD#5: the run summary -----------------------------------------------------------------------


def test_the_run_summary_sums_the_failed_samples() -> None:
    # CD-3: two Cases of fixture V: failed 6 + 6 of 12 + 12, directly after the heading (no gate).
    summary = _summary(_case(_wire("consistency_vote"), 1), _case(_wire("consistency_vote"), 2))
    heading = "<div class='sf-cmb__h' title='op_synthesis_1'>synthesis · vote · 2 cases</div>"
    no_value = _NA.format(title="no Case gave a value")

    assert heading + _line("samples · cons · failed 12 of 24") + _TABLE in summary
    assert _SAMPLES_CHIP.findall(summary) == [_chip("samples · cons · failed 12 of 24")]
    assert "<th scope='col' title='source: consistency'>cons mean</th>" in summary
    assert _summary_row("member_1", "2 of 2", _HALF, 2) in summary
    assert _summary_row("member_2", "0 of 2", _ONE, 2) in summary
    assert _summary_row("member_3", "0 of 2", no_value, 0) in summary


def test_a_case_without_evidence_is_not_counted() -> None:
    # CD-E1 (part 4 P19): the second Case's op_synthesis_1 has no evidence, so it adds nothing.
    bare = _case_of([*_models(3), CaseOperation("op_synthesis_1", "42", "stop", None)], 2)
    summary = _summary(_case(_wire("consistency_vote"), 1), bare)
    heading = "<div class='sf-cmb__h' title='op_synthesis_1'>synthesis · vote · 1 case</div>"

    assert heading + _line("samples · cons · failed 6 of 12") + _TABLE in summary
    assert _SAMPLES_CHIP.findall(summary) == [_chip("samples · cons · failed 6 of 12")]


# --- CD#6, CD#7: CHAR, the export and the trace --------------------------------------------------


def test_the_export_holds_the_consistency_record(tmp_path: Path) -> None:
    # CD-4 (C4): operations[].combine.consistency is the record, byte for byte after json.dumps,
    # between signal and declared (CR-3); no export change.
    wire = _wire("consistency_vote")
    result = _candidate(fixture_graph(3), (_case(wire),))
    report = sf.Report(benchmark=result.benchmark, case_count=1, candidates=(result,))
    path = report.export(tmp_path / "report.json")
    exported: list[Any] = [report.to_dict(), json.loads(path.read_text(encoding="utf-8"))]
    expected = {
        "cons": [
            {"member_id": "member_1", "matched": 2, "succeeded": 4, "failed": 0},
            {"member_id": "member_2", "matched": 2, "succeeded": 2, "failed": 2},
            {"member_id": "member_3", "matched": None, "succeeded": 0, "failed": 4},
        ]
    }

    assert wire["consistency"] == expected
    for value in exported:
        (case,) = value["candidates"][0]["cases"]
        (combine,) = [op["combine"] for op in case["operations"] if "combine" in op]
        keys = list(combine)
        position = keys.index("consistency")
        assert json.dumps(combine["consistency"]) == json.dumps(wire["consistency"])
        assert keys[position - 1 : position + 2] == ["signal", "consistency", "declared"]


def test_the_trace_field_sets_do_not_change() -> None:
    # CD-D5: the report-trace.v1 kinds and fields; every trace entry of the three cases uses them.
    assert TRACE_SCHEMA == "screamingface.report-trace.v1"
    assert set(TRACE_FIELDS) == {"model_call", "extract", "reduce", "budget"}
    assert len(TRACE_FIELDS["reduce"]) == 11
    for name in _NAMES:
        wire = _wire(name)
        owner = _candidate(fixture_graph(len(wire["members"])), (_case(wire),))
        trace = [entry.to_dict() for entry in owner.cases[0].trace()]

        assert trace, name
        assert all(list(e) == ["kind", *TRACE_FIELDS[str(e["kind"])]] for e in trace), name


# --- review P7 #1: a sample call in a nested Fusion has no member in the trace -------------------


def test_nested_fusion_sample_calls_have_no_member_in_the_trace() -> None:
    # N8: a sample call is a step row with no member. The outer combine reads the inner combine
    # that owns the samples; it must not give them its member label (review P7 #1).
    inner = sf.Fanout(
        ["prov/alpha", "prov/beta", "prov/eps"], signals={"cons": sf.Consistency(n=2)}, name="ia"
    ) >> sf.ArgMax("cons")
    plain = sf.Fanout(["prov/gamma", "prov/delta", "prov/eta"], name="ib") >> sf.Vote()
    outer = sf.Fanout([inner, plain, "prov/zeta"], name="outer") >> sf.Vote()
    graph = compile_candidate(outer, operators=engine_operators()).operations
    evidence = {
        "op_synthesis_1": _evidence(_wire("consistency_vote")),
        "op_synthesis_2": _evidence(_read(_L37_CASES)["vote_one_failed"]),
        "op_synthesis_3": _evidence(_read(_L37_CASES)["vote_one_failed"]),
    }
    operations = [
        CaseOperation(node.id, "42", "stop", None, combine=evidence[node.id])
        if node.kind == "combine"
        else CaseOperation(node.id, f"text {node.id}", "stop", None)
        for node in graph
    ]
    samples = {node.id for node in graph if node.kind == "sample"}
    owner = _candidate(graph, (_case_of(operations),))

    calls = {
        str(entry["operation_id"]): entry
        for entry in (item.to_dict() for item in owner.cases[0].trace())
        if entry["kind"] == "model_call"
    }

    assert len(samples) == 6  # alpha, beta and eps, n=2 each
    assert all(calls[key]["member_id"] is None for key in samples)
    # control: the member calls of the inner Fusion keep their member labels
    beta = next(node for node in graph if node.id == "op_model_2")
    assert (beta.kind, beta.label.split()[0]) == ("model", "beta")
    assert calls[beta.id]["member_id"] == "member_2"

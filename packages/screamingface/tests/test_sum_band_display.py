"""The sum and the band in the report (E4b part 6 unit 6, PRD sum-band-display, SD#1-10).

FEATURE: a declared sum is one more signal column whose header title names its formula (Case pane
and run summary); a gate with an abstain band shows the band in its chip and the verdict
``in band · abstain``; the run summary counts the Cases in the band; the run summary mean does not
overflow; the JSON export carries the band and ``in_band`` with no export change.
STORY: as a benchmark author who opens a Case or a run summary, I see the sum as a signal column
that names its formula, the band in the gate chip, and how many Cases abstained in the band
(ans:Q1 "recorded like any declared signal", ans:Q2 "recorded in the gate record").
INVARIANT defended: each case of the fixed list L37 renders the same bytes as on the part base
633fec3a1 (SD-D1); every text from the record is escaped (part 4 P8). The wires are the Engine
contract cases of ET/data/combine_contract/evidence_cases.json, read under requires_engine_app,
with a hand-built Case. Every expected string is written by hand from the PRD scenarios, never
copied from the code's output.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from _answer_fixtures import fixture_graph
from _combine_contract import requires_engine_app
from test_combine_run_summary import _candidate
from test_gate_display import (
    _AGREEMENT,
    _AT_06,
    _AT_07,
    _GATE_CHIP,
    _NOT_RUN,
    _case,
    _chip,
    _section,
    _wire,
    _wires,
)

import screamingface as sf
from screamingface._ui.combine_view import _mean_cell, combine_sections_html, combine_summary_html

pytestmark = requires_engine_app

_SUM_TITLE = "source: sum of 0.5 × sev_a + 0.3 × sev_b"
_NO_SIGNAL = "left out by the rule: no_signal"

# SD-D1 (test-plan §6 L37): the 37 evidence cases of the part base, and for each the sha256 of
# its Combine section + "\n" + its run summary, rendered by the SDK of the part base 633fec3a1.
_L37_DIGESTS: dict[str, str] = {
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
    "vote_gate_abstain": "2a24bca4dba42ba693bcc7e23fb84510fd37a23f87dc542caee765ed46a63a3d",
    "vote_gate_judge": "ca72741212bb4cb3eb3fa6e1bc495bec0501ecdc5d0a07197d880aff7bc71c1f",
    "vote_gate_majority": "59a1fcc4cc5bef3dffbc296d97d454d39d70cae88af7630e6574fd71207898ce",
    "vote_gate_not_run": "40cc8d78c3064143cbb5c40f6e1758ab2f1a0cc11193b0c76b9450773a7bf80f",
    "vote_gate_writer": "c0a95b452bfde059449b4cc9983a888e529ae72b442dc424bce9032f573a4873",
    "vote_judge_weights": "02172ce7161c7820c84979fa389adc3aef85af9cf46cd37056bf34338fc5b868",
    "vote_one_failed": "fab6c6c9df23dbd328b4b3ef499e5a5c25654a63104a129f94d39df72a51ed9f",
    "vote_tie": "fd6fe5f2f366879551b277d8554287e775ad6579d15a3fd08c9c46d661ad8cc3",
    "vote_weight_excluded": "6b0aa03f2a93cb59f5981e786211cdac77dee09972365a0506af03e2e6ebe91b",
    "vote_weighted": "f4f1c7083666f3a7c4244dc9c960572ec1241bd8bda1e028f12650affb636831",
}


# --- builders ------------------------------------------------------------------------------------


def _num(title: str, text: str) -> str:
    """A number span: the exact repr as the title, the 4-digit text."""

    return f"<span class='sf-cmb__n' title='{title}'>{text}</span>"


def _dash(title: str) -> str:
    """The missing-value mark with its reason."""

    return f"<span class='sf-cmb__na' title='{title}'>—</span>"


def _nn(count: int) -> str:
    return f" <span class='sf-cmb__nn'>n={count}</span></td>"


def _risk_head(source: str) -> str:
    """The Case pane header of the read sum column of pick_sum_min, for this source text."""

    return f"<th scope='col' title='source: {source}; read by the rule'>risk</th>"


def _summary_of(*wires: dict[str, Any]) -> str:
    """The run summary of one Candidate whose Cases (ids 1..n) hold these 3-member wires."""

    cases = tuple(_case(wire, case_id) for case_id, wire in enumerate(wires, start=1))
    return combine_summary_html(_candidate(fixture_graph(3), cases))


def _summary(*names: str) -> str:
    return _summary_of(*(_wire(name) for name in names))


def _sum_entry_wire(entry: dict[str, Any]) -> dict[str, Any]:
    """SD-E1, SD-D4: pick_sum_min with its declared ``risk`` entry replaced by ``entry``."""

    wire = _wire("pick_sum_min")
    wire["declared"]["risk"] = entry
    return wire


# --- SD#1: CHAR ----------------------------------------------------------------------------------


def test_existing_cases_render_the_same_bytes() -> None:
    # SD-D1: the fixed list L37, never a loop over the whole file.
    wires = _wires()

    assert len(_L37_DIGESTS) == 37
    for name, digest in _L37_DIGESTS.items():
        wire = wires[name]
        owner = _candidate(fixture_graph(len(wire["members"])), (_case(wire),))
        text = combine_sections_html(owner, owner.cases[0]) + "\n" + combine_summary_html(owner)
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == digest, name


# --- SD#2, SD#3: the sum header ------------------------------------------------------------------


def test_sum_column_title_names_the_coefficients() -> None:
    # SD-1 (ans:Q1, P14): the sum column names its formula; member_3 has no sum.
    section = _section(_wire("pick_sum_min"))
    member_3_cells = (
        f"<td>{_dash(_NO_SIGNAL)}</td><td>{_num('6.0', '6')}</td>"
        f"<td>{_dash(_NO_SIGNAL)}</td><td></td></tr>"
    )

    assert _risk_head("sum of 0.5 × sev_a + 0.3 × sev_b") in section
    assert "<th scope='col' title='source: verbalized'>sev_a</th>" in section
    assert "<th scope='col' title='source: verbalized'>sev_b</th>" in section
    assert member_3_cells in section


def test_run_summary_mean_header_names_the_sum() -> None:
    # SD-2 (P14): the `risk mean` header of the run summary names the same formula.
    summary = _summary("pick_sum_min")

    assert f"<th scope='col' title='{_SUM_TITLE}'>risk mean</th>" in summary
    assert "<th scope='col' title='source: verbalized'>sev_a mean</th>" in summary
    assert "gate ·" not in summary


# --- SD#4, SD#5: the band in the Case pane -------------------------------------------------------


def test_case_pane_shows_the_band_and_the_in_band_verdict() -> None:
    # SD-3 (ans:Q2, P14): the band chip, the in-band verdict and the in_band result chip.
    section = _section(_wire("vote_gate_band"))
    gate = _chip(
        f"gate · agreement &gt;= {_AT_07} · band [{_AT_06}, {_AT_07}]"
        f" · observed {_AGREEMENT} · in band · abstain"
    )

    assert _GATE_CHIP.findall(section) == [gate]
    assert _chip("agreement · " + _AGREEMENT) + gate + _chip("tie · no") in section
    assert _chip("abstain · in_band") in section


def test_case_pane_shows_a_band_on_the_majority_branch() -> None:
    # SD-D2 (P14): a band outside which the number fell, on the majority branch; and a band on a
    # gate that did not run (abstain-band AB-D4 keeps the band in the record).
    majority = _wire("vote_gate_majority")
    majority["gate"]["abstain_band"] = [0.7, 0.9]
    not_run = _wire("vote_gate_not_run")
    not_run["gate"]["abstain_band"] = [0.6, 0.7]

    assert _GATE_CHIP.findall(_section(majority)) == [
        _chip(
            f"gate · agreement &gt;= {_AT_06} · band [{_AT_07}, {_num('0.9', '0.9')}]"
            f" · observed {_AGREEMENT} · majority"
        )
    ]
    assert _GATE_CHIP.findall(_section(not_run)) == [
        _chip(
            f"gate · agreement &gt;= {_AT_06} · band [{_AT_06}, {_AT_07}]"
            f" · observed {_dash(_NOT_RUN)} · not run"
        )
    ]


# --- SD#6: the run summary gate line -------------------------------------------------------------


def test_run_summary_counts_the_band() -> None:
    # SD-4 (P14): ` · in band {b} of {N}` after fallback, before ` · not run`.
    first = _summary("vote_gate_majority", "vote_gate_abstain", "vote_gate_band")
    second = _summary("vote_gate_band", "vote_gate_not_run", "vote_gate_majority")

    assert _GATE_CHIP.findall(first) == [
        _chip("gate · majority 1 of 3 · fallback 1 of 3 · in band 1 of 3")
    ]
    assert _GATE_CHIP.findall(second) == [
        _chip("gate · majority 1 of 3 · fallback 0 of 3 · in band 1 of 3 · not run 1 of 3")
    ]


# --- SD#7: CHAR, the export ----------------------------------------------------------------------


def test_export_carries_the_band_and_in_band(tmp_path: Path) -> None:
    # SD-5 (ans:Q2): the export writes the gate record with its band, and the in_band result.
    result = _candidate(fixture_graph(3), (_case(_wire("vote_gate_band")),))
    report = sf.Report(benchmark=result.benchmark, case_count=1, candidates=(result,))
    path = report.export(tmp_path / "report.json")
    exported: list[Any] = [report.to_dict(), json.loads(path.read_text(encoding="utf-8"))]
    expected = {
        "observe": "agreement",
        "observed": 0.6666666666666666,
        "cmp": ">=",
        "threshold": 0.7,
        "passed": None,
        "branch": "band",
        "otherwise": "abstain",
        "abstain_band": [0.6, 0.7],
    }

    for value in exported:
        (case,) = value["candidates"][0]["cases"]
        (combine,) = [op["combine"] for op in case["operations"] if "combine" in op]
        assert combine["gate"] == expected
        assert list(combine["gate"]) == list(expected)
        assert combine["gate"]["abstain_band"] == [0.6, 0.7]
        assert combine["result"] == {
            "member_id": None,
            "value": None,
            "status": "abstain",
            "reason": "in_band",
        }


# --- SD#8: CHAR, a malformed sum entry -----------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        {"source": "sum"},
        {"source": "sum", "coefficients": ["a"]},
        {"source": "sum", "coefficients": "a"},
        {"source": "sum", "coefficients": {}},
        {"source": "sum", "coefficients": {"a": True}},
        {"source": "sum", "coefficients": {"a": "0.5"}},
        {"source": "sum", "coefficients": {"a": None}},
        {"source": "sum", "coefficients": {"a": 10**400}},
        {"source": "sum", "coefficients": {"a": 0.5, "b": "x"}},
    ],
    ids=[
        "no_coefficients",
        "list",
        "text",
        "empty",
        "bool",
        "number_as_text",
        "null",
        "int_past_float_range",
        "one_bad_term",
    ],
)
def test_a_malformed_sum_entry_shows_source_sum(entry: dict[str, Any]) -> None:
    # SD-E1: no error; the title falls back to the part 4 text `source: sum`.
    wire = _sum_entry_wire(entry)

    assert _risk_head("sum") in _section(wire)
    assert "<th scope='col' title='source: sum'>risk mean</th>" in _summary_of(wire)


# --- SD#9: the run summary mean ------------------------------------------------------------------


def test_run_summary_mean_does_not_overflow() -> None:
    # SD-D3 (P14; part 5 erratum E6): the exact mean, rounded once, when math.fsum overflows.
    assert _mean_cell([1e308, 1e308]) == "<td>" + _num("1e+308", "1e+308") + _nn(2)
    assert _mean_cell([-1e308, -1e308]) == "<td>" + _num("-1e+308", "-1e+308") + _nn(2)
    assert _mean_cell([1e308, 1e308, -1e308]) == (
        "<td>" + _num("3.333333333333333e+307", "3.333e+307") + _nn(3)
    )
    assert _mean_cell([1.0, 2.0]) == "<td>" + _num("1.5", "1.5") + _nn(2)
    assert _mean_cell([]) == "<td>" + _dash("no Case gave a value") + _nn(0)


# --- SD#10: a negative coefficient ---------------------------------------------------------------


def test_a_negative_coefficient_shows_as_written() -> None:
    # SD-D4: the coefficient as written (repr of the float), in the entry order; an int shows as a
    # float; a name reaches the page escaped (NFR §4).
    negative = _sum_entry_wire({"source": "sum", "coefficients": {"a": 2.0, "b": -0.5}})
    escaped = _sum_entry_wire({"source": "sum", "coefficients": {"a<b": 1}})

    assert _risk_head("sum of 2.0 × a + -0.5 × b") in _section(negative)
    assert _risk_head("sum of 1.0 × a&lt;b") in _section(escaped)

"""The report shows every sf.Gate decision: what ran, what made zero calls, and why.

FEATURE: E4c (OME-1291) report rows RP#1 - #14, #16 - #18, #20, #22, #23, #25, #26, #29 - #35
(the budget rows are PR-3, the skip-member row is PR-2).
STORY: as a researcher whose result is a saving, I audit every skip from the report alone: per Case
a "Branches" block, per run a "gates" block with counts and the ladder of each chain.
Records are hand-built to the Engine's ``gate-decision.v1`` shape (``E/combine/decision.py``).
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from _reducer_fixtures import engine_operators
from test_report import benchmark
from test_report_v1_identity import COMBINE_GOLDEN, combine_report

import screamingface as sf
from screamingface._evaluation.candidate import compile_candidate
from screamingface._evaluation.gate_decision import GateDecision, decode_gate_decision
from screamingface._evaluation.results import _case_operation
from screamingface._ui import branch_view, combine_view
from screamingface._ui.branch_view import GateSummary, branch_sections_html, condition_text
from screamingface._ui.report_view import _card_html
from screamingface.case_result import CaseAttempt, CaseOperation
from screamingface.errors import ExecutionError

GATE_GOLDEN = Path(__file__).parent / "data" / "report_v1_gate_report.json"
_SHA = "0123456789abcdef"
_TOPIC = sf.Keywords([("math", r"(?i)\bintegral\b"), ("code", r"(?i)\bpython\b")])
_ANSWERED = {"status": "answered", "reason": None}


# --- builders -------------------------------------------------------------------------------------


def selector(
    selector_id: str = "sel_1",
    *,
    kind: str = "keywords",
    status: str = "computed",
    labels: list[str] | None = None,
    parse: str | None = "ok",
    raw: str | None = None,
    chars: int = 11,
) -> dict[str, Any]:
    computed = status == "computed"
    return {
        "id": selector_id,
        "kind": kind,
        "status": status,
        "labels": (["math"] if labels is None else labels) if computed else None,
        "parse": parse if computed else None,
        "raw": raw if computed else None,
        "parse_error": None,
        "input_chars": chars,
        "input_sha256": _SHA,
    }


def record(
    gate: str = "gate_1",
    *,
    branch: str | None = "then",
    wanted: str | None = "keep",
    when: dict[str, Any] | None = None,
    observed: Any = "math",
    passed: bool | None = True,
    selectors: list[dict[str, Any]] | None = None,
    calls: tuple[int, int] = (1, 1),
    result: dict[str, Any] | None = None,
    panel: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A record the Engine writes; ``wanted="keep"`` means wanted = branch."""

    not_run = [
        {
            "branch": name,
            "reason": "not_selected",
            "model_calls": {"min": calls[0], "max": calls[1]},
        }
        for name in ("then", "otherwise")
        if name != branch
    ]
    return {
        "schema": "screamingface.gate-decision.v1",
        "gate_id": gate,
        "kind": "panel" if panel is not None else "input",
        "when": when or {"observe": "label:sel_1", "cmp": "eq", "value": "math"},
        "observed": observed,
        "passed": passed,
        "wanted": branch if wanted == "keep" else wanted,
        "branch": branch,
        "selectors": [selector()] if selectors is None else selectors,
        "not_run": not_run,
        "budget": None,
        "result": _ANSWERED if result is None else result,
        "panel": panel,
    }


def decision(value: dict[str, Any]) -> GateDecision:
    decoded = decode_gate_decision(value, "Case Operation decision")
    assert decoded is not None
    return decoded


def operation(gate: str, value: dict[str, Any] | None, output: str = "M") -> CaseOperation:
    return CaseOperation(
        f"op_{gate}", output, "stop", None, decision=None if value is None else decision(value)
    )


def case(
    case_id: int,
    operations: tuple[CaseOperation, ...] | None,
    *,
    output: str = "M",
    failure: str | None = None,
    abstained: bool = False,
    attempts: tuple[CaseAttempt, ...] | None = None,
) -> sf.CaseResult:
    if failure is not None:
        return sf.CaseResult(
            case_id=case_id,
            input=f"Question {case_id}",
            output=None,
            finish_reason=None,
            grade=None,
            failures=(
                sf.Failure(stage="candidate", code=failure, message="fixed", case_id=case_id),
            ),
            metadata={},
            operations=operations,
        )
    return sf.CaseResult(
        case_id=case_id,
        input=f"Question {case_id}",
        output="" if abstained else output,
        finish_reason="stop",
        grade=sf.CaseGrade(
            method="fixture", score=0.0 if abstained else 1.0, metrics={}, checks=()
        ),
        failures=(),
        metadata={},
        operations=operations,
        attempts=attempts,
        abstained=abstained,
    )


def gate_candidate(recipe: object, cases: tuple[sf.CaseResult, ...]) -> sf.CandidateResult:
    compiled = compile_candidate(recipe, operators=engine_operators())  # type: ignore[arg-type]
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
        coverage=round(
            sum(item.grade is not None and item.grade.score is not None for item in cases)
            / len(cases),
            4,
        ),
        metrics={},
        cases=cases,
        members=(),
        failures=(),
        usage=sf.Usage(input_tokens=10, output_tokens=4, cost_usd="0.01"),
    )


def router() -> object:
    """gate_1: math, else gate_2: code, else general (a chain of two)."""
    inner = sf.Gate(when=sf.label(_TOPIC) == "code", then="prov/coder", otherwise="prov/general")
    return sf.Gate(when=sf.label(_TOPIC) == "math", then="prov/math", otherwise=inner)


def router_case(case_id: int, taken: str) -> sf.CaseResult:
    """One Case of the router: ``taken`` is math, code or general."""
    if taken == "math":
        ops = (operation("gate_1", record()),)
    else:
        outer = record(branch="otherwise", observed=None if taken == "general" else "code")
        outer["passed"] = False
        inner_branch = "then" if taken == "code" else "otherwise"
        inner = record(
            "gate_2",
            branch=inner_branch,
            when={"observe": "label:sel_1", "cmp": "eq", "value": "code"},
            observed="code" if taken == "code" else None,
            passed=taken == "code",
            selectors=[selector(labels=["code"] if taken == "code" else [], parse=None)]
            if taken != "code"
            else [selector(labels=["code"])],
        )
        if taken == "general":
            inner["selectors"] = [selector(labels=[], parse="no_match")]
        ops = (operation("gate_1", outer), operation("gate_2", inner))
    return case(case_id, ops)


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


# --- decode and export (RP#1 - #5, #8, #32) -------------------------------------------------------


def test_report_without_gates_exports_byte_identically() -> None:
    # CHAR RP#1: the E4b golden keeps its bytes.
    assert combine_report().to_json() + "\n" == COMBINE_GOLDEN.read_text(encoding="utf-8")


def test_combine_sections_and_summary_are_unchanged_without_gates() -> None:
    # CHAR RP#2: no Gate, no Branches block and no gates summary; the Combine views stay.
    value = combine_report()
    candidate = value.candidates[0]
    summary, gates = combine_view.CombineSummary(), GateSummary()
    for item in candidate.cases:
        assert branch_sections_html(candidate, item) == ""
        summary.add(item)
        gates.add(item)
    assert gates.html(candidate) == ""
    assert "Branches" not in _card_html(candidate, value)


def test_decision_decodes_and_round_trips_byte_for_byte() -> None:
    raw = record(
        selectors=[selector(), selector("sel_2", kind="label_model", status="not_run")],
        calls=(2, 5),
    )
    raw["when"] = {"observe": "label:sel_1", "cmp": "eq", "value": "math"}
    decoded = decision(raw)
    assert json.dumps(decoded.to_dict()) == json.dumps(raw)
    assert list(decoded.to_dict()) == list(raw)


def _set(*path: object, value: object) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        target: Any = raw
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


def _drop_panel(raw: dict[str, Any]) -> None:
    del raw["panel"]


_CHANGES: dict[str, Callable[[dict[str, Any]], None]] = {
    "unknown_key": _set("note", value="secret value"),
    "missing_key": _drop_panel,
    "schema": _set("schema", value="screamingface.gate-decision.v9"),
    "gd_i1": _set("not_run", value=[]),
    "gd_i2": _set("wanted", value=None),
    "gd_i4": _set("panel", value={"operation_id": "op_synthesis_1", "branch": "majority"}),
    "gd_i7": _set("not_run", 0, "model_calls", value={"min": 3, "max": 1}),
    "sr_i1": _set("selectors", 0, "status", value="not_run"),
    "sr_i3": _set("selectors", 0, "labels", value=["Secret Value"]),
    "reason": _set("not_run", 0, "reason", value="secret value"),
}


def _broken(change: str) -> dict[str, Any]:
    raw = record()
    _CHANGES[change](raw)
    return raw


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ("unknown_key", "'note'"),
        ("missing_key", "'panel'"),
        ("schema", "schema"),
        ("gd_i1", "not_run"),
        ("gd_i2", "wanted"),
        ("gd_i4", "panel"),
        ("gd_i7", "not_run[0] model_calls"),
        ("sr_i1", "selectors[0]"),
        ("sr_i3", "selectors[0] labels[0]"),
        ("reason", "not_run[0] reason"),
    ],
)
def test_decision_decoder_refuses_unknown_missing_and_wrong_schema_without_echo(
    change: str, path: str
) -> None:
    # RP#4 / RP-20: the message names the field path, never the value.
    with pytest.raises(ExecutionError) as caught:
        decode_gate_decision(_broken(change), "Case Operation decision")
    assert path in str(caught.value)
    assert "secret value" not in str(caught.value).lower()


def test_older_sdk_policy_unknown_decision_key_is_a_version_mismatch() -> None:
    # RP#32: a Case Operation key this SDK does not know refuses (so the SDK ships first).
    raw = operation("gate_1", record()).to_dict()
    raw["verdict"] = {}
    with pytest.raises(ExecutionError, match="unsupported field 'verdict'"):
        _case_operation(raw)
    assert _case_operation(operation("gate_1", record()).to_dict()).decision is not None


def gate_report() -> sf.Report:
    cases = (router_case(1, "math"), router_case(2, "code"))
    candidate = gate_candidate(router(), cases)
    return sf.Report(benchmark=candidate.benchmark, case_count=2, candidates=(candidate,))


def test_export_writes_decision_only_on_join_operations() -> None:
    # RP#5 / RP-2: the export carries operations[].decision on op_gate_N only.
    value = gate_report()
    exported = json.loads(value.to_json())
    for item in exported["candidates"][0]["cases"]:
        for op in item["operations"]:
            assert ("decision" in op) == op["operation_id"].startswith("op_gate_")
    assert value.to_json() + "\n" == GATE_GOLDEN.read_text(encoding="utf-8")


def test_old_saved_report_reopens_without_branches_block() -> None:
    # RP#8 / RP-21: a report.v1 written before E4c decodes and renders with no Branches block.
    value = combine_report()
    html = value._repr_html_()
    assert "Branches" not in html
    assert ">gates<" not in html


# --- the Case pane (RP#6, #7, #9 - #14, #20, #22, #23, #25, #30, #31, #34, #35) ------------------


def test_branches_section_per_gate_in_nesting_order_with_indent() -> None:
    # RP#10 / RP-3
    candidate = gate_candidate(router(), (router_case(1, "general"),))
    html = branch_sections_html(candidate, candidate.cases[0])
    first, second = html.index("gate · gate_1"), html.index("gate · gate_2 · level 2")
    assert first < second
    assert "margin-left:0px" in html and "margin-left:16px" in html


def test_not_run_lines_show_reason_and_model_calls_range() -> None:
    # RP#7 / RP-6
    candidate = gate_candidate(router(), (case(1, (operation("gate_1", record(calls=(2, 5))),)),))
    text = _text(branch_sections_html(candidate, candidate.cases[0]))
    assert "ran · then" in text
    assert "not run · otherwise · not selected · avoided 2–5 model calls" in text


@pytest.mark.parametrize(
    ("when", "source"),
    [
        ({"observe": "label:sel_1", "cmp": "eq", "value": "math"}, "sf.label(sel_1) == 'math'"),
        ({"observe": "label:sel_1", "cmp": "ne", "value": "safe"}, "sf.label(sel_1) != 'safe'"),
        (
            {"observe": "labels:sel_2", "cmp": "has", "value": "code"},
            "sf.labels(sel_2).has('code')",
        ),
        ({"observe": "labels:sel_2", "cmp": "empty", "value": None}, "sf.labels(sel_2).empty()"),
        ({"observe": "agreement", "cmp": ">=", "value": 0.8}, "sf.agreement() >= 0.8"),
        ({"observe": "chosen:conf", "cmp": "<", "value": 0.7}, "sf.signal('conf').chosen() < 0.7"),
        ({"observe": "mean:conf", "cmp": ">=", "value": 80.0}, "sf.signal('conf').mean() >= 80.0"),
        ({"observe": "answered", "cmp": "eq", "value": True}, "sf.answered()"),
    ],
)
def test_condition_renders_in_source_form(when: dict[str, Any], source: str) -> None:
    # RP#11 / RP-4
    from screamingface._evaluation.gate_decision import GateWhen

    assert condition_text(GateWhen(when["observe"], when["cmp"], when["value"])) == source


def test_observed_number_uses_4_significant_digits_and_exact_title() -> None:
    # RP#20 / RP-5
    raw = record(
        when={"observe": "agreement", "cmp": ">=", "value": 0.8},
        observed=0.6666666666666666,
        passed=False,
        branch="otherwise",
        selectors=[],
        panel={"operation_id": "op_synthesis_1", "branch": "fallback"},
    )
    pane = branch_view._observed(decision(raw))
    assert ">0.6667<" in pane and "title='0.6666666666666666'" in pane
    assert pane.endswith(" · failed")


@pytest.mark.parametrize(
    ("entry", "shown"),
    [
        (selector(labels=[], parse="no_match"), "no match"),
        (selector(labels=[], parse="unrecognized", raw="physics"), 'unrecognized · "physics"'),
        (selector(labels=[], parse="unparsed"), "unparsed"),
        (selector(kind="label_model", status="not_run"), "not run"),
        (selector(labels=["math", "code"]), "labels · math, code"),
    ],
)
def test_selector_lines_show_labels_and_parse_states(entry: dict[str, Any], shown: str) -> None:
    # RP#12 / RP-7: the input summary, never the input text
    text = _text(branch_view._selector_line(decision(record(selectors=[entry])).selectors[0]))
    assert shown in text
    assert "input · 11 characters" in text


def test_failed_selector_line_says_the_default_branch_ran() -> None:
    # RP#35
    entry = selector(kind="label_model", status="failed")
    html = branch_view._selector_line(decision(record(selectors=[entry])).selectors[0])
    assert "failed · the default branch ran" in html
    assert "activity view" in html


def test_fired_guard_shows_guard_and_model_selector_not_run() -> None:
    # RP#13 / RP-8: the guard took the word fail_closed (a refusal keeps the record).
    raw = record(
        when={"observe": "label:sel_1", "cmp": "eq", "value": "jailbreak"},
        observed="jailbreak",
        calls=(1, 2),
        selectors=[
            selector(labels=["jailbreak"]),
            selector("sel_2", kind="label_model", status="not_run"),
        ],
        result={"status": "fail_closed", "reason": None},
    )
    raw["not_run"][0]["model_calls"] = {"min": 1, "max": 2}
    candidate = gate_candidate(router(), (case(1, (operation("gate_1", raw, ""),)),))
    text = _text(branch_sections_html(candidate, candidate.cases[0]))
    assert "guard fired · fail_closed" in text
    assert "label model · sel_2" in text and "not run" in text


def test_raw_token_is_escaped_and_cut_at_64() -> None:
    # RP#14 / RP-23
    raw_token = "<img onerror=x>" + "a" * 49
    entry = selector(labels=[], parse="unrecognized", raw=raw_token)
    html = branch_view._selector_line(decision(record(selectors=[entry])).selectors[0])
    assert "<img" not in html and "&lt;img" in html


def test_many_labels_show_first_8_and_more_title() -> None:
    # RP#30
    labels = [f"l{index}" for index in range(32)]
    html = branch_view._label_list(tuple(labels))
    assert "labels · l0, l1, l2, l3, l4, l5, l6, l7 +24 more" in _text(html)
    assert "l31" in html  # in the title


def test_fail_closed_case_without_operations_shows_short_line() -> None:
    # RP#9 / RP-18: a failed Case keeps no operations.
    failed = case(1, None, failure="fail_closed")
    candidate = gate_candidate(router(), (failed, router_case(2, "math")))
    text = _text(branch_sections_html(candidate, failed))
    assert "a guard ended the Case · fail_closed · no decision record" in text


def test_fail_closed_case_counts_apart_from_abstained() -> None:
    # RP#6 / RP-17: two different counts on the card's context line.
    cases = (
        case(1, None, failure="fail_closed"),
        case(
            2,
            (operation("gate_1", record(result={"status": "abstain", "reason": "gate_not_met"})),),
            abstained=True,
        ),
        router_case(3, "math"),
    )
    candidate = gate_candidate(router(), cases)
    value = sf.Report(benchmark=candidate.benchmark, case_count=3, candidates=(candidate,))
    card = _text(_card_html(candidate, value))
    assert "1 abstained" in card
    assert "fail_closed 1" in card


def test_gate_operation_without_record_shows_dash_section() -> None:
    # RP#23 / RP-19
    candidate = gate_candidate(router(), (case(1, (operation("gate_1", None),)),))
    html = branch_sections_html(candidate, candidate.cases[0])
    assert "decision · " in _text(html)
    assert "no decision record for this gate" in html


def test_record_whose_branch_did_not_finish_shows_result_dash() -> None:
    # RP-19 second half: DECIDE's record (result null) after a refused body.
    candidate = gate_candidate(router(), (case(1, (operation("gate_1", record(result=None)),)),))
    raw = record()
    raw["result"] = None
    candidate = gate_candidate(router(), (case(1, (operation("gate_1", raw),)),))
    html = branch_sections_html(candidate, candidate.cases[0])
    assert "the branch did not finish" in html


def test_nested_gates_of_not_run_body_show_not_reached() -> None:
    # RP#22 / RP-12: math ran, so gate_2 (inside otherwise) was not reached.
    candidate = gate_candidate(router(), (router_case(1, "math"),))
    text = _text(branch_sections_html(candidate, candidate.cases[0]))
    assert "gate · gate_2 · not reached" in text


def test_panel_gate_section_links_to_its_combine_section() -> None:
    # RP#25 / RP-14, RP-33
    recipe = sf.Fanout(["prov/a", "prov/b", "prov/c"]) >> sf.Gate(
        when=sf.agreement() >= 0.8, then=sf.Vote(), otherwise="prov/large"
    )
    raw = record(
        when={"observe": "agreement", "cmp": ">=", "value": 0.8},
        observed=1.0,
        selectors=[],
        panel={"operation_id": "op_synthesis_1", "branch": "majority"},
    )
    candidate = gate_candidate(recipe, (case(1, (operation("gate_1", raw),)),))
    text = _text(branch_sections_html(candidate, candidate.cases[0]))
    assert "decided by · combine · " in text
    assert "no evidence" in text  # the Case has no op_synthesis_1 evidence here


def test_status_words_are_text_and_dashes_have_titles() -> None:
    # RP#31 / RP-32
    raw = record(
        observed=None,
        passed=False,
        branch="otherwise",
        selectors=[selector(labels=[], parse="no_match")],
    )
    candidate = gate_candidate(router(), (case(1, (operation("gate_1", raw),)),))
    html = branch_sections_html(candidate, candidate.cases[0])
    for word in ("ran · otherwise", "not run · then", "result · answered"):
        assert word in _text(html)
    assert all("title=" in dash for dash in re.findall(r"<span class='sf-cmb__na'[^>]*>", html))


def test_deep_nesting_caps_indent_and_names_level() -> None:
    # RP#34 / RP-31: six nested Gates, all taking otherwise.
    value: object = "prov/last"
    for _ in range(6):
        value = sf.Gate(when=sf.label(_TOPIC) == "math", then="prov/m", otherwise=value)
    ops = tuple(
        operation(
            f"gate_{index}",
            record(f"gate_{index}", branch="otherwise", observed=None, passed=False),
        )
        for index in range(1, 7)
    )
    candidate = gate_candidate(value, (case(1, ops),))
    html = branch_sections_html(candidate, candidate.cases[0])
    assert "level 6" in html
    assert "margin-left:64px" in html and "margin-left:80px" not in html


# --- the run summary (RP#16, #17, #18, #26, #29, #33) ---------------------------------------------


def test_gate_summary_counts_add_up() -> None:
    # RP#16 / RP-15, RP-25: then + otherwise + none == decided; the avoided range sums.
    rng = random.Random(1291)
    summary = GateSummary()
    expected_min = expected_max = 0
    for index in range(40):
        branch = rng.choice(["then", "otherwise"])
        low = rng.randrange(0, 3)
        high = low + rng.randrange(0, 3)
        expected_min, expected_max = expected_min + low, expected_max + high
        raw = record(
            branch=branch, calls=(low, high), observed="math" if branch == "then" else None
        )
        raw["passed"] = branch == "then"
        summary.add(case(index, (operation("gate_1", raw),)))
    row = summary.gates["gate_1"]
    assert row.then + row.otherwise + row.none == row.decided == 40
    assert (row.avoided_min, row.avoided_max) == (expected_min, expected_max)


def test_ladder_shows_share_resolved_at_each_branch() -> None:
    # RP#17 / RP-16
    cases = (
        router_case(1, "math"),
        router_case(2, "math"),
        router_case(3, "code"),
        router_case(4, "general"),
    )
    candidate = gate_candidate(router(), cases)
    summary = GateSummary()
    for item in cases:
        summary.add(item)
    text = _text(summary.html(candidate))
    assert (
        "ladder · resolved at the first branch 50.0% · gate_2 25.0% · last otherwise 25.0%" in text
    )
    assert "2 of 4 cases" in summary.html(candidate)


def test_ladder_denominator_is_cases_where_the_chain_started() -> None:
    # RP#26 / RP-27: a Case whose chain did not start is not in the denominator.
    cases = (router_case(1, "math"), case(2, ()))
    candidate = gate_candidate(router(), cases)
    summary = GateSummary()
    for item in cases:
        summary.add(item)
    assert "resolved at the first branch 100.0%" in _text(summary.html(candidate))


def test_lone_gate_has_no_ladder_line() -> None:
    # RP#29 / RP-26
    lone = sf.Gate(when=sf.label(_TOPIC) == "math", then="prov/m", otherwise="prov/g")
    cases = (case(1, (operation("gate_1", record()),)),)
    candidate = gate_candidate(lone, cases)
    summary = GateSummary()
    summary.add(cases[0])
    html = summary.html(candidate)
    assert "gate · gate_1" in _text(html) and "ladder" not in html


def test_card_feeds_gate_summary_in_the_single_case_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    # RP#18 / RP-24: GateSummary.add runs in the same loop as CombineSummary.add.
    calls: list[str] = []
    real_combine, real_gate = combine_view.CombineSummary.add, GateSummary.add
    monkeypatch.setattr(
        combine_view.CombineSummary,
        "add",
        lambda self, item: (calls.append("c"), real_combine(self, item))[1],
    )
    monkeypatch.setattr(
        GateSummary, "add", lambda self, item: (calls.append("g"), real_gate(self, item))[1]
    )
    value = gate_report()
    _card_html(value.candidates[0], value)
    assert calls == ["c", "g"] * 2


def test_attempt_gates_are_not_shown_or_counted() -> None:
    # RP#33 / RP-29: only case.operations count, never an Attempt's.
    grade = sf.CaseGrade(method="fixture", score=1.0, metrics={}, checks=())
    attempt = CaseAttempt(
        attempt=1,
        status="scored",
        output="M",
        finish_reason="stop",
        refusal=None,
        grade=grade,
        failures=(),
        operations=(operation("gate_1", record()),),
    )
    attempts = (attempt, replace(attempt, attempt=2))
    item = case(1, None, attempts=attempts)
    candidate = gate_candidate(router(), (item,))
    summary = GateSummary()
    summary.add(item)
    assert summary.gates == {}
    assert branch_sections_html(candidate, item) == ""


# --- RP#24 (PR-2, unit 12): skip-Gate members --------------------------------------------------


def test_skip_gate_members_show_not_selected_in_both_sections() -> None:
    # RP#24 / RP-13: the unselected member's Gate section says not run · then · not selected;
    # the block's Combine section shows it as not_selected, by its selector id.
    from screamingface.combine_evidence import CombineAnswerRow, CombineEvidence, CombineResult

    skills = sf.Keywords([("math", "integral"), ("code", "python")], multi=True)
    recipe = sf.Model("prov/prep") >> (
        sf.Fanout(
            [
                sf.Gate(when=sf.labels(skills).has("math"), then="prov/m"),
                sf.Gate(when=sf.labels(skills).has("code"), then="prov/c"),
            ]
        )
        >> sf.Vote()
    )
    when = {"observe": "labels:sel_1", "cmp": "has", "value": "math"}
    picked = record("gate_1", when=when, observed=["math"], selectors=[selector(labels=["math"])])
    code_when = {**when, "value": "code"}
    skipped = record(
        "gate_2",
        branch="otherwise",
        when=code_when,
        observed=["math"],
        passed=False,
        selectors=[selector(labels=["math"])],
    )
    skipped["result"] = None
    evidence = CombineEvidence(
        kind="answer",
        reducer="vote",
        operators=["last_line@1", "text@1", "mode@1", "first_holder@1"],
        members=[
            CombineAnswerRow(
                member_id="member_1", raw="M", value="m", status="answered", reason=None, signals={}
            ),
            CombineAnswerRow(
                member_id="member_2",
                raw=None,
                value=None,
                status="excluded",
                reason="not_selected",
                signals={},
            ),
        ],
        chosen=["member_1"],
        built=False,
        tie=False,
        result=CombineResult(member_id="member_1", value="m", status="answered", reason=None),
        dropped=0,
        finish_reason="stop",
        agreement=1.0,
        skipped=["member_2"],
    )
    operations = (
        operation("gate_1", picked),
        operation("gate_2", skipped, output=""),
        CaseOperation("op_synthesis_1", "M", "stop", None, combine=evidence),
    )
    item = case(1, operations)
    candidate = gate_candidate(recipe, (item,))

    branches = branch_sections_html(candidate, item)
    assert "not run · then · not selected" in branches
    combine = combine_view.combine_sections_html(candidate, item)
    assert "not_selected · not selected by sel_1" in combine

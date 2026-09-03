"""Contract tests for the report-sourced tape (OME-978).

These run in the DEFAULT test lane — no docker, no subprocesses, no report file.
They pin the pure seams `fixtures/report_tape.py` gives the bless tool's `--report`
mode, because a tape that mis-parses one case or attaches the wrong payload would
freeze a WRONG fusion golden and every later CI replay would defend the wrong
number:

- a saved SDK report parses into a tape (member/synthesis payloads per scored case,
  judge verdicts per (case, criterion), statuses for every case — failed included),
- a captured request body is matched to exactly one payload — or refused loudly;
  a failed case's body is a deliberate SKIP, never an error and never a payload,
- fabricated cache payloads are deterministic and carry the report's text verbatim,
- the fusion golden round-trips through ``GoldenReport`` and old single-model
  goldens (no ``kind`` field) stay valid unchanged.
"""

from __future__ import annotations

import json

import pytest
from fixtures.report_tape import (
    BodyMatch,
    BodySkip,
    ReportTape,
    body_strings,
    fabricate_payload,
    match_body,
    parse_report,
)
from harness.goldens import GoldenReport, build_candidate

# -- a synthetic report shaped exactly like screamingface.report.v1 ------------------

_MEMBER_1 = "openrouter/a/alpha"
_MEMBER_2 = "openrouter/b/beta"
_SYNTH = "openrouter/c/gamma"
_JUDGE = "openrouter/j/judge"


def _case_input(question: str) -> str:
    return json.dumps(
        {
            "schema": "screamingface.candidate-input.v1",
            "messages": [
                {"role": "user", "content": "earlier turn"},
                {"role": "assistant", "content": "earlier answer"},
                {"role": "user", "content": question},
            ],
        }
    )


def _check(criterion_id: str, label: str, raw_output: str) -> dict:
    return {
        "type": "rubric_item",
        "id": criterion_id,
        "label": label,
        "evidence": [
            {
                "sequence": 1,
                "producer": {"type": "model", "id": _JUDGE},
                "valid": True,
                "raw_output": raw_output,
                "metadata": None,
                "outcome": "met",
                "explanation": "…",
            }
        ],
        "metadata": None,
        "outcome": "met",
    }


def _scored_case(case_id: int, question: str, *, checks: list[dict]) -> dict:
    return {
        "status": "scored",
        "case_id": case_id,
        "input": _case_input(question),
        "output": f"synthesis for case {case_id}",
        "finish_reason": "stop",
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": 1,
        "grade": {
            "method": "rubric",
            "score": 0.5,
            "metrics": {"judged": len(checks), "expected": len(checks), "invalid_replies": 0},
            "checks": checks,
        },
        "failures": None,
        "metadata": None,
        "operations": [
            {
                "operation_id": "op_model_1",
                "output": f"alpha answer {case_id}",
                "finish_reason": "stop",
            },
            {
                "operation_id": "op_model_2",
                "output": f"beta answer {case_id}",
                "finish_reason": "stop",
            },
            {
                "operation_id": "op_synthesis_1",
                "output": f"synthesis for case {case_id}",
                "finish_reason": "stop",
            },
        ],
    }


def _failed_case(case_id: int, question: str) -> dict:
    # WHY no "operations": the real report omits the key entirely on failed cases —
    # the parser must treat that as "nothing recorded", not a shape error.
    return {
        "status": "failed",
        "case_id": case_id,
        "input": _case_input(question),
        "output": None,
        "finish_reason": None,
        "refusal": None,
        "stop_reason": None,
        "rounds_executed": 0,
        "grade": {"method": "rubric", "score": None, "metrics": {}, "checks": []},
        "failures": [{"stage": "candidate", "code": "x", "message": "boom"}],
        "metadata": None,
    }


def _report(cases: list[dict] | None = None) -> dict:
    if cases is None:
        cases = [
            _scored_case(
                1,
                "How to treat a paper cut?",
                checks=[
                    _check("1", "mentions washing the wound", "judge verdict 1-1"),
                    _check("2", "advises seeing a doctor if infected", "judge verdict 1-2"),
                ],
            ),
            _scored_case(
                2,
                "Is coffee dehydrating?",
                # INVARIANT: this label REPEATS across cases — the rubric reuses
                # criteria, so matching must disambiguate by case first.
                checks=[_check("1", "mentions washing the wound", "judge verdict 2-1")],
            ),
            _failed_case(3, "What is a safe aspirin dose?"),
        ]
    return {
        "schema": "screamingface.report.v1",
        "started_at": "2026-08-19T00:00:00Z",
        "completed_at": "2026-08-19T01:00:00Z",
        "benchmark": {
            "id": "healthbench-worst30",
            "revision": "39cfd96b068f7230",
            "case_count": len(cases),
        },
        "candidates": [
            {
                "benchmark": "healthbench-worst30",
                "run_id": "run-x",
                "started_at": "2026-08-19T00:00:00Z",
                "completed_at": "2026-08-19T01:00:00Z",
                "name": "best_open_source",
                "kind": "fusion",
                "url4": "(candidate:0.0:'…')",
                "models": [_MEMBER_1, _MEMBER_2, _SYNTH],
                "operations": [
                    {
                        "id": "op_model_1",
                        "kind": "model",
                        "label": "alpha answer",
                        "depends_on": [],
                    },
                    {"id": "op_model_2", "kind": "model", "label": "beta answer", "depends_on": []},
                    {
                        "id": "op_synthesis_1",
                        "kind": "synthesis",
                        "label": "best_open_source synthesis",
                        "depends_on": ["op_model_1", "op_model_2"],
                    },
                ],
                "score": 0.25,
                "coverage": 0.6667,
                "metrics": {},
                "cases": cases,
                "members": [
                    {
                        "operation_id": "op_model_1",
                        "name": "alpha",
                        "kind": "model",
                        "models": [_MEMBER_1],
                    },
                    {
                        "operation_id": "op_model_2",
                        "name": "beta",
                        "kind": "model",
                        "models": [_MEMBER_2],
                    },
                ],
                "failures": [],
            }
        ],
        "usage": {},
    }


def _tape() -> ReportTape:
    return parse_report(_report())


# -- parsing -------------------------------------------------------------------------


def test_parse_report_reads_the_fusion_lineup_and_board() -> None:
    tape = _tape()
    assert tape.board == "healthbench-worst30"
    assert tape.recipe == "best_open_source"
    assert tape.member_routes == (_MEMBER_1, _MEMBER_2)
    assert tape.synthesizer_route == _SYNTH
    assert tape.judge_route == _JUDGE
    assert tape.expected_score == 0.25
    assert tape.expected_coverage == 0.6667


def test_parse_report_keeps_every_case_status_failed_included() -> None:
    # The golden pins failed cases too — the tape must carry them even though it
    # holds no payloads for them.
    tape = _tape()
    assert tape.case_statuses == {"1": "scored", "2": "scored", "3": "failed"}


def test_parse_report_maps_member_synthesis_and_judge_payloads() -> None:
    tape = _tape()
    case = tape.cases_by_id["1"]
    assert case.member_outputs[_MEMBER_1] == ("alpha answer 1", "stop")
    assert case.member_outputs[_MEMBER_2] == ("beta answer 1", "stop")
    assert case.synthesis_output == ("synthesis for case 1", "stop")
    assert [check.raw_output for check in case.checks] == [
        "judge verdict 1-1",
        "judge verdict 1-2",
    ]


def test_parse_report_refuses_multiple_candidates() -> None:
    report = _report()
    report["candidates"].append(report["candidates"][0])
    with pytest.raises(ValueError, match="exactly one candidate"):
        parse_report(report)


def test_parse_report_refuses_a_non_fusion_candidate() -> None:
    report = _report()
    report["candidates"][0]["kind"] = "model"
    with pytest.raises(ValueError, match="fusion"):
        parse_report(report)


def test_parse_report_refuses_invalid_judge_replies() -> None:
    # invalid_replies > 0 means the run retried a judge; the report keeps only the
    # final reply, so a tape built from it could not serve the retry sequence.
    report = _report()
    report["candidates"][0]["cases"][0]["grade"]["metrics"]["invalid_replies"] = 1
    with pytest.raises(ValueError, match="invalid_replies"):
        parse_report(report)


def test_parse_report_refuses_duplicate_member_routes() -> None:
    report = _report()
    report["candidates"][0]["members"][1]["models"] = [_MEMBER_1]
    with pytest.raises(ValueError, match="distinct"):
        parse_report(report)


def test_parse_report_accepts_repeated_member_answers_across_cases() -> None:
    # Real runs repeat member texts (9 cases shared one refusal string in the
    # Aug-19 report). Synthesis matching identifies a case by its FULL member-output
    # set, so repeats are fine as long as no two cases share the whole set.
    cases = [
        _scored_case(1, "question one", checks=[_check("1", "l1", "v1")]),
        _scored_case(2, "question two", checks=[_check("1", "l1", "v2")]),
    ]
    shared_refusal = "I'm sorry, but I can't help with that."
    for case in cases:
        case["operations"][0]["output"] = shared_refusal
    tape = parse_report(_report(cases))
    assert tape.cases_by_id["1"].member_outputs[_MEMBER_1] == (shared_refusal, "stop")
    assert tape.cases_by_id["2"].member_outputs[_MEMBER_1] == (shared_refusal, "stop")


def test_parse_report_refuses_two_cases_sharing_their_whole_member_output_set() -> None:
    # If EVERY member answer of two cases is identical, a synthesis body could not
    # be attributed to either case — that ambiguity must refuse at parse time.
    cases = [
        _scored_case(1, "question one", checks=[_check("1", "l1", "v1")]),
        _scored_case(2, "question two", checks=[_check("1", "l1", "v2")]),
    ]
    for slot in (0, 1):
        cases[1]["operations"][slot]["output"] = cases[0]["operations"][slot]["output"]
    with pytest.raises(ValueError, match="member"):
        parse_report(_report(cases))


def test_parse_report_refuses_duplicate_case_questions() -> None:
    # Two cases with the same identifying text could not be told apart when a
    # captured body arrives — guessing would attach the wrong answers.
    cases = [
        _scored_case(1, "same question", checks=[_check("1", "l", "v1")]),
        _scored_case(2, "same question", checks=[_check("1", "l", "v2")]),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        parse_report(_report(cases))


# -- body matching -------------------------------------------------------------------


def _body(model: str, text: str) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer accurately."},
            {"role": "user", "content": text},
        ],
        "max_tokens": 16384,
    }


def test_body_strings_collects_every_nested_string() -> None:
    body = {"a": "one", "b": {"c": ["two", {"d": "three"}]}, "e": 5}
    assert set(body_strings(body)) >= {"one", "two", "three"}


def test_match_body_serves_a_member_request() -> None:
    tape = _tape()
    match = match_body(tape, _body(_MEMBER_1, "…wrapped… How to treat a paper cut? …"))
    assert isinstance(match, BodyMatch)
    assert match.role == "member"
    assert match.case_id == "1"
    assert match.content == "alpha answer 1"
    assert match.finish_reason == "stop"
    assert match.model == _MEMBER_1


def test_match_body_serves_a_synthesis_request_by_member_outputs() -> None:
    # The synthesis prompt embeds the member answers, not necessarily the question —
    # the member outputs are what identify the case.
    tape = _tape()
    match = match_body(tape, _body(_SYNTH, "panel: alpha answer 2 // beta answer 2 // synthesize"))
    assert isinstance(match, BodyMatch)
    assert match.role == "synthesis"
    assert match.case_id == "2"
    assert match.content == "synthesis for case 2"


def test_match_body_serves_a_synthesis_request_with_json_escaped_answers() -> None:
    # INVARIANT: url4 renders a struct q= by json.dumps-ing the whole object into
    # ONE string (url4.dag.nodes.StructNode), so member answers reach the synthesis
    # prompt JSON-ESCAPED — newlines as \n, quotes as \", non-ASCII as \uXXXX.
    # Matching must find the recorded text in that spelling too.
    cases = [
        _scored_case(1, "question one", checks=[_check("1", "l1", "v1")]),
        _scored_case(2, "question two", checks=[_check("1", "l1", "v2")]),
    ]
    cases[0]["operations"][0]["output"] = 'line one\nline "two" — it’s tricky'
    tape = parse_report(_report(cases))
    rendered_struct = json.dumps(
        {
            "input": "…",
            "outputs": {
                "member_1": 'line one\nline "two" — it’s tricky',
                "member_2": "beta answer 1",
            },
        }
    )
    match = match_body(tape, _body(_SYNTH, f"Produce the final answer.\n\n{rendered_struct}"))
    assert isinstance(match, BodyMatch)
    assert match.case_id == "1"
    assert match.content == "synthesis for case 1"


def test_match_body_serves_a_judge_request_case_first_then_criterion() -> None:
    # INVARIANT: the criterion label repeats across cases (real rubrics reuse
    # criteria) — the case is pinned by the synthesized answer FIRST, and only that
    # case's checks are searched for the label.
    tape = _tape()
    match = match_body(
        tape,
        _body(_JUDGE, "grade: synthesis for case 2 -- criterion: mentions washing the wound"),
    )
    assert isinstance(match, BodyMatch)
    assert match.role == "judge"
    assert match.case_id == "2"
    assert match.content == "judge verdict 2-1"
    assert match.model == _JUDGE


def test_match_body_skips_a_failed_cases_member_request() -> None:
    # The real run recorded nothing for this case; the replay must keep failing it.
    # A SKIP (not an error) lets the loop converge with the hole intact.
    tape = _tape()
    outcome = match_body(tape, _body(_MEMBER_1, "…What is a safe aspirin dose?…"))
    assert isinstance(outcome, BodySkip)
    assert "failed" in outcome.reason


def test_match_body_refuses_an_unknown_model_route() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        match_body(_tape(), _body("openrouter/x/stranger", "How to treat a paper cut?"))


def test_match_body_refuses_an_unmatchable_member_request() -> None:
    with pytest.raises(ValueError, match="no case"):
        match_body(_tape(), _body(_MEMBER_1, "text that matches nothing"))


def test_match_body_refuses_a_judge_request_with_an_unknown_criterion() -> None:
    with pytest.raises(ValueError, match="criterion"):
        match_body(_tape(), _body(_JUDGE, "grade: synthesis for case 2 -- criterion: novel"))


# -- payload fabrication -------------------------------------------------------------


def test_fabricate_payload_is_deterministic_and_carries_the_text_verbatim() -> None:
    a = fabricate_payload(model=_MEMBER_1, content="two\nlines", finish_reason="stop")
    b = fabricate_payload(model=_MEMBER_1, content="two\nlines", finish_reason="stop")
    assert a == b
    parsed = json.loads(a)
    assert parsed["choices"][0]["message"]["content"] == "two\nlines"
    assert parsed["choices"][0]["finish_reason"] == "stop"
    assert parsed["model"] == _MEMBER_1


# -- fusion goldens ------------------------------------------------------------------


def _fusion_golden_document() -> dict:
    return {
        "schema": "screamingface.golden-report.v1",
        "board": "healthbench-worst30",
        "revision": "39cfd96b068f7230",
        "kind": "fusion",
        "recipe": "best_open_source",
        "models": [_MEMBER_1, _MEMBER_2],
        "synthesizer": _SYNTH,
        "limit": None,
        "expression_sha": "a" * 64,
        "final_score": "-0.091",
        "case_count": 2,
        "gradeable_count": 1,
        "case_statuses": {"1": "scored", "3": "failed"},
        # OME-1094: a failed case must name its reason or the golden refuses to load.
        "case_failures": {"3": [{"stage": "grading", "code": "case_error"}]},
    }


def test_golden_report_round_trips_a_fusion_golden() -> None:
    golden = GoldenReport.model_validate(_fusion_golden_document())
    assert golden.kind == "fusion"
    assert golden.recipe == "best_open_source"
    assert golden.models == (_MEMBER_1, _MEMBER_2)
    assert golden.synthesizer == _SYNTH


def test_golden_report_defaults_to_single_model_kind() -> None:
    # INVARIANT: every golden blessed before OME-978 has no `kind` field and must
    # keep validating exactly as before — this is the backward-compat contract.
    document = _fusion_golden_document()
    for fusion_only in ("kind", "recipe", "synthesizer"):
        document.pop(fusion_only)
    document["models"] = [_MEMBER_1]
    golden = GoldenReport.model_validate(document)
    assert golden.kind == "model"
    assert golden.recipe is None
    assert golden.synthesizer is None


@pytest.mark.parametrize(
    "strip",
    ["recipe", "synthesizer"],
)
def test_golden_report_refuses_a_fusion_golden_missing_its_lineup(strip: str) -> None:
    document = _fusion_golden_document()
    document[strip] = None
    with pytest.raises(ValueError, match=strip):
        GoldenReport.model_validate(document)


def test_golden_report_refuses_a_fusion_golden_with_one_member() -> None:
    document = _fusion_golden_document()
    document["models"] = [_MEMBER_1]
    with pytest.raises(ValueError, match="member"):
        GoldenReport.model_validate(document)


# -- candidate building --------------------------------------------------------------


def test_build_candidate_builds_the_fusion_recipe() -> None:
    import screamingface as sf

    golden = GoldenReport.model_validate(_fusion_golden_document())
    candidate = build_candidate(golden)
    assert isinstance(candidate, sf.Fusion)
    assert candidate.name == "best_open_source"
    assert [member.name for member in candidate.members] == ["alpha", "beta"]
    members = [member for member in candidate.members if isinstance(member, sf.Model)]
    assert tuple(member.model for member in members) == (_MEMBER_1, _MEMBER_2)
    assert isinstance(candidate.synthesizer, sf.Model)
    assert candidate.synthesizer.model == _SYNTH


def test_build_candidate_keeps_the_single_model_path() -> None:
    import screamingface as sf

    document = _fusion_golden_document()
    for fusion_only in ("kind", "recipe", "synthesizer"):
        document.pop(fusion_only)
    document["models"] = [_MEMBER_1]
    candidate = build_candidate(GoldenReport.model_validate(document))
    assert isinstance(candidate, sf.Model)
    assert candidate.model == _MEMBER_1

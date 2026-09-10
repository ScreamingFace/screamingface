"""Contract tests for the fresh-dump bless path and the corrective-loop golden (OME-1098).

Default test lane — no docker, no keys, no dump. Two additions are pinned here:

- ``kind: "corrective_loop"`` goldens: unlike a fusion golden (route names only —
  report mode re-keys, so request bytes never need to match the recording), a
  fresh-dump replay must render BYTE-IDENTICAL requests to hit the recorded cache
  keys, so the golden carries the full member/judge specs (route + prompt + params)
  and ``build_candidate`` reconstructs the exact ``sf.CorrectiveLoop``.
- the fresh-dump bless's pure seams: the candidate-spec file and the saved SDK
  report parse into the replay inputs and the expected outcome, refusing loudly on
  every ambiguity instead of blessing a wrong golden.
"""

from __future__ import annotations

import pytest
from fixtures.slice_snapshot import (
    author_golden,
    parse_candidate_spec,
    parse_fresh_report,
)
from harness.goldens import GoldenReport, build_candidate

_MEMBER_1 = "openrouter/mistralai/ministral-3b-2512"
_MEMBER_2 = "openrouter/microsoft/phi-4"
_JUDGE = "openrouter/deepseek/deepseek-v4-flash"
_ANSWER_PROMPT = "Answer the request accurately and completely."
_PARAMS = {"max_tokens": 8192, "temperature": 0.0}
_SHA = "0" * 64


def _member_specs() -> list[dict[str, object]]:
    return [
        {"model": _MEMBER_1, "prompt": _ANSWER_PROMPT, "params": _PARAMS},
        {"model": _MEMBER_2, "prompt": _ANSWER_PROMPT, "params": _PARAMS},
    ]


def _judge_spec() -> dict[str, object]:
    return {"model": _JUDGE, "prompt": None, "params": _PARAMS}


def _loop_golden_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": "screamingface.golden-report.v1",
        "board": "ifeval",
        "revision": "ifeval-2026-09",
        "kind": "corrective_loop",
        "models": [_MEMBER_1, _MEMBER_2],
        "member_specs": _member_specs(),
        "judge_spec": _judge_spec(),
        "max_rounds": 3,
        "limit": 50,
        "expression_sha": _SHA,
        "final_score": "0.75",
        "case_count": 2,
        "gradeable_count": 1,
        "case_statuses": {"case_1": "scored", "case_2": "failed"},
        "case_failures": {"case_2": [{"stage": "grading", "code": "incomplete_verdicts"}]},
    }
    document.update(overrides)
    return document


# -- the corrective_loop golden kind -------------------------------------------------


def test_a_corrective_loop_golden_round_trips() -> None:
    golden = GoldenReport.model_validate(_loop_golden_document())

    assert golden.kind == "corrective_loop"
    assert tuple(spec.model for spec in golden.member_specs) == (_MEMBER_1, _MEMBER_2)
    assert golden.member_specs[0].prompt == _ANSWER_PROMPT
    assert golden.member_specs[0].params == _PARAMS
    assert golden.judge_spec is not None and golden.judge_spec.model == _JUDGE
    assert golden.max_rounds == 3
    assert golden.limit == 50


def test_a_corrective_loop_golden_requires_its_judge() -> None:
    with pytest.raises(Exception, match="judge"):
        GoldenReport.model_validate(_loop_golden_document(judge_spec=None))


def test_a_corrective_loop_golden_requires_max_rounds() -> None:
    with pytest.raises(Exception, match="max_rounds"):
        GoldenReport.model_validate(_loop_golden_document(max_rounds=None))


def test_a_corrective_loop_golden_requires_member_specs() -> None:
    with pytest.raises(Exception, match="member"):
        GoldenReport.model_validate(_loop_golden_document(member_specs=[]))


def test_models_must_mirror_the_member_spec_routes() -> None:
    # INVARIANT: `models` stays meaningful for every reader that predates the loop
    # kind, so it must spell exactly the member routes, in order.
    with pytest.raises(Exception, match="models"):
        GoldenReport.model_validate(_loop_golden_document(models=[_MEMBER_2, _MEMBER_1]))


def test_loop_fields_are_refused_on_other_kinds() -> None:
    # A model golden that smuggles in loop fields is a confused file, not a golden.
    document = _loop_golden_document(kind="model", models=[_MEMBER_1])
    with pytest.raises(Exception, match="corrective_loop"):
        GoldenReport.model_validate(document)


def test_build_candidate_builds_the_corrective_loop() -> None:
    import screamingface as sf

    golden = GoldenReport.model_validate(_loop_golden_document())
    candidate = build_candidate(golden)

    assert isinstance(candidate, sf.CorrectiveLoop)
    members = [member for member in candidate.members if isinstance(member, sf.Model)]
    assert tuple(member.model for member in members) == (_MEMBER_1, _MEMBER_2)
    # The specs' prompts/params must survive: they render into the request bytes
    # the recorded cache keys were computed from.
    assert members[0].prompt == _ANSWER_PROMPT
    assert dict(members[0].params) == _PARAMS
    assert isinstance(candidate.judge, sf.Model)
    assert candidate.judge.model == _JUDGE
    assert candidate.max_rounds == 3


# -- author_golden for the loop kind -------------------------------------------------


def test_author_golden_writes_the_corrective_loop_lineup() -> None:
    golden = author_golden(
        board="ifeval",
        revision="ifeval-2026-09",
        kind="corrective_loop",
        member_specs=_member_specs(),
        judge_spec=_judge_spec(),
        max_rounds=3,
        limit=50,
        rendered_url4="url4://ifeval/loop",
        final_score=0.75,
        case_statuses={"case_1": "scored", "case_2": "failed"},
        case_failures={"case_2": [{"stage": "grading", "code": "incomplete_verdicts"}]},
    )

    assert golden["kind"] == "corrective_loop"
    assert golden["models"] == [_MEMBER_1, _MEMBER_2]
    assert golden["member_specs"] == _member_specs()
    assert golden["judge_spec"] == _judge_spec()
    assert golden["max_rounds"] == 3
    # No fusion keys on a loop golden — each kind keeps its own document shape.
    assert "recipe" not in golden
    assert "synthesizer" not in golden
    GoldenReport.model_validate(golden)


# -- the candidate-spec file ---------------------------------------------------------


def _candidate_spec() -> dict[str, object]:
    return {
        "kind": "corrective_loop",
        "members": _member_specs(),
        "judge": _judge_spec(),
        "max_rounds": 3,
    }


def test_parse_candidate_spec_builds_the_replay_inputs() -> None:
    member_specs, judge_spec, max_rounds = parse_candidate_spec(_candidate_spec())

    assert tuple(spec.model for spec in member_specs) == (_MEMBER_1, _MEMBER_2)
    assert member_specs[1].prompt == _ANSWER_PROMPT
    assert judge_spec.model == _JUDGE
    assert max_rounds == 3


def test_parse_candidate_spec_refuses_other_kinds() -> None:
    spec = _candidate_spec()
    spec["kind"] = "fusion"
    with pytest.raises(SystemExit, match="corrective_loop"):
        parse_candidate_spec(spec)


def test_parse_candidate_spec_refuses_a_malformed_member() -> None:
    spec = _candidate_spec()
    spec["members"] = [{"prompt": "no route"}]
    with pytest.raises(SystemExit, match="member"):
        parse_candidate_spec(spec)


# -- the saved SDK report as the expected outcome ------------------------------------


def _fresh_report() -> dict[str, object]:
    return {
        "schema": "screamingface.report.v1",
        "benchmark": {"id": "ifeval", "revision": "ifeval-2026-09"},
        "candidates": [
            {
                "kind": "corrective_loop",
                "name": "ministral-3b-2512+phi-4",
                "url4": "url4://ifeval/recorded-expression",
                "score": 0.75,
                "coverage": 0.5,
                "cases": [
                    {"case_id": "case_1", "status": "scored"},
                    {"case_id": "case_2", "status": "failed"},
                ],
            }
        ],
    }


def test_parse_fresh_report_reads_the_recorded_outcome() -> None:
    facts = parse_fresh_report(_fresh_report())

    assert facts.board == "ifeval"
    assert facts.kind == "corrective_loop"
    assert facts.rendered_url4 == "url4://ifeval/recorded-expression"
    assert facts.expected_score == 0.75
    assert facts.expected_coverage == 0.5
    assert facts.case_statuses == {"case_1": "scored", "case_2": "failed"}


def test_parse_fresh_report_refuses_an_unknown_schema() -> None:
    report = _fresh_report()
    report["schema"] = "somebody.else.v9"
    with pytest.raises(SystemExit, match="schema"):
        parse_fresh_report(report)


def test_parse_fresh_report_refuses_multiple_candidates() -> None:
    report = _fresh_report()
    report["candidates"] = [report["candidates"][0]] * 2  # type: ignore[index]
    with pytest.raises(SystemExit, match="candidate"):
        parse_fresh_report(report)


# -- review findings (PR #870): report authority + loop-golden refresh ---------------


def test_report_backed_bless_refuses_expect_flag_overrides() -> None:
    # INVARIANT (review finding, blocking): in a report-backed mode the saved report
    # is the ONLY outcome authority — an --expect-score flag must never be able to
    # bless a replay that contradicts the report.
    import argparse

    from fixtures.slice_snapshot import pin_report_expectations

    args = argparse.Namespace(expect_score="0.8", expect_coverage=None)
    with pytest.raises(SystemExit, match="authority"):
        pin_report_expectations(args, score=0.9, coverage=0.96)

    args = argparse.Namespace(expect_score=None, expect_coverage="0.5")
    with pytest.raises(SystemExit, match="authority"):
        pin_report_expectations(args, score=0.9, coverage=0.96)


def test_report_backed_bless_pins_the_reports_own_outcome() -> None:
    import argparse

    from fixtures.slice_snapshot import pin_report_expectations

    args = argparse.Namespace(expect_score=None, expect_coverage=None)
    pin_report_expectations(args, score=0.9375, coverage=0.96)

    assert args.expect_score == "0.9375"
    assert args.expect_coverage == "0.96"


def test_replay_input_fields_carries_the_loop_spec_through_a_refresh() -> None:
    # INVARIANT (review finding): refreshing a corrective_loop golden must re-author
    # it with its full member/judge specs — dropping them would refuse validation
    # after the replay already ran.
    from fixtures.slice_snapshot import replay_input_fields

    golden = GoldenReport.model_validate(_loop_golden_document())
    fields = replay_input_fields(golden)

    authored = author_golden(
        **fields,
        board="ifeval",
        revision="ifeval-2026-09",
        limit=50,
        rendered_url4="url4://ifeval/loop",
        final_score=0.75,
        case_statuses={"case_1": "scored", "case_2": "failed"},
        case_failures={"case_2": [{"stage": "grading", "code": "incomplete_verdicts"}]},
    )

    assert authored["kind"] == "corrective_loop"
    assert authored["member_specs"] == _member_specs()
    assert authored["judge_spec"] == _judge_spec()
    assert authored["max_rounds"] == 3


def test_refresh_and_fresh_dump_flags_refuse_each_other() -> None:
    # INVARIANT (review finding, blocking): boolean mode flags dodge the
    # `is not None` exclusion guard, so the pair must refuse explicitly —
    # silently ignoring the fresh recording is the one unacceptable outcome.
    import argparse

    from fixtures.slice_snapshot import _run_gated_bless

    args = argparse.Namespace(refresh_golden=True, dump_fresh=True, board="ifeval")
    with pytest.raises(SystemExit, match="cannot be combined"):
        _run_gated_bless(args)


def test_fusion_fields_are_refused_on_a_loop_golden() -> None:
    # The mirror of test_loop_fields_are_refused_on_other_kinds: recipe/synthesizer
    # on a corrective_loop golden would be silently dead fields, not inputs.
    with pytest.raises(Exception, match="corrective_loop"):
        GoldenReport.model_validate(_loop_golden_document(recipe="open_panel"))
    with pytest.raises(Exception, match="corrective_loop"):
        GoldenReport.model_validate(_loop_golden_document(synthesizer=_JUDGE))

"""OME-1031: exact derived accounting, independent of benchmark scoring."""

from decimal import Decimal
from inspect import signature

import pytest
from test_report_panel import candidate, case

import screamingface as sf
from screamingface.accounting import accounting_breakdown, member_usage
from screamingface.case_result import CaseOperation
from screamingface.operation import OperationInfo


def replace(value, **changes):
    fields = {name: getattr(value, name) for name in signature(type(value)).parameters}
    return type(value)(**(fields | changes))


def accounting(cost: str | None = "0.1", **changes):
    return replace(
        sf.OperationAccounting(
            provider="provider",
            request_model="provider/model",
            response_model="model",
            usage=sf.Usage(input_tokens=10, output_tokens=4, cost_usd=cost),
            provider_latency_ms=20,
            provider_attempts=1,
            cache=sf.OperationCache(hits=0, misses=1, bypasses=0, unknown=0),
        ),
        **changes,
    )


def result(*, missing=False, root: str | None = "0.5"):
    evidence = sf.Evidence(
        sequence=1,
        producer=sf.EvidenceProducer(type="model", id="judge"),
        valid=True,
        raw_output="MET",
        outcome="MET",
        accounting=accounting("0.2"),
    )
    check = sf.Check(type="rubric", id="check", label="Correct", evidence=[evidence])
    c = replace(
        case(checks=(check,)),
        operations=[CaseOperation("op", "answer", "stop", None if missing else accounting())],
    )
    return replace(
        candidate("Example", 0.0, cases=(c,)), usage=sf.Usage(cost_usd=root), run_cost_status=None
    )


def test_grouping_and_remainder_do_not_change_report():
    c = result()
    original = c.to_dict()
    view = c.accounting
    assert view == accounting_breakdown(c)
    assert view.unattributed_cost_usd == Decimal("0.2")
    assert view.by_stage["generation"].usage.cost_usd == Decimal("0.1")
    assert view.by_stage["grading"].usage.cost_usd == Decimal("0.2")
    assert view.by_case[1].usage.cost_usd == Decimal("0.3")
    assert view.by_model["provider/model"].calls == 2
    assert view.by_operation[("generation", "op")].provider_latency_ms == 20
    assert view.by_case[1].usage.reasoning_tokens is None
    assert c.to_dict() == original
    assert "accounting" not in original


def test_missing_record_keeps_group_unknown_but_known_cost_is_subtracted():
    view = result(missing=True).accounting
    assert view.by_stage["generation"].usage.cost_usd is None
    assert view.by_case[1].usage.cost_usd is None
    assert view.by_case[1].calls is None
    assert view.unattributed_cost_usd == Decimal("0.3")


def test_unpriced_record_or_unknown_root_cannot_produce_remainder():
    c = result()
    op = replace(c.cases[0].operations[0], accounting=accounting(None))
    c = replace(c, cases=[replace(c.cases[0], operations=[op])])
    assert c.accounting.unattributed_cost_usd is None
    assert result(root=None).accounting.unattributed_cost_usd is None


def test_negative_remainder_disables_breakdown_without_breaking_report(caplog):
    c = result(root="0.01")
    assert not c.accounting.consistent
    assert c.accounting.rows == ()
    assert c.accounting.unattributed_cost_usd is None
    assert "accounting" in caplog.text
    assert c.score == 0.0


def test_cache_hit_is_zero_not_unknown():
    c = result()
    cached = accounting(
        "0",
        provider_latency_ms=0,
        provider_attempts=0,
        cache=sf.OperationCache(hits=1, misses=0, bypasses=0, unknown=0),
    )
    c = replace(
        c, cases=[replace(c.cases[0], operations=[CaseOperation("op", "answer", "stop", cached)])]
    )
    row = c.accounting.by_stage["generation"]
    assert row.calls == 1
    assert row.cache.hits == 1
    assert row.provider_attempts == 0
    assert row.usage.cost_usd == 0


def test_member_usage_requires_one_record_for_every_case():
    c = result()
    usage = member_usage(c.cases, "op")
    assert usage is not None
    assert usage.cost_usd == Decimal("0.1")
    assert member_usage(c.cases, "absent") is None
    assert member_usage(result(missing=True).cases, "op") is None
    missing_case = replace(c.cases[0], case_id=2, operations=None)
    assert member_usage([*c.cases, missing_case], "op") is None
    assert member_usage([], "op") is None


def test_synthesis_is_separate_and_member_groups_use_identity():
    c = result()
    member = sf.MemberResult(
        operation_id="op",
        name="Same label",
        kind="model",
        models=["provider/model"],
        failures=None,
        duration_ms=None,
        usage=None,
    )
    c = replace(
        c,
        kind="fusion",
        members=[member],
        operations=[
            *c.operations,
            OperationInfo(id="synth", kind="synthesis", label="Writer", depends_on=["op"]),
        ],
        cases=[
            replace(
                c.cases[0],
                operations=[
                    *c.cases[0].operations,
                    CaseOperation("synth", "final", "stop", accounting("0.1")),
                ],
            )
        ],
    )
    assert c.accounting.by_member["op"].usage.cost_usd == Decimal("0.1")
    assert c.accounting.by_stage["synthesis"].usage.cost_usd == Decimal("0.1")


def test_unknown_operation_identity_disables_unsafe_attribution():
    c = result()
    c = replace(
        c,
        cases=[
            replace(
                c.cases[0], operations=[CaseOperation("surprise", "answer", "stop", accounting())]
            )
        ],
    )
    assert not c.accounting.consistent
    assert not c.accounting.rows


def test_group_maps_are_immutable():
    with pytest.raises(TypeError):
        result().accounting.by_stage["new"] = None


def test_duplicate_operation_records_disable_breakdown_and_member_total():
    c = result()
    c = replace(
        c, cases=[replace(c.cases[0], operations=[*c.cases[0].operations, *c.cases[0].operations])]
    )
    assert not c.accounting.consistent
    assert member_usage(c.cases, "op") is None


def test_corrective_loop_candidate_work_is_not_attributed():
    c = result()
    members = [
        sf.MemberResult(
            operation_id=name,
            name=name,
            kind="model",
            models=["provider/model"],
            usage=None,
            failures=None,
            duration_ms=None,
        )
        for name in ("A", "B")
    ]
    c = replace(
        c,
        kind="corrective_loop",
        members=members,
        operations=[OperationInfo(id=name, label=name, kind="model") for name in ("A", "B")],
    )
    assert set(c.accounting.by_stage) == {"grading"}
    assert not c.accounting.by_member
    assert c.accounting.unattributed_cost_usd == Decimal("0.3")


def test_deterministic_grading_is_not_an_unknown_model_call():
    c = result()
    evidence = sf.Evidence(
        sequence=1,
        producer=sf.EvidenceProducer(type="function", id="exact"),
        valid=True,
        raw_output=True,
        outcome="MET",
    )
    check = sf.Check(type="exact", id="exact", label="Exact", evidence=[evidence])
    c = replace(c, cases=[replace(c.cases[0], grade=replace(c.cases[0].grade, checks=[check]))])
    assert set(c.accounting.by_stage) == {"generation"}


def test_partial_fields_unknown_model_and_missing_grade():
    c = result()
    value = accounting(None, request_model=None, provider_latency_ms=None, provider_attempts=None)
    c = replace(
        c, cases=[replace(c.cases[0], operations=[CaseOperation("op", "answer", "stop", value)])]
    )
    summary = c.accounting.by_model[None]
    assert summary.provider_latency_ms is None
    assert summary.provider_attempts is None
    assert summary.calls == 1


def test_missing_operations_and_empty_summary_are_unavailable():
    from screamingface.accounting import summarize

    c = result()
    c = replace(c, cases=[replace(c.cases[0], operations=None)])
    assert c.accounting.by_stage["generation"].calls is None
    assert summarize([]).calls is None


def test_zero_remainder_is_valid_and_small_costs_are_exact():
    c = result(root="0.3")
    assert c.accounting.unattributed_cost_usd == Decimal("0")


def test_non_call_operations_do_not_create_paid_rows_and_missing_grade_is_allowed():
    c = result()
    c = replace(
        c,
        operations=[
            *c.operations,
            OperationInfo(id="wrapper", kind="pipeline", label="Wrapper", depends_on=["op"]),
        ],
    )
    assert len(c.accounting.rows) == 2
    failed_case = replace(
        c.cases[0],
        grade=None,
        status="failed",
        failures=[
            sf.Failure(stage="grading", code="grading_failed", message="fixture failure", case_id=1)
        ],
    )
    c = replace(c, score=None, metrics={}, coverage=0.0, cases=[failed_case])
    assert set(c.accounting.by_stage) == {"generation"}

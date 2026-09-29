"""Missing observations cannot masquerade as complete per-model totals."""

from decimal import Decimal

import pytest
from test_accounting_breakdown import accounting, replace, result

import screamingface as sf
from screamingface.case_result import CaseOperation
from screamingface.operation import OperationInfo


def two_cases(*, declared="provider/model", member=False):
    c = result(root="0.9")
    members = []
    if member:
        members = [
            sf.MemberResult(
                operation_id="op",
                name="Member",
                kind="model",
                models=[declared],
                failures=None,
                duration_ms=None,
                usage=None,
            )
        ]
    missing = replace(
        c.cases[0],
        case_id=2,
        operations=[CaseOperation("op", "answer", "stop", None)],
    )
    return replace(
        c,
        kind="fusion" if member else "model",
        models=[declared],
        members=members,
        cases=[c.cases[0], missing],
    )


@pytest.mark.parametrize("member", [False, True])
def test_missing_observation_invalidates_only_its_declared_model(member):
    c = two_cases(member=member)
    # INVARIANT: a different complete model must remain usable when attribution is exact.
    cases = []
    for case in c.cases:
        check = case.grade.checks[0]
        evidence = replace(check.evidence[0], accounting=accounting("0.2", request_model="judge"))
        cases.append(
            replace(case, grade=replace(case.grade, checks=[replace(check, evidence=[evidence])]))
        )
    c = replace(c, cases=cases)
    original = c.to_dict()
    view = c.accounting
    summary = view.by_model["provider/model"]
    assert summary.usage.cost_usd is None
    assert summary.usage.input_tokens is None
    assert summary.calls is None
    assert summary.cache is None
    assert summary.provider_latency_ms is None
    assert summary.provider_attempts is None
    assert view.by_model["judge"].usage.cost_usd == Decimal("0.4")
    assert None not in view.by_model
    assert view.by_stage["grading"].usage.cost_usd == Decimal("0.4")
    assert c.to_dict() == original
    assert c.usage.cost_usd == Decimal("0.9")


def test_conflicting_declared_and_request_model_cannot_hide_missing_call():
    view = two_cases(declared="configured/alias").accounting
    assert view.by_model["provider/model"].usage.cost_usd is None
    assert view.by_model["provider/model"].calls is None
    assert "configured/alias" not in view.by_model
    assert view.by_model[None].usage.cost_usd is None
    with pytest.raises(TypeError):
        view.by_model["provider/model"] = None


def test_missing_synthesis_without_model_mapping_invalidates_named_groups():
    c = result()
    c = replace(
        c, operations=[*c.operations, OperationInfo(id="synth", kind="synthesis", label="Combine")]
    )
    view = c.accounting
    assert view.by_model["provider/model"].usage.cost_usd is None
    assert view.by_model[None].calls is None
    assert view.by_stage["generation"].usage.cost_usd == Decimal("0.1")


@pytest.mark.parametrize("producer", ["provider/model", "judge-alias"])
def test_missing_judge_record_never_splits_off_a_partial_model_total(producer):
    c = result(root="0.9")
    check = c.cases[0].grade.checks[0]
    present = replace(check.evidence[0], producer=sf.EvidenceProducer(type="model", id=producer))
    cases = [
        replace(
            c.cases[0],
            case_id=index,
            grade=replace(c.cases[0].grade, checks=[replace(check, evidence=[evidence])]),
        )
        for index, evidence in enumerate([present, replace(present, accounting=None)], start=1)
    ]
    view = replace(c, cases=cases).accounting
    assert view.by_model["provider/model"].usage.cost_usd is None
    assert view.by_model["provider/model"].calls is None
    assert "judge-alias" not in view.by_model
    assert view.by_stage["generation"].usage.cost_usd == Decimal("0.2")
    assert view.by_stage["grading"].usage.cost_usd is None


def test_present_accounting_with_unknown_model_invalidates_named_totals():
    c = result()
    op = CaseOperation("op", "answer", "stop", accounting(request_model=None))
    view = replace(c, cases=[replace(c.cases[0], operations=[op])]).accounting
    assert view.by_model["provider/model"].usage.cost_usd is None
    assert view.by_model[None].usage.cost_usd == Decimal("0.1")
    assert view.by_model[None].calls == 1


def test_complete_records_keep_observed_model_and_zero_cost():
    c = result()
    zero = accounting("0", request_model="cached/model")
    op = CaseOperation("op", "answer", "stop", zero)
    view = replace(c, cases=[replace(c.cases[0], operations=[op])]).accounting
    assert view.by_model["cached/model"].usage.cost_usd == 0
    assert view.by_model["provider/model"].usage.cost_usd == Decimal("0.2")
    assert "openrouter/x" not in view.by_model


def test_no_observations_still_retains_declared_model_as_unknown():
    c = two_cases()
    missing = replace(c.cases[1], case_id=1)
    view = replace(c, cases=[missing]).accounting
    assert view.by_model["provider/model"].usage.cost_usd is None
    assert None not in view.by_model


def test_composite_member_does_not_supply_a_model_mapping():
    c = two_cases(member=True)
    member = replace(c.members[0], kind="pipeline", models=["provider/model", "other/model"])
    view = replace(c, members=[member]).accounting
    assert view.by_model["provider/model"].usage.cost_usd is None
    assert None in view.by_model

"""Compact accounting preserves exact truth without retaining Case outputs."""

import tracemalloc
from decimal import Decimal
from operator import setitem

import pytest
from test_accounting_breakdown import accounting, replace, result

import screamingface as sf
from screamingface._results.cases import DiskCases
from screamingface.accounting import _declared_judge_models


@pytest.mark.parametrize(
    "missing,root", [(False, "0.5"), (True, "0.5"), (False, None), (False, "0.01")]
)
def test_context_matches_public_accounting(missing, root):
    from screamingface.accounting import _accounting_context

    candidate = result(missing=missing, root=root)
    expected = candidate.accounting
    original = candidate.to_dict()
    context = _accounting_context(candidate)
    assert context.consistent == expected.consistent
    assert context.unattributed_cost_usd == expected.unattributed_cost_usd
    assert not hasattr(context, "rows")
    assert candidate.to_dict() == original
    if context.consistent:
        with pytest.raises(TypeError):
            setitem(getattr(context, "operation_models"), "bad", "model")


def test_unknown_observed_cost_preserves_unknown_remainder():
    from screamingface.accounting import _accounting_context

    candidate = result()
    op = replace(candidate.cases[0].operations[0], accounting=accounting(None))
    candidate = replace(candidate, cases=[replace(candidate.cases[0], operations=[op])])
    assert _accounting_context(candidate).unattributed_cost_usd is None


class GeneratedCases(DiskCases):
    def __init__(self, prototype, count):
        self.prototype = prototype
        self._count = count
        self.gradeable = count

    def __iter__(self):
        check = self.prototype.grade.checks[0]
        for index in range(self._count):
            evidence = replace(check.evidence[0], raw_output=str(index) + "x" * 131072)
            yield replace(
                self.prototype,
                case_id=index,
                grade=replace(self.prototype.grade, checks=[replace(check, evidence=[evidence])]),
            )


def test_judge_attribution_does_not_retain_outputs_across_cases():
    source = result()
    candidate = replace(source, cases=GeneratedCases(source.cases[0], 200))
    tracemalloc.start()
    try:
        assert _declared_judge_models(candidate) == {}
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2_000_000


def test_context_streams_large_evidence_and_exact_cost():
    from screamingface.accounting import _accounting_context

    source = result()
    candidate = replace(
        source, cases=GeneratedCases(source.cases[0], 200), usage=sf.Usage(cost_usd="100")
    )
    tracemalloc.start()
    try:
        context = _accounting_context(candidate)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert context.consistent
    assert context.unattributed_cost_usd == Decimal("40")
    assert peak < 2_000_000


def test_disclosures_preserve_exact_html_without_full_breakdown(monkeypatch):
    from screamingface._ui.accounting_view import _activity, case_accounting, run_accounting_note

    candidate = result()
    expected = {1: "".join(_activity(row) for row in candidate.accounting.rows)}
    note = run_accounting_note(candidate)

    def forbidden(self):
        raise AssertionError("disclosure materialized the full AccountingBreakdown")

    monkeypatch.setattr(sf.CandidateResult, "accounting", property(forbidden))
    assert case_accounting(candidate) == expected
    assert run_accounting_note(candidate) == note

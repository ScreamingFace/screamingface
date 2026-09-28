"""Completed report accounting is visible, escaped and available without JavaScript."""

from test_accounting_breakdown import replace, result

import screamingface as sf


def test_report_renders_breakdown_and_case_disclosures():
    c = result()
    html = sf.Report(benchmark=c.benchmark, case_count=1, candidates=[c])._repr_html_()
    assert "Cost &amp; usage" in html
    assert "Provider time" in html
    assert "Unattributed" in html
    assert "$0.2000" in html
    assert "sf-cost-block" in html
    assert "Input tokens" in html
    assert "Output tokens" in html
    assert "not wall time" in html
    assert "sf-cost-fields" in html


def test_unknown_values_and_inconsistent_totals_are_explained():
    c = result(missing=True)
    html = sf.Report(benchmark=c.benchmark, case_count=1, candidates=[c])._repr_html_()
    assert "Unknown" in html
    c = result(root="0.01")
    html = sf.Report(benchmark=c.benchmark, case_count=1, candidates=[c])._repr_html_()
    assert "Accounting breakdown unavailable" in html
    assert "Unattributed" not in html


def test_accounting_labels_are_escaped():
    c = result()
    c = replace(c, operations=[replace(c.operations[0], label="<img src=x onerror=evil()>")])
    html = sf.Report(benchmark=c.benchmark, case_count=1, candidates=[c])._repr_html_()
    assert "<img src=x onerror=evil()>" not in html
    assert "&lt;img src=x onerror=evil()&gt;" in html


def test_case_view_uses_native_keyboard_controls_and_named_cache_counts():
    c = result()
    html = sf.Report(benchmark=c.benchmark, case_count=1, candidates=[c])._repr_html_()
    assert "type='radio'" in html
    assert "1 miss" in html

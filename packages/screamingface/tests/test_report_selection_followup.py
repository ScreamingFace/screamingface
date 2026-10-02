"""Exact identities, bounded fallback and live selection synchronization."""

import pytest
from test_case_navigation import multi_candidate_report
from test_saved_runs import saved_fixture

import screamingface as sf
from screamingface._ui.case_navigation import CaseNavigation
from screamingface._ui.report_browser import ReportBrowser


@pytest.mark.parametrize("candidate", [-1, 0])
def test_exact_string_identity_precedes_numeric_fallback(candidate):
    report = multi_candidate_report(count=3, candidates=1, identities=[[1, "01", "1"]])
    nav = CaseNavigation(report.candidates)
    nav.select(candidate)
    assert nav.resolve("01") == "01"
    assert nav.resolve("1") == "1"
    assert nav.resolve("001") == 1


def test_static_fallback_does_not_materialize_all_accounting_rows(tmp_path, monkeypatch):
    from screamingface.report import CandidateResult

    _, saved = saved_fixture(tmp_path, 60)
    report = sf.reports.get(saved.key, directory=tmp_path)

    def no_full_accounting(candidate):
        pytest.fail("static rendering materialized all case accounting")

    monkeypatch.setattr(CandidateResult, "accounting", property(no_full_accounting))
    html = report._repr_html_()
    assert "preview of first 25" in html
    assert "case 24" in html


def test_manual_rail_selection_is_preserved_when_switching_candidate(tmp_path, monkeypatch):
    import re

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report())
    browser.candidate.value = 0
    row_id = re.findall(r"<label[^>]*for='([^']+)'", browser.cases.value)[23]
    browser._case_events._handle_mouse_msg(
        None, {"type": "click", "target": {"id": row_id + "-row"}}, None
    )
    browser.candidate.value = 1
    assert browser._focus_id == 23
    assert re.search(r"id='[^']+-23' checked", browser.cases.value)


def test_widget_free_fallback_uses_bounded_accounting(tmp_path, monkeypatch):
    import builtins

    from screamingface.report import CandidateResult

    _, saved = saved_fixture(tmp_path, 60)
    report = sf.reports.get(saved.key, directory=tmp_path)
    original = builtins.__import__
    seen = []

    def without_widgets(name, *args, **kwargs):
        if name == "screamingface._ui.report_browser":
            raise ImportError("widget-free fallback")
        return original(name, *args, **kwargs)

    def no_full_accounting(candidate):
        pytest.fail("fallback materialized all accounting rows")

    monkeypatch.setattr(CandidateResult, "accounting", property(no_full_accounting))
    monkeypatch.setattr(builtins, "__import__", without_widgets)
    monkeypatch.setattr("IPython.display.display", seen.append)
    report._display_notebook()
    assert len(seen) == 1
    assert seen[0].data.count("class='sf-case-radio'") == 25


@pytest.mark.parametrize("identity", [1, "01"])
def test_manual_selection_preserves_identity_type(tmp_path, monkeypatch, identity):
    import re

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report(count=3, identities=[[1, "01", "1"]] * 2))
    browser.candidate.value = 0
    index = 0 if isinstance(identity, int) else 1
    row_id = re.findall(r"<label[^>]*for='([^']+)'", browser.cases.value)[index]
    browser._case_events._handle_mouse_msg(None, {"type": "click", "target": {"id": row_id}}, None)
    browser.candidate.value = 1
    assert browser._focus_id == identity
    assert type(browser._focus_id) is type(identity)
    assert re.search(rf"id='[^']+-{index}' checked", browser.cases.value)


def test_irrelevant_or_stale_case_events_do_not_change_selection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report())
    before = browser._focus_id
    for target in ("", "sf-case-not-this-report-0", "sf-case-00000000--1"):
        browser._select_case({"target": {"id": target}})
    assert browser._focus_id == before

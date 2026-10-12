"""Pagination preserves merged report truth and remains usable after failures."""

import builtins
import json

import pytest
from test_accounting_breakdown import replace
from test_report_browser import large_report

import screamingface as sf


@pytest.mark.asyncio
async def test_failed_candidate_filter_restores_rendered_selection(tmp_path, monkeypatch):
    from test_case_navigation import multi_candidate_report

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report())
    browser.next.click()
    assert browser._page_task is not None
    await browser._page_task
    original = browser.cases.value
    original_count = browser.count.value

    def fail(page):
        raise OSError("page unavailable")

    monkeypatch.setattr(browser, "_page_html", fail)
    browser.candidate.value = 1
    assert browser._page_task is not None
    await browser._page_task
    assert browser.cases.value == original
    assert browser.candidate.value == browser.navigation.selected == -1
    assert browser.count.value == original_count
    assert not browser.candidate.disabled
    assert "Could not load cases" in browser.notice.value


def test_linked_cards_and_download_preserve_named_scores_and_archive_cost(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = large_report(30)
    owner = replace(
        source.candidates[0],
        scores={"f1": 1.0, "exact": 0.75},
        cache_saved_cost_archive_usd="1.25",
        cache_unpriced_hits=0,
        run_cost_status=None,
    )
    source = sf.Report(benchmark=source.benchmark, case_count=30, candidates=[owner])
    expected = source.to_dict()
    browser = ReportBrowser(source)
    card = browser.widget.children[1].children[0].value
    assert "f1" in card and "exact" in card and "headline" in card
    browser.go_to.value = "29"
    browser.export.click()
    assert json.loads(browser.snapshot.read_text()) == expected
    assert source.to_dict() == expected


def test_notebook_display_uses_widget_and_static_fallback(monkeypatch):
    from IPython import display

    source = large_report(1)
    shown = []
    monkeypatch.setattr(display, "display", shown.append)
    source._ipython_display_()
    assert "sf-report-browser" in shown[-1]._dom_classes
    original = builtins.__import__

    def without_widgets(name, *args, **kwargs):
        if name == "screamingface._ui.report_browser":
            raise ImportError("notebook extra not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_widgets)
    source._ipython_display_()
    assert isinstance(shown[-1], display.HTML)
    data = shown[-1].data
    assert isinstance(data, str) and "Report" in data


def test_static_preview_bounds_large_case_content_and_many_failures():
    source = large_report(30)
    first = replace(source.candidates[0].cases[0], input="<script>" * 10000)
    failures = [
        sf.Failure(stage="grading", code="grading_failed", message="x" * 1000) for _ in range(30)
    ]
    owner = replace(
        source.candidates[0], cases=[first, *source.candidates[0].cases[1:]], failures=failures
    )
    source = sf.Report(benchmark=source.benchmark, case_count=30, candidates=[owner])
    html = source._repr_html_()
    assert "preview of first 25" in html
    assert "Preview · export the complete report" in html
    assert "<script>" not in html
    assert html.count("class='sf-pane'") == 25
    assert "30 failures" in html and "export" in html
    assert len(html.encode()) < 500_000


@pytest.mark.parametrize("action", ["next", "candidate"])
def test_synchronous_navigation_failure_keeps_visible_selection(tmp_path, monkeypatch, action):
    from test_case_navigation import multi_candidate_report

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report())
    render = browser._page_html
    visible = browser.cases.value

    def fail(page):
        raise OSError("page unavailable")

    monkeypatch.setattr(browser, "_page_html", fail)
    if action == "next":
        browser.next.click()
    else:
        browser.candidate.value = 1
    assert browser.page == 0
    assert browser.candidate.value == browser.navigation.selected == -1
    assert browser.cases.value == visible
    assert browser.count.value == "1–25 of 120"
    assert browser.previous.disabled and not browser.next.disabled
    assert "Could not load cases" in browser.notice.value
    monkeypatch.setattr(browser, "_page_html", render)
    browser.next.click()
    assert browser.count.value == "26–50 of 120"
    assert "Could not load cases" not in browser.notice.value


@pytest.mark.parametrize(
    "failure",
    [FileNotFoundError("server disappeared"), json.JSONDecodeError("bad metadata", "{", 1)],
)
def test_missing_server_metadata_keeps_saved_download_accessible(tmp_path, monkeypatch, failure):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)

    def missing():
        raise failure
        yield

    monkeypatch.setattr("jupyter_server.serverapp.list_running_servers", missing)
    browser = ReportBrowser(large_report(1))
    browser.export.click()
    assert browser.snapshot.exists()
    assert not browser._exporting
    assert "saved to" in browser.exports.value
    assert browser.export_slot.children == (browser.exports,)


@pytest.mark.asyncio
async def test_async_missing_server_metadata_keeps_saved_download_accessible(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)

    def missing():
        raise FileNotFoundError("server disappeared")

    monkeypatch.setattr("jupyter_server.serverapp.list_running_servers", missing)
    browser = ReportBrowser(large_report(1))
    browser.export.click()
    assert browser._export_task is not None
    await browser._export_task
    assert browser.snapshot.exists()
    assert not browser._exporting
    assert "saved to" in browser.exports.value
    assert browser.export_slot.children == (browser.exports,)

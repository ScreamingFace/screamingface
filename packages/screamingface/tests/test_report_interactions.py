"""Search and rapid navigation remain bounded on disk-backed reports."""

import pytest
from test_report_browser import large_report
from test_report_panel import candidate


def test_disk_search_does_not_decode_every_case(tmp_path, monkeypatch):
    from test_saved_runs import saved_fixture

    import screamingface as sf
    from screamingface._results import cases
    from screamingface._ui.report_browser import ReportBrowser

    _, saved = saved_fixture(tmp_path / "saved", count=60)
    report = sf.reports.get(saved.key, directory=tmp_path / "saved")
    ReportBrowser(report)

    def reject(body):
        raise AssertionError("search rebuilt a CaseResult instead of scanning the index")

    monkeypatch.setattr(cases, "_decode", reject)
    assert list(report.candidates[0].cases._matching_indices("answer 59")) == [59]
    assert list(report.candidates[0].cases._matching_indices("contract")) == list(range(60))
    assert list(report.candidates[0].cases._matching_indices("clause 40")) == [40]
    assert list(report.candidates[0].cases._matching_indices("does not exist")) == []


def test_disk_search_preserves_full_text_unicode_and_literal_queries(tmp_path):
    import json

    from test_saved_runs import saved_fixture

    import screamingface as sf
    from screamingface._ui.report_browser import ReportBrowser

    _, saved = saved_fixture(tmp_path / "saved", count=2)
    payload = json.loads(saved.path.read_text())
    payload["cases"][1]["input"] = "x" * 24000 + " Straße needle%_"
    saved.path.write_text(json.dumps(payload, ensure_ascii=False))
    report = sf.reports.get(saved.key, directory=tmp_path / "saved")
    ReportBrowser(report)
    assert list(report.candidates[0].cases._matching_indices("strasse")) == [1]
    assert list(report.candidates[0].cases._matching_indices("needle%_")) == [1]
    assert list(report.candidates[0].cases._matching_indices("needle%' OR 1=1 --")) == []


@pytest.mark.asyncio
async def test_page_loading_coalesces_rapid_clicks_to_latest_page(tmp_path, monkeypatch):
    import threading

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(300))
    release = threading.Event()
    original = browser._page_html
    calls = []

    def delayed(page):
        calls.append(page)
        assert release.wait(5)
        return original(page)

    monkeypatch.setattr(browser, "_page_html", delayed)
    try:
        browser.next.click()
        assert not browser.previous.disabled and not browser.next.disabled
        assert browser.go_to.disabled and browser.next.icon == "spinner"
        for _ in range(10):
            browser.next.click()
        assert browser._page_task is not None
        release.set()
        await browser._page_task
    finally:
        release.set()
    assert calls == [11]
    assert browser.count.value == "276–300 of 300" and "answer 275" in browser.cases.value
    assert not browser.previous.disabled and browser.next.disabled and not browser.go_to.disabled
    assert browser.next.icon == "chevron-right"


@pytest.mark.asyncio
async def test_page_disk_error_preserves_current_page(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    browser.next.click()
    assert browser._page_task is not None
    await browser._page_task

    def fail(page):
        raise OSError("disk unavailable")

    monkeypatch.setattr(browser, "_page_html", fail)
    browser.next.click()
    assert browser._page_task is not None
    await browser._page_task
    assert browser.page == 1
    assert browser.count.value == "26–50 of 60" and "answer 25" in browser.cases.value
    assert "Could not load cases" in browser.notice.value
    assert not browser.next.disabled and not browser.go_to.disabled


def test_page_accounting_only_visits_candidates_on_the_page(monkeypatch):
    from test_report_panel import report

    from screamingface._ui import report_view

    source = report(candidate("a", 1.0), candidate("b", 1.0))
    owner = source.candidates[0]
    calls = []
    original = report_view.case_accounting

    def selected(candidate, **kwargs):
        calls.append(candidate.name)
        return original(candidate, **kwargs)

    monkeypatch.setattr(report_view, "case_accounting", selected)
    report_view.cases_page_html(source, [(owner, owner.cases[0])])
    assert calls == [owner.name]


@pytest.mark.asyncio
async def test_new_page_request_discards_an_inflight_stale_render(tmp_path, monkeypatch):
    import asyncio
    import threading

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    started, release = threading.Event(), threading.Event()
    seen = []

    def delayed(page):
        if page == 1:
            started.set()
            assert release.wait(5)
        return f"page {page}"

    monkeypatch.setattr(browser, "_page_html", delayed)
    browser.cases.observe(lambda change: seen.append(change["new"]), names="value")
    try:
        browser.next.click()
        assert await asyncio.to_thread(started.wait, 2)
        browser.next.click()
        release.set()
        assert browser._page_task is not None
        await browser._page_task
    finally:
        release.set()
    assert seen == ["page 2"]
    assert browser.count.value == "51–60 of 60"


def test_page_load_does_not_rescan_disk_cases_for_accounting(tmp_path, monkeypatch):
    from test_saved_runs import saved_fixture

    import screamingface as sf
    from screamingface._results.cases import DiskCases
    from screamingface._ui.report_browser import ReportBrowser

    _, saved = saved_fixture(tmp_path / "saved", count=60)
    report = sf.reports.get(saved.key, directory=tmp_path / "saved")
    browser = ReportBrowser(report)

    def reject(self):
        raise AssertionError("page load rescanned all saved cases")

    monkeypatch.setattr(DiskCases, "__iter__", reject)
    assert "answer 25" in browser._page_html(1)


@pytest.mark.parametrize("root", ["0.9", "0.01"])
def test_page_accounting_context_preserves_cost_and_consistency(root):
    from test_accounting_breakdown import result

    from screamingface._ui.accounting_view import case_accounting, run_accounting_note
    from screamingface.accounting import _accounting_context

    source = result(root=root)
    selected = source.cases[0]
    context = _accounting_context(source)
    assert case_accounting(source, case_ids={selected.case_id}) == case_accounting(
        source, case_ids={selected.case_id}, context=context, cases=(selected,)
    )
    assert run_accounting_note(source) == run_accounting_note(source, context=context)


def test_page_context_preserves_cross_case_model_conflicts():
    from test_accounting_model_completeness import two_cases

    from screamingface._ui.accounting_view import case_accounting
    from screamingface.accounting import _accounting_context

    source = two_cases(declared="alias", member=True)
    selected = source.cases[1]
    assert case_accounting(source, case_ids={selected.case_id}) == case_accounting(
        source, case_ids={selected.case_id}, context=_accounting_context(source), cases=(selected,)
    )

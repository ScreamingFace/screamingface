"""Large reports must stay lossless without copying them into notebook output."""

from datetime import UTC, datetime

import pytest
from test_report_panel import candidate

from screamingface import Usage
from screamingface._ui.report_view import report_html
from screamingface.case_result import CaseGrade, CaseResult
from screamingface.operation import OperationInfo
from screamingface.report import BenchmarkInfo, CandidateResult, Report


def large_report(count=4182):
    cases = tuple(
        CaseResult(
            case_id=index,
            input="contract " * 1250,
            output=f"answer {index}",
            finish_reason="stop",
            failures=[],
            grade=CaseGrade(method="deterministic", score=1.0, metrics={}, checks=[]),
            metadata={"category": f"clause {index % 41}"},
        )
        for index in range(count)
    )
    benchmark = BenchmarkInfo("contracteval", "fixture", count)
    item = CandidateResult(
        benchmark=benchmark,
        run_id="demo",
        name="model",
        started_at=datetime(2026, 9, 30, tzinfo=UTC),
        completed_at=datetime(2026, 9, 30, tzinfo=UTC),
        kind="model",
        url4=candidate("model", 1.0).url4,
        models=["demo"],
        score=1.0,
        coverage=1.0,
        metrics={},
        operations=[OperationInfo(id="op", kind="model", label="answer", depends_on=())],
        cases=cases,
        members=[],
        failures=[],
        usage=Usage(),
    )
    return Report(benchmark=item.benchmark, case_count=count, candidates=[item])


def test_large_static_report_output_is_bounded():
    html = report_html(large_report())
    print(f"HTML bytes: {len(html.encode()):,}")
    assert len(html.encode()) < 500_000
    assert html.count("class='sf-pane'") <= 25
    assert "data:application/json;base64" not in html


def test_browser_paginates_and_exports_losslessly(tmp_path, monkeypatch):
    import json

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = large_report(60)
    browser = ReportBrowser(source)
    assert browser.count.value == "1–25 of 60"
    assert browser.go_to.value == ""
    assert not browser.snapshot.exists()
    browser.next.click()
    assert browser.count.value == "26–50 of 60"
    browser.next.click()
    assert browser.count.value == "51–60 of 60"
    assert browser.next.disabled
    assert "answer 59" in browser.cases.value
    browser._export_json()
    assert json.loads(browser.snapshot.read_text()) == source.to_dict()


def test_streaming_export_does_not_materialize_whole_report(tmp_path, monkeypatch):
    from screamingface.report import Report

    source = large_report(30)
    expected = source.to_json()

    def reject(*args):
        raise AssertionError("eager full-report serialization")

    monkeypatch.setattr(Report, "to_json", reject)
    monkeypatch.setattr(Report, "to_dict", reject)
    assert source.export(tmp_path / "report.json").read_text() == expected


def test_original_case_panes_escape_content_and_export_full_input(tmp_path, monkeypatch):
    import json

    from test_report_panel import report

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    case = CaseResult(
        case_id="<script>",
        input="<script>hi</script>" * 2500,
        output="answer tail",
        finish_reason="stop",
        failures=[],
        grade=CaseGrade(method="deterministic", score=1.0, metrics={}, checks=[]),
        metadata={},
    )
    browser = ReportBrowser(report(candidate("model", 1.0, cases=(case,))))
    assert "<script>" not in browser.cases.value
    assert "&lt;script&gt;" in browser.cases.value
    assert "sf-pane__q" in browser.cases.value
    assert "answer tail" in browser.cases.value
    browser._export_json()
    assert (
        json.loads(browser.snapshot.read_text())["candidates"][0]["cases"][0]["input"] == case.input
    )


def test_disk_errors_preserve_interactive_access(tmp_path, monkeypatch):
    from pathlib import Path

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    (tmp_path / "screamingface-reports").write_text("not a directory")
    browser = ReportBrowser(large_report(2))
    assert browser.notice.value == ""
    assert list(browser.navigation.indices(0)) == [0, 1]
    browser._export_json()
    assert "Download failed" in browser.notice.value
    assert not browser.export.disabled
    assert browser.export.description == "Download"
    assert not browser.snapshot.exists()
    assert isinstance(browser.snapshot, Path)


def test_widget_state_does_not_contain_all_cases(tmp_path, monkeypatch):
    import json

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report())

    def states(widget):
        yield widget.get_state()
        for child in getattr(widget, "children", ()):
            yield from states(child)

    payload = json.dumps(list(states(browser.widget)), default=str)
    assert len(payload) < 1_000_000
    assert "answer 4181" not in payload
    assert browser.cases.value.count("class='sf-pane'") == 25
    browser.page = 4181 // 25
    browser._render_page()
    assert "answer 4181" in browser.cases.value


def test_file_links_use_server_base_url_and_download_endpoint(tmp_path, monkeypatch):
    from screamingface._ui.report_files import download_link

    monkeypatch.setenv("JPY_PARENT_PID", "123")
    monkeypatch.setattr(
        "jupyter_server.serverapp.list_running_servers",
        lambda: iter(
            [
                {"pid": 456, "root_dir": str(tmp_path), "base_url": "/"},
                {"pid": 123, "root_dir": str(tmp_path), "base_url": "/user/me/"},
            ]
        ),
    )
    link = download_link(tmp_path / "a b.json", "All <results>")
    assert "/user/me/files/a%20b.json?download=1" in link
    assert "All &lt;results&gt;" in link
    assert 'download="a b.json"' in link
    assert "saved to" in download_link(tmp_path.parent / "outside.json", "All results")


def test_failed_streaming_export_keeps_previous_file(tmp_path, monkeypatch):
    import pytest

    from screamingface import _report_export

    source = large_report(2)
    destination = tmp_path / "report.json"
    destination.write_text("previous complete report")

    def broken(report):
        yield '{"partial":'
        raise OSError("disk full")

    monkeypatch.setattr(_report_export, "iter_report_json", broken)
    with pytest.raises(OSError, match="disk full"):
        source.export(destination)
    assert destination.read_text() == "previous complete report"
    assert list(tmp_path.iterdir()) == [destination]


def test_pagination_keeps_shared_case_ids_distinct(tmp_path, monkeypatch):
    from test_report_panel import report

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = report(candidate("first", 1.0), candidate("second", 0.0))
    browser = ReportBrowser(source)
    assert browser.entries[1][0].name == "second"
    assert browser.entries[0][0].name == "first"


def test_original_case_presentation_has_no_new_tabs(tmp_path, monkeypatch):
    import ipywidgets as widgets

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    assert not any(isinstance(child, widgets.Tab) for child in browser.widget.children)
    assert "sf-master" in browser.cases.value
    assert "sf-rail__item" in browser.cases.value
    assert "answer 24" in browser.cases.value
    assert "answer 25" not in browser.cases.value
    browser.next.click()
    assert "answer 25" in browser.cases.value
    assert "answer 0</pre>" not in browser.cases.value


@pytest.mark.asyncio
async def test_export_busy_state_prevents_duplicate_work(tmp_path, monkeypatch):
    import asyncio
    import threading

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(1))
    started, release = threading.Event(), threading.Event()
    original = Report.export
    calls = []

    def slow_export(report, path):
        calls.append(path)
        started.set()
        assert release.wait(5)
        return original(report, path)

    monkeypatch.setattr(Report, "export", slow_export)
    browser.export.click()
    assert browser.export.disabled
    assert browser.export.description == "Preparing…"
    assert await asyncio.to_thread(started.wait, 5)
    browser.export.click()
    release.set()
    assert browser._export_task is not None
    await browser._export_task
    browser.export.click()
    assert len(calls) == 1
    assert browser.export.disabled
    assert browser.export_slot.children == (browser.exports,)
    assert "Download" in browser.exports.value


@pytest.mark.asyncio
async def test_async_export_failure_allows_retry(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(1))
    original = Report.export

    def fail(report, path):
        raise OSError("disk full")

    monkeypatch.setattr(Report, "export", fail)
    browser.export.click()
    assert browser._export_task is not None
    await browser._export_task
    assert not browser.export.disabled
    assert "disk full" in browser.notice.value
    monkeypatch.setattr(Report, "export", original)
    browser.export.click()
    assert browser._export_task is not None
    await browser._export_task
    assert browser.export.disabled
    assert browser.export_slot.children == (browser.exports,)
    assert "Download failed" not in browser.notice.value


def test_export_replaces_one_control_without_redundant_status(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "screamingface._ui.report_files._served_url", lambda path: "/files/report.json"
    )
    browser = ReportBrowser(large_report(1))
    assert browser.export_slot.children == (browser.export,)
    assert browser.export.description == "Download"
    browser.export.click()
    assert browser.export_slot.children == (browser.exports,)
    assert browser.notice.value == ""
    assert browser.export not in browser.widget.children
    assert browser.exports.value.count("<a ") == 1
    assert ">Download</a>" in browser.exports.value


def test_case_header_contains_actions_and_plain_title(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    assert browser.case_box in browser.widget.children
    assert browser.case_header.children == (
        browser.case_title,
        browser.candidate,
        browser.go_to,
        browser.count,
        browser.pagination,
        browser.export_slot,
    )
    assert browser.pagination.children == (browser.previous, browser.next)
    assert browser.export_slot not in browser.widget.children
    assert "<summary>" not in browser.cases.value
    assert isinstance(browser.case_title, browser.w.Label)
    assert browser.case_title.value == "Case results"
    assert browser.cases.layout.display != "none"
    browser.next.click()
    assert "26–50" in browser.count.value


def test_go_to_case_and_clear_preserves_full_export(tmp_path, monkeypatch):
    import json

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = large_report(60)
    browser = ReportBrowser(source)
    browser.next.click()
    browser.go_to.value = "59"
    assert browser.count.value == "51–60 of 60"
    assert browser.page == 2
    assert "answer 59" in browser.cases.value
    browser.go_to.value = "40"
    assert browser.count.value == "26–50 of 60"
    browser.go_to.value = "missing"
    assert "Case missing not found" in browser.notice.value
    assert browser.count.value == "26–50 of 60"
    browser.go_to.value = ""
    assert browser.count.value == "1–25 of 60"
    browser.export.click()
    assert json.loads(browser.snapshot.read_text()) == source.to_dict()


@pytest.mark.asyncio
async def test_go_to_renders_in_worker_and_restores_controls(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    browser.go_to.value = "59"
    assert browser.go_to.disabled
    assert browser._page_task is not None
    await browser._page_task
    assert not browser.go_to.disabled
    assert browser.count.value == "51–60 of 60"

    def fail(page):
        raise OSError("disk unavailable")

    monkeypatch.setattr(browser, "_page_html", fail)
    browser.go_to.value = "0"
    assert browser._page_task is not None
    await browser._page_task
    assert not browser.go_to.disabled
    assert browser.count.value == "51–60 of 60"
    assert "Could not load cases" in browser.notice.value

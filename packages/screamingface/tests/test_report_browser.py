"""Large reports must stay lossless without copying them into notebook output."""

from datetime import UTC, datetime

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


def test_browser_filters_whole_report_and_exports_losslessly(tmp_path, monkeypatch):
    import json

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = large_report(60)
    browser = ReportBrowser(source)
    assert browser.count.value.startswith("Showing 1–25 of 60")
    browser.next.click()
    assert browser.count.value.startswith("Showing 26–50 of 60")
    browser.search.value = "answer 59"
    assert browser.count.value.startswith("Showing 1–1 of 1")
    assert browser.matches == [59]
    assert json.loads(browser.snapshot.read_text()) == source.to_dict()
    browser.search.value = "no such case"
    assert browser.count.value.startswith("Showing 0–0 of 0")
    assert browser.next.disabled and browser.previous.disabled


def test_streaming_export_does_not_materialize_whole_report(tmp_path, monkeypatch):
    from screamingface.report import Report

    source = large_report(30)
    expected = source.to_json()

    def reject(*args):
        raise AssertionError("eager full-report serialization")

    monkeypatch.setattr(Report, "to_json", reject)
    monkeypatch.setattr(Report, "to_dict", reject)
    assert source.export(tmp_path / "report.json").read_text() == expected


def test_page_boundaries_global_category_filter_and_sort(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(large_report(60))
    browser.next.click()
    browser.next.click()
    assert browser.count.value.startswith("Showing 51–60")
    assert browser.next.disabled
    browser.previous.click()
    assert browser.count.value.startswith("Showing 26–50")
    browser.category.value = "clause 18"
    assert browser.matches == [18, 59]
    assert browser.page == 0
    browser.sort.value = "-score"
    assert browser.matches == [18, 59]
    browser.candidate.value = "demo"
    assert browser.matches == [18, 59]
    browser.status.value = "failed"
    assert browser.matches == []
    browser.status.value = "passed"
    assert browser.matches == [18, 59]
    browser.search.value = "model"
    assert browser.matches == [18, 59]


def test_full_content_paging_and_escaping(tmp_path, monkeypatch):
    import json
    from html import unescape

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
    assert "<script>" not in browser.detail.value
    assert "Preview" in browser.detail.value
    assert browser.text_page.max == 4
    pieces = []
    for page in range(1, browser.text_page.max + 1):
        browser.text_page.value = page
        pieces.append(unescape(browser.full.value.split(">", 1)[1].rsplit("</pre>", 1)[0]))
    assert "".join(pieces) == case.input
    browser.full_field.value = "Output"
    assert "answer tail" in browser.full.value
    assert browser.text_page.value == 1
    browser.full_field.value = "Case JSON"
    assert json.loads(browser._text) == case.to_dict()


def test_csv_scopes_and_case_json_are_exact(tmp_path, monkeypatch):
    import csv
    import json

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = large_report(60)
    browser = ReportBrowser(source)
    browser.search.value = "answer 59"
    browser._export_csv(True)
    with next(browser.directory.glob("filtered-*.csv")).open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert json.loads(rows[0]["case_json"]) == source.candidates[0].cases[59].to_dict()
    browser._export_csv(False)
    with next(browser.directory.glob("all-*.csv")).open() as stream:
        assert len(list(csv.DictReader(stream))) == 60
    assert "all CSV" in browser.exports.value


def test_disk_errors_preserve_interactive_access(tmp_path, monkeypatch):
    from pathlib import Path

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    (tmp_path / "screamingface-reports").write_text("not a directory")
    browser = ReportBrowser(large_report(2))
    assert "Could not save report" in browser.notice.value
    assert browser.matches == [0, 1]
    browser._export_csv(False)
    assert "Export failed" in browser.notice.value
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
    assert len(payload) < 100_000
    assert "answer 4181" not in payload
    assert len(browser.cases.options) == 25
    browser.search.value = "answer 4181"
    assert browser.matches == [4181]
    assert "answer 4181" in browser.detail.value


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


def test_candidate_filter_keeps_shared_case_ids_distinct(tmp_path, monkeypatch):
    from test_report_panel import report

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    source = report(candidate("first", 1.0), candidate("second", 0.0))
    browser = ReportBrowser(source)
    browser.candidate.value = "run-second"
    assert browser.matches == [1]
    browser.sort.value = "score"
    browser.candidate.value = ""
    assert browser.matches == [1, 0]
    browser.sort.value = "-score"
    assert browser.matches == [0, 1]


def test_failed_and_ungraded_filters_include_failed_grading(tmp_path, monkeypatch):
    from test_report_panel import report

    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(report(candidate("model", None)))
    browser.status.value = "failed"
    assert browser.matches == [0]
    browser.status.value = "ungraded"
    assert browser.matches == [0]

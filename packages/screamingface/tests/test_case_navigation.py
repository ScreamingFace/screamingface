"""One shared browser filters the complete result list and navigates exact cases."""

from dataclasses import fields

import pytest
from test_report_browser import large_report

from screamingface.report import Report


def multi_candidate_report(count=60, candidates=2, identities=None):
    items = []
    for index in range(candidates):
        source = large_report(count).candidates[0]
        values = {field.name: getattr(source, field.name) for field in fields(source)}
        values.pop("_metric_items")
        values.update(name=f"candidate-{index}", run_id=f"run-{index}", metrics=source.metrics)
        if identities is not None:
            from screamingface._evaluation.results import _case_result

            values["cases"] = tuple(
                _case_result({**case.to_dict(), "case_id": case_id})
                for case, case_id in zip(source.cases, identities[index], strict=True)
            )
        items.append(type(source)(**values))
    return Report(benchmark=items[0].benchmark, case_count=count, candidates=items)


def test_all_lists_case_results_across_candidates():
    from screamingface._ui.case_navigation import CaseNavigation

    nav = CaseNavigation(multi_candidate_report().candidates)
    assert nav.selected == -1
    assert nav.indices(0) == tuple(value for i in range(12) for value in (i, 60 + i)) + (12,)
    assert nav.indices(4) == tuple(value for i in range(50, 60) for value in (i, 60 + i))
    assert nav.locate("59") == 4
    assert nav.caption(4) == "101–120 of 120"
    nav.select(1)
    assert list(nav.indices(1)) == list(range(85, 110))
    assert nav.locate("59") == 2
    assert nav.caption(2) == "51–60 of 60"


def test_all_with_many_candidates_is_bounded():
    from screamingface._ui.case_navigation import CaseNavigation

    nav = CaseNavigation(multi_candidate_report(count=2, candidates=30).candidates)
    assert len(nav.indices(0)) == 25
    assert len(nav.indices(1)) == 25
    assert nav.caption(1) == "26–50 of 60"
    assert nav.locate("1") == 1


def test_single_candidate_all_keeps_ordinary_pagination():
    from screamingface._ui.case_navigation import CaseNavigation

    nav = CaseNavigation(large_report(60).candidates)
    assert nav.locate("59") == 2
    assert nav.caption(2) == "51–60 of 60"


def test_case_identity_is_not_combined_result_position():
    import pytest

    from screamingface._ui.case_navigation import CaseNavigation

    nav = CaseNavigation(multi_candidate_report().candidates)
    with pytest.raises(ValueError, match="Case 46000 not found"):
        nav.locate("46000")
    assert nav.locate("0") == 0


def test_live_controls_select_candidates_and_exact_cases(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report())
    assert browser.candidate.value == -1
    assert browser.candidate.options[0] == ("All Candidates", -1)
    assert browser.candidate.description == ""
    assert browser.go_to.placeholder == "Go to case number"
    browser.go_to.value = "59"
    assert browser.count.value == "101–120 of 120"
    assert all(name in browser.cases.value.upper() for name in ("CANDIDATE-0", "CANDIDATE-1"))
    combined_rail = browser.cases.value.split("<div class='sf-rail'>")[1].split(
        "<div class='sf-detail'>"
    )[0]
    assert "sf-rail__q" in combined_rail
    assert "sf-rail__who" in combined_rail
    assert "case 59" in combined_rail
    browser.candidate.value = 1
    candidate_rail = browser.cases.value.split("<div class='sf-rail'>")[1].split(
        "<div class='sf-detail'>"
    )[0]
    assert "sf-rail__who" not in candidate_rail
    assert "sf-rail__q" in candidate_rail
    assert browser.count.value == "51–60 of 60"
    assert "-9' checked" in browser.cases.value
    browser.candidate_buttons[0].click()
    assert browser.candidate.value == 0
    assert browser.count.value == "51–60 of 60"
    browser.go_to.value = "46000"
    assert "Case 46000 not found" in browser.notice.value
    assert browser.count.value == "51–60 of 60"


def test_go_to_on_disk_does_not_scan_prompts(tmp_path, monkeypatch):
    from test_saved_runs import saved_fixture

    import screamingface as sf
    from screamingface._results import cases
    from screamingface._ui.report_browser import ReportBrowser

    _, saved = saved_fixture(tmp_path, count=60)
    browser = ReportBrowser(sf.reports.get(saved.key, directory=tmp_path))
    original = cases._decode
    reads = []

    def count(body):
        reads.append(body)
        return original(body)

    monkeypatch.setattr(cases, "_decode", count)
    browser.go_to.value = "59"
    assert browser.count.value == "51–60 of 60"
    assert len(reads) == 10


def test_sparse_and_reordered_string_identities_are_grouped_correctly():
    import pytest

    from screamingface._ui.case_navigation import CaseNavigation

    source = multi_candidate_report(count=2, identities=[[20, 10], ["named", 20]])
    nav = CaseNavigation(source.candidates)
    assert nav.indices(0) == (0, 3, 1, 2)
    assert nav.locate("20") == 0
    assert nav.locate("named") == 0
    assert nav.caption(0) == "1–4 of 4"
    nav.select(1)
    assert nav.locate("named") == 0
    with pytest.raises(ValueError, match="not found"):
        nav.locate("10")
    with pytest.raises(ValueError, match="unknown Candidate"):
        nav.select(2)


def test_go_to_matches_string_numeric_ids():
    from screamingface._ui.case_navigation import CaseNavigation

    nav = CaseNavigation(
        multi_candidate_report(count=2, identities=[["0", "1"], ["0", "1"]]).candidates
    )
    assert nav.resolve("1") == "1"
    assert nav.locate("1") == 0


@pytest.mark.asyncio
async def test_all_navigation_keeps_accepting_rapid_clicks(tmp_path, monkeypatch):
    from screamingface._ui.report_browser import ReportBrowser

    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(multi_candidate_report(count=100))
    browser.go_to.value = "1"
    assert browser._page_task is not None
    await browser._page_task
    for _ in range(5):
        browser.next.click()
    assert not browser.previous.disabled and not browser.next.disabled
    assert browser._page_task is not None
    await browser._page_task
    assert browser.count.value == "126–150 of 200"
    assert browser.go_to.value == "62"
    assert not browser.candidate.disabled and not browser.go_to.disabled
    browser.candidate.value = 1
    assert browser.count.value == "51–75 of 100"
    assert "-12' checked" in browser.cases.value

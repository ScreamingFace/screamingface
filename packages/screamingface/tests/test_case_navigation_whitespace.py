"""Case navigation preserves exact padded string IDs before trying integer IDs."""

import pytest
from test_case_navigation import multi_candidate_report

from screamingface._ui.case_navigation import CaseNavigation
from screamingface._ui.report_browser import ReportBrowser


def padded_report():
    return multi_candidate_report(
        count=3, identities=[[42, "42", " 42 "], [42, "padded", " padded "]]
    )


@pytest.mark.parametrize("selection", [-1, 0])
def test_padded_numeric_string_wins_over_integer_and_plain_string(selection):
    nav = CaseNavigation(padded_report().candidates)
    nav.select(selection)
    assert nav.resolve(" 42 ") == " 42 "
    assert nav.resolve("42") == "42"
    assert nav.resolve("\t42\n") == 42


@pytest.mark.parametrize("selection", [-1, 1])
def test_padded_text_identity_is_retained(selection):
    nav = CaseNavigation(padded_report().candidates)
    nav.select(selection)
    assert nav.resolve(" padded ") == " padded "
    assert nav.resolve("padded") == "padded"
    with pytest.raises(ValueError, match="not found"):
        nav.resolve("  padded  ")


def test_filtered_candidate_uses_integer_fallback_without_other_candidates_string():
    nav = CaseNavigation(padded_report().candidates)
    nav.select(1)
    assert nav.resolve(" 42 ") == 42


@pytest.mark.parametrize("query,expected", [(" 42 ", " 42 "), (" padded ", " padded ")])
def test_live_go_to_selects_exact_padded_identity(tmp_path, monkeypatch, query, expected):
    monkeypatch.chdir(tmp_path)
    browser = ReportBrowser(padded_report())
    browser.go_to.value = query
    assert browser._focus_id == expected
    assert "not found" not in browser.notice.value
    assert browser.go_to.value == query


def test_padded_id_without_plain_string_collision_resolves_exactly():
    nav = CaseNavigation(
        multi_candidate_report(count=2, identities=[[" 42 ", 42], [" padded ", "other"]]).candidates
    )
    assert nav.resolve(" 42 ") == " 42 "
    assert nav.resolve(" padded ") == " padded "

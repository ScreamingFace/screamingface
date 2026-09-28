"""Case cost panels stay scoped and work without notebook JavaScript."""

from test_accounting_breakdown import replace, result

import screamingface as sf
from screamingface._ui.accounting_view import case_accounting, case_tabs


def test_case_blocks_have_named_values_and_no_subtable():
    c = result()
    html = case_accounting(c)[1]
    assert "<table" not in html
    for label in ("Cost", "Input tokens", "Output tokens", "Cache", "Provider time"):
        assert label in html
    assert "1 miss" in html
    assert "$0.1000" in html
    assert "$0.2000" in html
    assert "Unattributed" not in html


def test_case_panels_never_include_another_cases_values():
    c = result()
    second = replace(
        c.cases[0],
        case_id=2,
        operations=None,
        grade=None,
        status="failed",
        failures=[sf.Failure(stage="grading", code="grading_failed", message="fixture", case_id=2)],
    )
    c = replace(c, cases=[*c.cases, second], coverage=0.5)
    panels = case_accounting(c)
    assert "$0.1000" in panels[1]
    assert "$0.1000" not in panels[2]
    assert "Unknown" in panels[2]


def test_native_tab_groups_are_unique_and_answer_is_default():
    first = case_tabs("answer", "cost")
    second = case_tabs("answer", "cost")
    assert first != second
    assert "Answer &amp; grading" in first
    assert "Cost &amp; usage" in first
    assert "type='radio'" in first
    assert "checked" in first
    assert "<script" not in first


def test_cost_is_in_activity_header_without_help_disclosure():
    from xml.etree import ElementTree

    panel = ElementTree.fromstring(f"<div>{case_accounting(result())[1]}</div>")
    help_section = panel.find("details")
    assert help_section is None
    assert "About these numbers" not in "".join(panel.itertext())
    block = panel.find("section")
    assert block is not None
    header = block.find("header")
    assert header is not None
    assert "$0.1000" in "".join(header.itertext())
    fields = block.find("dl")
    assert fields is not None
    groups = [[term.text for term in group.findall("dt")] for group in fields]
    assert groups == [["Calls", "Cache"], ["Input tokens", "Output tokens"], ["Provider time"]]

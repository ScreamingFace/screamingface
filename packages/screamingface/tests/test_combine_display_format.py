"""E4b part 4, display format of the Combine views (PRD display-format, rows DF#1-11).

The helpers of ``S/_ui/combine_view.py`` turn one stored value into one table cell: a float at 4
significant digits with its exact stored value as the title, an em dash with its reason for a
missing value, and an escaped, clipped member value (ans:Q3, P5-P9, P17). Every expected value
is hand-computed in the PRD (DF-1 .. DF-D4), never copied from the code.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from _answer_fixtures import evidence_cases

from screamingface._evaluation.combine_evidence import decode_combine_evidence
from screamingface._ui import combine_view
from screamingface._ui.accounting_view import STYLE as ACCOUNTING_STYLE
from screamingface._ui.combine_view import (
    STYLE,
    dash_html,
    missing_reason,
    number_html,
    text_html,
)
from screamingface._ui.report_view import _STYLE, _cell, _score_text

# The Engine wire `rank_cut_not_met` (ET/data/combine_contract/evidence_cases.json), copied here as
# the case-pane PRD §7 says: the SDK copy of the fixture file does not hold it.
_RANK_CUT_NOT_MET: dict[str, Any] = {
    "schema": "screamingface.combine-evidence.v1",
    "kind": "selection",
    "reducer": "rank",
    "operators": ["by_signal@1", "top_k@1"],
    "members": [
        {
            "member_id": "member_1",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"field:score": 0.3},
            "weight": None,
            "score": 0.3,
            "rank": 2,
        },
        {
            "member_id": "member_2",
            "raw": None,
            "value": None,
            "status": "excluded",
            "reason": "no_signal",
            "signals": {"field:score": None},
            "weight": None,
            "score": None,
        },
        {
            "member_id": "member_3",
            "raw": None,
            "value": None,
            "status": "answered",
            "reason": None,
            "signals": {"field:score": 0.6},
            "weight": None,
            "score": 0.6,
            "rank": 1,
        },
    ],
    "tally": None,
    "judge": None,
    "fields": None,
    "chosen": [],
    "built": False,
    "agreement": None,
    "tie": False,
    "median": None,
    "presentation_order": None,
    "separator_collision": None,
    "signal": {"key": "field:score", "order": "max"},
    "cut": {"k": 3, "order": "max"},
    "result": {"member_id": None, "value": None, "status": "abstain", "reason": "cut_not_met"},
    "dropped": 0,
    "finish_reason": "stop",
}

# Tokens that existing tests forbid in a report's HTML (for example
# ST/test_case_abstained.py:158, ST/test_unjudged_check_display.py:89,
# ST/test_rich_display.py:176, ST/test_named_scores.py:233). The style is in every report.
_BANNED_TOKENS = (
    "abstained",
    "excluded",
    "incorrect",
    "graded",
    "reasoning",
    "cost",
    "scores",
    " — ",
    " · ",
)


# --- DF#1, DF#2 CHAR: the house formats stay as they are --------------------------------------


def test_score_text_keeps_six_significant_digits() -> None:
    assert _score_text(0.123456789) == "0.123457"


def test_cost_cell_dash_has_a_title() -> None:
    html = _cell("cost", "—", title="cost not reported by this run")

    assert html == (
        "<div class='sf-report__cell' title='cost not reported by this run'>"
        "<div class='sf-report__k'>cost</div><div class='sf-report__v'>—</div></div>"
    )


# --- DF#3, DF#4: numbers (ans:Q3, P5) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text", "title"),
    [
        (0.123456, "0.1235", "0.123456"),
        (90.0, "90", "90.0"),
        (2 / 3, "0.6667", "0.6666666666666666"),
        (12345.678, "1.235e+04", "12345.678"),
        (-1.5, "-1.5", "-1.5"),
        (0.0, "0", "0.0"),
    ],
)
def test_number_shows_four_significant_digits_and_the_exact_title(
    value: float, text: str, title: str
) -> None:
    assert number_html(value, "x") == f"<span class='sf-cmb__n' title='{title}'>{text}</span>"


def test_missing_number_is_an_em_dash_with_its_reason() -> None:
    expected = "<span class='sf-cmb__na' title='member failed: empty'>—</span>"

    assert number_html(None, "member failed: empty") == expected
    assert dash_html("member failed: empty") == expected


# --- DF#5: escaped reason (P8) -----------------------------------------------------------------


def test_reason_in_the_title_is_escaped() -> None:
    html = dash_html("a<b'c&")

    assert html == "<span class='sf-cmb__na' title='a&lt;b&#x27;c&amp;'>—</span>"
    assert number_html(None, "a<b'c&") == html


# --- DF#6, DF#7, DF#8: member value text (P7, P8) ----------------------------------------------


def test_text_cell_clips_at_80_characters() -> None:
    assert text_html("x" * 80, "r") == "x" * 80
    assert text_html("x" * 81, "r") == "x" * 80 + "…"
    # The clip counts the stored characters, then escapes: no entity is ever cut in half.
    assert text_html("<" * 81, "r") == "&lt;" * 80 + "…"
    # An empty value is a recorded value, not a missing one.
    assert text_html("", "r") == ""


def test_text_cell_escapes_markup() -> None:
    html = text_html("<img src=x onerror=evil()>", "r")

    assert html == "&lt;img src=x onerror=evil()&gt;"
    assert "<img" not in html


def test_missing_text_is_an_em_dash_with_its_reason() -> None:
    assert text_html(None, "member failed: empty") == (
        "<span class='sf-cmb__na' title='member failed: empty'>—</span>"
    )


# --- DF#9: the reason of a missing value follows the row status (MR-1..MR-3, P6) ----------------


def test_missing_reason_follows_the_status() -> None:
    vote = evidence_cases()["vote_one_failed"].members
    ranked = decode_combine_evidence(copy.deepcopy(_RANK_CUT_NOT_MET), "ev")
    assert ranked is not None

    assert (vote[1].status, vote[1].reason) == ("fail", "empty")
    assert missing_reason(vote[1], "value") == "member failed: empty"  # MR-1
    assert (ranked.members[1].status, ranked.members[1].reason) == ("excluded", "no_signal")
    assert missing_reason(ranked.members[1], "score") == "left out by the rule: no_signal"  # MR-2
    assert vote[0].status == "answered"
    assert missing_reason(vote[0], "weight") == "no weight recorded"  # MR-3


# --- DF#10: the style rules (P9) ---------------------------------------------------------------


def test_combine_style_is_scoped_themed_and_has_no_banned_token() -> None:
    assert STYLE.startswith("<style>")
    assert STYLE.endswith("</style>")
    body = STYLE.removeprefix("<style>").removesuffix("</style>")
    rule = r"([^{}]+)\{([^{}]*)\}"
    rules = {selectors.strip(): block for selectors, block in re.findall(rule, body)}

    assert rules
    assert re.sub(rule, "", body).strip() == ""  # nothing outside the rules
    for selectors in rules:
        for selector in selectors.split(","):
            assert selector.strip().startswith(".sf-cmb"), selector
    assert "#" not in body
    assert "<" not in body
    assert "rgb" not in body
    for token in _BANNED_TOKENS:
        assert token not in body, token
    for block in rules.values():
        for color in re.findall(r"(?<![-\w])color:([^;}]+)", block):
            assert color.strip().startswith("var(--sf-"), color
    assert "text-align:left" in rules[".sf-cmb__t th"]
    assert "text-align:left" in rules[".sf-cmb__t td"]
    assert rules[".sf-cmb__t tbody tr"] == "background:transparent!important"
    assert _STYLE.count(STYLE) == 1
    assert ACCOUNTING_STYLE + STYLE in _STYLE


# --- DF#11: no public name (ans:Q1, P17) --------------------------------------------------------


def test_combine_view_adds_no_public_name() -> None:
    assert getattr(combine_view, "__all__", None) == []

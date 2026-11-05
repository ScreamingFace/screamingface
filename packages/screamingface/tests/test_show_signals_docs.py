"""The README and the CHANGELOG describe E4b part 4, show signals (unit 5, docs).

FEATURE: a researcher reads the SDK README to learn where the report shows the combine steps, how
the numbers read, and what the JSON export holds (ans:Q1 to ans:Q3). The rows are DC#1 to DC#5 of
docs/spec/2026-10-15-e4b-show-signals/prd/docs.md. Part 4 adds no public name (ans:Q1), so these
tests read the docs only. ``_section`` flattens the whitespace, so a re-wrap of the README prose
does not break a test.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_evidence_completeness_docs import _section

_PACKAGE = Path(__file__).resolve().parents[1]
_README = _PACKAGE / "README.md"
_CHANGELOG = _PACKAGE / "CHANGELOG.md"
_HEADING = re.compile(r"^#{2,3} .*$", re.MULTILINE)
_BROWSE = "### Browse completed Case results"
_COMBINE = "### Combine steps in the report"
_ACCOUNTING = "### Completed accounting breakdown"
_PART_4 = "E4b part 4"
# The tokens that other docs tests count or pick in the Unreleased bullets (PRD docs §2):
# test_pick_output.py:273, test_mean.py:219, test_evidence_completeness_docs.py:105-110.
_COUNTED_TOKENS = (
    "`output_missing`",
    "`sf.Pick(",
    "`sf.Mean(",
    "`no_weight`",
    "`sf.report.CombineCut`",
    "`judge_operation_id`",
    "`sf.JudgeWriterWarning`",
)


def _headings_between(first: str, last: str) -> list[str]:
    """The ``##`` and ``###`` headings of the README from ``first`` up to, not with, ``last``."""

    text = _README.read_text(encoding="utf-8")
    start = text.index(f"\n{first}\n")
    end = text.index(f"\n{last}\n")
    return _HEADING.findall(text[start + 1 : end + 1])


def _unreleased() -> str:
    text = _CHANGELOG.read_text(encoding="utf-8")
    return text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]


def _first_features_bullets() -> list[str]:
    """The bullets under the FIRST ``### Features`` of ``## Unreleased``, in file order.

    WHY not ``_unreleased_entries``: ``## Unreleased`` has two ``### Features`` lists, and that
    helper does not tell them apart.
    """

    features = _unreleased().split("\n### Features\n", 1)[1].split("\n### ", 1)[0]
    return [entry.strip() for entry in features.split("\n* ")[1:]]


def _part_4_bullets() -> list[str]:
    return [entry for entry in _unreleased().split("\n* ") if _PART_4 in entry]


def test_readme_has_the_browse_and_accounting_sections_in_order() -> None:
    # DC#1 CHAR (README.md:1333, :1362): the two neighbours of the new section, in this order.
    text = _README.read_text(encoding="utf-8")
    assert text.count(f"\n{_BROWSE}\n") == 1
    assert text.count(f"\n{_ACCOUNTING}\n") == 1
    assert text.index(f"\n{_BROWSE}\n") < text.index(f"\n{_ACCOUNTING}\n")


def test_readme_documents_the_combine_section_the_summary_and_the_export() -> None:
    # DC#2 (DC-1, ans:Q1 to ans:Q3, N1): the section is directly after Browse, directly before
    # Accounting, and names the three surfaces, the number format and the export key.
    assert _headings_between(_BROWSE, _ACCOUNTING) == [_BROWSE, _COMBINE]
    section = _section(_COMBINE)
    for phrase in (
        "**The Case pane.**",
        "**The run summary.**",
        "**The export.**",
        "4 significant digits",
        "an em dash",
        "`trace`",
        "`report.trace_dict()`",
        "`whole@1`",
        "`json_object@1`",
    ):
        assert phrase in section, phrase


def test_deterministic_synthesizers_section_points_to_the_trace_key() -> None:
    # DC#3 (DC-D2): the sentence about report.v1 now names the trace key and the new section.
    synthesizers = _section("### Deterministic synthesizers")
    assert "each Case with a combine step also has a `trace` key" in synthesizers
    assert '(see "Combine steps in the report")' in synthesizers
    assert "`report.to_dict()` and `report.export()` stay `report.v1`" in synthesizers


def test_changelog_has_one_part_4_bullet_first_in_features() -> None:
    # DC#4 (DC-2): one part 4 bullet, the first under the first Features list, before part 3.
    assert len(_part_4_bullets()) == 1
    bullets = _first_features_bullets()
    assert _PART_4 in bullets[0]
    assert bullets[0].endswith("No Engine change.")
    assert "(E4b part 3)" in bullets[1]
    assert 'the README section "Signal sources"' in bullets[1]


def test_part_4_bullet_holds_no_token_that_other_docs_tests_count() -> None:
    # DC#5 (DC-D1): the existing docs tests keep their bullet counts and their picks.
    bullets = _part_4_bullets()
    assert len(bullets) == 1
    for token in _COUNTED_TOKENS:
        assert token not in bullets[0], token

"""The README and the CHANGELOG describe E4b part 2, evidence completeness (unit 6, docs).

FEATURE: a researcher reads the SDK README to learn what the combine evidence and the trace say.
Each test first checks that the branch code has the public name, then that the doc names it, so
a doc cannot describe a name that the code does not have. The PRDs name no doc test. These are
unit-local guards (D6#1 to D6#4). The README text is compared with its whitespace flattened, so a
re-wrap of the prose does not break a test.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import screamingface as sf
from screamingface import report
from screamingface.answer import ANSWER_REASONS, ANSWER_STATUSES, MEMBER_STATUSES
from screamingface.combine_evidence import CombineAnswerRow, CombineEvidence
from screamingface.report_trace import TRACE_FIELDS

_PACKAGE = Path(__file__).resolve().parents[1]
_README = _PACKAGE / "README.md"
_CHANGELOG = _PACKAGE / "CHANGELOG.md"
_NEXT_HEADING = re.compile(r"^#{2,3} ", re.MULTILINE)
_EXCLUDED_SIGNAL = 'the status `"excluded"` and the reason `no_signal`'
_EXCLUDED_WEIGHT = 'the status `"excluded"` and the reason `no_weight`'


def _section(heading: str) -> str:
    """The README text under ``heading``, up to the next ``##`` or ``###`` heading, flattened."""

    text = _README.read_text(encoding="utf-8")
    assert heading in text, f"README.md has no {heading!r} section"
    rest = text[text.index(heading) + len(heading) :]
    end = _NEXT_HEADING.search(rest)
    body = rest if end is None else rest[: end.start()]
    return " ".join(body.split())


def _unreleased_entries() -> list[str]:
    text = _CHANGELOG.read_text(encoding="utf-8")
    unreleased = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    return unreleased.split("\n* ")


def test_readme_documents_the_excluded_status_and_its_two_reasons() -> None:
    # D6#1 (ans:Q3, P2-P5): the code has the words, and the README says where they appear.
    assert "excluded" in ANSWER_STATUSES
    assert "excluded" in MEMBER_STATUSES
    assert {"no_signal", "no_weight"} <= ANSWER_REASONS

    synthesizers = _section("### Deterministic synthesizers")
    assert "**Members left out.**" in synthesizers
    assert '`status: "excluded"`' in synthesizers
    assert 'sf.Answer(status="excluded", reason="no_signal")' in synthesizers
    assert "`dropped` and the quorum count only failed members" in synthesizers
    assert "Fixed weights (a list) never leave a member out." in synthesizers
    # the weighted median, the mean and the weighted vote each say it once
    assert synthesizers.count(_EXCLUDED_WEIGHT) == 3
    for heading in (
        "### Pick and merge JSON fields",
        "### Rank and Concat selections",
        "### Filter selection",
    ):
        assert _EXCLUDED_SIGNAL in _section(heading), heading


def test_readme_rank_section_documents_the_rank_and_the_cut() -> None:
    # D6#2 (P6, P7, P14). Oracle: PRD rank-and-cut RK-1, hand-computed (min order, costs
    # member_1 0.03, member_2 0.01, member_3 0.02, member_4 0.01 -> 2, 4, 3, 1).
    assert "rank" in {f.name for f in dataclasses.fields(CombineAnswerRow)}
    assert "cut" in {f.name for f in dataclasses.fields(CombineEvidence)}
    assert [f.name for f in dataclasses.fields(report.CombineCut)] == ["k", "order"]

    rank = _section("### Rank and Concat selections")
    assert "**Rank and cut in the evidence.**" in rank
    assert "`CombineAnswerRow.rank`" in rank
    assert "`sf.report.CombineCut`" in rank
    assert "the ranks are member_2 1, member_4 2, member_3 3 and member_1 4" in rank
    assert 'the cut is `{"k": 2, "order": "min"}`' in rank
    assert "`cut_not_met`, the ranks and the cut are still written" in rank


def test_readme_judge_section_documents_the_trace_link_and_the_warning() -> None:
    # D6#3 (ans:Q1, ans:Q2, ans:Q4, P8-P10).
    assert {"judge_operation_id", "judge_model"} <= set(TRACE_FIELDS["reduce"])
    assert issubclass(sf.JudgeWriterWarning, sf.EvaluationWarning)
    assert "JudgeWriterWarning" in sf.__all__

    judge = _section("### Judge synthesizer")
    assert "**The judge in the trace.**" in judge
    assert "`judge_operation_id`" in judge
    assert "`judge_model`" in judge
    assert "The `combine` evidence itself has no judge model." in judge
    assert "**The judge and the writer.**" in judge
    assert "`sf.JudgeWriterWarning`" in judge
    assert "It does not stop the run and does not change the url4." in judge
    assert 'warnings.filterwarnings("ignore", category=sf.JudgeWriterWarning)' in judge


def test_changelog_has_the_four_part_2_bullets_after_the_pick_output_bullet() -> None:
    # D6#4: one bullet per feature, in this order, right after the pick-output bullet.
    entries = _unreleased_entries()
    markers = (
        "`no_weight`",
        "`sf.report.CombineCut`",
        "`judge_operation_id`",
        "`sf.JudgeWriterWarning`",
    )
    for marker in markers:
        assert len([entry for entry in entries if marker in entry]) == 1, marker
    anchor = next(i for i, entry in enumerate(entries) if "`output_missing`" in entry)
    for offset, marker in enumerate(markers, start=1):
        assert marker in entries[anchor + offset], marker
    for entry in entries[anchor + 1 : anchor + 3]:
        assert "**Requires an SF Engine and an SDK from the same E4b release" in entry
    for entry in entries[anchor + 3 : anchor + 5]:
        assert entry.rstrip().endswith("No Engine change.")

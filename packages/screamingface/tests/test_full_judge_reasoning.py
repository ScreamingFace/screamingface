"""A judge's reasoning longer than the preview stays readable in full (OME-1340).

FEATURE: the report cut a criterion's reasoning at 400 characters and nothing held the
rest — about one in five HealthBench reasonings lost their ending, and an imported
board's whole-rubric breakdown (~2,800 characters) showed only its first item.
STORY: as a researcher reading a judged case, I see a short preview under the verdict
and can open the judge's full reasoning, line breaks intact, without leaving the notebook.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape

import screamingface as sf
from screamingface._ui.report_view import report_html
from screamingface.case_result import CaseGrade, CaseResult, Check, Evidence, EvidenceProducer
from screamingface.operation import OperationInfo
from screamingface.report import BenchmarkInfo, CandidateResult, Report

_BENCHMARK = BenchmarkInfo(id="inspect-frontierscience", revision="r1", case_count=1)
_START = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
_END = datetime(2026, 9, 25, 10, 5, tzinfo=UTC)
# The preview length the report keeps under every verdict.
_PREVIEW = 400
_FULL_BLOCK = "sf-check__full"


def _report(explanation: str) -> Report:
    """A one-case report whose single criterion carries ``explanation`` as its reasoning."""
    check = Check(
        type="criterion",
        id="rubric",
        label="inspect scorer verdict",
        outcome="UNMET",
        evidence=[
            Evidence(
                sequence=1,
                producer=EvidenceProducer("scorer", "inspect/scorer"),
                valid=True,
                raw_output=explanation,
                outcome="UNMET",
                explanation=explanation,
            )
        ],
        metadata={"criterion_type": "positive"},
    )
    case = CaseResult(
        case_id=1,
        input="the prompt",
        output="the answer",
        finish_reason="stop",
        grade=CaseGrade(method="rubric", score=0.3, metrics={}, checks=[check]),
        failures=[],
        metadata={},
    )
    candidate = CandidateResult(
        benchmark=_BENCHMARK,
        run_id="run-m",
        started_at=_START,
        completed_at=_END,
        name="m",
        kind="model",
        url4="(candidate:0.0:'(m:0.0:/openrouter/x)!\\'$m\\'')!''",
        models=["openrouter/x"],
        operations=[OperationInfo(id="op", kind="model", label="answer", depends_on=())],
        score=0.3,
        coverage=1.0,
        metrics={"mean": 0.3},
        cases=[case],
        members=[],
        failures=[],
        usage=sf.Usage(input_tokens=10, output_tokens=10),
    )
    return Report(benchmark=_BENCHMARK, case_count=1, candidates=[candidate])


def _check_row(explanation: str) -> str:
    """The rendered criterion row — the one element this feature changes."""
    html: str = report_html(_report(explanation))
    start: int = html.index("<div class='sf-check'>")
    return html[start : html.index("<span class='sf-badge", start)]


def _full_text(row: str) -> str:
    """The unescaped text inside the full-reasoning block, as the reader sees it."""
    match: re.Match[str] | None = re.search(
        r"<div class='sf-check__full-text'>(.*?)</div></details>", row, re.S
    )
    assert match is not None, "no full-reasoning block rendered"
    return unescape(match.group(1))


def _breakdown(items: int) -> str:
    """A judge's per-item rubric breakdown, one item per line, like inspect graders write."""
    return "\n".join(
        f"Item {n}: earned 1 of 2 points, because the answer names the mechanism "
        f"but gives no evidence for step {n}."
        for n in range(1, items + 1)
    )


def test_long_reasoning_keeps_the_preview_and_adds_the_full_text() -> None:
    reasoning: str = _breakdown(8)
    assert len(reasoning) > _PREVIEW
    row: str = _check_row(reasoning)

    # The preview is today's clipped row, so the verdict area still scans at a glance.
    assert f"… {len(reasoning) - _PREVIEW:,} more characters" in row
    # The items past the cut — the ones that decide the score — are now reachable.
    assert f"<details class='{_FULL_BLOCK}'><summary>full reasoning</summary>" in row
    assert _full_text(row) == reasoning
    assert "Item 8:" in _full_text(row)


def test_reasoning_at_exactly_the_preview_length_gets_no_toggle() -> None:
    at_limit: str = "x" * _PREVIEW
    over_limit: str = "x" * (_PREVIEW + 1)

    # WHY: a toggle revealing nothing new would be noise on every short criterion.
    assert _FULL_BLOCK not in _check_row(at_limit)
    assert _FULL_BLOCK in _check_row(over_limit)
    assert _full_text(_check_row(over_limit)) == over_limit


def test_short_reasoning_renders_exactly_as_before() -> None:
    row: str = _check_row("It fails to specify 'variance-weighted'.")

    # INVARIANT: the common case is untouched — same row, byte for byte, no toggle.
    assert (
        "<div class='sf-check__why'>It fails to specify &#x27;variance-weighted&#x27;.</div>"
        "</span>" in row
    )
    assert _FULL_BLOCK not in row


def test_markup_only_in_the_full_text_is_escaped() -> None:
    # The payload sits past the preview cut, so ONLY the full-text block carries it.
    reasoning: str = "a" * (_PREVIEW + 10) + "<script>alert('judge')</script>"
    row: str = _check_row(reasoning)

    # INVARIANT: judge output is untrusted model text; at full length it is still text.
    assert "<script>" not in row
    assert "&lt;script&gt;" in row
    assert _full_text(row) == reasoning


def test_the_full_text_keeps_the_judges_line_breaks() -> None:
    reasoning: str = _breakdown(8)
    html: str = report_html(_report(reasoning))

    assert "Item 1:" in _full_text(_check_row(reasoning))
    assert "\nItem 2:" in _full_text(_check_row(reasoning))
    # WHY: HTML merges newlines into spaces unless the block preserves them — without
    # this rule an 8-item breakdown would render as one wall of text.
    rule: re.Match[str] | None = re.search(r"\.sf-check__full-text\{([^}]*)\}", html)
    assert rule is not None
    assert "white-space:pre-wrap" in rule.group(1)


def test_opening_the_full_text_hides_the_now_redundant_preview() -> None:
    html: str = report_html(_report(_breakdown(8)))

    # WHY: open, the full text starts with the preview's 400 characters — showing both
    # would make the reader read the opening twice.
    assert ".sf-check__label:has(>.sf-check__full[open])>.sf-check__why{display:none}" in html

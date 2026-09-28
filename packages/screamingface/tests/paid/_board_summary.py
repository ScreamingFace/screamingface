"""The paid smoke's overview: what each board did, read back from its kept Report.

Mental model: the smoke is a referee (pass/fail on infrastructure codes only); this
module is the scoreboard beside it. It turns each board's exported Report into one
stats line under the board's progress line, an end-of-run table in the log, and the
same table in Markdown for the CI run page. A dev or researcher sees the whole
press at a glance: did grading run, what it cost, which board is near the token cap.

Worked example: a board with Cases [scored, failed(missing_case_row wrapping
model_token_cap)] and usage {cost 0.0032, out 16400, reasoning 14100} reads

    graded 1/2 · correct 1/1 · $0.0032 · out 16.4k (reasoning 14.1k) · run 7f3a91c2
    └─ model_token_cap ×1 (reported as missing_case_row)

INVARIANT: a view, never a verdict. Nothing here decides pass/fail, so "correct"
(2 Cases of noise) can never fail a board; it is a hint that answer extraction
works, not a score.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

_INDENT: Final = "    "
_SECONDS_PER_MINUTE: Final = 60
_THOUSAND: Final = 1000
_RUN_ID_CHARS: Final = 8


@dataclass(frozen=True)
class BoardSummary:
    """One finished board's overview; the numbers are None when no Report was kept."""

    board: str
    problems: tuple[str, ...]
    seconds: float
    cases: int | None = None
    graded: int | None = None
    correct: int | None = None
    scored: int | None = None
    cost_usd: Decimal | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    run_id: str | None = None
    failure_codes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Healthy when the referee found no problem — the only pass/fail source."""
        return not self.problems


def summarize_board(
    board: str, problems: list[str], seconds: float, report_path: Path
) -> BoardSummary:
    """Read one board's kept Report back into its overview.

    Stages: (1) load the export; a board that raised has none, so its numbers stay
    None rather than showing zeros as if measured; (2) count graded Cases and read
    the candidate's metrics, usage and run id; (3) collapse failure codes, putting a
    wrapped code's real reason first (OME-1390: token exhaustion arrives as
    `missing_case_row` with the real code in `metadata.source_error`).

    Args:
        board: the imported benchmark id.
        problems: the referee's verdict for this board (empty = healthy).
        seconds: the board's wall time.
        report_path: where `_smoke_one_board` kept the board's Report export.

    Returns:
        The overview; stats fields are None when the Report is missing or unreadable.
    """
    # Stage 1 — load the kept Report, if there is one.
    try:
        exported: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
        candidate: dict[str, Any] = exported["candidates"][0]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return BoardSummary(board, tuple(problems), seconds)

    # Stage 2 — graded Cases, metrics, usage, run id.
    cases: list[dict[str, Any]] = candidate.get("cases") or []
    metrics: dict[str, Any] = candidate.get("metrics") or {}
    usage: dict[str, Any] = candidate.get("usage") or {}
    return BoardSummary(
        board=board,
        problems=tuple(problems),
        seconds=seconds,
        cases=len(cases),
        graded=sum(1 for case in cases if case.get("status") == "scored"),
        correct=_int_or_none(metrics.get("correct")),
        scored=_int_or_none(metrics.get("scored_cases")),
        cost_usd=_decimal_or_none(usage.get("cost_usd")),
        output_tokens=_int_or_none(usage.get("output_tokens")),
        reasoning_tokens=_int_or_none(usage.get("reasoning_tokens")),
        run_id=candidate.get("run_id"),
        # Stage 3 — collapsed failure codes, real reason first.
        failure_codes=_failure_codes(cases),
    )


def detail_lines(summary: BoardSummary) -> list[str]:
    """The lines printed under a board's progress line: stats, then its codes."""
    if summary.cases is None:
        return [f"{_INDENT}no report kept — see the failure block below"]
    parts: list[str] = [
        f"graded {summary.graded}/{summary.cases}",
        f"correct {_fraction(summary.correct, summary.scored)}",
        _cost(summary.cost_usd),
        f"out {_tokens(summary.output_tokens)}{_reasoning(summary.reasoning_tokens)}",
    ]
    if summary.run_id:
        parts.append(f"run {summary.run_id[:_RUN_ID_CHARS]}")
    lines: list[str] = [_INDENT + " · ".join(parts)]
    if summary.failure_codes:
        lines.append(f"{_INDENT}└─ {', '.join(summary.failure_codes)}")
    return lines


def run_summary_lines(summaries: list[BoardSummary], wall_seconds: float) -> list[str]:
    """The end-of-run block: press totals, then one line per failed board."""
    lines: list[str] = [f"[paid smoke] {_totals(summaries, wall_seconds)}"]
    for summary in _failed_first(summaries):
        if summary.ok:
            continue
        codes: str = ", ".join(summary.failure_codes) or "see the failure block below"
        graded: str = _fraction(summary.graded, summary.cases)
        lines.append(f"  FAILED  {summary.board}  graded {graded}  {codes}")
    return lines


def run_summary_markdown(summaries: list[BoardSummary], wall_seconds: float) -> str:
    """The same overview as a Markdown table for the CI run page, failed boards first."""
    rows: list[str] = [
        f"### Paid smoke — {_totals(summaries, wall_seconds)}",
        "",
        "| Board | Verdict | Graded | Correct | Cost | Output tokens | Time | Run "
        "| Failure codes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for summary in _failed_first(summaries):
        verdict: str = "✅ ok" if summary.ok else "❌ failed"
        run: str = (summary.run_id or "—")[:_RUN_ID_CHARS]
        rows.append(
            f"| {summary.board} | {verdict} | {_fraction(summary.graded, summary.cases)} "
            f"| {_fraction(summary.correct, summary.scored)} | {_cost(summary.cost_usd)} "
            f"| {_tokens(summary.output_tokens)} | {round(summary.seconds)}s | {run} "
            f"| {', '.join(summary.failure_codes) or '—'} |"
        )
    return "\n".join(rows) + "\n"


def _totals(summaries: list[BoardSummary], wall_seconds: float) -> str:
    """One line of press totals — the first thing a reader of the log or CI page sees."""
    healthy: int = sum(1 for summary in summaries if summary.ok)
    graded: int = sum(summary.graded or 0 for summary in summaries)
    cases: int = sum(summary.cases or 0 for summary in summaries)
    cost: Decimal = sum((summary.cost_usd or Decimal(0) for summary in summaries), Decimal(0))
    minutes, seconds = divmod(round(wall_seconds), _SECONDS_PER_MINUTE)
    return (
        f"{healthy}/{len(summaries)} ok · {len(summaries) - healthy} failed · "
        f"{graded} Cases graded / {cases} · {_cost(cost)} total · {minutes}m{seconds:02d}s wall"
    )


def _failed_first(summaries: list[BoardSummary]) -> list[BoardSummary]:
    """Failed boards first, each group alphabetical — stable across presses."""
    return sorted(summaries, key=lambda summary: (summary.ok, summary.board))


def _failure_codes(cases: list[dict[str, Any]]) -> tuple[str, ...]:
    """Count failure codes across Cases, naming a wrapped code by its real reason."""
    counted: Counter[tuple[str, str | None]] = Counter()
    for case in cases:
        for failure in case.get("failures") or []:
            outer: str = str(failure.get("code"))
            source: Any = ((failure.get("metadata") or {}).get("source_error") or {}).get("code")
            wrapped: str | None = outer if source and source != outer else None
            counted[(str(source) if wrapped else outer, wrapped)] += 1
    return tuple(
        f"{code} ×{count}" + (f" (reported as {wrapped})" if wrapped else "")
        for (code, wrapped), count in counted.items()
    )


def _fraction(numerator: int | None, denominator: int | None) -> str:
    """`k/n`, or an em dash when the Report did not carry the numbers."""
    if numerator is None or denominator is None:
        return "—"
    return f"{numerator}/{denominator}"


def _cost(cost: Decimal | None) -> str:
    """Dollars to four places — flash-model boards cost fractions of a cent."""
    return "$—" if cost is None else f"${cost:.4f}"


def _tokens(count: int | None) -> str:
    """Token counts in thousands once they pass 1000 (16400 → 16.4k)."""
    if count is None:
        return "—"
    return str(count) if count < _THOUSAND else f"{count / _THOUSAND:.1f}k"


def _reasoning(count: int | None) -> str:
    """The reasoning share of the output — the part that runs into the token cap."""
    return f" (reasoning {_tokens(count)})" if count else ""


def _int_or_none(value: Any) -> int | None:
    """An exported integer field, or None when the Report lacks it."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decimal_or_none(value: Any) -> Decimal | None:
    """The exported cost string as a Decimal, or None when absent or malformed."""
    try:
        return None if value is None else Decimal(str(value))
    except InvalidOperation:
        return None

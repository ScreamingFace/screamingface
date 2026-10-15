"""Free tests: each board's overview (log line, end-of-run table, CI page table).

INVARIANT: the overview is a VIEW of the kept Report, never a verdict. Pass/fail
still comes only from infrastructure failure codes; graded/correct/cost/tokens are
there so a dev or researcher sees the whole press at a glance: did grading run,
where the money went, which board is close to the token budget.
"""

from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from _board_summary import (
    BoardSummary,
    detail_lines,
    run_summary_lines,
    run_summary_markdown,
    summarize_board,
)


def _case(status: str, *failures: dict[str, Any]) -> dict[str, Any]:
    """One exported Case with its status and failures."""
    return {"status": status, "failures": list(failures)}


def _wrapped_token_cap() -> dict[str, Any]:
    """The shape the first press saw: the real code hides under missing_case_row."""
    return {
        "code": "missing_case_row",
        "metadata": {"source_error": {"code": "model_token_cap"}},
    }


def _write_report(path: Path, cases: list[dict[str, Any]], **candidate: Any) -> Path:
    """Write a Report export shaped like the SDK's (the fields the overview reads)."""
    body: dict[str, Any] = {
        "run_id": "7f3a91c2d4e5",
        "metrics": {"correct": 1, "scored_cases": 1},
        "usage": {"cost_usd": "0.0032", "output_tokens": 16400, "reasoning_tokens": 14100},
        "cases": cases,
    }
    body.update(candidate)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidates": [body]}), encoding="utf-8")
    return path


def test_summary_reads_graded_correct_cost_tokens_and_run_id(tmp_path: Path) -> None:
    """Every overview number comes from the kept Report, so the log matches the evidence."""
    report: Path = _write_report(
        tmp_path / "inspect-demo.json", [_case("scored"), _case("failed", _wrapped_token_cap())]
    )

    summary: BoardSummary = summarize_board("inspect-demo", ["p"], 252.4, report)

    assert (summary.graded, summary.cases) == (1, 2)
    assert (summary.correct, summary.scored) == (1, 1)
    assert summary.cost_usd == Decimal("0.0032")
    assert (summary.output_tokens, summary.reasoning_tokens) == (16400, 14100)
    assert summary.run_id == "7f3a91c2d4e5"


def test_wrapped_failure_shows_its_real_code(tmp_path: Path) -> None:
    """missing_case_row hides model_token_cap (OME-1390): show the real reason first."""
    report: Path = _write_report(
        tmp_path / "b.json",
        [_case("failed", _wrapped_token_cap()), _case("failed", _wrapped_token_cap())],
    )

    summary: BoardSummary = summarize_board("b", ["p"], 1.0, report)

    assert summary.failure_codes == ("model_token_cap ×2 (reported as missing_case_row)",)


def test_board_without_a_report_says_so_instead_of_inventing_numbers(tmp_path: Path) -> None:
    """evaluate raised → no Report kept; the overview must not show zeros as if measured."""
    summary: BoardSummary = summarize_board("b", ["raised"], 3.0, tmp_path / "missing.json")

    assert summary.cases is None
    assert detail_lines(summary) == ["    no report kept — see the failure block below"]


def test_healthy_board_detail_is_one_line_of_stats(tmp_path: Path) -> None:
    """A healthy board costs one extra line: graded, correct, cost, tokens, run id."""
    report: Path = _write_report(tmp_path / "ok.json", [_case("scored"), _case("scored")])

    lines: list[str] = detail_lines(summarize_board("ok", [], 18.0, report))

    assert lines == [
        "    graded 2/2 · correct 1/1 · $0.0032 · out 16.4k (reasoning 14.1k) · run 7f3a91c2"
    ]


def test_failed_board_detail_adds_its_codes_indented(tmp_path: Path) -> None:
    """The why sits right under the board, so a reader needn't scroll to the final block."""
    report: Path = _write_report(tmp_path / "f.json", [_case("failed", _wrapped_token_cap())])

    lines: list[str] = detail_lines(summarize_board("f", ["p"], 5.0, report))

    assert lines[1] == "    └─ model_token_cap ×1 (reported as missing_case_row)"


def _summaries(tmp_path: Path) -> list[BoardSummary]:
    """One healthy and one failed board, as a finished press would hold them."""
    ok: Path = _write_report(tmp_path / "ok.json", [_case("scored"), _case("scored")])
    bad: Path = _write_report(
        tmp_path / "bad.json",
        [_case("failed", _wrapped_token_cap()), _case("failed", _wrapped_token_cap())],
        usage={"cost_usd": "0.0100", "output_tokens": 500, "reasoning_tokens": 0},
    )
    return [
        summarize_board("inspect-ok", [], 18.0, ok),
        summarize_board("inspect-bad", ["p"], 252.0, bad),
    ]


def test_run_summary_totals_the_press_and_lists_only_failed_boards(tmp_path: Path) -> None:
    """Healthy boards collapse into the header counts; failed ones get a line each."""
    lines: list[str] = run_summary_lines(_summaries(tmp_path), wall_seconds=1022.0)

    assert lines[0] == (
        "[paid smoke] 1/2 ok · 1 failed · 2 Cases graded / 4 · $0.0132 total · 17m02s wall"
    )
    assert lines[1:] == [
        "  FAILED  inspect-bad  graded 0/2  model_token_cap ×2 (reported as missing_case_row)"
    ]


def test_markdown_table_lists_failed_boards_first(tmp_path: Path) -> None:
    """The CI run page shows the same overview; the failures are the rows read first."""
    markdown: str = run_summary_markdown(_summaries(tmp_path), wall_seconds=1022.0)
    rows: list[str] = [line for line in markdown.splitlines() if line.startswith("| inspect-")]

    assert "1/2 ok · 1 failed" in markdown
    assert rows[0].startswith("| inspect-bad | ❌ failed | 0/2 |")
    assert rows[1].startswith("| inspect-ok | ✅ ok | 2/2 |")


def test_markdown_table_ends_with_a_total_row(tmp_path: Path) -> None:
    """The last row totals the press, so a reader never adds a column by hand.

    Time is the press's WALL time, not the sum of board times: boards run in
    parallel, so their times overlap and a sum would overstate how long it took.
    Failure codes aggregate across boards with the wrapped reason kept.
    """
    markdown: str = run_summary_markdown(_summaries(tmp_path), wall_seconds=1022.0)
    last_row: str = markdown.rstrip("\n").splitlines()[-1]

    assert last_row == (
        "| **Total** | 1/2 ok | 2/4 | 2/2 | $0.0132 | 16.9k | 17m02s wall | — "
        "| model_token_cap ×2 (reported as missing_case_row) |"
    )


# --- Warnings (OME-1527 row 15b): loud in every overview, never a failure. ---


def _warned(tmp_path: Path) -> list[BoardSummary]:
    """A healthy Corrective Loop entry whose chain did not run, beside a healthy board."""
    report: Path = _write_report(tmp_path / "ok.json", [_case("scored"), _case("scored")])
    loop: BoardSummary = summarize_board("ifeval · corrective loop", [], 30.0, report)
    return [
        dataclasses.replace(loop, warnings=("chain not exercised: x",)),
        summarize_board("inspect-ok", [], 18.0, report),
    ]


def test_a_warning_never_fails_the_board(tmp_path: Path) -> None:
    """Owner decision: a press where every Case passed round 1 is unlucky, not broken."""
    loop: BoardSummary = _warned(tmp_path)[0]

    assert loop.ok
    assert detail_lines(loop)[-1] == "    WARNING chain not exercised: x"


def test_the_log_block_and_the_run_page_both_carry_the_warning(tmp_path: Path) -> None:
    """The warning sits where the owner reads the verdict: the end-of-run block and the
    CI page, under the table so the table's own last row stays the total."""
    summaries: list[BoardSummary] = _warned(tmp_path)

    lines: list[str] = run_summary_lines(summaries, wall_seconds=60.0)
    markdown: str = run_summary_markdown(summaries, wall_seconds=60.0)

    assert lines[0].startswith("[paid smoke] 2/2 ok · 0 failed")
    assert lines[1:] == ["  WARNING  ifeval · corrective loop  chain not exercised: x"]
    assert markdown.rstrip("\n").splitlines()[-1] == (
        "> ⚠️ **ifeval · corrective loop** — chain not exercised: x"
    )

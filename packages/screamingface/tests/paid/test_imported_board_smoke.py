"""The paid smoke: every Benchmark the Engine serves runs once for real (OME-1275).

FEATURE: a cheap owner-pressed button that re-proves the whole shelf's product pipe —
SDK → gateway → OpenRouter → engine grading — after any refactor. The shelf is every
Benchmark the live Engine lists, Imported and hand-built, narrowed by the button's
`scope` choice (`_scope.py`).

STORY: as the owner, before citing "every Benchmark runs", I run
`just screamingface test-paid-benchmarks` and get, for a small bounded spend, either a
green run or the exact Benchmark + failure code that broke.

WHY shape-only assertions: scores are nondeterministic and protected elsewhere (the
golden replay lane). This lane fails ONLY on infrastructure failure codes; a wrong,
refused, or truncated model answer still passes, because model quality is not wiring.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _board_summary import (
    BoardSummary,
    detail_lines,
    run_summary_lines,
    run_summary_markdown,
    summarize_board,
)
from _case_provenance import provenance_markdown
from _panel import BOARD_CONCURRENCY, CASE_LIMIT, fusion_panel
from _scope import SCOPE_ENV, pick_shelf, resolve_scope
from conftest import PaidStack, assets_root

if TYPE_CHECKING:
    import screamingface as _sf

pytestmark = pytest.mark.paid

# WHY a tolerance list instead of `Failure.retryable`: these four codes are the
# model/provider BEHAVING badly through a correctly wired pipe (a refusal, a token
# cap, an empty reply, a 429). Every other declared code — the aigateway_http_*
# family, benchmark_unavailable, contract/grading errors — means OUR pipe broke,
# which is exactly what this lane exists to catch. `retryable` can be None and
# would let a permanent wiring failure hide behind a transient label.
#
# WHY judged boards stay strict too: on an LLM-judged board (frontierscience), a
# rate-limited or failing JUDGE surfaces as `scorer_error`, not `rate_limited` —
# the wrapped scorer cannot tell "judge busy" from "judge route broken". Grading is
# the exact seam this lane guards, so it fails; a genuine judge 429 costs a rerun.
TOLERATED_MODEL_SIDE_CODES: frozenset[str] = frozenset(
    {
        "provider_refusal",
        "model_token_cap",
        "model_empty_content",
        "rate_limited",
    }
)


def test_every_benchmark_runs_end_to_end(
    paid_stack: PaidStack, capsys: pytest.CaptureFixture[str]
) -> None:
    """INVARIANT: each picked Benchmark's full product pipe can execute a real run.

    One loop, not per-board parametrize: the board list lives on the live engine,
    which does not exist at collection time (the SDK venv cannot import the engine).
    The loop collects every board's verdict so one broken board never hides the
    rest, and the final assertion message carries board name + stage + code.
    """
    import screamingface as sf

    # The paid_stack fixture already refused an unknown scope before booting.
    scope: str = resolve_scope(os.environ.get(SCOPE_ENV))
    with sf.Client(engine_url=paid_stack.engine_url) as client:
        listed: list[tuple[str, str]] = [
            (benchmark.id, benchmark.origin) for benchmark in client.benchmarks.list()
        ]
    boards, shelf_problems = pick_shelf(listed, scope)
    # A picked kind with nothing listed (e.g. an engine booted without the inspect
    # extra) is a lane bug, not a Benchmark bug; fail here before spending anything.
    assert not shelf_problems, "\n".join(shelf_problems)

    # WHY print past pytest's capture: this is one test looping over the whole
    # shelf, so `-v` shows a single line until every board is done. The owner
    # watching a press (terminal or CI log) needs to see a broken board the
    # moment it finishes, not after the whole paid run.
    with capsys.disabled():
        print(
            f"\n[paid smoke] scope {scope}: {len(boards)} Benchmarks, {CASE_LIMIT} Cases each, "
            f"{BOARD_CONCURRENCY} at a time",
            flush=True,
        )

    # WHY parallel boards: reasoning boards take minutes each, so a serial shelf ran
    # for about an hour. Cost is unchanged, since every board still runs once.
    # WHY one client per board: a worker thread owns its client for the whole run;
    # none is shared across threads. Progress prints from THIS thread only, because
    # `capsys.disabled()` toggles global capture state and is not thread-safe.
    open_client: Callable[[], AbstractContextManager[_sf.Client]] = partial(
        sf.Client, engine_url=paid_stack.engine_url
    )
    press_started: float = time.monotonic()
    summaries: list[BoardSummary] = _run_shelf(
        open_client, boards, paid_stack.log_dir / "reports", capsys
    )
    # The press overview, written BEFORE the verdict so a failing press still leaves it.
    _publish_overview(summaries, time.monotonic() - press_started, paid_stack.log_dir, capsys)

    problems: list[str] = [problem for summary in summaries for problem in summary.problems]
    assert not problems, (
        "Benchmarks failed the paid smoke (Benchmark: stage/code — message):\n"
        + "\n".join(problems)
    )


def _run_shelf(
    open_client: Callable[[], AbstractContextManager[_sf.Client]],
    boards: list[str],
    reports_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> list[BoardSummary]:
    """Smoke every board, BOARD_CONCURRENCY at a time, printing each as it finishes.

    Stages: (1) submit one worker per board, each on its own client; (2) as each
    finishes (completion order), read its kept Report back into an overview and
    print the progress line plus its stats under it. Prints happen on this thread only.

    WHY read the kept Report back: the overview (graded, correct, cost, tokens, run
    id) is a view of the evidence `_smoke_one_board` already wrote, so the log line
    and the report on disk can never disagree.

    Args:
        open_client: builds a fresh client context manager per worker.
        boards: the picked Benchmark ids, from the live engine (see `_scope.pick_shelf`).
        reports_dir: where each board's Report is kept as ``<board>.json``.
        capsys: pytest's capture fixture, used to print past the capture.

    Returns:
        One overview per board, in completion order; their problems are the verdict.
    """
    summaries: list[BoardSummary] = []
    # Stage 1 — one worker per board.
    with ThreadPoolExecutor(max_workers=BOARD_CONCURRENCY) as pool:
        running: dict[Future[tuple[list[str], float]], str] = {
            pool.submit(_smoke_board_timed, open_client, board, reports_dir): board
            for board in boards
        }
        # Stage 2 — overview + print, in completion order.
        for finished, future in enumerate(as_completed(running), start=1):
            board_problems, seconds = future.result()
            board: str = running[future]
            summary: BoardSummary = summarize_board(
                board, board_problems, seconds, reports_dir / f"{board}.json"
            )
            summaries.append(summary)
            line: str = _progress_line(finished, len(boards), board, board_problems, seconds)
            with capsys.disabled():
                print("\n".join([line, *detail_lines(summary)]), flush=True)
    return summaries


def _publish_overview(
    summaries: list[BoardSummary],
    wall_seconds: float,
    log_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print the press totals block and keep `summary.md` for the bundle and CI page.

    The workflow appends `summary.md` to the run page. A failed write only warns:
    the overview is a convenience and must never replace the real verdict. Under the
    table, "Where the Cases came from" reads each bundle's provenance.json (OME-1492).
    """
    with capsys.disabled():
        print("\n" + "\n".join(run_summary_lines(summaries, wall_seconds)), flush=True)
    try:
        (log_dir / "summary.md").write_text(
            run_summary_markdown(summaries, wall_seconds)
            + "\n"
            + provenance_markdown([summary.board for summary in summaries], assets_root()),
            encoding="utf-8",
        )
    except OSError as exc:
        with capsys.disabled():
            print(f"[paid smoke] could not write summary.md — {exc}", flush=True)


def _progress_line(
    position: int, total: int, board: str, problems: list[str], seconds: float
) -> str:
    """Say one finished board's verdict in a single line the owner can scan live.

    Example: board 4 of 24 with one infrastructure problem after 7.0s reads
    ``[4/24] inspect-frontierscience … FAILED: 1 problem (7s)``; a healthy board
    reads ``… ok (42s)``. The problem text itself stays in the final assertion.

    Args:
        position: how many boards have finished, this one included (boards run in
            parallel, so this is completion order, not shelf order).
        total: how many boards this press runs.
        board: the Benchmark id.
        problems: the board's infrastructure problems; empty means healthy.
        seconds: wall time the board took, rounded to whole seconds for display.

    Returns:
        The progress line, without a trailing newline.
    """
    verdict: str = "ok"
    if problems:
        noun: str = "problem" if len(problems) == 1 else "problems"
        verdict = f"FAILED: {len(problems)} {noun}"
    return f"[{position}/{total}] {board} … {verdict} ({round(seconds)}s)"


def _smoke_board_timed(
    open_client: Callable[[], AbstractContextManager[_sf.Client]], board: str, reports_dir: Path
) -> tuple[list[str], float]:
    """One parallel worker: open a client of its own, smoke one board, time it.

    INVARIANT: always returns a verdict, never raises. An exception escaping a worker
    would surface from its future and abort the collection loop, hiding every other
    board's verdict. `_smoke_one_board` already catches evaluate's failures, so this
    catch covers only the client's own open and close.

    Args:
        open_client: builds a fresh client context manager (one per worker thread).
        board: the Benchmark id.
        reports_dir: where the board's Report is kept (see `_smoke_one_board`).

    Returns:
        The board's problems (empty when healthy) and its wall time in seconds.
    """
    started: float = time.monotonic()
    try:
        with open_client() as client:
            problems: list[str] = _smoke_one_board(client, board, reports_dir)
    except Exception as exc:  # noqa: BLE001
        problems = [f"{board}: client failed — {exc!r}"]
    return problems, time.monotonic() - started


def _smoke_one_board(client: _sf.Client, board: str, reports_dir: Path) -> list[str]:
    """Run one board's Fusion evaluation, keep its Report on disk, and describe its
    infrastructure failures.

    Args:
        client: the SDK client connected to the paid stack's engine.
        board: the Benchmark id (e.g. ``inspect-gsm8k`` or ``draco``).
        reports_dir: where this board's full Report lands as ``<board>.json`` — the
            per-case evidence (member + synthesizer answers, grade, judge reasoning,
            run and trace ids) that the failure strings below only summarize.

    Returns:
        One human-readable line per problem; empty when the board's pipe is healthy.
    """
    import screamingface as sf

    try:
        report = client.evaluate(fusion_panel(), benchmark=board, limit=CASE_LIMIT, progress=False)
    except sf.ScreamingFaceError as exc:
        # The run never produced a report — a preflight refusal, a dead route, a
        # transport failure. Always a smoke failure; the message names the cause.
        return [f"{board}: evaluate raised — {exc}"]
    except Exception as exc:  # noqa: BLE001
        # WHY the broad catch (PR #1035 review): this loop's contract is "one broken
        # board never hides the rest". An exception that leaks past the SDK's own
        # error type would otherwise abort the loop and silently discard the other
        # boards' verdicts — it is still recorded as this board's failure, never swallowed.
        return [f"{board}: evaluate raised unexpectedly — {exc!r}"]

    problems: list[str] = []
    # WHY export before judging: a failing board's Report IS the debugging evidence,
    # and the smoke would otherwise read it for failure strings and discard the rest
    # — so debugging a failed case meant paying for the run again. It lands in the
    # stack's log dir, which CI uploads and the just recipe prints.
    try:
        report.export(reports_dir / f"{board}.json")
    except OSError as exc:
        problems.append(f"{board}: could not keep the report for debugging — {exc}")
    return problems + _report_problems(board, report)


def _no_graded_reason(codes: list[str]) -> str:
    """Say why no Case was graded, advising a rerun only when that is honest.

    WHY branch on the codes: "rerun" is the right advice only when every Case died on
    a tolerated code. The first paid press printed it for `missing_case_row`, which is
    a real failure. The empty case is guarded because all() over zero failures is
    True, which would bring the false claim back.

    Args:
        codes: every failure code across the board's Cases, in Case order.

    Returns:
        The tail of the board's "no Case was graded" verdict.
    """
    if not codes:
        return "and no Case reported a failure"
    if all(code in TOLERATED_MODEL_SIDE_CODES for code in codes):
        return "every attempt died on a tolerated model-side code; rerun"
    return "see its case failures below"


def _report_problems(board: str, report: _sf.Report) -> list[str]:
    """Read one board's Report like a referee: did the pipe carry every Case to a
    grade, and did anything fail that was not the model misbehaving?"""
    candidate = report.candidates.only
    problems: list[str] = []
    if len(candidate.cases) != CASE_LIMIT:
        problems.append(
            f"{board}: expected {CASE_LIMIT} cases in the report, got {len(candidate.cases)}"
        )
    # WHY strict (PR #1035 review): with every Case lost to tolerated model-side codes
    # (e.g. two 429s), the board's GRADING path ran zero times — a pass would claim a
    # pipe this run never exercised. Flash models at temperature 0 on benign benchmark
    # prompts essentially never doubly refuse, so the rare flake costs a cents-level
    # rerun; the silent alternative costs trust in every green run.
    if not any(case.status == "scored" for case in candidate.cases):
        codes: list[str] = [failure.code for case in candidate.cases for failure in case.failures]
        problems.append(
            f"{board}: no Case was graded, so this run proved nothing about the board — "
            f"{_no_graded_reason(codes)}"
        )
    for case in candidate.cases:
        for failure in case.failures:
            if failure.code in TOLERATED_MODEL_SIDE_CODES:
                continue
            problems.append(
                f"{board}: case {case.case_id} {failure.stage}/{failure.code} — {failure.message}"
            )
    return problems

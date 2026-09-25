"""The paid smoke: every imported board runs once for real (OME-1275).

FEATURE: a cheap owner-pressed button that re-proves the whole imported shelf's
product pipe — SDK → gateway → OpenRouter → engine grading — after any refactor.

STORY: as the owner, before citing "every imported board runs", I run
`just screamingface test-paid-inspect` and get, for a small bounded spend, either a
green run or the exact board + failure code that broke.

WHY shape-only assertions: scores are nondeterministic and protected elsewhere (the
golden replay lane). This lane fails ONLY on infrastructure failure codes; a wrong,
refused, or truncated model answer still passes, because model quality is not wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _panel import CASE_LIMIT, fusion_panel
from conftest import PaidStack

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


def test_every_imported_board_runs_end_to_end(paid_stack: PaidStack) -> None:
    """INVARIANT: each imported board's full product pipe can execute a real run.

    One loop, not per-board parametrize: the board list lives on the live engine,
    which does not exist at collection time (the SDK venv cannot import the engine).
    The loop collects every board's verdict so one broken board never hides the
    rest, and the final assertion message carries board name + stage + code.
    """
    import screamingface as sf

    with sf.Client(engine_url=paid_stack.engine_url) as client:
        boards: list[str] = [
            benchmark.id
            for benchmark in client.benchmarks.list()
            if benchmark.origin == "inspect_evals"
        ]
        # An empty shelf means the engine booted without the inspect extra — a lane
        # bug, not a board bug; fail here before spending anything.
        assert boards, (
            "the live engine lists no origin='inspect_evals' benchmarks — "
            "was its venv synced with --extra benchmarks?"
        )

        problems: list[str] = []
        for board in boards:
            problems.extend(_smoke_one_board(client, board, paid_stack.log_dir / "reports"))

    assert not problems, (
        "imported boards failed the paid smoke (board: stage/code — message):\n"
        + "\n".join(problems)
    )


def _smoke_one_board(client: _sf.Client, board: str, reports_dir: Path) -> list[str]:
    """Run one board's Fusion evaluation, keep its Report on disk, and describe its
    infrastructure failures.

    Args:
        client: the SDK client connected to the paid stack's engine.
        board: the imported benchmark id (``inspect-<key>``).
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
        problems.append(
            f"{board}: no Case was graded — every attempt died on a tolerated "
            f"model-side code, so this run proved nothing about the board; rerun"
        )
    for case in candidate.cases:
        for failure in case.failures:
            if failure.code in TOLERATED_MODEL_SIDE_CODES:
                continue
            problems.append(
                f"{board}: case {case.case_id} {failure.stage}/{failure.code} — {failure.message}"
            )
    return problems

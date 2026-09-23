"""The paid smoke: every imported board runs once for real (OME-1275).

FEATURE: a cheap owner-pressed button that re-proves the whole imported shelf's
product pipe — SDK → gateway → OpenRouter → engine grading — after any refactor.

STORY: as the owner, before citing "17 imported boards supported", I run
`just screamingface test-paid-inspect` and get, for under a dollar, either a green
run or the exact board + failure code that broke.

WHY shape-only assertions: scores are nondeterministic and protected elsewhere (the
golden replay lane). This lane fails ONLY on infrastructure failure codes; a wrong,
refused, or truncated model answer still passes, because model quality is not wiring.
"""

from __future__ import annotations

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
            problems.extend(_smoke_one_board(client, board))

    assert not problems, (
        "imported boards failed the paid smoke (board: stage/code — message):\n"
        + "\n".join(problems)
    )


def _smoke_one_board(client: _sf.Client, board: str) -> list[str]:
    """Run one board's Fusion evaluation and describe its infrastructure failures."""
    import screamingface as sf

    try:
        report = client.evaluate(fusion_panel(), benchmark=board, limit=CASE_LIMIT, progress=False)
    except sf.ScreamingFaceError as exc:
        # The run never produced a report — a preflight refusal, a dead route, a
        # transport failure. Always a smoke failure; the message names the cause.
        return [f"{board}: evaluate raised — {exc}"]

    candidate = report.candidates.only
    problems: list[str] = []
    if len(candidate.cases) != CASE_LIMIT:
        problems.append(
            f"{board}: expected {CASE_LIMIT} cases in the report, got {len(candidate.cases)}"
        )
    for case in candidate.cases:
        for failure in case.failures:
            if failure.code in TOLERATED_MODEL_SIDE_CODES:
                continue
            problems.append(
                f"{board}: case {case.case_id} {failure.stage}/{failure.code} — {failure.message}"
            )
    return problems

"""With each Case parked, the aggregate's memory per Case is small and flat in the Case count.

FEATURE: memory fix 3 (OME-1835), unit 2.
Spec: ``docs/spec/2026-11-16-streamed-candidate-result.md``.
After unit 1, the result was streamed into the run spool, but the aggregate still held the whole
``CaseResult`` list while it marked, finalized and wrote the result: about 3 x the result bytes
per Case. Unit 2 parks each Case's wire JSON in the run's Case-result store as it is marked,
scores on a light projection per Case, and writes the body from the parked text.

How it is measured: the harness of ``test_streamed_result_memory.py`` (synthetic MMLU-Pro
bundle, hosted run path, stub gateway, tracemalloc), with its 5-member Fusion Candidate and the
single-model Candidate of ``test_case_result_memory.py``.

- Aggregate: the traced peak after the last model call, above what was live at that call.
- Held: what is still live when the run ends, above what was live at that call.

Each is divided by N. BEFORE unit 2 (unit 1 baseline, ledger
``docs/work/2026-11-16-parked-case-results.md``): Fusion aggregate peak about 32 KiB per Case,
single model about 11.6. This file does not change the bounds of ``test_streamed_result_memory.py``
or ``test_case_result_memory.py`` (append-only tests); it adds tighter bounds for the parked path.

INVARIANT: the bound is per Case, so it holds whatever N is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("inspect_ai")
pytest.importorskip("inspect_evals")

from test_case_result_memory import _CANDIDATE, _MODEL  # noqa: E402
from test_streamed_result_memory import (  # noqa: E402
    _FUSION_CANDIDATE,
    _FUSION_MODELS,
    _measure,
)

_CASES = 300
#: The flatness sizes: the acceptance criterion's N=500 and N=2,000 (about 35 s together).
#: WHY not a smaller N: at N=250 and below the aggregate's peak is a fixed event of about
#: 1.3 MiB, not the per-Case cost, so the per-Case value there is not the slope (N=125: 10.6).
_SMALL_CASES = 500
_LARGE_CASES = 2000

#: Per-Case bounds, in KiB: the highest of 3 local runs, x1.25, rounded up to 0.5.
#: BEFORE unit 2 (the held path: ``aggregate_body_async`` patched, locally, to return
#: ``HeldResultBody(await self.aggregate_result_async(...))``): Fusion N=300 aggregate 31.89;
#: one emoji 31.35; single model N=500 10.86, N=2,000 11.32. So each bound below fails the
#: held path.
#: AFTER unit 2 (3 runs): Fusion N=300 aggregate 5.24 to 5.25; one emoji 4.67 to 4.81; single
#: model N=500 5.80 to 5.84, N=2,000 5.98 to 6.00; held -3.15 to -1.42 (below what was live at
#: the last call: the Case phase is freed). A sweep in one process, N=500 to 4,000: 5.82 to
#: 6.06, no trend.
#: WHY the held bound is 1.0: as in ``test_streamed_result_memory.py``; a held result breaks it.
#: WHY a slack of 0.5 for flatness: N=2,000 minus N=500 measured 0.14 to 0.19. A per-Case cost
#: that grows with N (an index of every row, a list decoded once per Case) breaks it.
#: What the aggregate still holds per Case is the light projection and the Case's parked
#: location; a held ``CaseResult`` list (about 3 x the result bytes per Case) breaks the bound.
_PARKED_FUSION_AGGREGATE_KIB_PER_CASE = 7.0
_PARKED_WIDE_AGGREGATE_KIB_PER_CASE = 6.5
_PARKED_SINGLE_AGGREGATE_KIB_PER_CASE = 7.5
_FLAT_SLACK_KIB_PER_CASE = 0.5
_HELD_KIB_PER_CASE = 1.0


@pytest.mark.asyncio
async def test_a_parked_five_member_fusion_aggregate_is_bounded(tmp_path: Path) -> None:
    aggregate, held, outcome = await _measure(
        tmp_path, _CASES, _FUSION_CANDIDATE, _FUSION_MODELS, emoji_call=None
    )
    print(f"parked fusion N={_CASES} aggregate={aggregate:.2f} KiB/Case held={held:.2f} KiB/Case")
    assert outcome == "succeeded"
    assert aggregate < _PARKED_FUSION_AGGREGATE_KIB_PER_CASE, f"aggregate {aggregate:.2f} KiB/Case"
    assert held < _HELD_KIB_PER_CASE, f"held {held:.2f} KiB/Case"


@pytest.mark.asyncio
async def test_one_wide_character_keeps_the_parked_aggregate_bounded(tmp_path: Path) -> None:
    # WHY call 7: it is the first model call of a later Case, so one answer in the whole run
    # carries the emoji; a whole-result str would turn wide, a parked fragment does not spread.
    aggregate, held, outcome = await _measure(
        tmp_path, _CASES, _FUSION_CANDIDATE, _FUSION_MODELS, emoji_call=7
    )
    print(
        f"parked fusion+emoji N={_CASES} aggregate={aggregate:.2f} KiB/Case "
        f"held={held:.2f} KiB/Case"
    )
    assert outcome == "succeeded"
    assert aggregate < _PARKED_WIDE_AGGREGATE_KIB_PER_CASE, f"aggregate {aggregate:.2f} KiB/Case"
    assert held < _HELD_KIB_PER_CASE, f"held {held:.2f} KiB/Case"


@pytest.mark.asyncio
async def test_the_parked_aggregate_per_case_is_flat_in_the_case_count(tmp_path: Path) -> None:
    measured: dict[int, float] = {}
    for cases in (_SMALL_CASES, _LARGE_CASES):
        aggregate, held, outcome = await _measure(
            tmp_path / str(cases), cases, _CANDIDATE, (_MODEL,), emoji_call=None
        )
        print(f"parked single N={cases} aggregate={aggregate:.2f} KiB/Case held={held:.2f}")
        assert outcome == "succeeded"
        assert aggregate < _PARKED_SINGLE_AGGREGATE_KIB_PER_CASE, (
            f"N={cases}: aggregate {aggregate:.2f} KiB/Case"
        )
        measured[cases] = aggregate
    # WHY a slack and not a slope: the aggregate's fixed cost spread over fewer Cases makes the
    # smaller N the higher value; a per-Case cost that grows with N puts the larger N above it.
    assert measured[_LARGE_CASES] <= measured[_SMALL_CASES] + _FLAT_SLACK_KIB_PER_CASE, (
        f"aggregate per Case grows with N: {measured}"
    )

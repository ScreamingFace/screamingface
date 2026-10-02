"""What reproducing a row costs: its spend, plus the cache saving when the spend is exact.

FEATURE: OME-1382 (`OME-1251` D5). A cached run spends about $0, because a cache hit costs nothing
upstream. Ranked on that spend it takes a Pareto slot it has not earned (`OME-1143`). The board
stores the spend and the provider-reported saving as two fields and adds them here, at the point
of use; nothing ever stores the sum.

INVARIANT: every read path that RANKS or DISPLAYS a cost calls this one function, so the table, the
frontier marks, the chart, the card, the trend and the spec history serve one number per row
(`OME-1145` D-L). The ONE path that must not is `store._score_to_schema`: it feeds the private
export, whose bytes are the sha256 that authorises a purge, so it keeps the three stored fields.
"""

from __future__ import annotations

from decimal import Decimal

from .schemas import RunCostStatus


def reproduction_cost(
    run_cost_usd: Decimal | None,
    run_cost_status: RunCostStatus | None,
    cache_saved_cost_usd: Decimal | None,
) -> Decimal | None:
    """``run_cost_usd + cache_saved_cost_usd`` for a ``complete`` row with a saving, else the spend.

    INVARIANT: only ``complete`` is summed. It asserts the spend is exact, and the SDK sends it for
    a cached run only when every hit was provider-priced (owner, 2026-10-02), so the sum is the full
    cost. ``partial`` and ``unavailable`` carry no amount by contract, so a saving beside them is a
    lower bound and is never promoted to a cost. A legacy row (status null) is never summed either.
    """
    if run_cost_status != "complete" or run_cost_usd is None or cache_saved_cost_usd is None:
        return run_cost_usd
    return run_cost_usd + cache_saved_cost_usd

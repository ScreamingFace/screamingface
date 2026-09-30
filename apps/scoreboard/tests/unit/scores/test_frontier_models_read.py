"""The two narrow reads behind the frontier statistic (OME-1145, OME-1179 constraint 4).

INVARIANT: neither read materialises recipes or display metadata for the whole board. The
history read is the comparable rows' ranking fields; the models read is scoped to the ids that
were ever on the frontier, and chunked so a large `IN (...)` cannot exceed parameter limits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from scoreboard.scores import store as store_module
from scoreboard.scores.models import Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "draco-3pass"
REV = "rev-1"
T0 = datetime(2026, 9, 1, tzinfo=UTC)


async def _seed(count: int) -> list[str]:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id=BOARD, display_name="Draco", revision=REV, case_count=100
    )
    ids = []
    for i in range(count):
        outcome = await store.submit(
            ScoreSubmission(
                benchmark_id=BOARD,
                spec_id=f"spec-{i}",
                url4_expression=f"url4://spec-{i}",
                submitted_by="tester@example.test",
                score=0.5,
                total_questions=100,
                ran_with_providers=["openrouter"],
                models=[f"openrouter/deepseek/model-{i}"],
                run_cost_usd=Decimal("1.00"),
                run_cost_status="complete",
            )
        )
        await Score.filter(id=outcome.score.id).update(
            submitted_at=T0 + timedelta(hours=i), benchmark_revision=REV
        )
        ids.append(str(outcome.score.id))
    return ids


async def test_the_models_read_returns_exactly_the_requested_ids(tortoise_db: None) -> None:
    ids = await _seed(4)

    members = await ScoreStore().frontier_member_models(ids[:2])

    assert set(members) == set(ids[:2])
    assert members[ids[0]].models == ("openrouter/deepseek/model-0",)
    assert members[ids[0]].openness_override is None


async def test_the_models_read_is_chunked_and_still_complete(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = await _seed(5)
    monkeypatch.setattr(store_module, "_MODELS_READ_CHUNK", 2)

    members = await ScoreStore().frontier_member_models(ids)

    assert set(members) == set(ids)


async def test_the_models_read_carries_the_override(tortoise_db: None) -> None:
    ids = await _seed(1)
    await Score.filter(id=ids[0]).update(openness_override="open")

    members = await ScoreStore().frontier_member_models(ids)

    assert members[ids[0]].openness_override == "open"


async def test_an_empty_id_set_reads_nothing(tortoise_db: None) -> None:
    assert await ScoreStore().frontier_member_models([]) == {}


async def test_the_history_read_is_the_comparable_rows_in_submission_order(
    tortoise_db: None,
) -> None:
    ids = await _seed(3)
    await Score.filter(id=ids[1]).update(benchmark_revision="old-rev")
    await Score.filter(id=ids[2]).update(total_questions=1)

    rows = await ScoreStore().frontier_history_inputs(
        BOARD, registered_revision=REV, registered_case_count=100
    )

    assert [row.source_id for row in rows] == [ids[0]]
    assert rows[0].submitted_at == T0
    assert rows[0].run_cost_usd == Decimal("1.00")

"""Store-level tests for the metadata edit's conditional UPDATE (MD-D2, OME-1307 E14a).

WHY a store test: through the route, two gathered PATCHes are serialised (SQLite runs one after
the other, PostgreSQL's row lock does the same), so the loser is always stopped by the earlier
`row.metadata_revision != expected_revision` check and never reaches the conditional `UPDATE`.
Only a row that goes stale AFTER it was read reaches that branch.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from tortoise import BaseDBAsyncClient

from scoreboard.scores import metadata_store
from scoreboard.scores.metadata_store import MetadataRevisionConflict, ScoreMetadataStore
from scoreboard.scores.models import Score, ScoreMetadataEvent
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "metadata-store"
OWNER = "ana@x.org"


async def _seed() -> UUID:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id=BOARD, display_name="Metadata store")
    outcome = await store.submit(
        ScoreSubmission(
            benchmark_id=BOARD,
            spec_id="a",
            url4_expression="url4://a",
            submitted_by=OWNER,
            score=0.5,
            total_questions=100,
            ran_with_providers=["openrouter"],
            run_cost_usd=Decimal("1.00"),
            run_cost_status="complete",
        )
    )
    return outcome.score.id


async def test_the_conditional_update_is_the_last_defence_against_a_stale_row(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT (MD-D2): the `UPDATE ... WHERE metadata_revision = <read>` loses to a rival.

    The replacement lock returns the real row and then bumps the stored revision behind it, so the
    row object the store holds is stale: it passes the earlier revision check and only the
    conditional UPDATE can refuse it. The bump uses the transaction's connection, because on
    PostgreSQL another connection would wait on the row lock the store holds.
    """
    score_id = await _seed()
    real_lock = metadata_store._lock_row

    async def lock_then_go_stale(conn: BaseDBAsyncClient, locked_id: UUID) -> Score | None:
        row = await real_lock(conn, locked_id)
        await Score.filter(id=locked_id).using_db(conn).update(metadata_revision=2)
        return row

    monkeypatch.setattr(metadata_store, "_lock_row", lock_then_go_stale)

    with pytest.raises(MetadataRevisionConflict) as raised:
        await ScoreMetadataStore().update_metadata(
            score_id,
            changes={"paper_url": "https://x.org/p"},
            expected_revision=1,
            editor=OWNER,
        )

    assert raised.value.current.metadata_revision == 2
    assert await ScoreMetadataEvent.filter(score_id=score_id).count() == 0
    # WHY no revision assertion: the conflict rolls the transaction back, and the rival's bump was
    # made on the same connection, so what the row holds afterwards depends on the database.
    assert (await Score.get(id=score_id)).paper_url is None

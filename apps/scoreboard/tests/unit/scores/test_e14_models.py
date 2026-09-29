"""E14 (OME-1307) storage models: round trip, uniqueness, cascades, and the legacy wire shape."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from scoreboard.delete_scores import delete_scores
from scoreboard.export_private_submissions import format_jsonl_bytes
from scoreboard.scores.models import (
    CacheVersionPublication,
    ReportedResult,
    Score,
    ScoreMetadataEvent,
    System,
    SystemRevision,
)
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BOARD = "e14-board"


def _submission(spec_id: str = "spec") -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=BOARD,
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{spec_id}",
        submitted_by="owner@example.test",
        score=0.5,
        total_questions=100,
        correct_questions=50,
        ran_with_providers=["openrouter"],
        run_cost_usd=Decimal("1.000000"),
        run_cost_status="complete",
    )


async def _score(spec_id: str = "spec") -> uuid.UUID:
    store = ScoreStore()
    if not await Score.exists():
        await store.register_benchmark(benchmark_id=BOARD, display_name="E14 board")
    outcome = await store.submit(_submission(spec_id), idempotency_key=f"key-{spec_id}")
    return outcome.score.id


async def _result(score_id: uuid.UUID, **overrides: Any) -> ReportedResult:
    values: dict[str, Any] = {
        "head_id": score_id,
        "is_original": False,
        "score": 0.5,
        "total_questions": 100,
    }
    values.update(overrides)
    return await ReportedResult.create(**values)


async def _leading_index_columns(table: str) -> set[str]:
    # AIDEV-NOTE: SQLite only. `tortoise_db` cannot run on PostgreSQL today (its schema fixture is
    # sync and calls `asyncio.run` inside a running loop), so the PostgreSQL index check lives in
    # `test_migration_e14_postgres.py`.
    connection = Tortoise.get_connection("default")
    leading: set[str] = set()
    for index in await connection.execute_query_dict(f'PRAGMA index_list("{table}")'):
        info = await connection.execute_query_dict(f'PRAGMA index_info("{index["name"]}")')
        leading |= {row["name"] for row in info if row["seqno"] == 0}
    return leading


async def test_sch8_new_models_round_trip_and_enforce_unique_columns(tortoise_db: None) -> None:
    score_id = await _score()
    system = await System.create(name="sys-one", owner="owner@example.test")
    revision = await SystemRevision.create(
        system=system,
        revision=1,
        fingerprint="a" * 64,
        candidate_url4="url4://candidate",
        declared_by="owner@example.test",
    )
    result = await _result(
        score_id,
        is_original=True,
        run_id="run-1",
        cache_version_id=uuid.uuid4(),
        run_cost_usd=Decimal("1.250000"),
        models=["m1"],
        replay_repeated_key_collapses=0,
    )
    event = await ScoreMetadataEvent.create(
        score_id=score_id,
        from_revision=1,
        to_revision=2,
        before={"authors": None, "paper_url": None},
        after={"authors": ["a"], "paper_url": "https://example.test/p"},
    )
    publication = await CacheVersionPublication.create(result=result)

    assert (await System.get(id=system.id)).name == "sys-one"
    assert (await SystemRevision.get(id=revision.id)).fingerprint == "a" * 64
    fetched = await ReportedResult.get(id=result.id)
    assert ((await fetched.head).id, fetched.run_cost_usd, fetched.models) == (
        score_id,
        Decimal("1.250000"),
        ["m1"],
    )
    assert (await ScoreMetadataEvent.get(id=event.id)).after[
        "paper_url"
    ] == "https://example.test/p"
    stored = await CacheVersionPublication.get(result_id=result.id)
    assert (stored.state, stored.attempts, (await publication.result).id) == (
        "private",
        0,
        result.id,
    )

    with pytest.raises(IntegrityError):
        await System.create(name="sys-one", owner="other@example.test")
    with pytest.raises(IntegrityError):
        await SystemRevision.create(
            system=await System.create(name="sys-two", owner="o"),
            revision=1,
            fingerprint="a" * 64,
            candidate_url4="u",
            declared_by="d",
        )
    with pytest.raises(IntegrityError):
        await SystemRevision.create(
            system=system, revision=1, fingerprint="b" * 64, candidate_url4="u", declared_by="d"
        )
    with pytest.raises(IntegrityError):
        await _result(score_id, run_id="run-1")
    with pytest.raises(IntegrityError):
        await _result(score_id, cache_version_id=fetched.cache_version_id)

    # WHY leading column: `Meta.indexes = (("head_id", "submitted_at"),)` must resolve to the
    # COLUMN `score_id`, not the attribute name (plan 4.5).
    assert "score_id" in await _leading_index_columns("reported_result")


async def test_sch13_partial_index_fixture_creates_the_indexes(
    partial_unique_indexes: None,
) -> None:
    score_id = await _score()
    await _result(score_id, is_original=True)

    with pytest.raises(IntegrityError):
        await _result(score_id, is_original=True)
    await _result(score_id, is_original=False)


async def test_sch10_deleting_a_score_cascades_its_results_and_events(tortoise_db: None) -> None:
    first = await _score("first")
    second = await _score("second")
    for score_id in (first, second):
        await _result(score_id, is_original=True)
        await ScoreMetadataEvent.create(
            score_id=score_id, from_revision=1, to_revision=2, before={}, after={}
        )

    await Score.filter(id=first).delete()
    assert await ReportedResult.filter(head_id=first).count() == 0
    assert await ScoreMetadataEvent.filter(score_id=first).count() == 0
    assert await ReportedResult.filter(head_id=second).count() == 1

    reviewed = await delete_scores(BOARD, score_ids=[second], expected=1)
    await delete_scores(
        BOARD,
        score_ids=[second],
        expected=1,
        confirmed=True,
        expected_sha256=reviewed.sha256(),
    )
    assert await Score.filter(id=second).count() == 0
    assert await ReportedResult.all().count() == 0
    assert await ScoreMetadataEvent.all().count() == 0


async def test_sch11_score_schema_output_is_unchanged_for_a_legacy_row(tortoise_db: None) -> None:
    await ScoreStore().register_benchmark(benchmark_id=BOARD, display_name="E14 board")
    outcome = await ScoreStore().submit(_submission(), idempotency_key="key-legacy")
    row = outcome.score

    # INVARIANT: this schema is also the private-export row, whose bytes authorize a purge. A
    # legacy row must not gain a key, or a certified export could no longer authorize its purge.
    dumped = row.model_dump(mode="json")
    assert not {"paper_url", "metadata_updated_at", "system_revision_id"} & dumped.keys()

    exported = json.loads(format_jsonl_bytes([row]).decode().splitlines()[0])
    assert (
        not {
            "paper_url",
            "metadata_revision",
            "metadata_updated_at",
            "system_revision_id",
        }
        & exported.keys()
    )
    assert datetime.now(UTC) >= row.submitted_at

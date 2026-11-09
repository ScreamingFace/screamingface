"""The model side of migration 0021: the metadata columns and one score per frozen copy.

FEATURE: author and paper metadata on a score, logged on every edit, and a frozen copy that names
at most one score (the pinned cache lookup answers with exactly one row).
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from tortoise import fields
from tortoise.exceptions import IntegrityError

from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent

COPY = "33333333-3333-4333-8333-333333333333"


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (Score, "authors_metadata"),
        (Score, "paper_metadata"),
        (ScoreMetadataEvent, "old_authors_metadata"),
        (ScoreMetadataEvent, "new_authors_metadata"),
        (ScoreMetadataEvent, "old_paper_metadata"),
        (ScoreMetadataEvent, "new_paper_metadata"),
    ],
)
def test_each_metadata_column_is_nullable_json(model: Any, name: str) -> None:
    field = cast(Any, model._meta.fields_map[name])

    assert isinstance(field, fields.JSONField)
    assert field.null is True


def test_the_frozen_copy_is_unique_on_its_own() -> None:
    assert ("frozen_copy_id",) in Score._meta.unique_together


async def _score(spec_id: str, frozen_copy_id: str | None) -> Score:
    return await Score.create(
        benchmark_id="hle",
        spec_id=spec_id,
        url4_expression="url4://x",
        score=0.5,
        total_questions=10,
        ran_with_providers=["openai"],
        frozen_copy_id=frozen_copy_id,
    )


@pytest.mark.asyncio
async def test_a_second_score_cannot_name_the_same_copy(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="HLE")
    await _score("a", COPY)

    with pytest.raises(IntegrityError):
        await _score("b", COPY)


@pytest.mark.asyncio
async def test_many_scores_may_name_no_copy(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="HLE")
    for spec in ("a", "b", "c"):
        await _score(spec, None)

    assert await Score.filter(frozen_copy_id__isnull=True).count() == 3


@pytest.mark.asyncio
async def test_metadata_round_trips_as_stored(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="HLE")
    row = await _score("a", None)
    authors = {"Ana@Uni.edu": {"full_name": "Ana Silva", "orcid": "0000", "senior": True}}
    paper = {"title": "A study", "pages": 12}

    await Score.filter(id=row.id).update(authors_metadata=authors, paper_metadata=paper)
    stored = await Score.get(id=row.id)

    assert stored.authors_metadata == authors
    assert stored.paper_metadata == paper


@pytest.mark.asyncio
async def test_a_row_without_metadata_reads_without_either_key(tortoise_db: None) -> None:
    # INVARIANT: excluded when null, so the private JSONL export's bytes do not change for a row
    # that never carried metadata (the export hashes them to authorise a purge).
    from scoreboard.scores.store import _score_to_schema

    await Benchmark.create(id="hle", display_name="HLE")
    row = await _score("a", None)

    schema = _score_to_schema(await Score.get(id=row.id))

    assert "authors_metadata" not in schema.model_dump(mode="python")
    assert "paper_metadata" not in schema.model_dump(mode="python")
    assert "authors_metadata" not in json.loads(schema.model_dump_json())
    assert "paper_metadata" not in json.loads(schema.model_dump_json())


@pytest.mark.asyncio
async def test_a_row_with_metadata_carries_it_to_the_read_schema(tortoise_db: None) -> None:
    from scoreboard.scores.store import _score_to_schema

    await Benchmark.create(id="hle", display_name="HLE")
    row = await _score("a", None)
    authors = {"ana@uni.edu": {"full_name": "Ana Silva"}}
    paper = {"title": "A study"}
    await Score.filter(id=row.id).update(authors_metadata=authors, paper_metadata=paper)

    schema = _score_to_schema(await Score.get(id=row.id))

    assert schema.authors_metadata == authors
    assert schema.paper_metadata == paper

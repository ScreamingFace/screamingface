"""Rows seeded with the models, for tests that must not go through `POST /v1/scores`."""

from __future__ import annotations

import uuid

from scoreboard.scores.models import CacheVersionPublication, ReportedResult, Score
from tests.unit.publish._fakes import Seeded, canonical_pair, pair_sha
from tests.unit.submissions._receipts import ANA, URL4_A


async def seed_rows(*, board: str = "pub", state: str = "private", reporter: str = ANA) -> Seeded:
    """One head, one original result and one publication row, written with the ORM."""
    pair = canonical_pair()
    version_id = uuid.uuid4()
    head = await Score.create(
        benchmark_id=board,
        spec_id="spec",
        url4_expression=URL4_A,
        submitted_by=reporter,
        score=0.75,
        total_questions=4,
        ran_with_providers=["openai"],
    )
    result = await ReportedResult.create(
        head=head,
        is_original=True,
        reporter=reporter,
        score=0.75,
        total_questions=4,
        cache_version_id=version_id,
        cache_version_sha256=pair_sha(pair),
        cache_entry_count=1,
        cache_call_count=1,
        cache_coverage_status="complete",
    )
    await CacheVersionPublication.create(result=result, state=state)
    return Seeded(head_id=str(head.id), result_id=str(result.id), version_id=version_id, pair=pair)

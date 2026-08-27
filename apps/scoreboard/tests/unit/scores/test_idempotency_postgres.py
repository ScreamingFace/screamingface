"""The scoped idempotency key must round-trip on PostgreSQL, not just SQLite.

WHY a self-contained connection instead of the `tortoise_db` fixture: that fixture routes through
`postgres_schema_database_url`, which calls `asyncio.run()` inside an already-running event loop
and errors before any test body executes (OME-430). Fixing it is that ticket's job; this file
opens its own connection so the PostgreSQL path is actually covered in the meantime.

Runs only when SCOREBOARD_TEST_DATABASE_URL is set; skips otherwise.
"""

from __future__ import annotations

import os

import pytest
from tortoise import Tortoise

from scoreboard.db import build_tortoise_config
from scoreboard.scores.models import Benchmark, IdempotencyKey, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import KEY_SCHEME, ScoreStore

pytestmark = pytest.mark.asyncio

DATABASE_URL = os.getenv("SCOREBOARD_TEST_DATABASE_URL", "")


def _submission(submitted_by: str) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="private-pg",
        spec_id="spec-1",
        url4_expression="url4://benchmark/spec-1",
        submitted_by=submitted_by,
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openai"],
    )


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="requires PostgreSQL")
async def test_a_private_submission_with_an_idempotency_key_round_trips_on_postgres() -> None:
    # INVARIANT: PostgreSQL rejects NUL in any character type. The first scoped-key implementation
    # embedded one, so this exact call failed with `invalid byte sequence for encoding "UTF8":
    # 0x00` in production while every SQLite test passed.
    await Tortoise.init(config=build_tortoise_config(DATABASE_URL))
    try:
        await Tortoise.generate_schemas(safe=True)
        store = ScoreStore()
        await store.register_benchmark(
            benchmark_id="private-pg", display_name="Private", visibility="private"
        )

        # `identity_verified=True` is LOAD-BEARING, not decoration. A private board refuses
        # unverified writes before opening any transaction, so without it this test raises
        # `PrivateBoardRequiresIdentity` and never reaches PostgreSQL at all — and because the
        # module is skipped wherever `SCOREBOARD_TEST_DATABASE_URL` is unset, that failure was
        # invisible in CI and showed up only in the one environment the test exists to cover
        # (review of PR #719). The scoped key is a private-board construct, so there is no
        # variant of this test that both reaches the key and skips the identity rule.
        alice, alice_created = await store.submit(
            _submission("alice@example.test"),
            idempotency_key="retry-1",
            identity_verified=True,
        )
        bob, bob_created = await store.submit(
            _submission("bob@example.test"),
            idempotency_key="retry-1",
            identity_verified=True,
        )

        assert alice_created is True
        assert bob_created is True
        assert bob.id != alice.id
        assert bob.submitted_by == "bob@example.test"

        rows = await IdempotencyKey.all()
        stored = [row.key for row in rows]
        assert len(stored) == 2
        assert all("\x00" not in key and len(key) <= 255 for key in stored)
        # Provenance round-trips through a real CharField too: `scheme` is what distinguishes a
        # mapping this code wrote from a legacy one, and a column that silently failed to persist
        # on PostgreSQL would make every reserved-namespace mapping look legacy.
        assert {row.scheme for row in rows} == {KEY_SCHEME}
    finally:
        # Remove only what this test created. `_drop_databases()` would destroy the whole
        # database, which makes the test non-repeatable and is destructive against a shared CI
        # PostgreSQL — found when a mutation check could not reconnect on the second run.
        await IdempotencyKey.all().delete()
        await Score.filter(benchmark_id="private-pg").delete()
        await Benchmark.filter(id="private-pg").delete()
        await Tortoise.close_connections()

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from scoreboard.scores.models import Benchmark, IdempotencyKey, Score
from scoreboard.scores.schemas import ClientInfo, LeaderboardEntry, ScoreSubmission
from scoreboard.scores.store import (
    BenchmarkVisibilityChanged,
    PrivateBoardRequiresIdentity,
    ScoreStore,
    _scoped_idempotency_key,
    _to_python_rows,
)

pytestmark = pytest.mark.asyncio


def _submission(
    *,
    spec_id: str = "spec-1",
    score: float = 0.75,
    providers: list[str] | None = None,
) -> ScoreSubmission:
    correct_questions = int(score * 100)
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{spec_id}/{score}",
        submitted_by="tester",
        score=score,
        total_questions=100,
        correct_questions=correct_questions,
        ran_with_providers=providers or ["openai"],
        ran_at_local=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
        client=ClientInfo(name="scoreboard-test", version="0.1.0", platform="test"),
        metadata={"source": "unit"},
    )


async def _store_with_benchmark() -> ScoreStore:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="hle",
        display_name="Humanity's Last Exam",
        description="Fixture benchmark",
        dataset_url="https://example.test/hle.jsonl",
    )
    return store


async def test_register_benchmark_and_list_benchmarks(tortoise_db: None) -> None:
    store = ScoreStore()

    registered = await store.register_benchmark(
        benchmark_id="hle",
        display_name="Humanity's Last Exam",
        description="Fixture benchmark",
        dataset_url="https://example.test/hle.jsonl",
    )
    benchmarks = await store.list_benchmarks()

    assert registered.id == "hle"
    assert benchmarks == [registered]


async def test_register_benchmark_updates_existing_row(tortoise_db: None) -> None:
    store = ScoreStore()

    await store.register_benchmark(
        benchmark_id="hle",
        display_name="Humanity's Last Exam",
        description="Fixture benchmark",
        dataset_url="https://example.test/hle.jsonl",
    )
    updated = await store.register_benchmark(
        benchmark_id="hle",
        display_name="News Hallucinations",
        description="OpenMined HLE benchmark",
        dataset_url="https://github.com/openmined/HLE.jsonl",
    )
    benchmarks = await store.list_benchmarks()

    assert await Benchmark.all().count() == 1
    assert updated.id == "hle"
    assert updated.display_name == "News Hallucinations"
    assert updated.description == "OpenMined HLE benchmark"
    assert updated.dataset_url == "https://github.com/openmined/HLE.jsonl"
    assert benchmarks == [updated]


async def test_submit_inserts_and_returns_score(tortoise_db: None) -> None:
    store = await _store_with_benchmark()

    score, created = await store.submit(_submission())

    assert created is True
    assert score.benchmark_id == "hle"
    assert score.spec_id == "spec-1"
    assert score.score == 0.75
    assert score.total_questions == 100
    assert score.correct_questions == 75
    assert score.ran_with_providers == ["openai"]
    assert score.client_name == "scoreboard-test"
    # OME-820: verified defaults to True as a placeholder that asserts NOTHING —
    # nothing re-runs submissions and nothing attests where a run executed. The
    # False case stays covered by the explicit-False row test.
    assert score.verified_by_screamingface is True
    assert await Score.all().count() == 1


async def test_submit_with_live_idempotency_key_returns_existing_score(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()

    first, first_created = await store.submit(_submission(score=0.5), idempotency_key="repeat-key")
    second, second_created = await store.submit(
        _submission(score=0.9), idempotency_key="repeat-key"
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.submitted_at == first.submitted_at
    assert second.score == 0.5
    assert await Score.all().count() == 1


async def test_submit_with_expired_idempotency_key_creates_new_score(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()
    first, _ = await store.submit(_submission(score=0.5), idempotency_key="expired-key")
    await IdempotencyKey.filter(key="expired-key").update(
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    second, second_created = await store.submit(
        _submission(score=0.9), idempotency_key="expired-key"
    )

    assert second_created is True
    assert second.id != first.id
    assert second.score == 0.9
    assert await Score.all().count() == 2


async def test_get_by_idempotency_key_respects_expiry_and_cleanup(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()
    score, _ = await store.submit(_submission(), idempotency_key="lookup-key")

    assert await store.get_by_idempotency_key("lookup-key") == score

    past = datetime.now(UTC) - timedelta(seconds=1)
    await IdempotencyKey.filter(key="lookup-key").update(expires_at=past)

    assert await store.get_by_idempotency_key("lookup-key") is None
    assert await store.cleanup_expired_idempotency_keys(datetime.now(UTC)) == 1
    assert await IdempotencyKey.all().count() == 0


async def test_leaderboard_returns_best_score_per_spec_in_rank_order(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()
    await store.submit(_submission(spec_id="spec-a", score=0.6, providers=["openai"]))
    await store.submit(_submission(spec_id="spec-a", score=0.9, providers=["anthropic"]))
    await store.submit(_submission(spec_id="spec-b", score=0.95, providers=["openai", "gemini"]))
    await store.submit(_submission(spec_id="spec-c", score=0.7, providers=["gemini"]))

    rows = await store.leaderboard("hle", top_n=2)

    assert [row.spec_id for row in rows] == ["spec-b", "spec-a"]
    assert [row.score for row in rows] == [0.95, 0.9]
    assert rows[0].ran_with_providers == ["openai", "gemini"]
    assert isinstance(rows[0].ran_with_providers, list)


async def test_leaderboard_uses_newer_submission_as_accuracy_tie_breaker(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()
    older, _ = await store.submit(_submission(spec_id="spec-a", score=0.9, providers=["older"]))
    newer, _ = await store.submit(_submission(spec_id="spec-a", score=0.9, providers=["newer"]))
    await Score.filter(id=older.id).update(
        submitted_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
    )
    await Score.filter(id=newer.id).update(
        submitted_at=datetime(2026, 5, 21, 13, 0, tzinfo=UTC),
    )

    rows = await store.leaderboard("hle")

    assert len(rows) == 1
    assert rows[0].ran_with_providers == ["newer"]


async def test_list_for_spec_returns_history_newest_first(tortoise_db: None) -> None:
    store = await _store_with_benchmark()
    older, _ = await store.submit(_submission(spec_id="spec-history", score=0.5))
    newer, _ = await store.submit(_submission(spec_id="spec-history", score=0.8))
    await Score.filter(id=older.id).update(
        submitted_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
    )
    await Score.filter(id=newer.id).update(
        submitted_at=datetime(2026, 5, 21, 13, 0, tzinfo=UTC),
    )

    rows = await store.list_for_spec("hle", "spec-history")

    assert [row.id for row in rows] == [newer.id, older.id]


async def test_mark_verified_flips_score_flag(tortoise_db: None) -> None:
    store = await _store_with_benchmark()
    score, _ = await store.submit(_submission())

    await store.mark_verified(score.id)

    verified = await Score.get(id=score.id)
    assert verified.verified_by_screamingface is True


async def test_submit_identical_recipe_without_header_returns_existing_score(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()

    first, first_created = await store.submit(_submission(spec_id="spec-dup", score=0.42))
    second, second_created = await store.submit(_submission(spec_id="spec-dup", score=0.42))

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.submitted_at == first.submitted_at
    assert await Score.all().count() == 1


async def test_submit_identical_recipe_ignores_submitted_by_and_client_metadata(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()
    first_submission = _submission(spec_id="spec-attrib", score=0.6)
    second_submission = first_submission.model_copy(
        update={
            "submitted_by": "someone-else",
            "client": ClientInfo(name="other-client", version="9.9.9", platform="other"),
            "ran_at_local": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    first, _ = await store.submit(first_submission)
    second, second_created = await store.submit(second_submission)

    assert second_created is False
    assert second.id == first.id
    assert second.submitted_by == first.submitted_by
    assert await Score.all().count() == 1


async def test_submit_identical_recipe_ignores_version(tortoise_db: None) -> None:
    # `version` is deliberately excluded from the content hash (see the WHY comment
    # on _content_hash) — model_copy bypasses the Literal[1] validator so this proves
    # the exclusion even though the public schema can't yet submit version=2 for real
    # (OME-391 / C28).
    store = await _store_with_benchmark()
    first_submission = _submission(spec_id="spec-version", score=0.65)
    second_submission = first_submission.model_copy(update={"version": 2})

    first, _ = await store.submit(first_submission)
    second, second_created = await store.submit(second_submission)

    assert second_created is False
    assert second.id == first.id
    assert await Score.all().count() == 1


async def test_submit_dedup_identity_is_the_exact_submitted_score(
    tortoise_db: None,
) -> None:
    # INVARIANT (OME-866): the Engine benchmark is the sole scoring authority, so the
    # submitted score is hashed EXACTLY as sent — the route's ±0.01 tolerance is gone
    # and with it the counts-derived hash (this test's pre-OME-866 version asserted
    # 0.6666666667 and 0.67 deduped together). Two floats that differ are two results;
    # the same float dedupes regardless of the optional binary-era counts around it.
    store = await _store_with_benchmark()
    exact = _submission(spec_id="spec-precision", score=0.75).model_copy(
        update={"total_questions": 3, "correct_questions": 2, "score": 0.6666666667}
    )
    approximate = exact.model_copy(update={"score": 0.67})
    resent_without_counts = exact.model_copy(update={"correct_questions": None})

    first, first_created = await store.submit(exact)
    second, second_created = await store.submit(approximate)
    third, third_created = await store.submit(resent_without_counts)

    assert first_created is True
    assert second_created is True
    assert second.id != first.id
    assert third_created is False
    assert third.id == first.id
    assert await Score.all().count() == 2


async def test_submit_identical_recipe_dedupes_across_different_idempotency_keys(
    tortoise_db: None,
) -> None:
    # The core C28 scenario: two clients each send their own Idempotency-Key for the
    # same underlying recipe — the header alone would never catch this, only the
    # content-hash backstop does (OME-391 / C28).
    store = await _store_with_benchmark()

    first, first_created = await store.submit(
        _submission(spec_id="spec-multi-key", score=0.55),
        idempotency_key="client-a-key",
    )
    second, second_created = await store.submit(
        _submission(spec_id="spec-multi-key", score=0.55),
        idempotency_key="client-b-key",
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.submitted_at == first.submitted_at
    assert await Score.all().count() == 1


async def test_submit_reused_key_after_content_hash_hit_stays_bound_to_original_score(
    tortoise_db: None,
) -> None:
    # Regression for the bug found in PR review: a content-hash hit with an
    # idempotency_key attached must bind that key permanently. Before the fix,
    # "client-b-key" stayed unbound after hitting recipe A via content_hash, so a
    # later, unrelated recipe B reusing "client-b-key" would silently create a new
    # row AND rebind the key to it — meaning a third replay of the *original*
    # client-b-key request would then wrongly return recipe B instead of recipe A
    # (OME-391 / C28).
    store = await _store_with_benchmark()
    recipe_a = _submission(spec_id="spec-bind-a", score=0.55)
    recipe_b = _submission(spec_id="spec-bind-b", score=0.9)

    first, _ = await store.submit(recipe_a, idempotency_key="client-a-key")
    second, second_created = await store.submit(recipe_a, idempotency_key="client-b-key")
    assert second_created is False
    assert second.id == first.id

    third, third_created = await store.submit(recipe_b, idempotency_key="client-b-key")

    assert third_created is False
    assert third.id == first.id
    assert await Score.all().count() == 1


async def test_submit_same_recipe_different_provider_order_is_not_deduped(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()

    first, _ = await store.submit(
        _submission(spec_id="spec-order", score=0.77, providers=["openai", "gemini"])
    )
    second, second_created = await store.submit(
        _submission(spec_id="spec-order", score=0.77, providers=["gemini", "openai"])
    )

    assert second_created is True
    assert second.id != first.id
    assert await Score.all().count() == 2


async def test_submit_different_accuracy_is_not_deduped(tortoise_db: None) -> None:
    store = await _store_with_benchmark()

    first, _ = await store.submit(_submission(spec_id="spec-diff", score=0.3))
    second, second_created = await store.submit(_submission(spec_id="spec-diff", score=0.31))

    assert second_created is True
    assert second.id != first.id
    assert await Score.all().count() == 2


async def test_postgres_concurrent_idempotency_submissions_share_winner(
    tortoise_db: None,
) -> None:
    # AIDEV-NOTE: this test currently only ever skips — see OME-430 for why
    # (postgres_schema_database_url calls asyncio.run() inside an already-running
    # event loop, and CI never sets SCOREBOARD_TEST_DATABASE_URL). Fix there, not here.
    if Tortoise.get_connection("default").capabilities.dialect != "postgres":
        pytest.skip("requires Postgres")

    store = await _store_with_benchmark()
    results = await asyncio.gather(
        *(
            store.submit(
                _submission(score=0.5 + (index / 100)),
                idempotency_key="race-key",
            )
            for index in range(10)
        ),
    )

    assert len({outcome.score.id for outcome in results}) == 1
    assert await Score.all().count() == 1


async def test_list_all_for_benchmark_returns_every_spec_ordered_by_submitted_at(
    tortoise_db: None,
) -> None:
    """OME-323: unlike leaderboard() (best-per-spec), this returns every row for a
    benchmark, chronologically — the frontier trend needs the full history, not
    just each spec's current best."""
    store = await _store_with_benchmark()
    await store.submit(_submission(spec_id="spec-1", score=0.5))
    await store.submit(_submission(spec_id="spec-1", score=0.9))
    await store.submit(_submission(spec_id="spec-2", score=0.3))

    rows = await store.list_all_for_benchmark("hle")

    assert len(rows) == 3
    assert [row.submitted_at for row in rows] == sorted(row.submitted_at for row in rows)


async def test_list_all_for_benchmark_empty_for_unknown_benchmark(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()

    assert await store.list_all_for_benchmark("unknown") == []


async def test_postgres_concurrent_identical_recipe_submissions_share_winner(
    tortoise_db: None,
) -> None:
    # AIDEV-NOTE: see OME-430 — same dead-fixture issue as the test above.
    if Tortoise.get_connection("default").capabilities.dialect != "postgres":
        pytest.skip("requires Postgres")

    store = await _store_with_benchmark()
    results = await asyncio.gather(
        *(store.submit(_submission(spec_id="spec-race", score=0.66)) for _ in range(10)),
    )

    assert len({outcome.score.id for outcome in results}) == 1
    assert await Score.all().count() == 1


# --- OME-775: benchmark revision resolution ------------------------------------------------
# INVARIANT: the resolved revision is the same value whether the Client sent it as a typed
# top-level field or nested in the free-form metadata dict. Wire position must not change
# identity — the store has one resolution rule and everything downstream reads its output.


def _revision_submission(
    *,
    spec_id: str = "spec-rev",
    benchmark_revision: str | None = None,
    metadata: dict[str, object] | None = None,
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{spec_id}",
        submitted_by="tester",
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openai"],
        benchmark_revision=benchmark_revision,
        metadata=metadata,
    )


async def _stored_revision(score_id: object) -> str | None:
    # WHY assert on the persisted row rather than the returned schema: this step's contract is
    # resolution + storage. Exposure on the read schemas is a separate contract with its own
    # tests, so the two can fail independently.
    row = await Score.get(id=score_id)
    return row.benchmark_revision


async def test_submit_stores_a_typed_top_level_benchmark_revision(tortoise_db: None) -> None:
    store = await _store_with_benchmark()

    score, _ = await store.submit(_revision_submission(benchmark_revision="rev-typed"))

    assert await _stored_revision(score.id) == "rev-typed"


async def test_submit_promotes_the_revision_from_metadata(tortoise_db: None) -> None:
    # WHY: this is the shape every deployed Client sends today
    # (packages/screamingface/.../leaderboards.py) — it must keep working.
    store = await _store_with_benchmark()

    score, _ = await store.submit(
        _revision_submission(metadata={"benchmark_revision": "rev-meta", "run_id": "r1"})
    )

    assert await _stored_revision(score.id) == "rev-meta"


async def test_submit_prefers_the_typed_revision_over_the_metadata_copy(
    tortoise_db: None,
) -> None:
    store = await _store_with_benchmark()

    score, _ = await store.submit(
        _revision_submission(
            benchmark_revision="rev-typed",
            metadata={"benchmark_revision": "rev-meta"},
        )
    )

    assert await _stored_revision(score.id) == "rev-typed"


async def test_submit_leaves_the_metadata_copy_intact(tortoise_db: None) -> None:
    # INVARIANT: promotion reads metadata, it never mutates or strips it. The client's
    # payload is stored as sent.
    store = await _store_with_benchmark()

    score, _ = await store.submit(
        _revision_submission(metadata={"benchmark_revision": "rev-meta", "run_id": "r1"})
    )

    assert score.metadata == {"benchmark_revision": "rev-meta", "run_id": "r1"}


async def test_submit_accepts_a_submission_with_no_revision_anywhere(tortoise_db: None) -> None:
    store = await _store_with_benchmark()

    score, created = await store.submit(_revision_submission(metadata={"source": "unit"}))

    assert created is True
    assert await _stored_revision(score.id) is None


@pytest.mark.parametrize(
    "metadata",
    [
        {"benchmark_revision": ""},
        {"benchmark_revision": 42},
        {"benchmark_revision": None},
        {"benchmark_revision": ["rev"]},
    ],
)
async def test_submit_treats_an_unusable_metadata_revision_as_absent(
    tortoise_db: None, metadata: dict[str, object]
) -> None:
    # WHY: metadata is free-form and client-supplied, so a non-string or empty value is
    # untrustworthy input, not a crash — it resolves to None rather than raising.
    store = await _store_with_benchmark()

    score, created = await store.submit(_revision_submission(metadata=metadata))

    assert created is True
    assert await _stored_revision(score.id) is None


# --- OME-775: revision participates in dedup identity (D3) ----------------------------------


async def test_same_recipe_at_two_revisions_does_not_dedup(tortoise_db: None) -> None:
    # INVARIANT: a different benchmark revision is a different thing measured, so it is part
    # of the recipe's identity. Before OME-775 these two collided and the second was silently
    # discarded — which would have made the ranking partition unreachable, since the second
    # revision's row never existed.
    store = await _store_with_benchmark()

    first, first_created = await store.submit(_revision_submission(benchmark_revision="rev-a"))
    second, second_created = await store.submit(_revision_submission(benchmark_revision="rev-b"))

    assert first_created is True
    assert second_created is True
    assert first.id != second.id
    assert await Score.all().count() == 2


async def test_identical_submissions_still_dedup_with_a_revision(tortoise_db: None) -> None:
    # The OME-391 guarantee must survive the identity change.
    store = await _store_with_benchmark()

    first, first_created = await store.submit(_revision_submission(benchmark_revision="rev-a"))
    second, second_created = await store.submit(_revision_submission(benchmark_revision="rev-a"))

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert await Score.all().count() == 1


async def test_identity_follows_the_resolved_revision_not_its_wire_position(
    tortoise_db: None,
) -> None:
    # INVARIANT: a revision sent typed and the same revision sent in metadata are the same
    # submission. If identity read the wire shape instead of the resolved value, a client
    # upgrading from the metadata form to the typed form would duplicate its whole history.
    store = await _store_with_benchmark()

    first, first_created = await store.submit(
        _revision_submission(metadata={"benchmark_revision": "rev-a"})
    )
    second, second_created = await store.submit(_revision_submission(benchmark_revision="rev-a"))

    assert first_created is True
    assert second_created is False
    assert first.id == second.id


# --- OME-775: ranking partitions on (spec_id, benchmark_revision) ---------------------------


async def test_leaderboard_ranks_each_revision_of_a_spec_separately(tortoise_db: None) -> None:
    # INVARIANT: results measured against different benchmark revisions are not comparable, so
    # the board must not let one beat the other. Before OME-775 this returned a single row —
    # the higher accuracy winning across an incomparable boundary.
    store = await _store_with_benchmark()
    await store.submit(
        _revision_submission(spec_id="spec-x", benchmark_revision="rev-old"),
    )
    await store.submit(
        _revision_submission(spec_id="spec-x", benchmark_revision="rev-new"),
    )

    rows = await store.leaderboard("hle")

    assert len(rows) == 2
    assert {row.benchmark_revision for row in rows} == {"rev-old", "rev-new"}
    assert {row.spec_id for row in rows} == {"spec-x"}


async def test_leaderboard_still_collapses_within_one_revision(tortoise_db: None) -> None:
    # Best-per-spec is preserved inside a revision — the partition adds a dimension, it does
    # not stop collapsing.
    store = await _store_with_benchmark()
    await store.submit(
        ScoreSubmission(
            benchmark_id="hle",
            spec_id="spec-y",
            url4_expression="url4://benchmark/spec-y/low",
            score=0.60,
            total_questions=100,
            correct_questions=60,
            ran_with_providers=["openai"],
            benchmark_revision="rev-same",
        )
    )
    await store.submit(
        ScoreSubmission(
            benchmark_id="hle",
            spec_id="spec-y",
            url4_expression="url4://benchmark/spec-y/high",
            score=0.90,
            total_questions=100,
            correct_questions=90,
            ran_with_providers=["openai"],
            benchmark_revision="rev-same",
        )
    )

    rows = await store.leaderboard("hle")

    assert len(rows) == 1
    assert rows[0].score == 0.90


async def test_leaderboard_groups_null_revision_rows_exactly_as_before(
    tortoise_db: None,
) -> None:
    # INVARIANT: backward compatibility. Every row predating OME-775 has a NULL revision, so
    # they must keep collapsing to best-per-spec rather than splintering into one row each.
    store = await _store_with_benchmark()
    await store.submit(_submission(spec_id="spec-legacy", score=0.60))
    await store.submit(_submission(spec_id="spec-legacy", score=0.85))

    rows = await store.leaderboard("hle")

    assert len(rows) == 1
    assert rows[0].score == 0.85
    assert rows[0].benchmark_revision is None


# --- OME-775: the revision reaches the score read DTO ---------------------------------------


async def test_score_read_schema_carries_the_resolved_revision(tortoise_db: None) -> None:
    store = await _store_with_benchmark()

    score, _ = await store.submit(_revision_submission(metadata={"benchmark_revision": "rev-read"}))

    assert score.benchmark_revision == "rev-read"


async def test_score_read_schema_serialises_an_absent_revision_as_null(
    tortoise_db: None,
) -> None:
    # INVARIANT: absent means null, never omitted — a client must be able to distinguish
    # "no revision recorded" from "field missing from this deployment".
    store = await _store_with_benchmark()

    score, _ = await store.submit(_revision_submission(metadata={"source": "unit"}))

    assert "benchmark_revision" in score.model_dump()
    assert score.benchmark_revision is None


# --- OME-775 follow-up: the board shows only the registered revision ------------------------
# The partition alone was not enough. It stopped one revision displacing another in the
# best-per-spec collapse, but the outer query still ordered every surviving row into ONE
# accuracy ranking — so a stale-revision score could hold rank 1 on a board registered at a
# different revision, presenting two incomparable numbers as a ranking. Verified against a
# running server before this was written.


async def _benchmark_at(revision: str | None) -> ScoreStore:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="Fixture", revision=revision)
    return store


async def test_leaderboard_excludes_scores_from_a_non_registered_revision(
    tortoise_db: None,
) -> None:
    # INVARIANT: every entry the board ranks was measured against the revision the board is
    # registered at. A higher score from an obsolete revision must not outrank a current one.
    store = await _benchmark_at("REV-CURRENT")
    await store.submit(
        _revision_submission(spec_id="old-winner", benchmark_revision="REV-OBSOLETE")
    )
    await store.submit(_revision_submission(spec_id="new-entry", benchmark_revision="REV-CURRENT"))

    rows = await store.leaderboard("hle")

    assert [row.spec_id for row in rows] == ["new-entry"]
    assert all(row.benchmark_revision == "REV-CURRENT" for row in rows)


async def test_leaderboard_without_a_registered_revision_filters_nothing(
    tortoise_db: None,
) -> None:
    # WHY: the retained legacy demo benchmarks have no Engine revision (D2). Filtering on a
    # null registered revision would empty their boards entirely.
    store = await _benchmark_at(None)
    await store.submit(_revision_submission(spec_id="legacy-a", benchmark_revision=None))
    await store.submit(_revision_submission(spec_id="legacy-b", benchmark_revision="whatever"))

    rows = await store.leaderboard("hle")

    assert {row.spec_id for row in rows} == {"legacy-a", "legacy-b"}


async def test_leaderboard_at_a_registered_revision_excludes_pre_revision_rows(
    tortoise_db: None,
) -> None:
    # Rows predating OME-775 carry a NULL revision. Once a benchmark declares a revision, such
    # a row cannot be asserted comparable to it, so it does not rank.
    store = await _benchmark_at("REV-CURRENT")
    await store.submit(_revision_submission(spec_id="pre-revision", benchmark_revision=None))
    await store.submit(_revision_submission(spec_id="current", benchmark_revision="REV-CURRENT"))

    rows = await store.leaderboard("hle")

    assert [row.spec_id for row in rows] == ["current"]


# --- OME-820: verified means "ran on OpenMined infrastructure" (spec 2.1) ---


async def test_a_new_submission_is_verified_by_default(tortoise_db: None) -> None:
    """The default exists so the board does not read "unverified" on every row.

    It asserts nothing: no service re-runs submissions (OME-414) and nothing
    attests where a run executed — the SDK takes independent engine and scoreboard
    URLs, and the chart ships authMode: disabled. OME-821 gives it a real meaning.
    """
    store = ScoreStore()
    await store.register_benchmark("hle", "HLE")

    outcome = await store.submit(_submission(spec_id="fresh"))

    assert outcome.created is True
    assert outcome.score.verified_by_screamingface is True


async def test_pre_existing_unverified_rows_are_not_backfilled(tortoise_db: None) -> None:
    """The column can still hold False, so a row is not forced true on read.

    NOTE ON SCOPE: this does NOT prove D5 ("no backfill"). `tortoise_db` builds the
    schema from the models via `tortoise_test_context`, so migration files never
    execute in tests — a future data migration flipping existing rows would leave
    this green. D5 is guarded separately by
    `test_no_migration_backfills_the_verified_column`, which reads the migration
    files themselves. Found in review of OME-820.
    """
    benchmark = await Benchmark.create(id="hle", display_name="HLE")
    legacy = await Score.create(
        benchmark=benchmark,
        spec_id="legacy",
        url4_expression="x",
        score=0.5,
        total_questions=2,
        correct_questions=1,
        ran_with_providers=["openai"],
        verified_by_screamingface=False,
        content_hash="legacy-hash",
    )

    reread = await Score.get(id=legacy.id)

    assert reread.verified_by_screamingface is False


async def test_mark_verified_flips_a_false_row_and_is_idempotent(
    tortoise_db: None,
) -> None:
    """Starts from an explicit False row so the transition is actually exercised.

    An earlier version of this test submitted a row (which now defaults to True) and
    asserted True afterwards — it would have passed even if mark_verified() did nothing
    at all. Found in review of OME-820.
    """
    benchmark = await Benchmark.create(id="hle", display_name="HLE")
    score = await Score.create(
        benchmark=benchmark,
        spec_id="idem",
        url4_expression="x",
        score=0.5,
        total_questions=2,
        correct_questions=1,
        ran_with_providers=["openai"],
        verified_by_screamingface=False,
        content_hash="idem-hash",
    )
    store = ScoreStore()

    await store.mark_verified(score.id)
    after_first = await Score.get(id=score.id)
    await store.mark_verified(score.id)
    after_second = await Score.get(id=score.id)

    assert after_first.verified_by_screamingface is True
    assert after_second.verified_by_screamingface is True


def test_no_migration_backfills_the_verified_column() -> None:
    """INVARIANT (D5): no migration may flip existing rows' verified_by_screamingface.

    This is the real D5 guard. The runtime test above cannot provide it: `tortoise_db`
    builds the schema from the models via `tortoise_test_context`, so migration files
    never execute under pytest and a data migration would go unnoticed.

    Reading the migration sources instead makes the invariant falsifiable — adding an
    UPDATE on this column fails here. WHY it matters: rows created before OME-820 were
    genuinely not verified (some are local test submissions), so backfilling them to
    True would publish a claim about runs nobody checked.
    """
    from pathlib import Path

    import scoreboard.scores.migrations as migrations_pkg

    directory = Path(migrations_pkg.__file__).parent
    sources = sorted(p for p in directory.glob("*.py") if p.name != "__init__.py")
    assert sources, "no migration files found — the guard would pass vacuously"

    # OME-865: check BOTH names. Migrations predating the rename carry the old one and
    # cannot be edited, while any future backfill would use the new one — so a guard that
    # knew only one name would go blind on half the history.
    names = ("verified_by_screamingface", "verified_by_openmined")
    offenders = [
        path.name
        for path in sources
        if any(name in (text := path.read_text()) for name in names)
        and any(word in text.lower() for word in ("update", "runpython", "runsql"))
    ]

    assert offenders == [], (
        f"migration(s) may backfill verified_by_screamingface: {offenders}. "
        "Existing rows must keep the value they were created with (OME-820 D5)."
    )


# --- OME-770: run cost through the store -----------------------------------


async def test_run_cost_persists_and_reads_back_on_the_leaderboard(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="HLE")
    store = ScoreStore()
    submission = _submission(spec_id="costed")
    submission = submission.model_copy(update={"run_cost_usd": Decimal("3.500000")})

    await store.submit(submission)
    entries = await store.leaderboard("hle")

    assert entries[0].run_cost_usd == Decimal("3.500000")


async def test_a_submission_without_a_cost_reads_back_none_not_zero(tortoise_db: None) -> None:
    """INVARIANT: unreported cost must stay distinguishable from a free run.

    OME-770's Pareto frontier would rank an unknown-cost entry as the cheapest
    submission if these ever collapsed into 0.
    """
    await Benchmark.create(id="hle", display_name="HLE")
    store = ScoreStore()

    await store.submit(_submission(spec_id="uncosted"))
    entries = await store.leaderboard("hle")

    assert entries[0].run_cost_usd is None


async def test_a_zero_cost_run_reads_back_as_zero(tortoise_db: None) -> None:
    """A fully cache-served run costs 0 — data, not a missing value."""
    await Benchmark.create(id="hle", display_name="HLE")
    store = ScoreStore()
    submission = _submission(spec_id="free").model_copy(update={"run_cost_usd": Decimal("0")})

    await store.submit(submission)
    entries = await store.leaderboard("hle")

    assert entries[0].run_cost_usd == Decimal("0")
    assert entries[0].run_cost_usd is not None


async def test_cost_is_outside_recipe_identity_so_dedup_still_collapses(tortoise_db: None) -> None:
    """INVARIANT: cost is a property of an execution, not of the recipe.

    Two submissions identical except for their cost are the same recipe and must
    dedup to one row — pinning that run_cost_usd stays out of content_hash, which
    OME-391's dedup guarantee depends on.
    """
    await Benchmark.create(id="hle", display_name="HLE")
    store = ScoreStore()
    base = _submission(spec_id="same-recipe")

    first = await store.submit(base.model_copy(update={"run_cost_usd": Decimal("1.00")}))
    second = await store.submit(base.model_copy(update={"run_cost_usd": Decimal("99.00")}))

    assert first.created is True
    assert second.created is False
    assert second.score.id == first.score.id
    assert await Score.all().count() == 1
    # The stored row keeps the FIRST cost; the second is discarded. Documented as
    # a known limitation on OME-770 — the fix is requiring cost, not mutating a
    # deduplicated row.
    assert second.score.run_cost_usd == Decimal("1.00")


# --- OME-770 review pass: raw projection rows must be fully typed (spec 2.5) ---


async def test_the_raw_leaderboard_projection_types_every_column() -> None:
    """INVARIANT: rows leaving the raw pypika projection are already Python-typed.

    The projection bypasses the ORM, so each column has to be converted
    explicitly. Only `ran_with_providers` was, and `run_cost_usd` reached
    `LeaderboardEntry` as a raw SQLite string — surviving purely because Pydantic
    coerces str -> Decimal in lax mode. That breaks the moment anything reads the
    rows BEFORE validation, which spec 2.5 requires: the cheapest-run stat must be
    computed in Python over Decimal, because SQLite compares this column as TEXT.
    """
    from scoreboard.scores.store import _to_python_rows

    rows = _to_python_rows(
        [
            {
                "spec_id": "s",
                "ran_with_providers": '["openai"]',
                "run_cost_usd": "3.5",
            },
            {
                "spec_id": "t",
                "ran_with_providers": '["openai"]',
                "run_cost_usd": None,
            },
        ]
    )

    assert rows[0]["ran_with_providers"] == ["openai"]
    assert rows[0]["run_cost_usd"] == Decimal("3.5")
    assert isinstance(rows[0]["run_cost_usd"], Decimal)
    # INVARIANT (D5): absent stays absent — never coerced to Decimal("0").
    assert rows[1]["run_cost_usd"] is None


async def test_one_unreadable_cost_does_not_take_down_the_whole_board() -> None:
    """INVARIANT: a corrupt cost degrades to null; it never fails the read path.

    On SQLite the column is VARCHAR(40) with no database-level guard, so raw SQL
    can write a value outside DECIMAL(12, 6). Converting it calls Decimal.quantize,
    which RAISES rather than returning — and that surfaced as HTTP 500 for EVERY
    entry on the board, not just the bad row. Verified end-to-end before this test.

    The ORM path is already safe (Tortoise's own to_python_value rejects such a
    write), and production is Postgres where the column really is DECIMAL(12, 6),
    so this is defence for a narrow case on a public read path (spec 2.7).
    """
    from scoreboard.scores.store import _to_python_rows

    rows = _to_python_rows(
        [
            {"spec_id": "good", "ran_with_providers": '["openai"]', "run_cost_usd": "3.5"},
            {"spec_id": "corrupt", "ran_with_providers": '["openai"]', "run_cost_usd": "1E+30"},
        ]
    )

    assert rows[0]["run_cost_usd"] == Decimal("3.5")
    # Degraded to "cost unknown" — an already-defined state — not an exception.
    assert rows[1]["run_cost_usd"] is None


async def test_corrupt_json_drops_the_row_instead_of_failing_the_board() -> None:
    """FieldError is NOT a ValueError, so the original guard could not catch it.

    JSONField.to_python_value raises tortoise FieldError on invalid JSON, which fell
    straight through `except (InvalidOperation, ValueError)` and 500'd the whole
    leaderboard — the exact failure that guard exists to prevent (found in review).

    ran_with_providers cannot degrade to None: LeaderboardEntry types it as list[str],
    so nulling it would fail validation and re-raise the 500. The row is dropped, and
    logged at WARNING so the omission is traceable.
    """
    from scoreboard.scores.store import _to_python_rows

    rows = _to_python_rows(
        [
            {"spec_id": "good", "ran_with_providers": '["openai"]', "run_cost_usd": "3.5"},
            {"spec_id": "bad-json", "ran_with_providers": "{not json", "run_cost_usd": "1.0"},
        ]
    )

    assert [row["spec_id"] for row in rows] == ["good"]
    assert rows[0]["ran_with_providers"] == ["openai"]


async def test_an_unreadable_cost_degrades_but_keeps_the_row() -> None:
    """A nullable column degrades in place; only a non-nullable one costs the row."""
    from scoreboard.scores.store import _to_python_rows

    rows = _to_python_rows(
        [{"spec_id": "bad-cost", "ran_with_providers": '["openai"]', "run_cost_usd": "1E+30"}]
    )

    assert [row["spec_id"] for row in rows] == ["bad-cost"]
    assert rows[0]["run_cost_usd"] is None


# --- OME-894: benchmark visibility ----------------------------------------------------------


async def test_register_benchmark_defaults_visibility_to_public(tortoise_db: None) -> None:
    store = ScoreStore()

    registered = await store.register_benchmark(
        benchmark_id="hle",
        display_name="Humanity's Last Exam",
    )

    assert registered.visibility == "public"


async def test_register_benchmark_persists_private_visibility(tortoise_db: None) -> None:
    store = ScoreStore()

    registered = await store.register_benchmark(
        benchmark_id="healthbench-worst30",
        display_name="HealthBench Worst-30% Challenge",
        visibility="private",
    )
    listed = await store.list_benchmarks()

    assert registered.visibility == "private"
    assert [benchmark.visibility for benchmark in listed] == ["private"]


async def test_register_benchmark_can_flip_visibility_back(tortoise_db: None) -> None:
    # INVARIANT: seeding is idempotent and update_or_create rewrites defaults, so a benchmark
    # cannot get stuck private after a mis-seed.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")

    reregistered = await store.register_benchmark(
        benchmark_id="hle", display_name="HLE", visibility="public"
    )

    assert reregistered.visibility == "public"
    assert await Benchmark.all().count() == 1


# --- OME-894: owner-scoped reads -------------------------------------------------------------
# Scoping lives in the QUERY, not in a post-filter over rows already fetched. The board's own
# ranking query is NOT owner-scoped: a private board does not rank at all, so a participant's own
# rows come from list_owned_entries instead (see below) and the ranking query keeps exactly the
# shape OME-775 gave it.

ALICE = "alice@example.test"
BOB = "bob@example.test"


def _owned_submission(
    *,
    submitted_by: str,
    spec_id: str,
    score: float = 0.75,
    benchmark_revision: str | None = None,
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{spec_id}/{submitted_by}/{score}",
        submitted_by=submitted_by,
        score=score,
        total_questions=100,
        correct_questions=int(score * 100),
        ran_with_providers=["openai"],
        benchmark_revision=benchmark_revision,
    )


async def _two_participant_board() -> ScoreStore:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", revision="rev-current")
    await store.submit(
        _owned_submission(
            submitted_by=ALICE,
            spec_id="spec-alice",
            score=0.60,
            benchmark_revision="rev-current",
        )
    )
    await store.submit(
        _owned_submission(
            submitted_by=BOB,
            spec_id="spec-bob",
            score=0.90,
            benchmark_revision="rev-current",
        )
    )
    return store


async def test_leaderboard_without_an_owner_is_unchanged(tortoise_db: None) -> None:
    # The public path must not shift because the owner-scoping parameter exists.
    store = await _two_participant_board()

    rows = await store.leaderboard("hle")

    assert [row.spec_id for row in rows] == ["spec-bob", "spec-alice"]


async def test_list_for_spec_scoped_to_an_owner_hides_another_participants_rows(
    tortoise_db: None,
) -> None:
    store = await _two_participant_board()

    mine = await store.list_for_spec("hle", "spec-alice", owner=ALICE)
    theirs = await store.list_for_spec("hle", "spec-bob", owner=ALICE)

    assert [row.spec_id for row in mine] == ["spec-alice"]
    assert theirs == []


def _same_recipe(submitted_by: str) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id="shared-spec",
        url4_expression="url4://benchmark/shared",
        submitted_by=submitted_by,
        score=0.80,
        total_questions=100,
        correct_questions=80,
        ran_with_providers=["openai"],
    )


async def test_two_participants_sharing_a_recipe_keep_separate_rows_when_private(
    tortoise_db: None,
) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")

    first, first_created = await store.submit(_same_recipe(ALICE), identity_verified=True)
    second, second_created = await store.submit(_same_recipe(BOB), identity_verified=True)

    assert first_created is True
    assert second_created is True
    assert first.id != second.id
    # INVARIANT: neither participant is handed the other's row.
    assert first.submitted_by == ALICE
    assert second.submitted_by == BOB


async def test_one_participant_resubmitting_still_dedups_when_private(
    tortoise_db: None,
) -> None:
    # Per-person idempotency survives: only the cross-person collapse is removed.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")

    first, first_created = await store.submit(_same_recipe(ALICE), identity_verified=True)
    again, again_created = await store.submit(_same_recipe(ALICE), identity_verified=True)

    assert first_created is True
    assert again_created is False
    assert again.id == first.id


async def test_a_public_board_still_dedups_across_participants(tortoise_db: None) -> None:
    # INVARIANT: OME-391's recipe identity is untouched on a public board. Splitting it would
    # let anyone resubmit an existing public recipe under their own name and duplicate the board.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, first_created = await store.submit(_same_recipe(ALICE))
    second, second_created = await store.submit(_same_recipe(BOB))

    assert first_created is True
    assert second_created is False
    assert second.id == first.id


# --- OME-894 round 2: cross-participant leaks and lost own rows ------------------------------


async def test_a_shared_idempotency_key_does_not_cross_participants_when_private(
    tortoise_db: None,
) -> None:
    # INVARIANT: the idempotency key is checked BEFORE the content hash and was keyed globally,
    # so on a private board a second participant reusing a key received the first participant's
    # stored row — url4, metadata and id included — and created nothing of their own. The
    # per-submitter content hash could not help, because the key short-circuits ahead of it.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")

    first, first_created = await store.submit(
        _same_recipe(ALICE), idempotency_key="shared", identity_verified=True
    )
    second, second_created = await store.submit(
        _same_recipe(BOB), idempotency_key="shared", identity_verified=True
    )

    assert first_created is True
    assert second_created is True
    assert second.id != first.id
    assert second.submitted_by == BOB


async def test_a_repeated_key_from_the_same_participant_still_dedups_when_private(
    tortoise_db: None,
) -> None:
    # Per-person idempotency must survive the scoping: a retry is still a retry.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")

    first, _ = await store.submit(
        _same_recipe(ALICE), idempotency_key="retry", identity_verified=True
    )
    again, again_created = await store.submit(
        _same_recipe(ALICE), idempotency_key="retry", identity_verified=True
    )

    assert again_created is False
    assert again.id == first.id


async def test_a_public_board_keeps_its_global_idempotency_key(tortoise_db: None) -> None:
    # INVARIANT: unchanged on a public board. The key is a client's retry token there and its
    # existing semantics are not this ticket's to alter.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(_same_recipe(ALICE), idempotency_key="shared")
    second, second_created = await store.submit(_same_recipe(BOB), idempotency_key="shared")

    assert second_created is False
    assert second.id == first.id


async def test_a_public_raw_key_cannot_resolve_a_private_scoped_key(
    tortoise_db: None,
) -> None:
    # INVARIANT: client-controlled public keys and server-derived private keys occupy disjoint
    # stored namespaces. Before both sides were namespaced, a caller could compute the victim's
    # `sfp-<sha256>` token, send that exact string as a public raw key, and receive the victim's
    # private score and metadata from the key-first lookup.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="private", display_name="Private", visibility="private"
    )
    await store.register_benchmark(benchmark_id="public", display_name="Public")

    private_submission = _same_recipe(ALICE).model_copy(
        update={
            "benchmark_id": "private",
            "metadata": {"secret": "victim-only"},
        }
    )
    victim, victim_created = await store.submit(
        private_submission,
        idempotency_key="predictable-key",
        identity_verified=True,
    )
    private_stored_key = _scoped_idempotency_key("predictable-key", ALICE, per_submitter=True)
    assert private_stored_key is not None

    public_submission = _same_recipe(BOB).model_copy(
        update={
            "benchmark_id": "public",
            "metadata": {"source": "public"},
        }
    )
    public, public_created = await store.submit(
        public_submission,
        idempotency_key=private_stored_key,
        identity_verified=True,
    )

    assert victim_created is True
    assert public_created is True
    assert public.id != victim.id
    assert public.benchmark_id == "public"
    assert public.submitted_by == BOB
    assert public.metadata == {"source": "public"}


async def test_owned_rows_include_every_submission_for_one_spec(tortoise_db: None) -> None:
    # INVARIANT: a private view lists ALL the caller's rows. leaderboard() collapses to
    # best-per-spec (rn == 1), so routing my_submissions through it silently dropped a
    # participant's earlier submission to the same spec — reintroducing, within one spec, exactly
    # the invisible-submission failure D8 exists to prevent.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="hle", display_name="HLE", revision="rev-1", visibility="private"
    )
    for score in (0.60, 0.80):
        await store.submit(
            ScoreSubmission(
                benchmark_id="hle",
                spec_id="spec-a",
                url4_expression=f"url4://benchmark/spec-a/{score}",
                submitted_by=ALICE,
                score=score,
                total_questions=100,
                correct_questions=int(score * 100),
                ran_with_providers=["openai"],
                benchmark_revision="rev-1",
            ),
            identity_verified=True,
        )

    owned = await store.list_owned_entries("hle", owner=ALICE)

    assert sorted(row.score for row in owned) == [0.60, 0.80]


async def test_owned_rows_exclude_other_participants(tortoise_db: None) -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    await store.submit(_same_recipe(ALICE), identity_verified=True)
    await store.submit(_same_recipe(BOB), identity_verified=True)

    owned = await store.list_owned_entries("hle", owner=ALICE)

    assert [row.submitted_by for row in owned] == [ALICE]


# --- review round 3: the scoped key must survive PostgreSQL, and the retry path must use it ---


def test_a_scoped_idempotency_key_is_storable_in_a_varchar_column() -> None:
    # INVARIANT: PostgreSQL rejects NUL in any character type — verified against postgres:16 with
    # `ERROR: invalid byte sequence for encoding "UTF8": 0x00`. The first implementation joined
    # submitter and key with "\x00", which SQLite accepted silently, so every private submission
    # carrying an Idempotency-Key would have failed only in production. The stored key must also
    # fit IdempotencyKey.key, which is VARCHAR(255).
    scoped = _scoped_idempotency_key(
        "retry-1", "a-very-long-address-" * 12 + "@example.test", per_submitter=True
    )

    assert scoped is not None
    assert "\x00" not in scoped
    assert scoped.isascii() and scoped.isprintable()
    assert len(scoped) <= 255


def test_a_scoped_key_separates_submitters_and_is_stable() -> None:
    alice = _scoped_idempotency_key("k", "alice@example.test", per_submitter=True)
    bob = _scoped_idempotency_key("k", "bob@example.test", per_submitter=True)

    assert alice != bob
    assert alice == _scoped_idempotency_key("k", "alice@example.test", per_submitter=True)


async def test_public_and_private_keys_use_disjoint_stored_namespaces() -> None:
    private = _scoped_idempotency_key("k", ALICE, per_submitter=True)
    assert private is not None
    public = _scoped_idempotency_key(private, BOB, per_submitter=False)

    assert public is not None and public.startswith("sfu-")
    assert private.startswith("sfp-")
    assert public != private


def test_a_public_key_is_stored_verbatim() -> None:
    assert _scoped_idempotency_key("k", "alice@example.test", per_submitter=False) == "k"


async def test_the_concurrent_retry_path_resolves_with_the_scoped_key(
    tortoise_db: None,
) -> None:
    # INVARIANT: the IntegrityError branch in submit() must consult the SCOPED key. Using the raw
    # key there re-opens the cross-participant leak this PR closed, for exactly the concurrent
    # case the branch exists to handle.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    await store.submit(_same_recipe(ALICE), idempotency_key="shared", identity_verified=True)

    seen: list[str | None] = []
    real_resolve = ScoreStore._resolve_existing
    real_create = Score.create

    async def _record(self, idempotency_key, content_hash):  # type: ignore[no-untyped-def]
        seen.append(idempotency_key)
        return await real_resolve(self, idempotency_key, content_hash)

    raised = {"done": False}

    async def _race_once(**kwargs):  # type: ignore[no-untyped-def]
        # Force the concurrent-insert branch exactly once, which is the only way to reach the
        # IntegrityError handler without a real race.
        if not raised["done"]:
            raised["done"] = True
            raise IntegrityError("simulated concurrent insert")
        return await real_create(**kwargs)

    ScoreStore._resolve_existing = _record  # type: ignore[method-assign]
    Score.create = _race_once  # type: ignore[method-assign]
    try:
        with contextlib.suppress(Exception):
            await store.submit(_same_recipe(BOB), idempotency_key="shared", identity_verified=True)
    finally:
        ScoreStore._resolve_existing = real_resolve  # type: ignore[method-assign]
        Score.create = real_create  # type: ignore[method-assign]

    assert raised["done"], "the IntegrityError branch was never reached"
    # Whatever it looked up, it must never have been the bare cross-participant key.
    assert "shared" not in seen


# --- review round 6: the reserved namespace survives a Helm rollout window -------------------
# `0009` clears `sfp-%`, but the migrate Job is a `pre-upgrade` hook — it runs BEFORE the new
# pods roll. Old replicas keep serving through that window and keep storing client keys
# verbatim, so a row written then outlives the migration. The migration cannot close this; the
# lookup has to. Found in review of PR #719.


async def _stale_reserved_mapping(store: ScoreStore, *, owner: str, victim: str) -> Score:
    """Bind `owner`'s derived private key to a score submitted by `victim`.

    This is exactly the row an old replica writes when it accepts `Idempotency-Key: sfp-<...>`
    verbatim, which is what the pre-`0009` code did.
    """
    victim_score = await Score.create(
        benchmark_id="hle",
        spec_id="victim-spec",
        url4_expression="url4://benchmark/victim",
        submitted_by=victim,
        score=0.99,
        total_questions=100,
        correct_questions=99,
        ran_with_providers=["openai"],
        content_hash="victim-hash",
        metadata={"secret": "victim-only"},
    )
    stored_key = _scoped_idempotency_key("rollout-key", owner, per_submitter=True)
    assert stored_key is not None and stored_key.startswith("sfp-")
    await IdempotencyKey.create(
        key=stored_key,
        score=victim_score,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    return victim_score


async def test_a_private_key_hit_owned_by_another_participant_is_not_served(
    tortoise_db: None,
) -> None:
    # INVARIANT: on a private board a key-resolved row must belong to the caller. The prefix
    # reserves the namespace going forward; it cannot vouch for what is already in the table.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    victim_score = await _stale_reserved_mapping(store, owner=ALICE, victim=BOB)

    outcome = None
    # Fails closed when there is nothing of her own to fall back to: the corrupt slot is ALICE's
    # own derived key and is not rebound on a read, so the submission is refused rather than
    # answered with another participant's row. Refusing is acceptable here; answering is not.
    with contextlib.suppress(IntegrityError):
        outcome, _ = await store.submit(
            _same_recipe(ALICE), idempotency_key="rollout-key", identity_verified=True
        )

    if outcome is not None:
        assert outcome.submitted_by == ALICE
        assert outcome.id != victim_score.id
        assert outcome.metadata != {"secret": "victim-only"}
    # BOB's row must survive either way — nothing here may delete another participant's score.
    assert await Score.get_or_none(id=victim_score.id) is not None


async def test_a_corrupt_reserved_slot_still_replays_the_callers_own_row(
    tortoise_db: None,
) -> None:
    # The fallback that makes the fix usable rather than merely safe: ignoring the foreign row
    # drops through to the per-submitter content hash, which can only ever match the caller.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    await _stale_reserved_mapping(store, owner=ALICE, victim=BOB)
    mine, created = await store.submit(_same_recipe(ALICE), identity_verified=True)
    assert created

    replay, replay_created = await store.submit(
        _same_recipe(ALICE), idempotency_key="rollout-key", identity_verified=True
    )

    assert not replay_created
    assert replay.id == mine.id
    assert replay.submitted_by == ALICE


async def test_a_public_board_still_replays_a_global_key_across_submitters(
    tortoise_db: None,
) -> None:
    # The regression guard: the owner test must apply ONLY to private boards. A public
    # idempotency key is a global retry token and that semantics is not this ticket's to change.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, _ = await store.submit(_same_recipe(ALICE), idempotency_key="global")
    second, second_created = await store.submit(_same_recipe(BOB), idempotency_key="global")

    assert not second_created
    assert second.id == first.id


# --- review round 8: what the mapping POINTS AT decides, not what the request is ------------
# The round-6 test branched on the request's `per_submitter`. A board that flips public -> private
# leaves its pre-flip raw mappings live for the 24h TTL, and the key lookup is global rather than
# per-benchmark, so reusing such a key on ANY public board took the `not per_submitter`
# short-circuit and returned the now-private score. Found in review of PR #719.


async def test_a_raw_mapping_is_not_replayed_after_its_board_turned_private(
    tortoise_db: None,
) -> None:
    # INVARIANT: a mapping is honoured only when the caller may READ what it points at.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    alice_score, _ = await store.submit(
        _same_recipe(ALICE), idempotency_key="shared", identity_verified=True
    )

    # The config change the ticket exists to enable — and the moment the stale mapping turns toxic.
    await store.set_visibility("hle", "private")
    await store.register_benchmark(benchmark_id="other", display_name="Other")

    bob = _owned_submission(submitted_by=BOB, spec_id="bob-spec").model_copy(
        update={"benchmark_id": "other"}
    )
    replayed, created = await store.submit(bob, idempotency_key="shared", identity_verified=True)

    assert created, "BOB must get his own row, not a replay of a now-private score"
    assert replayed.id != alice_score.id
    assert replayed.submitted_by == BOB


async def test_an_escaped_public_key_cannot_be_supplied_as_a_raw_key(
    tortoise_db: None,
) -> None:
    # INVARIANT: no client-supplied value may address a SERVER-generated storage token. Escaping
    # `sfp-` produced `sfu-<digest>` and stored ordinary keys verbatim, so sending that digest back
    # as a raw key addressed the same mapping and replayed the first caller's score.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    escaped = _scoped_idempotency_key("sfp-collide", ALICE, per_submitter=False)
    assert escaped is not None and escaped.startswith("sfu-")

    first, _ = await store.submit(_same_recipe(ALICE), idempotency_key="sfp-collide")
    second, created = await store.submit(
        _owned_submission(submitted_by=BOB, spec_id="bob-spec"), idempotency_key=escaped
    )

    assert created, "a distinct client key must not resolve to another caller's mapping"
    assert second.id != first.id


def test_no_generated_storage_token_is_a_fixed_point_of_the_public_path() -> None:
    # INVARIANT: no value this function GENERATES may be supplied by a client and stored
    # unchanged. That is the whole of the namespace separation, expressed without naming any
    # prefix — so adding a third namespace and forgetting `RESERVED_KEY_PREFIXES` turns this red
    # instead of silently reopening the collision that review round 8 found.
    #
    # WHY this rather than hashing every public key: hashing is the structural fix, but it edits
    # three prior expiry tests that address IdempotencyKey rows by their raw key, and buys nothing
    # measurable today. This keeps the conservative fix honest instead (review of PR #719).
    # AIDEV-NOTE: a server token is any output that DIFFERS from its input. Selecting them by
    # prefix would rebuild the very denylist this test exists to police — a third namespace would
    # be filtered out of the check and the test would pass while the collision reopened. Verified:
    # renaming the private prefix to `sfx-` leaves a prefix-filtered version green.
    tokens = set()
    for raw in ("k", "retry-1", "sfp-x", "sfu-x", ""):
        for who in (ALICE, BOB):
            for per in (True, False):
                produced = _scoped_idempotency_key(raw, who, per_submitter=per)
                if produced is not None and produced != raw:
                    tokens.add(produced)

    assert tokens, "the probe generated no server-owned tokens — the fixture is wrong, not the code"
    for token in tokens:
        assert _scoped_idempotency_key(token, "carol@example.test", per_submitter=False) != token, (
            f"{token!r} is a server-generated storage token a client can supply verbatim; "
            "add its prefix to RESERVED_KEY_PREFIXES"
        )


# --- review round 9: privacy is decided BEFORE ownership, and ownership is not a claim ------
# Round 8 put the owner-match short-circuit ahead of the privacy check, so the check never ran when
# the names agreed. Under `auth_mode=disabled` the body's `submitted_by` is trusted, which turned
# that short-circuit into a read primitive for private rows. Found in review of PR #719.


async def test_claiming_the_owners_name_does_not_yield_a_private_row(tortoise_db: None) -> None:
    # INVARIANT: ownership by unverified string gates nothing. `identity_verified` is what admits a
    # caller to the ownership comparison at all, so claiming the victim's address buys nothing —
    # the claim is never compared. Note the attacker's submit passes NO identity argument: that is
    # the whole scenario, and marking it verified would quietly make the attacker legitimate.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    victim, _ = await store.submit(
        _same_recipe(ALICE), idempotency_key="stale", identity_verified=True
    )
    await store.set_visibility("hle", "private")
    await store.register_benchmark(benchmark_id="pub", display_name="Pub")

    attacker = _owned_submission(submitted_by=ALICE, spec_id="attacker").model_copy(
        update={"benchmark_id": "pub"}
    )
    got, created = await store.submit(attacker, idempotency_key="stale")

    assert created, "the attacker must get their own row, never the private one"
    assert got.id != victim.id


async def test_a_private_board_replays_an_identical_payload_via_the_content_hash(
    tortoise_db: None,
) -> None:
    # The content-hash path, which is independent of the key and must keep working on its own.
    # Round 9 named this test for a cost it no longer imposes — back then a private target was
    # refused outright and this was the owner's ONLY route to a replay. The verified owner now gets
    # the key fast path too (see the test above), so this guards the hash path rather than a
    # consolation prize for losing the key one.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    mine, created = await store.submit(
        _same_recipe(ALICE), idempotency_key="mine", identity_verified=True
    )
    assert created

    replay, replay_created = await store.submit(
        _same_recipe(ALICE), idempotency_key="mine", identity_verified=True
    )

    assert not replay_created
    assert replay.id == mine.id


async def test_a_legacy_row_in_the_reserved_namespace_cannot_leak_a_private_score(
    tortoise_db: None,
) -> None:
    # INVARIANT: reserving a namespace obliges us to purge it. `main` stores client keys verbatim,
    # so a crafted `sfu-<digest>` mapping can already exist, and round 8 made the escape path emit
    # exactly that namespace.
    #
    # AIDEV-NOTE: what is enforceable AT THE LOOKUP is the privacy half. A legacy `sfu-` row is
    # byte-indistinguishable from one this code wrote, so the runtime cannot reject it on identity
    # alone — and rejecting it on content-hash mismatch would break idempotency itself, since
    # replaying a DIFFERENT recipe under the same key IS the contract. Existing rows are cleared by
    # `0009`, which runs pre-upgrade and so can only ever see legacy ones. A row written during the
    # rollout window survives, and the residual is a wrong replay of a PUBLIC score inside it; a
    # private one cannot be reached, which is what this test pins.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    victim = await Score.create(
        benchmark_id="hle",
        spec_id="victim",
        url4_expression="url4://victim",
        submitted_by=BOB,
        score=0.99,
        total_questions=100,
        correct_questions=99,
        ran_with_providers=["openai"],
        content_hash="victim-hash",
        metadata={"secret": "victim-only"},
    )
    legacy = _scoped_idempotency_key("sfp-X", ALICE, per_submitter=False)
    assert legacy is not None and legacy.startswith("sfu-")
    await IdempotencyKey.create(
        key=legacy, score=victim, expires_at=datetime.now(UTC) + timedelta(hours=24)
    )

    got, _ = await store.submit(
        _same_recipe(ALICE), idempotency_key="sfp-X", identity_verified=True
    )

    assert got.id != victim.id
    assert got.metadata != {"secret": "victim-only"}


def test_migration_0009_clears_both_reserved_namespaces() -> None:
    # Reserving `sfu-` in round 8 without purging it left the finding open for existing data.
    source = (
        Path(__file__).resolve().parents[3]
        / "src/scoreboard/scores/migrations/0009_idempotency_key_namespaces.py"
    ).read_text()

    assert "sfp-%" in source
    assert "sfu-%" in source, "the reserved sfu- namespace is emitted but never purged"


def test_a_raw_row_missing_a_typed_field_is_left_alone() -> None:
    # `_to_python_rows` coerces the columns a raw query returns as strings. A projection that does
    # not SELECT one of them must be passed through untouched rather than KeyError'd — the branch
    # that skips an absent field had no test.
    rows = _to_python_rows([{"spec_id": "s", "score": 0.5}])

    assert rows == [{"spec_id": "s", "score": 0.5}]


async def test_a_private_scoped_key_pointing_at_a_public_row_is_not_replayed(
    tortoise_db: None,
) -> None:
    # The round-9 reorder moved the private-target case ahead of the ownership test, which left THIS
    # branch — private request, PUBLIC target, not the caller's — uncovered. The key lookup is
    # global, so a stale mapping can point off the board the request is aimed at.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="pub", display_name="Pub")
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    someone_elses = await Score.create(
        benchmark_id="pub",
        spec_id="theirs",
        url4_expression="url4://theirs",
        submitted_by=BOB,
        score=0.99,
        total_questions=100,
        correct_questions=99,
        ran_with_providers=["openai"],
        content_hash="theirs-hash",
    )
    scoped = _scoped_idempotency_key("k", ALICE, per_submitter=True)
    assert scoped is not None
    await IdempotencyKey.create(
        key=scoped, score=someone_elses, expires_at=datetime.now(UTC) + timedelta(hours=24)
    )

    got, created = await store.submit(
        _same_recipe(ALICE), idempotency_key="k", identity_verified=True
    )

    assert created
    assert got.id != someone_elses.id
    assert got.submitted_by == ALICE


async def test_the_concurrent_retry_branch_replays_what_the_race_winner_bound(
    tortoise_db: None,
) -> None:
    # The round-3 review flagged this handler as uncovered and round 8 rerouted it through
    # `_resolve_owned`; its success RETURN was still never executed.
    #
    # AIDEV-NOTE: driven at the SEAM, not through the database. Reaching that return needs a racer
    # to COMMIT between this caller's precheck and its insert, and the suite's fixture is
    # single-connection in-memory SQLite — a row written "outside" the transaction is rolled back
    # with it, so no ordering of real writes gets there. Controlling what the re-resolve returns
    # tests the handler's own contract: on IntegrityError, look again, and replay what is found.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    winner, _ = await store.submit(_same_recipe(BOB), idempotency_key="winner")

    real_resolve = ScoreStore._resolve_existing
    real_create = Score.create
    calls = {"resolve": 0}
    raised = {"done": False}

    async def _empty_then_found(self, idempotency_key, content_hash):  # type: ignore[no-untyped-def]
        calls["resolve"] += 1
        if calls["resolve"] == 1:
            return None  # the precheck sees nothing; the racer has not committed yet
        return await Score.get_or_none(id=winner.id)

    async def _lose_the_race(**kwargs):  # type: ignore[no-untyped-def]
        if not raised["done"]:
            raised["done"] = True
            raise IntegrityError("simulated concurrent insert")
        return await real_create(**kwargs)

    ScoreStore._resolve_existing = _empty_then_found  # type: ignore[method-assign]
    Score.create = _lose_the_race  # type: ignore[method-assign]
    try:
        replayed, created = await store.submit(_same_recipe(ALICE), idempotency_key="loser")
    finally:
        ScoreStore._resolve_existing = real_resolve  # type: ignore[method-assign]
        Score.create = real_create  # type: ignore[method-assign]

    assert raised["done"], "the IntegrityError branch was never reached"
    # INVARIANT: the loser of the race REPLAYS rather than erroring — that is the handler's reason
    # to exist, and it had no test proving it.
    assert not created
    assert replayed.id == winner.id


async def test_binding_a_key_tolerates_a_concurrent_identical_bind(tortoise_db: None) -> None:
    # `_bind_idempotency_key` swallows IntegrityError because a concurrent request winning the same
    # bind leaves the desired end state either way. That swallow was uncovered, so nothing proved
    # the caller still gets its row instead of a 500.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    original, _ = await store.submit(_same_recipe(ALICE))

    real_create = IdempotencyKey.create

    async def _already_bound(**kwargs):  # type: ignore[no-untyped-def]
        raise IntegrityError("simulated concurrent bind")

    IdempotencyKey.create = _already_bound  # type: ignore[method-assign]
    try:
        # No mapping exists, so this resolves by CONTENT HASH and then tries to bind the key.
        replay, created = await store.submit(_same_recipe(ALICE), idempotency_key="late-bind")
    finally:
        IdempotencyKey.create = real_create  # type: ignore[method-assign]

    assert not created
    assert replay.id == original.id


async def test_the_reclaim_leaves_a_mapping_a_concurrent_writer_just_bound(
    tortoise_db: None,
) -> None:
    # INVARIANT: this request may clear an EXPIRED mapping, or the exact row it observed and
    # refused — never a live mapping some other request bound. An unconditional delete let two
    # requests sharing a key but carrying different recipes BOTH insert and BOTH report `created`,
    # with the key left on the last writer, breaking same-key-replays-original.
    #
    # AIDEV-NOTE: driven at the seam. The race is "both prechecks miss, then the winner commits",
    # and single-connection in-memory SQLite cannot interleave two real transactions. Blinding only
    # the FIRST `_resolve_existing` call reproduces exactly that ordering: the precheck sees
    # nothing, and the handler's re-resolve afterwards sees the winner's committed mapping.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    winner, created = await store.submit(
        _owned_submission(submitted_by=ALICE, spec_id="a"), idempotency_key="race"
    )
    assert created

    real_resolve = ScoreStore._resolve_existing
    calls = {"n": 0}

    async def _blind_precheck(self, idempotency_key, content_hash):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_resolve(self, idempotency_key, content_hash)

    ScoreStore._resolve_existing = _blind_precheck  # type: ignore[method-assign]
    try:
        loser, loser_created = await store.submit(
            _owned_submission(submitted_by=BOB, spec_id="b"), idempotency_key="race"
        )
    finally:
        ScoreStore._resolve_existing = real_resolve  # type: ignore[method-assign]

    assert not loser_created, "the loser must replay, not create a second row under the same key"
    assert loser.id == winner.id
    bound = await IdempotencyKey.get_or_none(key="race").prefetch_related("score")
    assert bound is not None and bound.score.id == winner.id, "the key was rebound away"


async def test_the_unowned_key_lookup_will_not_serve_a_private_score(tortoise_db: None) -> None:
    # INVARIANT: every score-bearing read is owner-scoped. This helper takes no identity, so it
    # cannot scope anything — it must refuse a private row rather than hand it to whoever holds the
    # key. It has no production caller today, which is the only reason this was not already a leak,
    # and precisely why it must not be left as a loaded gun for the next route to pick up
    # (self-review of PR #719).
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    victim, _ = await store.submit(
        _same_recipe(ALICE), idempotency_key="victim-key", identity_verified=True
    )
    assert await store.get_by_idempotency_key("victim-key") is not None

    await store.set_visibility("hle", "private")

    assert await store.get_by_idempotency_key("victim-key") is None
    # The row itself is untouched — this refuses a READ, it does not delete anything.
    assert await Score.get_or_none(id=victim.id) is not None


async def test_owned_entries_project_every_declared_field_from_the_row(tortoise_db: None) -> None:
    # INVARIANT: `list_owned_entries` hand-builds `LeaderboardEntry` field by field, which is a
    # SECOND projection of a DTO the ranking query also constructs (`LeaderboardEntry(**row)`).
    # That is the OME-852 shape the codebase warns about at `_get_benchmark_or_404`: the two drift,
    # and here the casualty would be a 500 on the private read path this ticket exists to protect —
    # `extra="forbid"` plus a required field means an omitted one raises rather than degrades.
    #
    # Asserted GENERICALLY against `model_fields` rather than a hand-listed set, so a field added to
    # the DTO and not to the projection fails here on its own: it would hold the DTO's default
    # instead of this row's distinctive value.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    submission = _owned_submission(submitted_by=ALICE, spec_id="mine", benchmark_revision="rev-9")
    await store.submit(submission, identity_verified=True)
    row = await Score.get(spec_id="mine")

    entries = await store.list_owned_entries(benchmark_id="hle", owner=ALICE)

    assert len(entries) == 1
    for name in LeaderboardEntry.model_fields:
        assert getattr(entries[0], name) == getattr(row, name), (
            f"{name!r} is declared on LeaderboardEntry but list_owned_entries does not carry it "
            "from the Score row"
        )


async def test_a_private_write_is_refused_when_the_caller_says_nothing(tortoise_db: None) -> None:
    # INVARIANT: the default is NOT-verified (owner decision, 2026-08-27). A call site that forgets
    # `identity_verified` makes private boards REFUSE — loud and safe — where the opposite default
    # would silently reopen the forged-write hole the argument exists to close. The route path is
    # explicit, so nothing else in the suite would notice the default being flipped.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")

    with pytest.raises(PrivateBoardRequiresIdentity):
        await store.submit(_same_recipe(ALICE))

    assert await Score.all().count() == 0, "the refusal must happen before anything is written"


async def test_a_public_write_is_unaffected_by_the_default(tortoise_db: None) -> None:
    # The regression guard: fail-closed applies to private boards ONLY. A public submission with no
    # identity argument is the ordinary case and must keep working.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    created_score, created = await store.submit(_same_recipe(ALICE))

    assert created and created_score.id is not None


# --- review round 18: a private target is honoured for its verified owner ---------------------
# Round 9 refused EVERY mapping pointing at a private row, because `submitted_by` is forgeable
# under `auth_mode=disabled` and an ownership comparison meant nothing. P1 gave the store
# `identity_verified`, so the comparison is sound exactly when identity is real — and the blanket
# refusal was breaking `same key replays the original` on every private board (review of #719).


async def test_a_private_board_replays_the_original_for_its_own_key(tortoise_db: None) -> None:
    # INVARIANT: the idempotency contract. The same key returns the FIRST result even when the
    # payload changed — that is what distinguishes a key from the content hash, which only catches
    # an identical retry.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    first, created = await store.submit(
        _owned_submission(submitted_by=ALICE, spec_id="first"),
        idempotency_key="k",
        identity_verified=True,
    )
    assert created

    replay, replay_created = await store.submit(
        _owned_submission(submitted_by=ALICE, spec_id="CHANGED"),
        idempotency_key="k",
        identity_verified=True,
    )

    assert not replay_created
    assert replay.id == first.id


async def test_a_verified_caller_is_still_refused_another_participants_private_row(
    tortoise_db: None,
) -> None:
    # Verified identity permits the comparison; it does not pass it. BOB may not have ALICE's row.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    hers, _ = await store.submit(
        _same_recipe(ALICE), idempotency_key="stale", identity_verified=True
    )
    await store.set_visibility("hle", "private")
    await store.register_benchmark(benchmark_id="pub", display_name="Pub")

    his = _owned_submission(submitted_by=BOB, spec_id="his").model_copy(
        update={"benchmark_id": "pub"}
    )
    got, created = await store.submit(his, idempotency_key="stale", identity_verified=True)

    assert created
    assert got.id != hers.id


async def test_a_reserved_prefix_public_key_keeps_replaying(tortoise_db: None) -> None:
    # The regression guard for removing the purge: a public caller whose raw key occupies a
    # reserved namespace is escaped, not deleted, so their retry still replays.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    first, _ = await store.submit(
        _owned_submission(submitted_by=ALICE, spec_id="one"), idempotency_key="sfp-raw"
    )

    replay, created = await store.submit(
        _owned_submission(submitted_by=ALICE, spec_id="two"), idempotency_key="sfp-raw"
    )

    assert not created
    assert replay.id == first.id


async def test_two_absent_submitters_do_not_count_as_the_same_owner(tortoise_db: None) -> None:
    # INVARIANT: ownership needs an actual owner. `Score.submitted_by` is nullable and
    # `ScoreSubmission.submitted_by` is optional, so `None == None` would otherwise read as "this
    # is mine" and hand over a private row. Unreachable through the route today — verified mode
    # 401s on a missing identity — which is exactly why it should not depend on that staying true.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    orphan = await Score.create(
        benchmark_id="hle",
        spec_id="orphan",
        url4_expression="url4://orphan",
        submitted_by=None,
        score=0.99,
        total_questions=100,
        correct_questions=99,
        ran_with_providers=["openai"],
        content_hash="orphan-hash",
        metadata={"secret": "not-yours"},
    )
    scoped = _scoped_idempotency_key("k", None, per_submitter=True)
    assert scoped is not None
    await IdempotencyKey.create(
        key=scoped, score=orphan, expires_at=datetime.now(UTC) + timedelta(hours=24)
    )

    anonymous = _same_recipe(ALICE).model_copy(update={"submitted_by": None})
    got, _ = await store.submit(anonymous, idempotency_key="k", identity_verified=True)

    assert got.id != orphan.id
    assert got.metadata != {"secret": "not-yours"}


# --- review round 20: stale visibility must never be acted on -------------------------------
# Reading visibility once narrows the window between the read and the write; it does not close it.
# A flip landing inside it leaves the request running on stale hashing AND a stale identity rule.


def _flip_to_private_after_the_visibility_read() -> tuple[object, object]:
    """Land the seed job's flip AFTER `submit()` has read visibility and hashed."""
    real = ScoreStore._resolve_existing
    fired = {"done": False}

    async def _hook(self, idempotency_key, content_hash):  # type: ignore[no-untyped-def]
        if not fired["done"]:
            fired["done"] = True
            await Benchmark.filter(id="hle").update(visibility="private")
        return await real(self, idempotency_key, content_hash)

    return real, _hook


async def test_the_readable_gate_refuses_a_private_row_to_everyone_but_its_owner(
    tortoise_db: None,
) -> None:
    # INVARIANT: ONE definition of "may read", used by every return from `_resolve_owned` — the key
    # path AND the content-hash fallback. Round 18 gated the key path and left the fallback beside
    # it ungated, so a stale public hash matching a now-private row handed that row over.
    #
    # AIDEV-NOTE: tested directly rather than through `submit()`. The only way a caller reaches the
    # fallback holding another submitter's private row is a visibility flip mid-request, and the
    # revalidation now refuses that BEFORE the fallback runs — so a submit-level test would assert
    # the revalidation and prove nothing about this gate. Both defences are real; only this one is
    # reachable in isolation.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    hers = await Score.create(
        benchmark_id="hle",
        spec_id="hers",
        url4_expression="url4://hers",
        submitted_by=ALICE,
        score=0.9,
        total_questions=100,
        correct_questions=90,
        ran_with_providers=["openai"],
        content_hash="hers-hash",
    )

    assert await store._readable_by(hers, submitted_by=ALICE, identity_verified=True) is hers
    assert await store._readable_by(hers, submitted_by=BOB, identity_verified=True) is None
    assert await store._readable_by(hers, submitted_by=ALICE, identity_verified=False) is None
    assert await store._readable_by(hers, submitted_by=None, identity_verified=True) is None
    assert await store._readable_by(None, submitted_by=ALICE, identity_verified=True) is None


async def test_the_fallback_return_is_wired_to_the_readable_gate(tortoise_db: None) -> None:
    # INVARIANT: `_resolve_owned`'s LAST return passes the gate, not just its first. Driven at
    # `_resolve_owned` deliberately: through `submit()` the only route to this state is a mid-flight
    # flip, which the revalidation refuses first — so the wiring would be untested while looking
    # covered. Both defences are real; this is the one that survives if the other is ever relaxed.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE", visibility="private")
    hers = await Score.create(
        benchmark_id="hle",
        spec_id="hers",
        url4_expression="url4://hers",
        submitted_by=ALICE,
        score=0.9,
        total_questions=100,
        correct_questions=90,
        ran_with_providers=["openai"],
        content_hash="hers-hash",
    )

    returned, refused = await store._resolve_owned(
        None, "hers-hash", per_submitter=False, submitted_by=BOB, identity_verified=False
    )

    assert returned is None, "the content-hash fallback handed over a private row"
    assert refused is None or refused.id == hers.id


async def test_a_flip_is_caught_on_the_replay_path_too(tortoise_db: None) -> None:
    # INVARIANT: the return path revalidates as well as the persist path. Nothing is written when a
    # row is replayed, but it was CHOSEN under a view of `visibility` that may have changed — and
    # the rules for what may be returned differ between public and private.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    await store.submit(_same_recipe(ALICE), identity_verified=True)

    # AIDEV-NOTE: `identity_verified=True` is load-bearing. Without it the flipped board makes the
    # row unreadable, `_resolve_owned` returns nothing, and the request falls through to the INSERT
    # — where the other revalidation fires. The test would still pass and would prove nothing about
    # this one.
    real, hook = _flip_to_private_after_the_visibility_read()
    ScoreStore._resolve_existing = hook  # type: ignore[method-assign]
    try:
        with pytest.raises(BenchmarkVisibilityChanged):
            await store.submit(_same_recipe(ALICE), identity_verified=True)
    finally:
        ScoreStore._resolve_existing = real  # type: ignore[method-assign]


async def test_an_unverified_write_is_not_persisted_after_a_mid_flight_flip(
    tortoise_db: None,
) -> None:
    # INVARIANT: a request that has become wrong must be refused, not completed. The identity rule
    # was decided while the board was public; by the time the row lands the board is private, so
    # persisting it stores an unverified claim under private-board semantics.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    real, hook = _flip_to_private_after_the_visibility_read()

    ScoreStore._resolve_existing = hook  # type: ignore[method-assign]
    try:
        with pytest.raises(BenchmarkVisibilityChanged):
            await store.submit(_owned_submission(submitted_by=BOB, spec_id="late"))
    finally:
        ScoreStore._resolve_existing = real  # type: ignore[method-assign]

    assert await Score.all().count() == 0, "nothing may be written under stale visibility"


async def test_an_undisturbed_submission_is_unaffected(tortoise_db: None) -> None:
    # The regression guard: revalidation must cost nothing when no flip happens, which is every
    # real request.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")

    first, created = await store.submit(_same_recipe(ALICE))
    replay, replayed = await store.submit(_same_recipe(ALICE))

    assert created and not replayed and replay.id == first.id


async def test_the_concurrent_retry_branch_revalidates_before_replaying(
    tortoise_db: None,
) -> None:
    # INVARIANT: every return from `submit()` answers from a view of `visibility` it has checked.
    # The pre-insert return did; this one did not — and it is reached precisely BECAUSE something
    # changed concurrently, so it is the least safe place to trust a stale read. The persist-path
    # check that already passed cannot speak for the time spent failing the insert.
    #
    # AIDEV-NOTE: the flip lands on the SECOND `_resolve_existing` call — the one the except branch
    # makes. Flipping inside `Score.create` looks more faithful and does not work: that runs inside
    # the insert transaction, so single-connection SQLite rolls the flip back with it and visibility
    # is public again by the time the branch is reached. Flipping earlier would be caught by the
    # persist-path check and prove nothing about this one.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    winner, _ = await store.submit(
        _owned_submission(submitted_by=ALICE, spec_id="winner"), identity_verified=True
    )

    real_resolve = ScoreStore._resolve_existing
    real_create = Score.create
    calls = {"n": 0}
    raised = {"done": False}

    async def _blind_precheck(self, idempotency_key, content_hash):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        await Benchmark.filter(id="hle").update(visibility="private")
        return await Score.get_or_none(id=winner.id)

    async def _fail_once(**kwargs):  # type: ignore[no-untyped-def]
        if not raised["done"]:
            raised["done"] = True
            raise IntegrityError("simulated concurrent insert")
        return await real_create(**kwargs)

    ScoreStore._resolve_existing = _blind_precheck  # type: ignore[method-assign]
    Score.create = _fail_once  # type: ignore[method-assign]
    try:
        with pytest.raises(BenchmarkVisibilityChanged):
            # ALICE's own row, verified: the privacy gate must HONOUR it, so the revalidation is
            # what refuses. A different submitter would be refused by the gate first and this
            # branch's check would never run — which is why it is reachable at all only for a
            # caller replaying their own private row.
            await store.submit(
                _owned_submission(submitted_by=ALICE, spec_id="loser"), identity_verified=True
            )
    finally:
        ScoreStore._resolve_existing = real_resolve  # type: ignore[method-assign]
        Score.create = real_create  # type: ignore[method-assign]

    assert raised["done"], "the IntegrityError branch was never reached"

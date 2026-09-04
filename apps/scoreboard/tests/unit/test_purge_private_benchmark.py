"""Fail-closed proof for the exceptional private-board purge (OME-1027).

The rollback procedure may destroy private submissions only when the operator proves that the
exact rows being deleted already exist in a staff-only export. Any ambiguity or concurrent change
must leave the benchmark and every dependent row untouched.
"""

from __future__ import annotations

import hashlib

import pytest

from scoreboard import purge_private_benchmark as purge_module
from scoreboard.export_private_submissions import collect_submissions, format_jsonl
from scoreboard.purge_private_benchmark import (
    PurgeRefused,
    export_sha256,
    purge_private_benchmark,
)
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Benchmark, IdempotencyKey, Score
from scoreboard.scores.schemas import BaselineImportRow, ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

BENCHMARK = "healthbench-worst30"


def _submission(spec_id: str) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=BENCHMARK,
        spec_id=spec_id,
        url4_expression=f"url4://{BENCHMARK}/{spec_id}",
        submitted_by="reviewer@example.test",
        score=0.8,
        total_questions=100,
        correct_questions=80,
        ran_with_providers=["openai"],
    )


async def _seed_private(*, submissions: int = 2) -> None:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id=BENCHMARK,
        display_name="HealthBench Worst 30",
        visibility="private",
    )
    for index in range(submissions):
        await store.submit(
            _submission(f"spec-{index}"),
            idempotency_key=f"purge-test-{index}",
            identity_verified=True,
        )


async def _current_digest() -> str:
    return export_sha256(await collect_submissions(BENCHMARK))


async def test_export_digest_matches_the_exact_cli_bytes(tortoise_db: None) -> None:
    await _seed_private(submissions=1)
    rows = await collect_submissions(BENCHMARK)

    cli_bytes = f"{format_jsonl(rows)}\n".encode()

    assert export_sha256(rows) == hashlib.sha256(cli_bytes).hexdigest()


async def test_dry_run_preserves_a_matching_private_export(tortoise_db: None) -> None:
    await _seed_private()
    digest = await _current_digest()

    outcome = await purge_private_benchmark(BENCHMARK, digest, confirmed=False)

    assert outcome == (
        f"would purge {BENCHMARK!r}: 2 submissions match export sha256 {digest}; "
        "re-run with --yes to delete"
    )
    assert await Benchmark.exists(id=BENCHMARK)
    assert await Score.filter(benchmark_id=BENCHMARK).count() == 2


async def test_a_malformed_digest_refuses_before_deleting_anything(tortoise_db: None) -> None:
    await _seed_private(submissions=1)

    with pytest.raises(PurgeRefused, match="exactly 64 hexadecimal"):
        await purge_private_benchmark(BENCHMARK, "not-a-sha256", confirmed=True)

    assert await Benchmark.exists(id=BENCHMARK)
    assert await Score.filter(benchmark_id=BENCHMARK).count() == 1


async def test_a_stale_export_refuses_without_deleting_anything(tortoise_db: None) -> None:
    await _seed_private(submissions=1)
    stale_digest = await _current_digest()
    await ScoreStore().submit(
        _submission("arrived-later"),
        idempotency_key="arrived-later",
        identity_verified=True,
    )

    with pytest.raises(PurgeRefused, match="does not match"):
        await purge_private_benchmark(BENCHMARK, stale_digest, confirmed=True)

    assert await Benchmark.exists(id=BENCHMARK)
    assert await Score.filter(benchmark_id=BENCHMARK).count() == 2


async def test_a_public_benchmark_is_never_purged(tortoise_db: None) -> None:
    await ScoreStore().register_benchmark(
        benchmark_id=BENCHMARK,
        display_name="Public",
        visibility="public",
    )

    with pytest.raises(PurgeRefused, match="not private"):
        await purge_private_benchmark(BENCHMARK, hashlib.sha256(b"").hexdigest(), confirmed=True)

    assert await Benchmark.exists(id=BENCHMARK)


async def test_an_unknown_benchmark_is_not_an_empty_private_board(tortoise_db: None) -> None:
    with pytest.raises(LookupError, match="unknown benchmark_id"):
        await purge_private_benchmark(BENCHMARK, hashlib.sha256(b"").hexdigest(), confirmed=True)


async def test_a_private_benchmark_with_a_baseline_is_never_purged(tortoise_db: None) -> None:
    await _seed_private(submissions=0)
    await BaselineStore().import_baseline(
        BaselineImportRow(
            benchmark_id=BENCHMARK,
            model_name="reference-model",
            score=0.7,
            source="operator",
        )
    )

    with pytest.raises(PurgeRefused, match="1 baseline"):
        await purge_private_benchmark(
            BENCHMARK,
            hashlib.sha256(b"").hexdigest(),
            confirmed=True,
        )

    assert await Benchmark.exists(id=BENCHMARK)


async def test_confirmed_matching_export_deletes_scores_and_idempotency_keys(
    tortoise_db: None,
) -> None:
    await _seed_private()
    digest = await _current_digest()

    outcome = await purge_private_benchmark(BENCHMARK, digest, confirmed=True)

    assert outcome == f"purged {BENCHMARK!r}: 2 submissions matched export sha256 {digest}"
    assert not await Benchmark.exists(id=BENCHMARK)
    assert await Score.filter(benchmark_id=BENCHMARK).count() == 0
    assert await IdempotencyKey.all().count() == 0


async def test_an_empty_private_benchmark_can_clear_the_preflight(tortoise_db: None) -> None:
    await _seed_private(submissions=0)

    outcome = await purge_private_benchmark(
        BENCHMARK,
        hashlib.sha256(b"").hexdigest(),
        confirmed=True,
    )

    assert "0 submissions" in outcome
    assert not await Benchmark.exists(id=BENCHMARK)


async def test_only_the_exact_named_private_benchmark_is_purged(tortoise_db: None) -> None:
    await _seed_private(submissions=1)
    await ScoreStore().register_benchmark(
        benchmark_id=f"{BENCHMARK}-copy",
        display_name="Copy",
        visibility="private",
    )

    await purge_private_benchmark(BENCHMARK, await _current_digest(), confirmed=True)

    assert not await Benchmark.exists(id=BENCHMARK)
    assert await Benchmark.exists(id=f"{BENCHMARK}-copy")


async def test_a_final_delete_failure_rolls_the_transaction_back(
    tortoise_db: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_private()
    digest = await _current_digest()

    async def _fail_to_delete_benchmark(*args: object, **kwargs: object) -> None:
        raise PurgeRefused("simulated final delete failure")

    monkeypatch.setattr(purge_module, "_delete_benchmark", _fail_to_delete_benchmark)

    with pytest.raises(PurgeRefused, match="simulated final delete failure"):
        await purge_private_benchmark(BENCHMARK, digest, confirmed=True)

    assert await Benchmark.exists(id=BENCHMARK)
    assert await Score.filter(benchmark_id=BENCHMARK).count() == 2
    assert await IdempotencyKey.all().count() == 2

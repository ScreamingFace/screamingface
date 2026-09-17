"""The staff read-only export for a private board (OME-894).

Staff access is deliberately out-of-band: no admin API, nothing to secure, guess or accidentally
expose. That also means this path must work when the API cannot help — it does not consult
`auth_mode`, and it is the only way to read a private board while the deployment runs
`auth_mode: disabled`.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from scoreboard.export_private_submissions import collect_submissions, format_jsonl
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio

ALICE = "alice@example.test"
BOB = "bob@example.test"
BENCHMARK = "healthbench-worst30"


def _submission(*, submitted_by: str, spec_id: str, score: float) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=BENCHMARK,
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{BENCHMARK}/{spec_id}",
        submitted_by=submitted_by,
        score=score,
        total_questions=100,
        correct_questions=int(score * 100),
        ran_with_providers=["openai"],
        run_cost_usd=Decimal("1.000000"),
    )


async def _seed() -> ScoreStore:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id=BENCHMARK,
        display_name="HealthBench Worst-30% Challenge",
        visibility="private",
    )
    await store.submit(
        _submission(submitted_by=ALICE, spec_id="spec-alice", score=0.60), identity_verified=True
    )
    await store.submit(
        _submission(submitted_by=BOB, spec_id="spec-bob", score=0.90), identity_verified=True
    )
    return store


async def test_every_participants_submission_is_exported(tortoise_db: None) -> None:
    await _seed()

    rows = await collect_submissions(BENCHMARK)

    assert sorted(row.spec_id for row in rows) == ["spec-alice", "spec-bob"]


async def test_the_export_keeps_the_full_submitter_address(tortoise_db: None) -> None:
    # INVARIANT: the public API publishes only the local part (OME-834). This export is the
    # audit path — staff need the domain to know WHICH verified identity produced a score, and
    # to contact them. Serialising through JSON mode would silently trim it and defeat the tool.
    await _seed()

    rows = await collect_submissions(BENCHMARK)
    exported = [json.loads(line) for line in format_jsonl(rows).splitlines()]

    assert sorted(row["submitted_by"] for row in exported) == [ALICE, BOB]


async def test_an_unknown_benchmark_is_refused(tortoise_db: None) -> None:
    # Loud rather than an empty export: "no submissions" and "you typed the id wrong" must not
    # look identical to someone reviewing a challenge.
    await _seed()

    with pytest.raises(LookupError):
        await collect_submissions("no-such-benchmark")


async def test_a_public_benchmark_can_also_be_exported(tortoise_db: None) -> None:
    # Not restricted to private boards: the tool reads the database, and refusing public
    # benchmarks would be an arbitrary limit on an operator script.
    store = ScoreStore()
    await store.register_benchmark(benchmark_id="hle", display_name="HLE")
    await store.submit(
        ScoreSubmission(
            benchmark_id="hle",
            spec_id="spec-1",
            url4_expression="url4://benchmark/hle/spec-1",
            submitted_by=ALICE,
            score=0.5,
            total_questions=100,
            correct_questions=50,
            ran_with_providers=["openai"],
            run_cost_usd=Decimal("1.000000"),
        )
    )

    rows = await collect_submissions("hle")

    assert [row.spec_id for row in rows] == ["spec-1"]

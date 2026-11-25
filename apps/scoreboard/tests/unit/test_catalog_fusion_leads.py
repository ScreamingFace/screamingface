"""`BenchmarkSummary.fusion_leads` (OME-1916): best fusion score vs. best solo-model score.

A dedicated file, not appended to `test_catalog_summary.py`: that file carries an
owner-approved, byte-exact test-contract edit (`.claude/test-change-approvals/OME-1916.json`)
to its existing field-set assertion, and the append-only checker pins the WHOLE file's blob —
any further change to it, even a pure addition elsewhere, would require recomputing and
re-recording that approval. A new file sidesteps that entirely: it carries none of the prior
commit's content, so it is pure addition by construction.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise
from tortoise.backends.base import executor

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score


@pytest.fixture(params=["sqlite", "postgres"])
def catalog_client(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient]:
    url = f"sqlite://{tmp_path / 'fusion_leads.sqlite3'}"
    if request.param == "postgres":
        url = request.getfixturevalue("postgres_schema_database_url")
    monkeypatch.setattr(executor, "EXECUTOR_CACHE", {})
    with TestClient(create_app(Settings(database_url=url, cors_origins=[]))) as client:
        assert client.portal is not None
        client.portal.call(Tortoise.generate_schemas)
        yield client


async def _seed_kind_scores(board: str, entries: list[tuple[str, float, str | None]]) -> None:
    """One benchmark with one Score per (spec, score, candidate_kind) entry.

    `candidate_kind` of `None` omits `metadata` entirely (an "unknown" row by
    `classify_candidate_kind`'s own contract, OME-1852); any other string is sent as
    `metadata={"candidate_kind": ...}`, including values the classifier does not
    recognise (still "unknown" — never a guess).
    """
    await Benchmark.create(id=board, display_name=board, revision="r1", case_count=10)
    for spec, score, kind in entries:
        await Score.create(
            benchmark_id=board,
            spec_id=spec,
            benchmark_revision="r1",
            score=score,
            total_questions=10,
            ran_with_providers=[],
            url4_expression="url4://test",
            metadata=None if kind is None else {"candidate_kind": kind},
        )


@pytest.mark.parametrize(
    ("entries", "expected"),
    [
        # Best fusion (0.9) beats best model (0.7): a fusion win.
        ([("f1", 0.9, "fusion"), ("m1", 0.7, "model")], True),
        # Best model (0.9) beats best fusion (0.7): not a fusion win.
        ([("f1", 0.7, "fusion"), ("m1", 0.9, "model")], False),
        # Tied maxes: "beats", not "beats or ties" — not a fusion win.
        ([("f1", 0.8, "fusion"), ("m1", 0.8, "model")], False),
        # Only fusion submissions: no solo-model group to beat.
        ([("f1", 0.9, "fusion"), ("f2", 0.5, "fusion")], False),
        # Only solo-model submissions: no fusion group.
        ([("m1", 0.9, "model"), ("m2", 0.5, "model")], False),
        # Only "unknown" (absent/unrecognised) candidate_kind: neither group exists.
        ([("u1", 0.9, None), ("u2", 0.5, "pipeline")], False),
        # An "unknown" row with the single highest score on the board must not count
        # toward either group, or silently suppress a genuine fusion win.
        ([("u1", 0.99, None), ("f1", 0.9, "fusion"), ("m1", 0.7, "model")], True),
    ],
)
def test_fusion_leads_compares_best_fusion_against_best_model(
    catalog_client: TestClient, entries: list[tuple[str, float, str | None]], expected: bool
) -> None:
    assert catalog_client.portal is not None
    catalog_client.portal.call(lambda: _seed_kind_scores("kinds", entries))
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["benchmarks"]}
    assert rows["kinds"]["fusion_leads"] is expected


def test_fusion_leads_false_on_a_benchmark_with_no_scores_at_all(
    catalog_client: TestClient,
) -> None:
    assert catalog_client.portal is not None
    catalog_client.portal.call(lambda: Benchmark.create(id="no-scores", display_name="No scores"))
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    row = response.json()["benchmarks"][0]
    assert row["id"] == "no-scores"
    assert row["fusion_leads"] is False


def test_fusion_leads_only_compares_the_best_run_per_spec(catalog_client: TestClient) -> None:
    """A stale, lower rerun of the same spec must not drag its kind's max down."""
    assert catalog_client.portal is not None

    async def seed() -> None:
        await Benchmark.create(id="reruns", display_name="Reruns", revision="r1", case_count=10)
        # Same spec, two runs: the lower one is NOT the canonical per-spec entry.
        await Score.create(
            benchmark_id="reruns",
            spec_id="fusion-spec",
            benchmark_revision="r1",
            score=0.95,
            total_questions=10,
            ran_with_providers=[],
            url4_expression="url4://test",
            metadata={"candidate_kind": "fusion"},
        )
        await Score.create(
            benchmark_id="reruns",
            spec_id="fusion-spec",
            benchmark_revision="r1",
            score=0.2,
            total_questions=10,
            ran_with_providers=[],
            url4_expression="url4://test",
            metadata={"candidate_kind": "fusion"},
        )
        await Score.create(
            benchmark_id="reruns",
            spec_id="model-spec",
            benchmark_revision="r1",
            score=0.5,
            total_questions=10,
            ran_with_providers=[],
            url4_expression="url4://test",
            metadata={"candidate_kind": "model"},
        )

    catalog_client.portal.call(seed)
    response = catalog_client.get("/v1/benchmarks/summary")
    assert response.status_code == 200
    row = next(b for b in response.json()["benchmarks"] if b["id"] == "reruns")
    assert row["fusion_leads"] is True

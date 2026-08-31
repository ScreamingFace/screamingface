from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import BaselineImportRow, ClientInfo, ScoreSubmission
from scoreboard.scores.store import ScoreStore

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def async_client(tortoise_db: None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _submission(
    *,
    benchmark_id: str = "hle",
    spec_id: str = "spec-1",
    score: float = 0.75,
    providers: list[str] | None = None,
    submitted_by: str | None = "tester",
) -> ScoreSubmission:
    total_questions = 1000
    correct_questions = int(score * total_questions)
    return ScoreSubmission(
        benchmark_id=benchmark_id,
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{benchmark_id}/{spec_id}/{score}",
        submitted_by=submitted_by,
        score=score,
        total_questions=total_questions,
        correct_questions=correct_questions,
        ran_with_providers=providers or ["openai"],
        ran_at_local=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
        client=ClientInfo(name="scoreboard-test", version="0.1.0", platform="test"),
        metadata={"source": "unit"},
    )


async def _register_benchmark(
    store: ScoreStore,
    benchmark_id: str = "hle",
    display_name: str = "Humanity's Last Exam",
) -> None:
    await store.register_benchmark(
        benchmark_id=benchmark_id,
        display_name=display_name,
        description="Fixture benchmark",
        dataset_url=f"https://example.test/{benchmark_id}.jsonl",
    )


async def test_list_benchmarks_returns_empty_list(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/v1/benchmarks")

    assert response.status_code == 200
    assert response.json() == {"benchmarks": []}


async def test_list_benchmarks_returns_registered_benchmarks_in_id_order(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store, benchmark_id="zeta", display_name="Zeta Benchmark")
    await _register_benchmark(store, benchmark_id="hle", display_name="Humanity's Last Exam")

    response = await async_client.get("/v1/benchmarks")

    assert response.status_code == 200
    body = response.json()
    assert [benchmark["id"] for benchmark in body["benchmarks"]] == ["hle", "zeta"]
    assert body["benchmarks"][0]["display_name"] == "Humanity's Last Exam"
    assert body["benchmarks"][0]["dataset_url"] == "https://example.test/hle.jsonl"
    assert "created_at" in body["benchmarks"][0]


async def test_get_leaderboard_returns_ranked_best_score_per_spec(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    await _register_benchmark(store, benchmark_id="other", display_name="Other Benchmark")
    await store.submit(_submission(spec_id="spec-a", score=0.6, providers=["openai"]))
    await store.submit(_submission(spec_id="spec-a", score=0.9, providers=["anthropic"]))
    await store.submit(_submission(spec_id="spec-b", score=0.95, providers=["openai", "gemini"]))
    await store.submit(_submission(spec_id="spec-c", score=0.7, providers=["gemini"]))
    await store.submit(_submission(benchmark_id="other", spec_id="spec-z", score=1.0))

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    body = response.json()
    assert body["benchmark"]["id"] == "hle"
    assert [entry["rank"] for entry in body["entries"]] == [1, 2, 3]
    assert [entry["spec_id"] for entry in body["entries"]] == ["spec-b", "spec-a", "spec-c"]
    assert [entry["score"] for entry in body["entries"]] == [0.95, 0.9, 0.7]
    assert body["entries"][0]["ran_with_providers"] == ["openai", "gemini"]
    # OME-820: verified defaults to True as a placeholder that asserts NOTHING —
    # nothing re-runs submissions and nothing attests where a run executed. The
    # False case stays covered by the explicit-False row test.
    assert body["entries"][0]["verified_by_screamingface"] is True
    assert body["entries"][1]["url4_expression"] == "url4://benchmark/hle/spec-a/0.9"


async def test_get_leaderboard_breaks_accuracy_ties_by_newer_submission(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    older, _ = await store.submit(_submission(spec_id="spec-a", score=0.9, providers=["older"]))
    newer, _ = await store.submit(_submission(spec_id="spec-a", score=0.9, providers=["newer"]))
    await Score.filter(id=older.id).update(
        submitted_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
    )
    await Score.filter(id=newer.id).update(
        submitted_at=datetime(2026, 5, 21, 13, 0, tzinfo=UTC),
    )

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["ran_with_providers"] == ["newer"]


async def test_get_leaderboard_clamps_top_to_max(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    for index in range(205):
        accuracy = (1000 - index) / 1000
        await store.submit(_submission(spec_id=f"spec-{index:03d}", score=accuracy))

    response = await async_client.get("/v1/leaderboard/hle", params={"top": 999})

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 200
    assert body["entries"][0]["rank"] == 1
    assert body["entries"][-1]["rank"] == 200


async def test_get_leaderboard_returns_404_for_unknown_benchmark(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/v1/leaderboard/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Benchmark not found"}


async def test_get_spec_history_returns_submissions_newest_first(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    older, _ = await store.submit(_submission(spec_id="spec-history", score=0.5))
    newer, _ = await store.submit(_submission(spec_id="spec-history", score=0.8))
    await store.submit(_submission(spec_id="other-spec", score=0.95))
    await Score.filter(id=older.id).update(
        submitted_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
    )
    await Score.filter(id=newer.id).update(
        submitted_at=datetime(2026, 5, 21, 13, 0, tzinfo=UTC),
    )

    response = await async_client.get("/v1/leaderboard/hle/spec-history/history")

    assert response.status_code == 200
    body = response.json()
    assert body["benchmark_id"] == "hle"
    assert body["spec_id"] == "spec-history"
    assert [submission["id"] for submission in body["submissions"]] == [
        str(newer.id),
        str(older.id),
    ]
    assert [submission["score"] for submission in body["submissions"]] == [0.8, 0.5]
    assert set(body["submissions"][0]) == {
        "id",
        # OME-775: a spec's history can span benchmark revisions, and entries measured against
        # different revisions are not comparable. Owner-approved contract change; the
        # assertion stays exact rather than being loosened to a subset check.
        "benchmark_revision",
        "score",
        "total_questions",
        "correct_questions",
        "submitted_at",
        "submitted_by",
        "verified_by_screamingface",
        # Widened for OME-770: the history response intentionally carries the run
        # cost. The set stays exhaustive on purpose — it is the guard that catches
        # an unintended field leaking into a response portal clients depend on.
        "run_cost_usd",
    }


async def test_get_spec_history_clamps_limit_to_max(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    for index in range(105):
        await store.submit(_submission(spec_id="spec-history", score=index / 200))

    response = await async_client.get(
        "/v1/leaderboard/hle/spec-history/history",
        params={"limit": 999},
    )

    assert response.status_code == 200
    assert len(response.json()["submissions"]) == 100


async def test_get_spec_history_returns_empty_list_for_unknown_spec(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)

    response = await async_client.get("/v1/leaderboard/hle/new-spec/history")

    assert response.status_code == 200
    assert response.json()["submissions"] == []


async def test_get_spec_history_returns_404_for_unknown_benchmark(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/v1/leaderboard/missing/spec-1/history")

    assert response.status_code == 404
    assert response.json() == {"detail": "Benchmark not found"}


async def test_openapi_includes_leaderboard_contracts(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/openapi.json")

    assert response.status_code == 200
    body = response.json()
    assert "/v1/benchmarks" in body["paths"]
    assert "/v1/leaderboard/{benchmark_id}" in body["paths"]
    assert "/v1/leaderboard/{benchmark_id}/{spec_id}/history" in body["paths"]
    assert "BenchmarksResponse" in body["components"]["schemas"]
    assert "LeaderboardResponse" in body["components"]["schemas"]
    assert "HistoryResponse" in body["components"]["schemas"]


async def test_get_leaderboard_returns_empty_baselines_when_none_imported(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store, benchmark_id="demo-benchmark", display_name="Demo Benchmark")

    response = await async_client.get("/v1/leaderboard/demo-benchmark")

    assert response.status_code == 200
    assert response.json()["baselines"] == []


async def test_get_leaderboard_returns_imported_baselines_ordered_by_accuracy(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store, benchmark_id="demo-benchmark", display_name="Demo Benchmark")
    baseline_store = BaselineStore()
    await baseline_store.import_baseline(
        BaselineImportRow(
            benchmark_id="demo-benchmark",
            model_name="Model A",
            score=0.55,
            source="lmarena",
        )
    )
    await baseline_store.import_baseline(
        BaselineImportRow(
            benchmark_id="demo-benchmark",
            model_name="Model B",
            score=0.71,
            source="artificial_analysis",
            source_url="https://artificialanalysis.ai/demo-benchmark",
        )
    )

    response = await async_client.get("/v1/leaderboard/demo-benchmark")

    assert response.status_code == 200
    body = response.json()
    assert [baseline["model_name"] for baseline in body["baselines"]] == ["Model B", "Model A"]
    assert body["baselines"][0]["source"] == "artificial_analysis"
    assert body["baselines"][0]["source_url"] == "https://artificialanalysis.ai/demo-benchmark"
    assert body["baselines"][1]["source_url"] is None


async def test_get_leaderboard_returns_404_for_unknown_benchmark_with_baselines_wired(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/v1/leaderboard/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Benchmark not found"}


async def test_openapi_includes_baseline_schema(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/openapi.json")

    assert response.status_code == 200
    assert "BaselineSchema" in response.json()["components"]["schemas"]


async def test_get_frontier_returns_404_for_unknown_benchmark(
    async_client: httpx.AsyncClient,
) -> None:
    response = await async_client.get("/v1/leaderboard/missing/frontier")

    assert response.status_code == 404
    assert response.json() == {"detail": "Benchmark not found"}


async def test_get_frontier_returns_empty_trend_for_a_benchmark_with_no_scores(
    async_client: httpx.AsyncClient,
) -> None:
    await _register_benchmark(ScoreStore())

    response = await async_client.get("/v1/leaderboard/hle/frontier")

    assert response.status_code == 200
    body = response.json()
    assert body["benchmark_id"] == "hle"
    assert body["current"] is None
    assert body["trend"] == []
    assert body["open_count"] == 0
    assert body["closed_count"] == 0
    assert body["open_share"] == 0.0


async def test_get_frontier_reflects_real_submissions(
    async_client: httpx.AsyncClient,
) -> None:
    await _register_benchmark(ScoreStore())
    await async_client.post(
        "/v1/scores",
        json=_submission(spec_id="spec-1", score=0.5, providers=["huggingface"]).model_dump(
            mode="json"
        ),
    )
    await async_client.post(
        "/v1/scores",
        json=_submission(spec_id="spec-2", score=0.9, providers=["openai"]).model_dump(mode="json"),
    )

    response = await async_client.get("/v1/leaderboard/hle/frontier")

    assert response.status_code == 200
    body = response.json()
    assert body["open_count"] == 1
    assert body["closed_count"] == 1
    assert body["current"]["label"] == "spec-2"
    assert body["current"]["openness"] == "closed"
    assert len(body["trend"]) == 2


# --- OME-834: no read path may publish a harvestable address ---


async def test_read_paths_publish_only_the_local_part(
    async_client: httpx.AsyncClient,
) -> None:
    """The API is public and unauthenticated, so this is where it has to happen.

    Stripping in the portal would leave every address in the JSON.
    """
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(
        _submission(spec_id="stripped", submitted_by="trask@openmined.org"),
    )

    board = await async_client.get("/v1/leaderboard/hle")
    history = await async_client.get("/v1/leaderboard/hle/stripped/history")

    entry = next(e for e in board.json()["entries"] if e["spec_id"] == "stripped")
    assert entry["submitted_by"] == "trask"
    assert history.json()["submissions"][0]["submitted_by"] == "trask"
    # No domain anywhere in either payload.
    assert "openmined.org" not in board.text
    assert "openmined.org" not in history.text


async def test_the_database_still_holds_the_full_address(
    async_client: httpx.AsyncClient,
) -> None:
    """INVARIANT (D2): only the WIRE form is trimmed.

    OpenMined must still be able to contact a submitter and audit which verified
    identity produced a score (OME-404). This is the assertion that stops a future
    "simplification" from moving the strip onto ScoreSubmission, which would write
    the truncated form to the database irreversibly.
    """
    store = ScoreStore()
    await _register_benchmark(store)
    outcome = await store.submit(
        _submission(spec_id="stored-full", submitted_by="trask@openmined.org"),
    )

    row = await Score.get(id=outcome.score.id)

    assert row.submitted_by == "trask@openmined.org"


# --- OME-820: the default must be visible on the public read paths ---


async def test_a_new_submission_reads_as_verified_on_both_read_paths(
    async_client: httpx.AsyncClient,
) -> None:
    """The board renders this flag; OME-771 builds a pool toggle on it.

    Until now every row read `false` forever, because nothing could set the flag
    and OME-414 is unstaffed.
    """
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(_submission(spec_id="verified-default"))

    board = await async_client.get("/v1/leaderboard/hle")
    history = await async_client.get("/v1/leaderboard/hle/verified-default/history")

    assert board.status_code == 200
    entry = next(e for e in board.json()["entries"] if e["spec_id"] == "verified-default")
    assert entry["verified_by_screamingface"] is True
    assert history.json()["submissions"][0]["verified_by_screamingface"] is True


# --- OME-770 review: cost must survive every read path ----------------------


async def test_get_spec_history_includes_the_run_cost(
    async_client: httpx.AsyncClient,
) -> None:
    """The ledger's acceptance named the history route explicitly, and it was
    dropping the field: `list_for_spec` returned it on ScoreSchema, but
    `_history_submission` mapped into a HistorySubmission that had no such field.
    """
    store = ScoreStore()
    await _register_benchmark(store)
    submission = _submission(spec_id="costed-history").model_copy(
        update={"run_cost_usd": Decimal("7.250000")},
    )
    await store.submit(submission)

    response = await async_client.get("/v1/leaderboard/hle/costed-history/history")

    assert response.status_code == 200
    returned = response.json()["submissions"][0]["run_cost_usd"]
    # Numeric equality, not string identity — Decimal scale (7.25 vs 7.250000)
    # survives the round trip differently and is not part of the contract.
    assert Decimal(returned) == Decimal("7.25")


async def test_get_spec_history_reports_an_absent_cost_as_null(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(_submission(spec_id="uncosted-history"))

    response = await async_client.get("/v1/leaderboard/hle/uncosted-history/history")

    assert response.json()["submissions"][0]["run_cost_usd"] is None


async def test_every_score_field_reaches_at_least_one_read_dto() -> None:
    """Guard against the duplication that has now caused two separate bugs.

    RankedLeaderboardEntry, HistorySubmission and ScoreSchema each redeclare
    subsets of the same underlying columns. Adding `run_cost_usd` to the schema
    but not to RankedLeaderboardEntry produced a runtime 500 (extra="forbid"),
    and omitting it from HistorySubmission silently dropped it from the history
    route — neither caught by the type checker. This asserts that a newly added
    Score field cannot be invisible on every read path at once.
    """
    from scoreboard.routes.leaderboard import HistorySubmission, RankedLeaderboardEntry
    from scoreboard.scores.models import Score
    from scoreboard.scores.schemas import ScoreSchema

    exposed = (
        set(RankedLeaderboardEntry.model_fields)
        | set(HistorySubmission.model_fields)
        | set(ScoreSchema.model_fields)
    )
    # Deliberately unpublished: dedup plumbing, the FK object, and the reverse
    # relation to idempotency keys (a relation, not a column).
    internal = {"content_hash", "benchmark", "idempotency_keys"}
    columns = {name for name in Score._meta.fields_map if not name.startswith("_")}

    missing = columns - exposed - internal
    assert missing == set(), f"Score columns absent from every read DTO: {sorted(missing)}"


# --- OME-770 review pass: the wire form must be backend-independent (spec 2.4) ---
#
# Pydantic emits Decimal as a JSON STRING carrying whatever scale/notation the
# value happens to have: "12.5" on SQLite, "12.500000" from a padded Postgres
# DECIMAL, and "1E+3" for a cost submitted as 1e3. Pass 2 computes a Pareto
# frontier and a cheapest-run stat in JS, where `<` on strings is lexicographic
# ("10" < "9.5" is true), so an unpinned scale makes $1000 rank cheaper than
# $3.50 and renders 1E+3 in the Cost column. Every read DTO pins it to 6dp.


def _costed(spec_id: str, cost: str) -> ScoreSubmission:
    """A submission carrying a raw, deliberately un-quantized cost.

    `model_copy` skips validation on purpose: it puts the awkward value (1E+3,
    12.5) into storage exactly as a legacy row or a non-submission write would,
    so these tests exercise the read-path serializer rather than the input
    validator that would otherwise have already normalized it.
    """
    return _submission(spec_id=spec_id).model_copy(update={"run_cost_usd": Decimal(cost)})


@pytest.mark.parametrize(
    ("submitted", "expected"),
    [
        ("12.5", "12.500000"),
        # Would otherwise serialize as the literal string "1E+3".
        ("1e3", "1000.000000"),
        ("0.000001", "0.000001"),
        ("0", "0.000000"),
    ],
)
async def test_leaderboard_serializes_the_cost_at_a_fixed_scale(
    async_client: httpx.AsyncClient,
    submitted: str,
    expected: str,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(_costed("fixed-scale", submitted))

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    entry = next(e for e in response.json()["entries"] if e["spec_id"] == "fixed-scale")
    assert entry["run_cost_usd"] == expected


async def test_spec_history_serializes_the_cost_at_a_fixed_scale(
    async_client: httpx.AsyncClient,
) -> None:
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(_costed("hist-scale", "1e3"))

    response = await async_client.get("/v1/leaderboard/hle/hist-scale/history")

    assert response.status_code == 200
    assert response.json()["submissions"][0]["run_cost_usd"] == "1000.000000"


async def test_an_absent_cost_serializes_as_null_not_a_string(
    async_client: httpx.AsyncClient,
) -> None:
    # INVARIANT (D5): absent must stay absent on the wire — not "0.000000", and
    # not the string "None".
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(_submission(spec_id="null-scale"))

    response = await async_client.get("/v1/leaderboard/hle")

    entry = next(e for e in response.json()["entries"] if e["spec_id"] == "null-scale")
    assert entry["run_cost_usd"] is None


# --- OME-770 review pass: the acceptance criteria name this route explicitly ---


async def test_get_leaderboard_includes_the_run_cost(
    async_client: httpx.AsyncClient,
) -> None:
    """Only a store-level test covered this route before; the spec names it."""
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(_costed("costed-board", "7.25"))
    await store.submit(_submission(spec_id="uncosted-board"))

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    by_spec = {e["spec_id"]: e for e in response.json()["entries"]}
    assert Decimal(by_spec["costed-board"]["run_cost_usd"]) == Decimal("7.25")
    assert by_spec["uncosted-board"]["run_cost_usd"] is None


# --- OME-770 review pass 2: sign-zero must be normalized on READ too (spec 2.6) ---


async def test_a_stored_negative_zero_serves_a_positive_cost(
    async_client: httpx.AsyncClient,
) -> None:
    """Normalizing only in the validator would leave already-stored rows broken.

    A "-0.000000" reachable by raw SQL, or written before the rule existed, must
    still serve "0.000000" — never a negative dollar figure on the board.
    """
    store = ScoreStore()
    await _register_benchmark(store)
    await store.submit(_costed("neg-zero", "-0.0"))

    board = await async_client.get("/v1/leaderboard/hle")
    history = await async_client.get("/v1/leaderboard/hle/neg-zero/history")

    entry = next(e for e in board.json()["entries"] if e["spec_id"] == "neg-zero")
    assert entry["run_cost_usd"] == "0.000000"
    assert history.json()["submissions"][0]["run_cost_usd"] == "0.000000"


async def test_list_benchmarks_exposes_the_focus_line(async_client: httpx.AsyncClient) -> None:
    # OME-874: the portal's Focus column reads this straight off /v1/benchmarks; a benchmark
    # without one must serialise as null rather than being omitted from the payload.
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id="draco",
        display_name="DRACO",
        description="Fixture benchmark",
        dataset_url=None,
        focus="Research reports with citations",
    )
    await _register_benchmark(store, benchmark_id="hle")

    response = await async_client.get("/v1/benchmarks")

    assert response.status_code == 200
    by_id = {benchmark["id"]: benchmark for benchmark in response.json()["benchmarks"]}
    assert by_id["draco"]["focus"] == "Research reports with citations"
    assert by_id["hle"]["focus"] is None


# --- OME-894 regression guard ----------------------------------------------------------------
# INVARIANT: a PUBLIC benchmark read ANONYMOUSLY is unchanged by private-leaderboard work. The
# risk in OME-894 is not failing to hide the private board — it is quietly breaking the public
# one while doing so. These are written BEFORE any privacy behaviour exists, so they fail for
# the right reason if a later step regresses the public path.
#
# WHY some assertions are supersets and others exact: the plan deliberately ADDS
# `visibility` to the benchmark DTO and a private flag to the board response, so pinning those
# key sets exactly would force editing this guard — a prior test — one step later. Superset
# there still catches a REMOVED or renamed field, which is the regression that matters. Where
# the plan adds nothing, the assertion is exact, because an unexpected new key on an entry is
# exactly how participant data would leak.

_PUBLIC_BENCHMARK_FIELDS = {
    "created_at",
    "dataset_url",
    "description",
    "display_name",
    "focus",
    "id",
    "revision",
}
_PUBLIC_BOARD_ENTRY_FIELDS = {
    "benchmark_revision",
    # OME-923 part B: a deliberate addition to the public board. Owner-approved change to
    # this OME-894 guard (2026-08-29); the assertion stays exact so any OTHER field
    # appearing here still fails, which is the leak this guard exists to catch.
    "on_pareto_frontier",
    "ran_with_providers",
    "rank",
    "run_cost_usd",
    "score",
    "spec_id",
    "submitted_at",
    "submitted_by",
    "total_questions",
    "url4_expression",
    "verified_by_screamingface",
}
_PUBLIC_HISTORY_ITEM_FIELDS = {
    "benchmark_revision",
    "correct_questions",
    "id",
    "run_cost_usd",
    "score",
    "submitted_at",
    "submitted_by",
    "total_questions",
    "verified_by_screamingface",
}
_PUBLIC_FRONTIER_FIELDS = {
    "benchmark_id",
    "closed_count",
    "current",
    "open_count",
    "open_share",
    "trend",
}


async def _seed_public_board(store: ScoreStore) -> None:
    await _register_benchmark(store)
    await store.submit(_submission(spec_id="spec-a", score=0.60, submitted_by="alice@example.test"))
    await store.submit(_submission(spec_id="spec-b", score=0.90, submitted_by="bob@example.test"))


async def test_ome894_guard_public_catalogue_is_unchanged_anonymously(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_public_board(ScoreStore())

    response = await async_client.get("/v1/benchmarks")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"benchmarks"}
    assert _PUBLIC_BENCHMARK_FIELDS <= set(body["benchmarks"][0])
    # The catalogue must never carry a score of any kind — it is the one path a private
    # benchmark stays listed on (OME-894 D4), so a score here would leak on that path.
    assert not {"score", "entries", "submissions"} & set(body["benchmarks"][0])


async def test_ome894_guard_public_board_is_unchanged_anonymously(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_public_board(ScoreStore())

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    body = response.json()
    assert {"benchmark", "entries", "baselines"} <= set(body)
    entries = body["entries"]
    assert len(entries) == 2
    assert set(entries[0]) == _PUBLIC_BOARD_ENTRY_FIELDS
    # Ranked, best first, numbered from 1 — an anonymous public read still gets real ranks.
    assert [entry["rank"] for entry in entries] == [1, 2]
    assert [entry["score"] for entry in entries] == [0.90, 0.60]
    # INVARIANT (OME-834): the domain is never published, on any path.
    assert [entry["submitted_by"] for entry in entries] == ["bob", "alice"]


async def test_ome894_guard_public_history_is_unchanged_anonymously(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_public_board(ScoreStore())

    response = await async_client.get("/v1/leaderboard/hle/spec-a/history")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"benchmark_id", "spec_id", "submissions"}
    assert set(body["submissions"][0]) == _PUBLIC_HISTORY_ITEM_FIELDS
    assert body["submissions"][0]["submitted_by"] == "alice"


async def test_ome894_guard_public_frontier_is_unchanged_anonymously(
    async_client: httpx.AsyncClient,
) -> None:
    await _seed_public_board(ScoreStore())

    response = await async_client.get("/v1/leaderboard/hle/frontier")

    assert response.status_code == 200
    assert set(response.json()) == _PUBLIC_FRONTIER_FIELDS


# --- OME-894: private boards ------------------------------------------------------------------

PRIVATE_ID = "healthbench-worst30"
ALICE_EMAIL = "alice@example.test"
BOB_EMAIL = "bob@example.test"


@pytest_asyncio.fixture
async def header_mode_client(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    # Same idiom as tests/unit/test_scores_routes.py: FORWARDED_ALLOW_IPS must be pinned
    # DISJOINT from allowed_networks or create_app's overlap guard refuses to start, and
    # ASGITransport's fake peer is ("127.0.0.1", 123) so 127.0.0.1/32 is the trusted network.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    settings = Settings.model_validate(
        {
            "database_url": "sqlite://:memory:",
            "cors_origins": [],
            "auth_mode": "cloudflare_headers",
            "allowed_networks": "127.0.0.1/32",
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as client:
        yield client


def _private_submission(
    *, submitted_by: str, spec_id: str, score: float, revision: str | None = "rev-current"
) -> ScoreSubmission:
    return ScoreSubmission(
        benchmark_id=PRIVATE_ID,
        spec_id=spec_id,
        url4_expression=f"url4://benchmark/{PRIVATE_ID}/{spec_id}",
        submitted_by=submitted_by,
        score=score,
        total_questions=100,
        correct_questions=int(score * 100),
        ran_with_providers=["openai"],
        benchmark_revision=revision,
    )


async def _seed_private_challenge() -> ScoreStore:
    store = ScoreStore()
    await store.register_benchmark(
        benchmark_id=PRIVATE_ID,
        display_name="HealthBench Worst-30% Challenge",
        revision="rev-current",
        visibility="private",
    )
    await store.submit(
        _private_submission(submitted_by=ALICE_EMAIL, spec_id="spec-alice", score=0.60),
        identity_verified=True,
    )
    await store.submit(
        _private_submission(submitted_by=BOB_EMAIL, spec_id="spec-bob", score=0.90),
        identity_verified=True,
    )
    return store


def _as(email: str) -> dict[str, str]:
    return {"X-User-Email": email}


async def test_private_catalogue_entry_is_listed_and_marked(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # Owner decision (Irina, 2026-08-24): listed and marked, since participants must be able to
    # find the challenge to enter it. The catalogue carries no scores, so listing leaks nothing.
    await _seed_private_challenge()

    response = await header_mode_client.get("/v1/benchmarks")

    assert response.status_code == 200
    entry = response.json()["benchmarks"][0]
    assert entry["id"] == PRIVATE_ID
    assert entry["visibility"] == "private"


async def test_anonymous_caller_sees_no_entries_on_a_private_board(
    header_mode_client: httpx.AsyncClient,
) -> None:
    await _seed_private_challenge()

    response = await header_mode_client.get(f"/v1/leaderboard/{PRIVATE_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["my_submissions"] == []
    # INVARIANT: a bare empty list is indistinguishable from "nobody has submitted". The response
    # says the listing was scoped, so a client can tell hidden-by-design from empty.
    assert body["scoped_to_caller"] is True
    assert body["benchmark"]["visibility"] == "private"


async def test_a_participant_sees_only_their_own_rows(
    header_mode_client: httpx.AsyncClient,
) -> None:
    await _seed_private_challenge()

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}", headers=_as(ALICE_EMAIL)
    )

    assert response.status_code == 200
    body = response.json()
    # INVARIANT: `entries` is the RANKING, and a private board has none — so it is empty for
    # everyone, including a participant. Their own rows are a different thing and live under a
    # different key, which is why no rank has to be suppressed and no client contract changes.
    assert body["entries"] == []
    mine = body["my_submissions"]
    assert [row["spec_id"] for row in mine] == ["spec-alice"]
    # Bob outscored Alice; nothing about that reaches her.
    assert all(row["submitted_by"] == "alice" for row in mine)


async def test_a_private_board_carries_no_rank_at_all(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # Telling a participant they are 4th tells them three people beat them. The field is ABSENT
    # rather than null: these rows were never ranked, so there is no rank to null out. That also
    # keeps RankedLeaderboardEntry.rank a required int, so no client contract changes.
    await _seed_private_challenge()

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}", headers=_as(ALICE_EMAIL)
    )

    mine = response.json()["my_submissions"]
    assert mine
    assert all("rank" not in row for row in mine)


async def test_a_participant_sees_their_row_from_another_revision(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # OME-894 D8 / OME-909: rank is suppressed here, so the registered-revision filter has no
    # purpose — and applying it would hide her own submission with no explanation.
    store = await _seed_private_challenge()
    await store.submit(
        _private_submission(
            submitted_by=ALICE_EMAIL,
            spec_id="spec-alice-old",
            score=0.55,
            revision="rev-obsolete",
        ),
        identity_verified=True,
    )

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}", headers=_as(ALICE_EMAIL)
    )

    assert sorted(row["spec_id"] for row in response.json()["my_submissions"]) == [
        "spec-alice",
        "spec-alice-old",
    ]


async def test_history_is_served_for_the_callers_own_spec(
    header_mode_client: httpx.AsyncClient,
) -> None:
    await _seed_private_challenge()

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/spec-alice/history", headers=_as(ALICE_EMAIL)
    )

    assert response.status_code == 200
    assert [row["submitted_by"] for row in response.json()["submissions"]] == ["alice"]


async def test_history_for_another_participants_spec_is_404_not_403(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: a 403 would confirm the spec exists, and spec ids are guessable model names.
    await _seed_private_challenge()

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/spec-bob/history", headers=_as(ALICE_EMAIL)
    )

    assert response.status_code == 404


async def test_history_for_a_nonexistent_spec_matches_another_participants(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: the two must be INDISTINGUISHABLE. A public board answers an unknown spec with
    # 200 and an empty list; if a private board kept that while 404-ing another participant's
    # spec, the status code alone would reveal which specs exist — the exact disclosure the
    # 404-not-403 rule above exists to prevent.
    await _seed_private_challenge()

    theirs = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/spec-bob/history", headers=_as(ALICE_EMAIL)
    )
    nonexistent = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/spec-nobody-ever/history", headers=_as(ALICE_EMAIL)
    )

    assert theirs.status_code == nonexistent.status_code == 404
    assert theirs.json() == nonexistent.json()


async def test_anonymous_history_on_a_private_board_is_404(
    header_mode_client: httpx.AsyncClient,
) -> None:
    await _seed_private_challenge()

    response = await header_mode_client.get(f"/v1/leaderboard/{PRIVATE_ID}/spec-alice/history")

    assert response.status_code == 404


async def test_frontier_is_unavailable_on_a_private_board(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # An aggregate over everyone by definition, and it publishes the running-best score and when
    # it changed — most of what the challenge hides. Unavailable even to a participant.
    await _seed_private_challenge()

    anonymous = await header_mode_client.get(f"/v1/leaderboard/{PRIVATE_ID}/frontier")
    participant = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/frontier", headers=_as(ALICE_EMAIL)
    )

    assert anonymous.status_code == 404
    assert participant.status_code == 404


async def test_disabled_auth_mode_yields_nothing_on_a_private_board(
    async_client: httpx.AsyncClient,
) -> None:
    # INVARIANT (OME-894 D2): with auth disabled there is no verified identity, so a supplied
    # header is an unverified claim and the board is readable by nobody. Staff read it out of
    # band. The `async_client` fixture runs in disabled mode, which is the deployed default.
    await _seed_private_challenge()

    board = await async_client.get(f"/v1/leaderboard/{PRIVATE_ID}", headers=_as(ALICE_EMAIL))
    history = await async_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/spec-alice/history", headers=_as(ALICE_EMAIL)
    )

    assert board.json()["entries"] == []
    assert board.json()["my_submissions"] == []
    assert history.status_code == 404


# --- review round 3: identity-scoped responses must not be shared-cacheable -------------------
# A private response varies by caller at a fixed URL. Without an explicit policy a shared cache
# may reuse one participant's response for another. The current proxy may not cache these, but
# keeping the policy at the privacy boundary stops a future proxy change becoming a data leak.

CACHE_POLICY = "private, no-store"


async def test_a_private_board_is_not_shared_cacheable(
    header_mode_client: httpx.AsyncClient,
) -> None:
    await _seed_private_challenge()

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}", headers=_as(ALICE_EMAIL)
    )

    assert response.headers["cache-control"] == CACHE_POLICY
    assert "X-User-Email" in response.headers["vary"]


async def test_an_anonymous_private_board_read_is_not_shared_cacheable(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # The empty response is identity-dependent too — caching it for a participant would hide
    # their own rows from them.
    await _seed_private_challenge()

    response = await header_mode_client.get(f"/v1/leaderboard/{PRIVATE_ID}")

    assert response.headers["cache-control"] == CACHE_POLICY


async def test_private_history_is_not_shared_cacheable(
    header_mode_client: httpx.AsyncClient,
) -> None:
    await _seed_private_challenge()

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/spec-alice/history", headers=_as(ALICE_EMAIL)
    )

    assert response.headers["cache-control"] == CACHE_POLICY


async def test_the_privacy_preserving_404_is_not_shared_cacheable(
    header_mode_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: the refusal is identity-dependent as well — caching alice's 404 for bob's spec
    # and replaying it to bob would deny him his own history.
    await _seed_private_challenge()

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}/spec-bob/history", headers=_as(ALICE_EMAIL)
    )

    assert response.status_code == 404
    assert response.headers["cache-control"] == CACHE_POLICY


async def test_a_public_board_carries_no_private_cache_policy(
    async_client: httpx.AsyncClient,
) -> None:
    # Regression guard: a public board is identical for every caller and must stay ordinarily
    # cacheable. Marking it no-store would quietly cost the board its caching.
    await _seed_public_board(ScoreStore())

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.headers.get("cache-control") != CACHE_POLICY


# --- review round 21: a read must not answer from a visibility read that has gone stale -------
# Round 20 closed this on the WRITE path and left every read deciding from a visibility read and
# then running a query, with nothing in between. The seed job flips boards while requests are in
# flight. Found in review of PR #719.


def _flip_private_during(method: str) -> tuple[object, object]:
    """Land the flip while `ScoreStore.<method>` is running — after the visibility read."""
    real = getattr(ScoreStore, method)

    async def _hook(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        await Benchmark.filter(id=PRIVATE_ID).update(visibility="private")
        return await real(self, *args, **kwargs)

    return real, _hook


async def _two_participants() -> None:
    store = ScoreStore()
    await store.register_benchmark(benchmark_id=PRIVATE_ID, display_name="HB")
    for who, spec in ((ALICE_EMAIL, "alice-spec"), (BOB_EMAIL, "bob-spec")):
        await store.submit(
            _private_submission(submitted_by=who, spec_id=spec, score=0.8, revision=None),
            identity_verified=True,
        )


async def test_a_flip_during_the_ranking_query_does_not_publish_the_board(
    async_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: nothing unscoped leaves once the board is private. This returned BOTH participants'
    # entries with `scoped_to_caller: false` on a board that was private by the time it answered.
    await _two_participants()
    real, hook = _flip_private_during("leaderboard")

    ScoreStore.leaderboard = hook  # type: ignore[method-assign]
    try:
        response = await async_client.get(f"/v1/leaderboard/{PRIVATE_ID}")
    finally:
        ScoreStore.leaderboard = real  # type: ignore[method-assign]

    body = response.json()
    assert response.status_code == 200
    assert body["entries"] == []
    assert body["scoped_to_caller"] is True
    assert ALICE_EMAIL.split("@")[0] not in response.text
    assert BOB_EMAIL.split("@")[0] not in response.text


async def test_a_flip_during_the_history_query_withholds_the_rows(
    async_client: httpx.AsyncClient,
) -> None:
    # Those rows were fetched UNSCOPED. Once the board is private they are not ours to return, and
    # the private branch answers exactly this shape with a 404.
    await _two_participants()
    real, hook = _flip_private_during("list_for_spec")

    ScoreStore.list_for_spec = hook  # type: ignore[method-assign]
    try:
        response = await async_client.get(f"/v1/leaderboard/{PRIVATE_ID}/bob-spec/history")
    finally:
        ScoreStore.list_for_spec = real  # type: ignore[method-assign]

    assert response.status_code == 404
    assert "bob-spec" not in response.text or response.json().get("submissions") is None


async def test_a_flip_during_the_frontier_query_withholds_the_aggregate(
    async_client: httpx.AsyncClient,
) -> None:
    # D5: a private board publishes no aggregate, to participants either.
    await _two_participants()
    real, hook = _flip_private_during("list_all_for_benchmark")

    ScoreStore.list_all_for_benchmark = hook  # type: ignore[method-assign]
    try:
        response = await async_client.get(f"/v1/leaderboard/{PRIVATE_ID}/frontier")
    finally:
        ScoreStore.list_all_for_benchmark = real  # type: ignore[method-assign]

    assert response.status_code == 404


async def test_an_undisturbed_public_read_is_unchanged(
    async_client: httpx.AsyncClient,
) -> None:
    # The regression guard: re-deciding must cost nothing when no flip happens, which is every real
    # request. One extra indexed read on the public branch, and the same body as before.
    await _two_participants()

    response = await async_client.get(f"/v1/leaderboard/{PRIVATE_ID}")

    body = response.json()
    assert response.status_code == 200
    assert len(body["entries"]) == 2
    assert body["scoped_to_caller"] is False


async def test_the_private_response_never_contradicts_itself(
    async_client: httpx.AsyncClient,
) -> None:
    # INVARIANT: `scoped_to_caller: true` and `visibility: "private"` are the same fact stated
    # twice, so no body may carry one without the other. The re-decision path reached
    # `_private_leaderboard` with a benchmark read BEFORE the flip and passed it through, so a
    # client trusting `visibility` — the field D4 added for exactly this — saw a public board.
    await _two_participants()
    real, hook = _flip_private_during("leaderboard")

    ScoreStore.leaderboard = hook  # type: ignore[method-assign]
    try:
        flipped = await async_client.get(f"/v1/leaderboard/{PRIVATE_ID}")
    finally:
        ScoreStore.leaderboard = real  # type: ignore[method-assign]

    body = flipped.json()
    assert body["scoped_to_caller"] is True
    assert body["benchmark"]["visibility"] == "private"

    # And the same holds on the ordinary private path, which must stay in step with it.
    await Benchmark.filter(id=PRIVATE_ID).update(visibility="private")
    steady = (await async_client.get(f"/v1/leaderboard/{PRIVATE_ID}")).json()
    assert steady["scoped_to_caller"] is True
    assert steady["benchmark"]["visibility"] == "private"


# ---- OME-923 part B: Pareto frontier marks -----------------------------------


async def _priced(
    store: ScoreStore,
    *,
    spec_id: str,
    score: float,
    cost: str | None,
) -> None:
    """Submit a row and then set its run cost directly.

    WHY not a `run_cost_usd` argument on `_submission`: that helper is prior-cycle test
    code, and sdlc rule 5 keeps prior tests unmodified. Writing the column afterwards
    mirrors how this file already backdates `submitted_at`.
    """
    created, _ = await store.submit(_submission(spec_id=spec_id, score=score))
    if cost is not None:
        await Score.filter(id=created.id).update(run_cost_usd=Decimal(cost))


# INVARIANT (D12): only a benchmark with a REGISTERED revision carries frontier marks, so every
# marking test below pins one. Rows must carry the same revision or the ranking query filters
# them out entirely (OME-775).
_PINNED = "rev-1"


async def _register_pinned(store: ScoreStore) -> None:
    await store.register_benchmark(
        benchmark_id="hle",
        display_name="Humanity's Last Exam",
        description="Fixture benchmark",
        dataset_url="https://example.test/hle.jsonl",
        revision=_PINNED,
    )


async def _row(
    store: ScoreStore,
    *,
    spec_id: str,
    score: float,
    cost: str | None,
    revision: str = _PINNED,
) -> None:
    """Submit a row, then set the revision it was measured against and its cost.

    WHY written afterwards rather than passed to `_submission`: that helper is prior-cycle test
    code and sdlc rule 5 keeps it unmodified. This mirrors how the file already backdates
    `submitted_at`.
    """
    created, _ = await store.submit(_submission(spec_id=spec_id, score=score))
    updates: dict[str, object] = {"benchmark_revision": revision}
    if cost is not None:
        updates["run_cost_usd"] = Decimal(cost)
    await Score.filter(id=created.id).update(**updates)


async def test_get_leaderboard_marks_the_pareto_frontier(
    async_client: httpx.AsyncClient,
) -> None:
    """FEATURE: OME-923 part B — the board marks best-score-for-the-money rows."""
    store = ScoreStore()
    await _register_pinned(store)
    await _row(store, spec_id="best-value", score=0.90, cost="1.00")
    # Same score, nine times the price: dominated, even though nobody outscored it (D7).
    await _row(store, spec_id="same-score-dearer", score=0.90, cost="9.00")
    await _row(store, spec_id="cheapest", score=0.70, cost="0.10")
    # Beaten on both axes by `cheapest`.
    await _row(store, spec_id="dominated", score=0.60, cost="5.00")
    # INVARIANT: the top score, but unpriced — excluded, and it must not knock out anything
    # either. Read as zero it would win the board outright on an unknown.
    await _row(store, spec_id="unpriced", score=0.95, cost=None)

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    entries = response.json()["entries"]
    marked = {entry["spec_id"] for entry in entries if entry["on_pareto_frontier"]}
    assert marked == {"best-value", "cheapest"}
    # The highest-score row is a SEPARATE claim: `unpriced` leads on score and holds no frontier
    # mark, so a row can be one, both or neither.
    assert entries[0]["spec_id"] == "unpriced"
    assert entries[0]["on_pareto_frontier"] is False


async def test_get_leaderboard_marks_nothing_when_no_row_reports_a_cost(
    async_client: httpx.AsyncClient,
) -> None:
    """Today's real board: OME-770 shipped the column, nothing has ever filled it. It must
    render as an ordinary board, not error and not mark anything."""
    store = ScoreStore()
    await _register_benchmark(store)
    await _priced(store, spec_id="spec-a", score=0.90, cost=None)
    await _priced(store, spec_id="spec-b", score=0.70, cost=None)

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 2
    assert all(entry["on_pareto_frontier"] is False for entry in entries)


async def test_a_private_board_emits_no_frontier_information(
    header_mode_client: httpx.AsyncClient,
) -> None:
    """INVARIANT (OME-894 D5): a participant sees no aggregate. The frontier is an aggregate
    over everyone's costs, so it must not reach a private board in any form — including via
    the caller's own rows."""
    await _seed_private_challenge()
    await Benchmark.filter(id=PRIVATE_ID).update(visibility="private")

    response = await header_mode_client.get(
        f"/v1/leaderboard/{PRIVATE_ID}", headers=_as(ALICE_EMAIL)
    )

    assert response.status_code == 200
    body = response.json()
    # `entries` is the public ranking and a private board has none, so the flag is never
    # emitted for anyone — the privacy rule holds by construction, not by a special case.
    assert body["entries"] == []
    assert body["my_submissions"], "the owner should still see her own rows"
    for row in body["my_submissions"]:
        assert "on_pareto_frontier" not in row


# ---- OME-923 part B: review fixes (PR #778) ----------------------------------


async def _priced_rev(
    store: ScoreStore,
    *,
    spec_id: str,
    score: float,
    cost: str,
    revision: str,
) -> None:
    """Submit a row, then set its cost AND the revision it was measured against."""
    created, _ = await store.submit(_submission(spec_id=spec_id, score=score))
    await Score.filter(id=created.id).update(
        run_cost_usd=Decimal(cost), benchmark_revision=revision
    )


async def test_the_board_can_be_read_whole(tortoise_db: None) -> None:
    """The store seam the fix rests on: `top_n=None` returns the board entire, which is what
    lets the route serve the page and the frontier from ONE read."""
    store = ScoreStore()
    await _register_benchmark(store)
    for index in range(5):
        await _priced(store, spec_id=f"spec-{index}", score=0.90 - index / 100, cost="1.00")

    assert len(await store.leaderboard(benchmark_id="hle", top_n=2)) == 2
    assert len(await store.leaderboard(benchmark_id="hle", top_n=None)) == 5


async def test_the_public_board_takes_exactly_one_ranking_read(
    async_client: httpx.AsyncClient,
) -> None:
    """INVARIANT: one read, so nothing unscoped can be fetched AFTER the `turned_private`
    guard. A second read placed after that guard leaked both participants of a private board
    when the flip landed during it (self-review, 2026-08-30). This pins the shape of the fix:
    a reintroduced second query fails here even if the leak itself is hard to time."""
    store = ScoreStore()
    await _register_benchmark(store)
    await _priced(store, spec_id="spec-a", score=0.90, cost="1.00")
    calls: list[object] = []
    real = ScoreStore.leaderboard

    async def _counting(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs.get("top_n", args[1] if len(args) > 1 else None))
        return await real(self, *args, **kwargs)

    ScoreStore.leaderboard = _counting  # type: ignore[method-assign]
    try:
        response = await async_client.get("/v1/leaderboard/hle")
    finally:
        ScoreStore.leaderboard = real  # type: ignore[method-assign]

    assert response.status_code == 200
    assert calls == [None], f"expected one whole-board read, got {calls}"


async def test_a_frontier_mark_does_not_change_with_top(
    async_client: httpx.AsyncClient,
) -> None:
    """INVARIANT: the mark is a claim about the whole board, so it cannot depend on how many
    rows the caller asked to see. Three rows tie on score and only the cheapest is truly on
    the frontier; computed over a truncated page, whichever dear row led the page was marked.

    AIDEV-NOTE: the spec_id prefixes are load-bearing. The board's outer ordering is
    `score DESC` with NO tiebreaker, so the order among equal scores is whatever the backend
    returns — alphabetical by spec_id on SQLite (index scan), insertion order on Postgres
    (heap scan). `z-cheapest` sorts last alphabetically AND is inserted last, so it falls
    outside `top=2` under either. Rename these and the test still passes but stops proving
    anything.
    """
    store = ScoreStore()
    await _register_pinned(store)
    await _row(store, spec_id="a-dear", score=0.90, cost="5.00")
    await _row(store, spec_id="b-dearer", score=0.90, cost="6.00")
    await _row(store, spec_id="z-cheapest", score=0.90, cost="1.00")

    full = await async_client.get("/v1/leaderboard/hle", params={"top": 3})
    cut = await async_client.get("/v1/leaderboard/hle", params={"top": 2})

    assert full.status_code == 200
    assert cut.status_code == 200
    marks_full = {e["spec_id"]: e["on_pareto_frontier"] for e in full.json()["entries"]}
    marks_cut = {e["spec_id"]: e["on_pareto_frontier"] for e in cut.json()["entries"]}
    assert marks_full == {"a-dear": False, "b-dearer": False, "z-cheapest": True}
    # The dominator is off the page here, which is exactly the case that used to flip a mark.
    assert "z-cheapest" not in marks_cut
    for spec_id, marked in marks_cut.items():
        assert marks_full[spec_id] == marked, f"{spec_id} changed mark with top"


# NOTE: a route-level test for cross-revision cohorts lived here. After D12 the route never
# computes a frontier on a board with mixed revisions — an unpinned board marks nothing, and
# a pinned one is filtered to a single revision — so the scenario is unreachable through HTTP.
# `test_an_unpinned_benchmark_carries_no_frontier_marks` below pins the new behaviour, and
# tests/unit/scores/test_pareto.py still covers the per-cohort function directly.


async def test_an_unpinned_benchmark_carries_no_frontier_marks(
    async_client: httpx.AsyncClient,
) -> None:
    """INVARIANT (D12): fail closed on a board with no REGISTERED revision.

    `benchmark_revision` is free-form client input, and `_build_leaderboard_query` applies its
    revision filter ONLY when the benchmark has a registered revision. Combined with per-cohort
    comparison, a submitter on such a board could send a unique revision, land in a cohort of
    one, and be marked "best score for cost" unconditionally — however bad and however dear.

    The board still ranks and lists every row. It just makes no cost claim about any of them.
    """
    store = ScoreStore()
    await _register_benchmark(store)  # deliberately no revision registered
    await _priced(store, spec_id="honest", score=0.90, cost="1.00")
    await _priced_rev(store, spec_id="gamer", score=0.10, cost="99.00", revision="mine-2026")

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 2, "the board must still list its rows"
    assert all(entry["on_pareto_frontier"] is False for entry in entries)


async def test_the_frontier_is_scoped_to_one_benchmark(
    async_client: httpx.AsyncClient,
) -> None:
    """INVARIANT: "no other submission on the same board" — the frontier must not reach across
    benchmarks. Different exams, different scales; a cheap high score on another board says
    nothing about value on this one.

    Correct in the query today (`where benchmark_id == ...`), but no test registered a second
    benchmark, so a frontier computed over the entire table would have passed the whole suite.
    """
    store = ScoreStore()
    await _register_pinned(store)
    await store.register_benchmark(
        benchmark_id="other",
        display_name="Other Benchmark",
        description="Fixture benchmark",
        dataset_url="https://example.test/other.jsonl",
        revision=_PINNED,
    )
    # The only priced row on `hle`, and a poor one.
    await _row(store, spec_id="local", score=0.50, cost="5.00")
    # Better AND cheaper — but on a different board, so it must not dominate anything here.
    foreign, _ = await store.submit(
        _submission(benchmark_id="other", spec_id="foreign", score=0.99)
    )
    await Score.filter(id=foreign.id).update(
        benchmark_revision=_PINNED, run_cost_usd=Decimal("0.01")
    )

    response = await async_client.get("/v1/leaderboard/hle")

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["spec_id"] for entry in entries] == ["local"]
    assert entries[0]["on_pareto_frontier"] is True

"""The paper link on a score (E14 A1, PRD `metadata-ownership` M1, M10, M16, M21; TDD #1-#5).

FEATURE: OME-1307 — `paper_url` is display-only provenance. It is stored as sent, replaces on a
same-owner resubmit when given, and never enters the recipe hash.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score
from scoreboard.scores.schemas import ScoreSubmission
from scoreboard.scores.store import ScoreStore, _content_hash

ALICE = "alice@example.test"
BOB = "bob@example.test"
PAPER = "https://arxiv.org/abs/2610.01234"

pytestmark = pytest.mark.asyncio


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "submitted_by": "tester",
        "score": 0.75,
        "total_questions": 4,
        "correct_questions": 3,
        "ran_with_providers": ["openai"],
        "run_cost_usd": "1.250000",
        "run_cost_status": "complete",
    }
    payload.update(overrides)
    return payload


def _submission(
    *,
    submitted_by: str = ALICE,
    authors: list[str] | None = None,
    paper_url: str | None = None,
) -> ScoreSubmission:
    # `paper_url` is only passed when given, so the CHAR tests (#1, #2) run on today's schema.
    extra: dict[str, Any] = {} if paper_url is None else {"paper_url": paper_url}
    return ScoreSubmission(
        benchmark_id="hle",
        spec_id="spec-1",
        url4_expression="url4://benchmark/hle/spec-1",
        submitted_by=submitted_by,
        authors=authors,
        **extra,
        score=0.75,
        total_questions=100,
        correct_questions=75,
        ran_with_providers=["openai"],
        run_cost_usd=Decimal("1.000000"),
        run_cost_status="complete",
    )


async def _make_app(tortoise_db: None, **settings: object) -> FastAPI:
    app = create_app(
        Settings.model_validate(
            {"database_url": "sqlite://:memory:", "cors_origins": [], **settings}
        )
    )
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    return app


@pytest_asyncio.fixture
async def disabled_client(tortoise_db: None) -> AsyncGenerator[AsyncClient, None]:
    app = await _make_app(tortoise_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def cloudflare_client(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    # Same pins as `app_with_cloudflare_auth` in test_scores_routes.py: FORWARDED_ALLOW_IPS must
    # be disjoint from allowed_networks, and ASGITransport's fake peer is 127.0.0.1.
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = await _make_app(
        tortoise_db, auth_mode="cloudflare_headers", allowed_networks="127.0.0.1/32"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


# --- #1 CHAR: a same-owner resubmit replaces authors; None keeps them (store.py OME-1054) ------


async def test_same_owner_resubmit_replaces_authors_and_none_keeps_them(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    store = ScoreStore()
    first, _ = await store.submit(_submission(authors=[ALICE]))

    replaced, created = await store.submit(_submission(authors=[ALICE, BOB]))
    assert created is False
    assert replaced.id == first.id
    assert replaced.authors == [ALICE, BOB]

    kept, created = await store.submit(_submission(authors=None))
    assert created is False
    assert kept.authors == [ALICE, BOB]
    assert (await Score.get(id=first.id)).authors == [ALICE, BOB]


# --- #2 CHAR: a private-board read by a non-owner is 404 (scores.py OME-894) -------------------


async def test_private_board_read_by_a_non_owner_is_404(cloudflare_client: AsyncClient) -> None:
    await Benchmark.create(id="private-x", display_name="Private", visibility="private")
    created = await cloudflare_client.post(
        "/v1/scores",
        json=_payload(benchmark_id="private-x"),
        headers={"X-User-Email": ALICE},
    )
    assert created.status_code == 201, created.text
    score_id = created.json()["id"]

    stranger = await cloudflare_client.get(f"/v1/scores/{score_id}", headers={"X-User-Email": BOB})
    owner = await cloudflare_client.get(f"/v1/scores/{score_id}", headers={"X-User-Email": ALICE})

    assert stranger.status_code == 404
    assert owner.status_code == 200


# --- #3 M1: POST stores the paper link and GET returns it --------------------------------------


async def test_post_stores_and_returns_paper_url(disabled_client: AsyncClient) -> None:
    created = await disabled_client.post("/v1/scores", json=_payload(paper_url=PAPER))

    assert created.status_code == 201, created.text
    assert created.json()["paper_url"] == PAPER
    score_id = created.json()["id"]
    assert (await Score.get(id=score_id)).paper_url == PAPER
    fetched = await disabled_client.get(f"/v1/scores/{score_id}")
    assert fetched.json()["paper_url"] == PAPER


async def test_paper_url_is_stored_exactly_as_sent(disabled_client: AsyncClient) -> None:
    # INVARIANT: no normalisation (pydantic `HttpUrl` would lower-case the host and add a slash).
    raw = "HTTPS://ArXiv.org/abs/2610.01234?v=2#Top"

    created = await disabled_client.post("/v1/scores", json=_payload(paper_url=raw))

    assert created.status_code == 201, created.text
    assert created.json()["paper_url"] == raw


async def test_a_score_without_a_paper_link_omits_the_key(disabled_client: AsyncClient) -> None:
    # INVARIANT: excluded when absent, like `models` and `run_cost_status` — the private JSONL
    # export hashes these bytes to authorise a purge, so no legacy row may gain `"paper_url": null`.
    created = await disabled_client.post("/v1/scores", json=_payload())

    assert created.status_code == 201, created.text
    assert "paper_url" not in created.json()
    assert "metadata_updated_at" not in created.json()


# --- #4 M10: a bad paper link is a 422 ---------------------------------------------------------

BAD_PAPER_URLS = [
    pytest.param("javascript:alert(1)", id="javascript"),
    pytest.param("ftp://example.org/paper.pdf", id="ftp"),
    pytest.param("https://example.org/" + "a" * 2029, id="2049-chars"),
    pytest.param("https://example.org/a\x00b", id="nul-char"),
    pytest.param("https://example.org/a\nb", id="newline"),
    pytest.param("https://example.org/a\x7fb", id="del-char"),
    pytest.param("https://", id="no-host"),
    pytest.param("https:///abs/1", id="empty-host"),
    pytest.param("//example.org/paper", id="no-scheme"),
    pytest.param("", id="empty"),
]


@pytest.mark.parametrize("value", BAD_PAPER_URLS)
async def test_post_rejects_a_bad_paper_url(disabled_client: AsyncClient, value: str) -> None:
    response = await disabled_client.post("/v1/scores", json=_payload(paper_url=value))

    assert response.status_code == 422, value
    # The field must be KNOWN and then refused; `extra_forbidden` would be a false green.
    errors = response.json()["detail"]
    assert errors[0]["loc"] == ["body", "paper_url"]
    assert errors[0]["type"] != "extra_forbidden"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("http://example.org/p", id="http"),
        pytest.param("HTTPS://Example.org/p", id="upper-case-scheme"),
        pytest.param("https://example.org/" + "a" * 2028, id="2048-chars"),
    ],
)
def test_submission_accepts_an_http_or_https_paper_url(value: str) -> None:
    assert _submission(paper_url=value).paper_url == value


# --- #5 M16: an older SDK resubmits without paper_url; the stored link survives ---------------


async def test_resubmit_without_paper_url_keeps_it(tortoise_db: None) -> None:
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    store = ScoreStore()
    first, _ = await store.submit(_submission(paper_url=PAPER))

    kept, created = await store.submit(_submission())

    assert created is False
    assert kept.paper_url == PAPER
    assert (await Score.get(id=first.id)).paper_url == PAPER


async def test_resubmit_with_paper_url_replaces_it_without_dating_the_frontier(
    tortoise_db: None,
) -> None:
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    store = ScoreStore()
    first, _ = await store.submit(_submission(paper_url=PAPER))

    replaced, created = await store.submit(_submission(paper_url="https://doi.org/10.1/x"))

    assert created is False
    assert replaced.paper_url == "https://doi.org/10.1/x"
    stored = await Score.get(id=first.id)
    assert stored.paper_url == "https://doi.org/10.1/x"
    # I4: display-only, so it never stamps `enriched_at`.
    assert stored.enriched_at is None


def test_paper_url_does_not_change_recipe_identity() -> None:
    assert _content_hash(_submission(paper_url=PAPER)) == _content_hash(_submission())

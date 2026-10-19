"""OME-1596: metadata keys obey AuthorEmail even with legacy submitted_by fallback."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.credit_metadata import authors_metadata_problems
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent
from scoreboard.scores.schemas import AuthorEmail


@pytest_asyncio.fixture
async def http(tortoise_db: None) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _payload(owner: str) -> dict[str, object]:
    return {
        "benchmark_id": "hle",
        "spec_id": "email-key-regression",
        "url4_expression": "url4://benchmark/email-key-regression",
        "score": 0.75,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
        "submitted_by": owner,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["submit", "resubmit", "patch"])
async def test_invalid_email_key_refused_before_write(http: AsyncClient, operation: str) -> None:
    payload = _payload("not-an-email")
    score_id = None
    if operation != "submit":
        # Preserve legacy submitter compatibility when no author metadata is supplied.
        created = await http.post("/v1/scores", json=payload)
        assert created.status_code == 201, created.text
        score_id = created.json()["id"]
    metadata = {"authors_metadata": {"not-an-email": {}}}
    if operation == "patch":
        response = await http.patch(
            f"/v1/scores/{score_id}", json=metadata, headers={"X-User-Email": "not-an-email"}
        )
    else:
        response = await http.post("/v1/scores", json=payload | metadata)
    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert [(e["loc"], e["type"]) for e in errors] == [
        (["body", "authors_metadata", "not-an-email"], "metadata_invalid")
    ]
    assert await Score.all().count() == (0 if score_id is None else 1)
    assert await ScoreMetadataEvent.all().count() == 0
    if score_id is not None:
        assert (await Score.get(id=score_id)).authors_metadata is None


@pytest.mark.parametrize("key", ["plain", "a@localhost", "a@.example.test", "a b@example.test"])
def test_metadata_keys_reject_malformed_email_syntax(key: str) -> None:
    problems = authors_metadata_problems({key: {}})
    assert len(problems) == 1
    assert problems[0].loc == ("authors_metadata", key)


@pytest.mark.parametrize("key", ["Alice+paper@Example.test", "a.b@lab.example.test"])
def test_metadata_keys_share_author_email_rule_without_normalization(key: str) -> None:
    assert TypeAdapter(AuthorEmail).validate_python(key) == key
    assert authors_metadata_problems({key: {}}) == []


@pytest.mark.asyncio
async def test_valid_submitter_fallback_accepts_casefolded_email_key(http: AsyncClient) -> None:
    metadata = {"ALICE+paper@Example.test": {"full_name": "Alice"}}
    response = await http.post(
        "/v1/scores",
        json=_payload("alice+paper@example.test") | {"authors_metadata": metadata},
    )
    assert response.status_code == 201, response.text
    assert (await Score.get(id=response.json()["id"])).authors_metadata == metadata

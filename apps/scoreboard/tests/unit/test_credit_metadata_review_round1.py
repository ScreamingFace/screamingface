"""Review round 1 on the metadata write path (PR 1440).

FEATURE: author and paper metadata are stored as JSON on every backend, so a value or key the
database cannot hold must be a 422 that names the field and the key, never a 503 (PostgreSQL JSONB
refuses the NUL character) or a 500 with the row already committed (SQLite stores a lone surrogate
that every later read then fails to encode).

Also here: the edit log keeps the untouched object's pair equal on a one-object edit, and the
casefold-duplicate refusal carries both spellings as structured input.

Every check compares parsed JSON fields or model fields.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent

pytestmark = pytest.mark.asyncio

OWNER = "alice@example.test"
HEADERS = {"X-User-Email": OWNER}
NUL = "a\x00b"
SURROGATE = "a\ud800b"
# A key holding a lone surrogate is reported with the surrogate written out as `\\ud800`, so the
# 422 itself can be encoded as UTF-8.
SURROGATE_SHOWN = "a\\ud800b"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark_id": "hle",
        "spec_id": "spec-1",
        "url4_expression": "url4://benchmark/spec-1",
        "score": 0.75,
        "total_questions": 4,
        "ran_with_providers": ["openai"],
    }
    payload.update(overrides)
    return payload


@pytest_asyncio.fixture
async def client(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "192.0.2.1")
    app = create_app(
        Settings.model_validate(
            {
                "database_url": "sqlite://:memory:",
                "cors_origins": [],
                "auth_mode": "cloudflare_headers",
                "allowed_networks": "127.0.0.1/32",
            }
        )
    )
    await Benchmark.create(id="hle", display_name="Humanity's Last Exam")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def _send(client: AsyncClient, method: str, url: str, body: dict[str, Any]) -> Any:
    """Send ``body`` as ASCII-escaped JSON, the way a client can carry a lone surrogate.

    WHY not `json=`: httpx encodes with `ensure_ascii=False`, which cannot encode a lone surrogate
    at all, so the request would never leave the test. `\\ud800` escaped in JSON is what a real
    client sends, and what the board's JSON parser turns back into the surrogate.
    """
    return await client.request(
        method,
        url,
        content=json.dumps(body),
        headers={**HEADERS, "Content-Type": "application/json"},
    )


def _locs(response: Any) -> list[list[Any]]:
    return [error["loc"] for error in response.json()["detail"]]


# The bad part, where it sits, and the location the 422 names.
UNSTORABLE = [
    pytest.param(
        "paper_metadata", {"title": NUL}, ["body", "paper_metadata", "title"], id="nul-known-value"
    ),
    pytest.param(
        "paper_metadata", {"venue": NUL}, ["body", "paper_metadata", "venue"], id="nul-open-value"
    ),
    pytest.param(
        "paper_metadata",
        {"title": SURROGATE},
        ["body", "paper_metadata", "title"],
        id="surrogate-known-value",
    ),
    pytest.param(
        "paper_metadata",
        {"venue": SURROGATE},
        ["body", "paper_metadata", "venue"],
        id="surrogate-open-value",
    ),
    pytest.param(
        "paper_metadata",
        {"url": "https://example.org/" + SURROGATE},
        ["body", "paper_metadata", "url"],
        id="surrogate-url",
    ),
    pytest.param("paper_metadata", {NUL: "x"}, ["body", "paper_metadata", NUL], id="nul-key"),
    pytest.param(
        "paper_metadata",
        {SURROGATE: "x"},
        ["body", "paper_metadata", SURROGATE_SHOWN],
        id="surrogate-key",
    ),
    pytest.param(
        "authors_metadata",
        {OWNER: {"full_name": NUL}},
        ["body", "authors_metadata", OWNER, "full_name"],
        id="nul-author-value",
    ),
    pytest.param(
        "authors_metadata",
        {OWNER: {SURROGATE: "x"}},
        ["body", "authors_metadata", OWNER, SURROGATE_SHOWN],
        id="surrogate-author-inner-key",
    ),
    pytest.param(
        "authors_metadata",
        {OWNER + NUL: {}},
        ["body", "authors_metadata", OWNER + NUL],
        id="nul-author-key",
    ),
    pytest.param(
        "authors_metadata",
        {OWNER + SURROGATE: {}},
        ["body", "authors_metadata", OWNER + SURROGATE_SHOWN],
        id="surrogate-author-key",
    ),
]


@pytest.mark.parametrize(("field", "value", "loc"), UNSTORABLE)
async def test_an_unstorable_part_is_a_422_on_submit_and_nothing_is_written(
    client: AsyncClient, field: str, value: dict[str, Any], loc: list[Any]
) -> None:
    response = await _send(client, "POST", "/v1/scores", _payload(**{field: value}))

    assert response.status_code == 422, response.text
    assert _locs(response) == [loc]
    assert await Score.all().count() == 0


@pytest.mark.parametrize(("field", "value", "loc"), UNSTORABLE)
async def test_an_unstorable_part_is_a_422_on_patch_and_nothing_changes(
    client: AsyncClient, field: str, value: dict[str, Any], loc: list[Any]
) -> None:
    created = await client.post("/v1/scores", json=_payload(), headers=HEADERS)
    score_id = created.json()["id"]

    response = await _send(client, "PATCH", f"/v1/scores/{score_id}", {field: value})

    assert response.status_code == 422, response.text
    assert _locs(response) == [loc]
    stored = await Score.get(id=score_id)
    assert (stored.authors_metadata, stored.paper_metadata) == (None, None)
    assert await ScoreMetadataEvent.filter(score_id=score_id).count() == 0
    assert (await client.get(f"/v1/scores/{score_id}")).status_code == 200


async def test_other_control_characters_stay_accepted(client: AsyncClient) -> None:
    # Only what the store cannot hold is refused; this is not a control-character ban.
    created = await client.post(
        "/v1/scores", json=_payload(paper_metadata={"venue": "a\tb\x01c"}), headers=HEADERS
    )

    assert created.status_code == 201, created.text
    assert (await Score.get(id=created.json()["id"])).paper_metadata == {"venue": "a\tb\x01c"}


async def test_editing_only_paper_metadata_keeps_the_authors_pair_equal(
    client: AsyncClient,
) -> None:
    authors = {OWNER: {"full_name": "Alice"}}
    created = await client.post(
        "/v1/scores",
        json=_payload(authors_metadata=authors, paper_metadata={"title": "Old"}),
        headers=HEADERS,
    )
    score_id = created.json()["id"]

    edited = await client.patch(
        f"/v1/scores/{score_id}", json={"paper_metadata": {"title": "New"}}, headers=HEADERS
    )

    assert edited.status_code == 200, edited.text
    [event] = await ScoreMetadataEvent.filter(score_id=score_id)
    assert event.old_authors_metadata == event.new_authors_metadata == authors
    assert (event.old_paper_metadata, event.new_paper_metadata) == (
        {"title": "Old"},
        {"title": "New"},
    )


async def test_editing_only_authors_metadata_keeps_the_paper_pair_equal(
    client: AsyncClient,
) -> None:
    paper = {"title": "T"}
    created = await client.post(
        "/v1/scores",
        json=_payload(authors_metadata={OWNER: {"full_name": "Old"}}, paper_metadata=paper),
        headers=HEADERS,
    )
    score_id = created.json()["id"]

    edited = await client.patch(
        f"/v1/scores/{score_id}",
        json={"authors_metadata": {OWNER: {"full_name": "New"}}},
        headers=HEADERS,
    )

    assert edited.status_code == 200, edited.text
    [event] = await ScoreMetadataEvent.filter(score_id=score_id)
    assert event.old_paper_metadata == event.new_paper_metadata == paper
    assert event.new_authors_metadata == {OWNER: {"full_name": "New"}}


async def test_two_spellings_of_one_author_name_both_in_the_422(client: AsyncClient) -> None:
    second = "Alice@Example.TEST"

    response = await client.post(
        "/v1/scores",
        json=_payload(authors=[OWNER], authors_metadata={OWNER: {}, second: {}}),
        headers=HEADERS,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["loc"] == ["body", "authors_metadata", second]
    assert detail[0]["input"] == [OWNER, second]


@pytest.mark.parametrize("schema", ["ScoreSubmission", "ScoreMetadataPatch", "ScoreSchema"])
@pytest.mark.parametrize("field", ["authors_metadata", "paper_metadata"])
async def test_the_openapi_document_describes_both_objects(schema: str, field: str) -> None:
    app = create_app(
        Settings.model_validate({"database_url": "sqlite://:memory:", "cors_origins": []})
    )
    schemas = app.openapi()["components"]["schemas"]
    # A response model can appear twice in the document (input and output variants).
    names = [name for name in schemas if name.partition("-")[0] == schema]

    assert names, schema
    for name in names:
        description = schemas[name]["properties"][field].get("description")
        assert isinstance(description, str) and description.strip(), (name, field)

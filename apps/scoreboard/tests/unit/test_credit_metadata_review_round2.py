"""Review round 2 on author and paper metadata (PR 1440).

FEATURE: a public write path must not answer a small request with a huge one, must store at most
a bounded object, must not log a change when an identical number comes back from PostgreSQL in a
different Python type, and the spec history read loads only the columns it serves.

Every check compares parsed JSON, byte lengths, list lengths or model fields.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scoreboard.config import Settings
from scoreboard.main import create_app
from scoreboard.routes.leaderboard import _history_submission
from scoreboard.scores.credit_metadata import METADATA_MAX_BYTES, stored_size
from scoreboard.scores.models import Benchmark, Score, ScoreMetadataEvent
from scoreboard.scores.schemas import SpecHistoryRow
from scoreboard.scores.store import ScoreStore, _metadata_equal, _score_to_schema

pytestmark = pytest.mark.asyncio

OWNER = "alice@example.test"
HEADERS = {"X-User-Email": OWNER, "Content-Type": "application/json"}
ASTRAL = "\U0001f600"


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
    # ASCII-escaped JSON, the way a client sends any text (see the round 1 tests for why).
    return await client.request(method, url, content=json.dumps(body), headers=HEADERS)


def _detail(response: Any) -> list[dict[str, Any]]:
    return response.json()["detail"]


# --- 1. a small request cannot buy a huge 422 -----------------------------------------------------

LONG_AUTHOR = "k" * 100_000 + "@x.org"
AMPLIFIERS = [
    pytest.param(
        {"authors_metadata": {LONG_AUTHOR: {f"k{i}": None for i in range(300)}}},
        id="100k-author-key-300-bad-inner-keys",
    ),
    pytest.param(
        {"authors_metadata": {f"a{i}{'x' * 200}@x.org": {"full_name": None} for i in range(40)}},
        id="40-authors",
    ),
    pytest.param(
        {"paper_metadata": {f"{i:03d}" + "k" * 61: None for i in range(300)}},
        id="300-bad-paper-keys",
    ),
    pytest.param(
        {"authors_metadata": {OWNER: {f"{i:03d}" + "k" * 61: None for i in range(300)}}},
        id="300-bad-inner-keys",
    ),
]


@pytest.mark.parametrize("body", AMPLIFIERS)
async def test_the_422_stays_small_next_to_the_request(
    client: AsyncClient, body: dict[str, Any]
) -> None:
    request = json.dumps(_payload(**body)).encode()

    response = await _send(client, "POST", "/v1/scores", _payload(**body))

    assert response.status_code == 422
    # One entry for the object, however many keys it holds.
    assert len(_detail(response)) == 1
    assert len(response.content) <= 3 * len(request) + 2048
    assert await Score.all().count() == 0


async def test_more_authors_than_the_credit_cap_is_one_problem(client: AsyncClient) -> None:
    body = {f"a{i}@x.org": {} for i in range(11)}

    response = await _send(client, "POST", "/v1/scores", _payload(authors_metadata=body))

    assert [entry["loc"] for entry in _detail(response)] == [["body", "authors_metadata"]]


async def test_an_author_key_longer_than_an_email_may_be_is_one_problem(
    client: AsyncClient,
) -> None:
    key = "k" * 300 + "@x.org"

    response = await _send(client, "POST", "/v1/scores", _payload(authors_metadata={key: {}}))

    assert [entry["loc"] for entry in _detail(response)] == [["body", "authors_metadata", key]]


async def test_messages_do_not_repeat_the_location(client: AsyncClient) -> None:
    response = await _send(
        client,
        "POST",
        "/v1/scores",
        _payload(authors=[OWNER], authors_metadata={OWNER: {"full_name": 5}}),
    )

    [entry] = _detail(response)
    assert entry["loc"] == ["body", "authors_metadata", OWNER, "full_name"]
    assert entry["msg"] == "must be a string"


# --- the 64 KiB cap per object ------------------------------------------------------------------


async def test_the_size_is_measured_as_stored() -> None:
    # Compact, ASCII-escaped JSON, as Tortoise writes the column: a four-byte character counts as
    # its twelve-byte surrogate-pair escape, a control character as its six-byte escape.
    assert stored_size({"t": "abc"}) == len('{"t":"abc"}')
    assert stored_size({"t": ASTRAL}) == len('{"t":""}') + 12
    assert stored_size({"t": "\x01"}) == len('{"t":"\\u0001"}')


AUTHORS = [f"a{i}@x.org" for i in range(10)]


def _authors_of_size(size: int) -> dict[str, dict[str, str]]:
    """`authors_metadata` of exactly ``size`` stored bytes, every bound respected."""
    body: dict[str, dict[str, str]] = {author: {} for author in AUTHORS}
    slots = [(author, f"k{index:02d}") for author in AUTHORS for index in range(20)]
    for author, key in slots:
        if stored_size(body) >= size:
            break
        body[author][key] = ""
        body[author][key] = "v" * min(500, size - stored_size(body))
    # The last key's framing can overshoot; give the bytes back from the last full value.
    excess = stored_size(body) - size
    author, key = next((a, k) for a, k in reversed(slots) if len(body[a].get(k, "")) > excess)
    body[author][key] = body[author][key][: len(body[author][key]) - excess]
    assert stored_size(body) == size
    return body


@pytest.mark.parametrize(
    ("size", "status"), [(METADATA_MAX_BYTES, 201), (METADATA_MAX_BYTES + 1, 422)]
)
@pytest.mark.parametrize("method", ["submit", "resubmit", "patch"])
async def test_the_cap_is_inclusive_on_every_write_path(
    client: AsyncClient, size: int, status: int, method: str
) -> None:
    body = _authors_of_size(size)
    fields = {"authors": AUTHORS, "authors_metadata": body}
    if method == "submit":
        response = await _send(client, "POST", "/v1/scores", _payload(**fields))
        expected = status
    else:
        created = await _send(client, "POST", "/v1/scores", _payload(authors=AUTHORS))
        score_id = created.json()["id"]
        if method == "patch":
            response = await _send(client, "PATCH", f"/v1/scores/{score_id}", fields)
        else:
            response = await _send(client, "POST", "/v1/scores", _payload(**fields))
        expected = 200 if status == 201 else 422

    assert response.status_code == expected, response.text[:300]
    if expected == 422:
        assert [entry["loc"] for entry in _detail(response)] == [["body", "authors_metadata"]]
        assert await ScoreMetadataEvent.all().count() == 0


def _paper_just_over_with_url() -> dict[str, Any]:
    # Control characters store as six-byte escapes, so a paper object within every per-key bound
    # can pass the cap; the url decides which side of it the object falls.
    paper: dict[str, Any] = {
        "url": "https://example.org/" + "u" * 2000,
        "title": "\x01" * 300,
        "citation": "\x01" * 2000,
    }
    for index in range(17):
        paper[f"k{index:02d}"] = "\x01" * 500
    while stored_size(paper) > METADATA_MAX_BYTES + 1000:
        paper["k16"] = paper["k16"][:-1]
    return paper


async def test_the_url_counts_toward_the_paper_cap(client: AsyncClient) -> None:
    paper = _paper_just_over_with_url()
    without_url = {key: value for key, value in paper.items() if key != "url"}
    assert stored_size(paper) > METADATA_MAX_BYTES >= stored_size(without_url)

    over = await _send(client, "POST", "/v1/scores", _payload(paper_metadata=paper))
    under = await _send(client, "POST", "/v1/scores", _payload(paper_metadata=without_url))

    assert [entry["loc"] for entry in _detail(over)] == [["body", "paper_metadata"]]
    assert under.status_code == 201, under.text[:300]


async def test_the_reviewers_1_4_mb_case_is_refused(client: AsyncClient) -> None:
    # From the round 2 review: every bound at its limit, in four-byte characters.
    authors = [f"a{i}@x.org" for i in range(10)]

    def entry() -> dict[str, Any]:
        values: dict[str, Any] = {"full_name": ASTRAL * 200, "institution": ASTRAL * 200}
        for k in range(18):
            values[f"{k:02d}" + ASTRAL * 62] = ASTRAL * 500
        return values

    paper: dict[str, Any] = {"title": ASTRAL * 300, "citation": ASTRAL * 2000}
    for k in range(18):
        paper[f"{k:02d}" + ASTRAL * 62] = ASTRAL * 500
    body = _payload(
        authors=authors, authors_metadata={a: entry() for a in authors}, paper_metadata=paper
    )
    assert stored_size(body["authors_metadata"]) > 1_000_000

    response = await _send(client, "POST", "/v1/scores", body)

    assert response.status_code == 422
    assert sorted(entry["loc"] for entry in _detail(response)) == [
        ["body", "authors_metadata"],
        ["body", "paper_metadata"],
    ]


# --- 2. the history read loads only what it serves ----------------------------------------------


async def test_history_rows_carry_only_the_history_columns(client: AsyncClient) -> None:
    await _send(
        client,
        "POST",
        "/v1/scores",
        _payload(
            authors=[OWNER, "bob@lab.org"],
            authors_metadata={OWNER: {"full_name": "Alice"}},
            paper_metadata={"title": "T"},
            run_cost_usd="1.250000",
        ),
    )

    [row] = await ScoreStore().list_for_spec("hle", "spec-1")

    assert isinstance(row, SpecHistoryRow)
    assert set(type(row).model_fields) == {
        "id",
        "spec_id",
        "benchmark_revision",
        "score",
        "total_questions",
        "correct_questions",
        "submitted_at",
        "submitted_by",
        "authors",
        "verified_by_screamingface",
        "run_cost_usd",
        "run_cost_status",
        "cache_saved_cost_usd",
        "cache_saved_cost_archive_usd",
    }


async def test_the_history_response_is_unchanged(client: AsyncClient) -> None:
    created = await _send(
        client,
        "POST",
        "/v1/scores",
        _payload(
            authors=[OWNER, "bob@lab.org"],
            authors_metadata={OWNER: {"full_name": "Alice"}},
            run_cost_usd="1.250000",
            cache_saved_cost_usd="0.500000",
            correct_questions=3,
        ),
    )
    legacy = await _send(client, "POST", "/v1/scores", _payload(score=0.5))
    stored = await Score.get(id=created.json()["id"])
    await Score.filter(id=legacy.json()["id"]).update(authors=None)

    response = await client.get("/v1/leaderboard/hle/spec-1/history")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"spec_id", "benchmark_id", "submissions"}
    # The history as the full-row path built it before the narrow read: a ScoreSchema from the
    # whole stored row, mapped by the route's own `_history_submission`.
    rows = await Score.filter(spec_id="spec-1").order_by("-submitted_at")
    expected = [_history_submission(_score_to_schema(row)).model_dump(mode="json") for row in rows]
    assert body["submissions"] == expected
    by_id = {row["id"]: row for row in body["submissions"]}
    assert by_id[str(stored.id)]["authors"] == ["alice", "bob"]
    assert by_id[str(stored.id)]["run_cost_usd"] == "1.750000"
    # A row with NULL authors still reads its submitter as the credit line.
    assert by_id[legacy.json()["id"]]["authors"] == ["alice"]


# --- 3. numbers that come back from PostgreSQL in another type ------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (1e23, 10**23),
        (1.5e300, int(Decimal("1.5e300"))),
        (1e20, 10**20),
        (0.1, 0.1),
        (1, 1.0),
        (-0.0, 0),
        (2**70, 2**70),
        ({"x": 1e23}, {"x": 10**23}),
    ],
)
async def test_equal_numbers_compare_equal_across_types(left: Any, right: Any) -> None:
    assert _metadata_equal(left, right)
    assert _metadata_equal(right, left)


@pytest.mark.parametrize(
    ("left", "right"),
    [(True, 1), (False, 0), (1e23, 10**23 + 1), (0.1, 0.2), ({"x": True}, {"x": 1}), ("1", 1)],
)
async def test_different_values_stay_different(left: Any, right: Any) -> None:
    assert not _metadata_equal(left, right)
    assert not _metadata_equal(right, left)


# --- 4. the claim refusal does not presume another owner ------------------------------------------


async def test_the_claim_message_is_neutral(client: AsyncClient) -> None:
    copy = "0192a1b2-c3d4-4e5f-8a9b-0c1d2e3f4a5b"
    captured = {"capture_status": "complete", "frozen_copy_id": copy}
    await _send(client, "POST", "/v1/scores", _payload(**captured))

    second = await _send(client, "POST", "/v1/scores", _payload(spec_id="spec-2", **captured))

    assert second.status_code == 422
    assert second.json()["detail"] == {
        "code": "frozen_copy_claimed",
        "message": "a score already names this frozen_copy_id",
    }
    assert await ScoreMetadataEvent.all().count() == 0

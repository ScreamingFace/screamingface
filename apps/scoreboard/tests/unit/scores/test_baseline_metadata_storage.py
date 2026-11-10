from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from scoreboard.config import Settings
from scoreboard.import_baselines import load_baselines_json
from scoreboard.main import create_app
from scoreboard.scores.baseline_store import BaselineStore
from scoreboard.scores.models import Baseline
from tests.unit.scores.test_baseline_comparison import BOARD, _board, _review, _row


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["before\x00after", "before\ud800after", "before\udfffafter"])
@pytest.mark.parametrize("location", ["prompt_note", "nested_value", "nested_key"])
async def test_unstorable_metadata_is_rejected_before_any_batch_write(
    tortoise_db: None, monkeypatch: pytest.MonkeyPatch, text: str, location: str
) -> None:
    await _board()
    valid = _row().model_dump(mode="json")
    metadata: dict = {"comparison": _review()}
    if location == "prompt_note":
        metadata["comparison"]["prompt_note"] = text
    elif location == "nested_value":
        metadata["extra"] = {"notes": [text]}
    else:
        metadata["extra"] = {text: "note"}
    upsert = AsyncMock(wraps=Baseline.update_or_create)
    monkeypatch.setattr(Baseline, "update_or_create", upsert)
    raw = json.dumps([valid, {**valid, "model_name": "Invalid", "metadata": metadata}])
    with pytest.raises(ValueError):
        rows = load_baselines_json(raw)
        await BaselineStore().import_many(rows)
    upsert.assert_not_awaited()
    assert await Baseline.all().count() == 0


@pytest.mark.parametrize("text", ["different\x00prompt", "different\ud800prompt"])
def test_direct_import_schema_rejects_unstorable_comparison_note(text: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _row(metadata={"comparison": _review(prompt_note=text)})
    assert caught.value.errors()[0]["loc"] == ("metadata",)


@pytest.mark.asyncio
async def test_valid_unicode_and_multiline_notes_round_trip(tortoise_db: None) -> None:
    await _board()
    metadata = {
        "comparison": _review(prompt_note="Instructions différentes.\n中文 🙂"),
        "extra": {"citation": ["Première ligne\nDeuxième ligne"]},
    }
    imported = await BaselineStore().import_baseline(_row(metadata=metadata))
    [stored] = await BaselineStore().list_baselines(BOARD)
    assert stored.id == imported.id
    assert stored.metadata == metadata
    assert stored.ranking_eligible is True


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_corrupt_legacy_metadata_cannot_break_the_read_api(
    tortoise_db: None, visibility: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _board(visibility=visibility)
    good = await BaselineStore().import_baseline(_row())
    bad = await Baseline.get(id=good.id)
    bad.metadata = {"comparison": _review(prompt_note="different\ud800prompt")}
    # WHY: simulate a legacy SQLite row on either backend; PostgreSQL correctly
    # refuses creating this data, but the shared read contract must reject it too.
    rows = [bad, await Baseline.get(id=good.id)]
    query = SimpleNamespace(order_by=AsyncMock(return_value=rows))
    monkeypatch.setattr(Baseline, "filter", lambda **kwargs: query)
    app = create_app(Settings(database_url="sqlite://:memory:", cors_origins=[]))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/leaderboard/{BOARD}")
    assert response.status_code == 200
    assert [row["metadata"] for row in response.json()["baselines"]] == [good.metadata]

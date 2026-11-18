"""OME-1955 — the discovered OpenRouter models, newest first.

FEATURE: the live listing sorts the discovered rows by the release date
(`created`) of each catalogue row, newest first. Operator entries stay first.

INVARIANT: with no dates the discovered order is the alphabetical order of today.
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.model_capabilities import model_row
from aigateway.core.parameter_discovery import RawResponse
from aigateway.plugins.openrouter_provider.live_models import (
    LIVE_MODELS_URL,
    fetch_live_model_catalog,
    live_listing_entries,
    parse_page_created,
)
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin
from aigateway.plugins.openrouter_provider.settings import OpenRouterPluginSettings


def _row(model_id: str, created: int | None = None) -> dict:
    row: dict[str, object] = {"id": model_id}
    if created is not None:
        row["created"] = created
    return row


def _page(
    rows: list[dict], *, next_url: str | None = None, total: int | None = None
) -> RawResponse:
    payload = {
        "data": rows,
        "links": {"next": next_url},
        "total_count": len(rows) if total is None else total,
    }
    return RawResponse(status=200, content_type="application/json", body=json.dumps(payload))


class _RoutingClient:
    def __init__(self, responses: dict[str, RawResponse]) -> None:
        self._responses = responses
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        return self._responses[url]


# ---------------------------------------------------------------- the date evidence


def test_parse_page_created_keeps_only_positive_integers() -> None:
    payload = {
        "data": [
            {"id": "a/good", "created": 1_700_000_000},
            {"id": "b/zero", "created": 0},
            {"id": "c/negative", "created": -5},
            {"id": "d/text", "created": "1700000000"},
            {"id": "e/bool", "created": True},
            {"id": "f/none", "created": None},
            {"id": "g/missing"},
            "not a row",
        ],
        "links": {"next": None},
        "total_count": 8,
    }
    assert parse_page_created(payload) == {"a/good": 1_700_000_000}


@pytest.mark.parametrize("payload", [None, [], {"data": "x"}, {"data": [{"id": 3, "created": 5}]}])
def test_parse_page_created_tolerates_a_non_envelope(payload: object) -> None:
    assert parse_page_created(payload) == {}


@pytest.mark.asyncio
async def test_fetch_catalog_collects_created_across_pages() -> None:
    second = "/api/v1/models?output_modalities=text&limit=250&offset=250"
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page([_row("a/old", 100)], next_url=second, total=2),
            f"{LIVE_MODELS_URL}&offset=250": _page([_row("b/new", 200)], total=2),
        }
    )
    catalog = await fetch_live_model_catalog(client=client)
    assert catalog.created == {"a/old": 100, "b/new": 200}


# ---------------------------------------------------------------- the listing order


def test_listing_orders_discovered_ids_newest_first() -> None:
    entries = live_listing_entries(
        OpenRouterPluginSettings(enabled=True),
        ("a/old", "b/new", "c/middle"),
        created={"a/old": 100, "b/new": 300, "c/middle": 200},
    )
    assert [entry.model_name for entry in entries] == [
        "openrouter/b/new",
        "openrouter/c/middle",
        "openrouter/a/old",
    ]


def test_listing_puts_same_date_ids_in_id_order() -> None:
    entries = live_listing_entries(
        OpenRouterPluginSettings(enabled=True),
        ("c/z", "a/x", "b/y"),
        created={"c/z": 50, "a/x": 50, "b/y": 50},
    )
    assert [entry.model_name for entry in entries] == [
        "openrouter/a/x",
        "openrouter/b/y",
        "openrouter/c/z",
    ]


def test_listing_puts_undated_ids_after_dated_ids() -> None:
    entries = live_listing_entries(
        OpenRouterPluginSettings(enabled=True),
        ("a/undated", "b/dated"),
        created={"b/dated": 10},
    )
    assert [entry.model_name for entry in entries] == [
        "openrouter/b/dated",
        "openrouter/a/undated",
    ]


def test_listing_without_dates_keeps_alphabetical_order() -> None:
    # WHY: the ids arrive out of order, so only the id part of the sort key gives this result.
    entries = live_listing_entries(OpenRouterPluginSettings(enabled=True), ("c/z", "a/x", "b/y"))
    assert [entry.model_name for entry in entries] == [
        "openrouter/a/x",
        "openrouter/b/y",
        "openrouter/c/z",
    ]


def test_listing_keeps_operator_entries_first_in_configured_order() -> None:
    settings = OpenRouterPluginSettings(
        enabled=True, default_models=["openrouter/z/op", "openrouter/a/op"]
    )
    # WHY: the newer id is last in id order, so only the dates give this result.
    entries = live_listing_entries(settings, ("a/old", "z/new"), created={"a/old": 1, "z/new": 900})
    assert [entry.model_name for entry in entries] == [
        "openrouter/z/op",
        "openrouter/a/op",
        "openrouter/z/new",
        "openrouter/a/old",
    ]


@pytest.mark.asyncio
async def test_discover_live_models_lists_newest_first() -> None:
    plugin = OpenRouterProviderPlugin(OpenRouterPluginSettings(enabled=True, live_models=True))
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page(
                [
                    _row("a/old", 100),
                    _row("b/new", 300),
                    _row("c/undated"),
                    {"id": "d/bad", "created": "bad"},
                ]
            )
        }
    )
    entries = await plugin.discover_live_models(client=client)
    assert entries is not None
    assert [model_row(plugin, entry)["id"] for entry in entries] == [
        "openrouter/b/new",
        "openrouter/a/old",
        "openrouter/c/undated",
        "openrouter/d/bad",
    ]


def test_dates_change_the_order_and_not_the_row_content() -> None:
    settings = OpenRouterPluginSettings(enabled=True)
    plugin = OpenRouterProviderPlugin(settings)
    ids = ("a/old", "z/new")

    def rows(entries: tuple) -> list[dict]:
        return sorted((model_row(plugin, entry) for entry in entries), key=lambda row: row["id"])

    dated = live_listing_entries(settings, ids, created={"a/old": 1, "z/new": 900})
    assert rows(dated) == rows(live_listing_entries(settings, ids))

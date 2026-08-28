"""OME-972 U2 — the paginated catalog fetch and its complete failure surface.

INVARIANT (all-or-nothing): ``fetch_live_model_ids`` either walks the WHOLE
``links.next`` chain under one aggregate deadline and returns every raw id, or
raises a sanitized ``DiscoveryError`` — a mid-chain failure never yields the
pages already collected, and an off-policy next link is refused BEFORE it is
ever dialed.
"""

from __future__ import annotations

import json

import pytest

from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
from aigateway.plugins.openrouter_provider import live_models
from aigateway.plugins.openrouter_provider.live_models import (
    LIVE_MODELS_URL,
    fetch_live_model_ids,
)

_BASE = "https://openrouter.ai/api/v1/models?output_modalities=text&limit=250"


def _paged_url(offset: int) -> str:
    return f"{_BASE}&offset={offset}"


def _next_link(offset: int) -> str:
    return f"/api/v1/models?output_modalities=text&limit=250&offset={offset}"


def _page(ids: list[str], *, next_url: str | None = None, total: int | None = None) -> RawResponse:
    """A STRICT well-formed page: both completeness fields always present.

    Mirrors the live envelope (probed 2026-08-24): ``{data, links, total_count}``
    on every page, with ``links.next = null`` marking the last one.
    """
    payload: dict[str, object] = {
        "data": [{"id": i} for i in ids],
        "links": {"next": next_url},
        "total_count": len(ids) if total is None else total,
    }
    return RawResponse(status=200, content_type="application/json", body=json.dumps(payload))


def _raw_page(payload: object) -> RawResponse:
    return RawResponse(status=200, content_type="application/json", body=json.dumps(payload))


class _RoutingClient:
    """Canned catalog server: one response per exact URL, every dial recorded."""

    def __init__(self, responses: dict[str, RawResponse]) -> None:
        self._responses = responses
        self.dialed: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.dialed.append(url)
        response = self._responses.get(url)
        if response is None:  # pragma: no cover - test authoring error, not behavior
            raise AssertionError(f"unexpected dial: {url}")
        return response


# ------------------------------------------------------------------ happy paths


@pytest.mark.asyncio
async def test_single_page_returns_raw_ids_and_dials_the_pinned_url_once() -> None:
    client = _RoutingClient({LIVE_MODELS_URL: _page(["b/y", "a/x", "a/x:free"])})
    ids = await fetch_live_model_ids(client=client)
    # WHY raw: publishability (colon filter, dedupe, sort, caps) is applied by
    # the CALLER — the fetch owns completeness of the chain, nothing else.
    assert ids == ("b/y", "a/x", "a/x:free")
    assert client.dialed == [LIVE_MODELS_URL]


@pytest.mark.asyncio
async def test_multi_page_chain_concatenates_in_order_with_validated_offsets() -> None:
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page(["a/1"], next_url=_next_link(250), total=3),
            _paged_url(250): _page(["b/2"], next_url=_next_link(500), total=3),
            _paged_url(500): _page(["c/3"], total=3),
        }
    )
    ids = await fetch_live_model_ids(client=client)
    assert ids == ("a/1", "b/2", "c/3")
    assert client.dialed == [LIVE_MODELS_URL, _paged_url(250), _paged_url(500)]


@pytest.mark.asyncio
async def test_matching_total_count_reconciles_clean() -> None:
    client = _RoutingClient({LIVE_MODELS_URL: _page(["a/1", "b/2"], total=2)})
    assert await fetch_live_model_ids(client=client) == ("a/1", "b/2")


# ------------------------------------------------------------- failure surface


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500])
async def test_upstream_error_status_propagates_with_the_status_class(status: int) -> None:
    client = _RoutingClient(
        {LIVE_MODELS_URL: RawResponse(status=status, content_type="application/json", body="{}")}
    )
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    # INVARIANT: reason stays the closed vocabulary token; the integer status
    # rides along so operators can tell auth onset (401) from outage (5xx)
    # in logs without any body content leaking.
    assert exc.value.reason == "bad_status"
    assert exc.value.status == status


@pytest.mark.asyncio
async def test_mid_chain_failure_discards_pages_already_collected() -> None:
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page(["a/1"], next_url=_next_link(250)),
            _paged_url(250): RawResponse(status=500, content_type="application/json", body=""),
        }
    )
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "bad_status"


@pytest.mark.asyncio
async def test_off_policy_next_fails_before_the_foreign_url_is_dialed() -> None:
    foreign = "https://evil.example/api/v1/models?output_modalities=text&limit=250&offset=250"
    client = _RoutingClient({LIVE_MODELS_URL: _page(["a/1"], next_url=foreign)})
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "model_catalog_truncated"
    # INVARIANT: validation happens BEFORE the dial — the foreign origin never
    # sees a connection attempt.
    assert client.dialed == [LIVE_MODELS_URL]


@pytest.mark.asyncio
async def test_unexpected_offset_in_next_fails_the_refresh() -> None:
    client = _RoutingClient({LIVE_MODELS_URL: _page(["a/1"], next_url=_next_link(500))})
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "model_catalog_truncated"
    assert client.dialed == [LIVE_MODELS_URL]


@pytest.mark.asyncio
async def test_total_count_mismatch_after_final_page_is_truncation() -> None:
    # WHY: next == null with fewer rows than the catalog claims means a page
    # silently went missing — treat exactly like a broken chain.
    client = _RoutingClient({LIVE_MODELS_URL: _page(["a/1", "b/2"], total=412)})
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "model_catalog_truncated"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"data": "nope", "links": {"next": None}, "total_count": 0},
        # Missing completeness metadata: indistinguishable from a truncated read.
        {"data": [{"id": "a/1"}]},
        {"data": [{"id": "a/1"}], "total_count": 1},
        {"data": [{"id": "a/1"}], "links": {"next": None}},
        # One malformed row poisons the page — never salvage the rest.
        {"data": [{"id": "a/1"}, {"name": "drifted"}], "links": {"next": None}, "total_count": 2},
    ],
    ids=["data-not-a-list", "no-metadata", "no-links", "no-total-count", "one-malformed-row"],
)
async def test_malformed_or_incomplete_page_fails_the_whole_refresh(payload: object) -> None:
    client = _RoutingClient({LIVE_MODELS_URL: _raw_page(payload)})
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "malformed_json"


@pytest.mark.asyncio
async def test_one_malformed_row_on_a_later_page_discards_the_whole_chain() -> None:
    # INVARIANT: all-or-nothing across the CHAIN too — page 1's good rows are
    # never returned because page 2 drifted.
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page(["a/1"], next_url=_next_link(250), total=2),
            _paged_url(250): _raw_page(
                {"data": [{"id": 7}], "links": {"next": None}, "total_count": 2}
            ),
        }
    )
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "malformed_json"


@pytest.mark.asyncio
async def test_total_count_disagreeing_between_pages_is_truncation() -> None:
    # WHY: the census must be stable for the whole walk. A shifting total means
    # the catalog changed under us (or a page answers a different query) —
    # either way the collected rows are not a complete snapshot.
    client = _RoutingClient(
        {
            LIVE_MODELS_URL: _page(["a/1"], next_url=_next_link(250), total=2),
            _paged_url(250): _page(["b/2"], total=9),
        }
    )
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "model_catalog_truncated"


@pytest.mark.asyncio
async def test_oversized_page_body_fails_the_refresh() -> None:
    huge = json.dumps({"data": [{"id": "a/" + "x" * 2_000_000}]})
    client = _RoutingClient(
        {LIVE_MODELS_URL: RawResponse(status=200, content_type="application/json", body=huge)}
    )
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "oversized"


@pytest.mark.asyncio
async def test_chain_longer_than_max_pages_is_truncation_not_a_bigger_read() -> None:
    responses = {LIVE_MODELS_URL: _page(["v/m-0"], next_url=_next_link(250))}
    for page in range(1, live_models._MAX_PAGES + 1):
        responses[_paged_url(page * 250)] = _page(
            [f"v/m-{page}"], next_url=_next_link((page + 1) * 250)
        )
    client = _RoutingClient(responses)
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "model_catalog_truncated"
    # WHY: the cap refuses BEFORE dialing page _MAX_PAGES+1.
    assert len(client.dialed) == live_models._MAX_PAGES


@pytest.mark.asyncio
async def test_raw_ids_over_the_catalog_bound_fail_as_too_large() -> None:
    # A single page that lies about its limit and floods rows past the
    # 10_000-model catalog bound is refused as soon as the bound is crossed.
    flood = [f"v/m-{i}" for i in range(10_001)]
    client = _RoutingClient({LIVE_MODELS_URL: _page(flood)})
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=client)
    assert exc.value.reason == "model_catalog_too_large"


@pytest.mark.asyncio
async def test_aggregate_deadline_bounds_the_whole_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    class _StallingClient:
        async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
            await asyncio.sleep(0.5)
            return _page(["a/1"])

    # INVARIANT: one wall-clock deadline covers the WHOLE pagination chain —
    # concurrent listers queue on this single flight, so a dribbling upstream
    # must not hold every caller for pages x per-page-timeout.
    monkeypatch.setattr(live_models, "_AGGREGATE_TIMEOUT_S", 0.05)
    with pytest.raises(DiscoveryError) as exc:
        await fetch_live_model_ids(client=_StallingClient())
    assert exc.value.reason == "timeout"

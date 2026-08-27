"""OME-1026 U4 (plan D5/D6/D10): the bounded Anthropic cursor walk.

FEATURE: opt-in live Anthropic model discovery — stitch every catalog page into ONE
all-or-nothing snapshot, or fail with a sanitized reason and change nothing.

INVARIANT (completeness without a census): the envelope has no ``total_count``, so
"complete" means the walk TERMINATED on ``has_more=false`` with monotone cursor progress
under every cap. There is nothing to reconcile a count against, so every guard is a walk
guard: cursor-progress, page cap, model cap, aggregate deadline.

INVARIANT (credential hygiene): EVERY dial carries exactly ``x-api-key`` and
``anthropic-version``, only to the allowlisted Anthropic origin, and no failure surface ever
carries the key. The canned client asserts both on every dial and raises AssertionError for an
unexpected URL, so a stray or credential-less dial fails LOUDLY instead of degrading quietly
into a seeds listing.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import SecretStr

from aigateway.core.parameter_discovery import DiscoveryError, DiscoveryLimits, RawResponse
from aigateway.plugins.anthropic_provider import live_models
from aigateway.plugins.anthropic_provider.live_models import (
    MODELS_LIST_URL,
    fetch_live_model_ids,
)

_FAKE_KEY = "sk-ant-fixture-not-a-real-key"
_API_VERSION = "2023-06-01"
_FIRST = f"{MODELS_LIST_URL}?limit=1000"


def _after(cursor: str) -> str:
    return f"{MODELS_LIST_URL}?limit=1000&after_id={cursor}"


def _body(rows: list[dict[str, Any]], *, has_more: bool = False, last_id: str | None = None) -> str:
    payload: dict[str, Any] = {"data": rows, "has_more": has_more}
    if last_id is not None:
        payload["last_id"] = last_id
    return json.dumps(payload)


def _rows(*ids: str) -> list[dict[str, Any]]:
    return [{"id": model_id, "type": "model"} for model_id in ids]


def _ok(body: str) -> RawResponse:
    return RawResponse(status=200, content_type="application/json", body=body)


class _CatalogClient:
    """Serves canned pages keyed by EXACT url; anything else is a loud failure.

    # WHY AssertionError and not a soft error (OME-972 correction-pass rule): a canned
    # client that returned "nothing" for an unexpected URL would let a future off-policy
    # dial launder itself into a silent seed fallback with the suite still green.
    """

    def __init__(self, pages: dict[str, RawResponse], *, delay_s: float = 0.0) -> None:
        self._pages = pages
        self._delay_s = delay_s
        self.dialed: list[str] = []
        self.headers_seen: list[dict[str, str]] = []

    async def get(
        self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None
    ) -> RawResponse:
        self.dialed.append(url)
        assert headers is not None, f"credential-less catalog dial to {url}"
        assert headers["x-api-key"] == _FAKE_KEY, "the discovery key must ride every dial"
        assert headers["anthropic-version"] == _API_VERSION
        self.headers_seen.append(dict(headers))
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if url not in self._pages:
            raise AssertionError(f"unexpected dial: {url}")
        return self._pages[url]


async def _fetch(client: Any, *, limits: DiscoveryLimits | None = None) -> tuple[str, ...]:
    return await fetch_live_model_ids(
        client=client,
        limits=limits,
        api_key=SecretStr(_FAKE_KEY),
        api_version=_API_VERSION,
    )


@pytest.mark.asyncio
async def test_a_single_page_catalog_is_returned_in_upstream_order() -> None:
    client = _CatalogClient({_FIRST: _ok(_body(_rows("claude-opus-5", "claude-sonnet-5")))})

    assert await _fetch(client) == ("claude-opus-5", "claude-sonnet-5")
    # The pinned first-page query: nothing but the page size.
    assert client.dialed == [_FIRST]


@pytest.mark.asyncio
async def test_every_dial_carries_the_credential_headers() -> None:
    client = _CatalogClient(
        {
            _FIRST: _ok(_body(_rows("claude-opus-5"), has_more=True, last_id="claude-opus-5")),
            _after("claude-opus-5"): _ok(_body(_rows("claude-sonnet-5"))),
        }
    )

    await _fetch(client)

    assert len(client.headers_seen) == 2
    for sent in client.headers_seen:
        assert sent == {"x-api-key": _FAKE_KEY, "anthropic-version": _API_VERSION}


@pytest.mark.asyncio
async def test_multiple_pages_are_stitched_in_upstream_order() -> None:
    client = _CatalogClient(
        {
            _FIRST: _ok(
                _body(
                    _rows("claude-opus-5", "claude-opus-4-8"),
                    has_more=True,
                    last_id="claude-opus-4-8",
                )
            ),
            _after("claude-opus-4-8"): _ok(
                _body(_rows("claude-sonnet-5"), has_more=True, last_id="claude-sonnet-5")
            ),
            _after("claude-sonnet-5"): _ok(_body(_rows("claude-haiku-4-5"))),
        }
    )

    assert await _fetch(client) == (
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5",
    )
    assert client.dialed == [_FIRST, _after("claude-opus-4-8"), _after("claude-sonnet-5")]


@pytest.mark.asyncio
async def test_duplicate_ids_preserve_first_occurrence_and_upstream_order() -> None:
    """D7: aliases and date-stamped snapshots stay UNFOLDED, unsorted, first-occurrence.

    # WHY pinned this precisely: the owner-approved MVP publishes both forms as separate
    # dispatchable ids. Sorting would reorder them away from Anthropic's newest-first
    # order, and folding would require an alias-to-snapshot relation Anthropic does not
    # publish — so this test forbids a future "tidy-up" from inventing either.
    """
    client = _CatalogClient(
        {_FIRST: _ok(_body(_rows("claude-x-5", "claude-x-5-20260101", "claude-x-5")))}
    )

    assert await _fetch(client) == ("claude-x-5", "claude-x-5-20260101")


@pytest.mark.asyncio
async def test_a_non_model_row_is_excluded_end_to_end() -> None:
    rows = _rows("claude-opus-5") + [{"id": "some-family", "type": "model_family"}]
    client = _CatalogClient({_FIRST: _ok(_body(rows))})

    assert await _fetch(client) == ("claude-opus-5",)


# --------------------------------------------------------------------------------------
# Cursor safety and pagination bounds.
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_injection_shaped_cursor_fails_the_refresh_and_dials_nothing_further() -> None:
    """plan MAJOR-2: a hostile ``last_id`` never becomes request material."""
    client = _CatalogClient(
        {_FIRST: _ok(_body(_rows("claude-opus-5"), has_more=True, last_id="x&limit=9999"))}
    )

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "malformed_json"
    # INVARIANT: rejected BEFORE embedding — exactly one dial ever happened.
    assert client.dialed == [_FIRST]


@pytest.mark.asyncio
async def test_a_repeated_cursor_is_truncation_not_a_longer_walk() -> None:
    client = _CatalogClient(
        {
            _FIRST: _ok(_body(_rows("claude-opus-5"), has_more=True, last_id="stuck")),
            _after("stuck"): _ok(_body(_rows("claude-sonnet-5"), has_more=True, last_id="stuck")),
        }
    )

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "model_catalog_truncated"
    assert client.dialed == [_FIRST, _after("stuck")]


@pytest.mark.asyncio
async def test_a_period_two_cursor_cycle_is_caught_before_the_page_cap() -> None:
    """CC-12: tracking only the PREVIOUS cursor would let an a->b->a cycle spin to the cap."""
    client = _CatalogClient(
        {
            _FIRST: _ok(_body(_rows("m-1"), has_more=True, last_id="a")),
            _after("a"): _ok(_body(_rows("m-2"), has_more=True, last_id="b")),
            _after("b"): _ok(_body(_rows("m-3"), has_more=True, last_id="a")),
        }
    )

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "model_catalog_truncated"
    # Stopped on the repeat, well short of the page cap.
    assert client.dialed == [_FIRST, _after("a"), _after("b")]


@pytest.mark.asyncio
async def test_an_endless_chain_of_fresh_cursors_is_bounded_by_the_page_cap() -> None:
    pages = {_FIRST: _ok(_body(_rows("m-0"), has_more=True, last_id="c0"))}
    for index in range(50):
        pages[_after(f"c{index}")] = _ok(
            _body(_rows(f"m-{index + 1}"), has_more=True, last_id=f"c{index + 1}")
        )
    client = _CatalogClient(pages)

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "model_catalog_truncated"
    # INVARIANT: the cap refuses BEFORE dialing page N+1, so a runaway chain costs a
    # bounded number of dials — never an unbounded walk on the request path.
    assert len(client.dialed) == live_models._MAX_PAGES


@pytest.mark.asyncio
async def test_empty_pages_claiming_more_still_terminate(monkeypatch) -> None:
    """CC-11: an empty ``data`` with ``has_more=true`` walks on, bounded by the page cap."""
    pages = {_FIRST: _ok(_body([], has_more=True, last_id="c0"))}
    for index in range(live_models._MAX_PAGES + 2):
        pages[_after(f"c{index}")] = _ok(_body([], has_more=True, last_id=f"c{index + 1}"))
    client = _CatalogClient(pages)

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "model_catalog_truncated"
    assert len(client.dialed) == live_models._MAX_PAGES


# --------------------------------------------------------------------------------------
# Failure mapping (D10) — a degraded LISTING, never a broken chat.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
@pytest.mark.asyncio
async def test_an_upstream_error_status_maps_to_bad_status_with_the_exact_code(status: int) -> None:
    """CC-10: a revoked or throttled operator key degrades the listing, never dispatch."""
    client = _CatalogClient(
        {_FIRST: RawResponse(status=status, content_type="application/json", body="{}")}
    )

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "bad_status"
    assert exc.value.status == status
    # sanitized: no credential material rides out on the failure surface.
    assert _FAKE_KEY not in str(exc.value)


@pytest.mark.asyncio
async def test_a_transport_failure_surfaces_as_unreachable() -> None:
    class _DeadClient:
        async def get(self, url: str, *, timeout_s: float, max_bytes: int, headers: Any = None):
            raise DiscoveryError("unreachable")

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(_DeadClient())

    assert exc.value.reason == "unreachable"


@pytest.mark.asyncio
async def test_an_oversized_page_fails_the_refresh() -> None:
    client = _CatalogClient({_FIRST: _ok(_body(_rows(*[f"claude-{n}" for n in range(200)])))})

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client, limits=DiscoveryLimits(max_bytes=500))

    assert exc.value.reason == "oversized"


@pytest.mark.asyncio
async def test_too_many_models_fails_the_refresh(monkeypatch) -> None:
    # INVARIANT: over the cap fails CLOSED — never truncate-and-cache, which would publish
    # a listing that silently omits models.
    monkeypatch.setattr(live_models, "_MAX_CATALOG_MODELS", 2)
    client = _CatalogClient({_FIRST: _ok(_body(_rows("m-1", "m-2", "m-3")))})

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "model_catalog_too_large"


@pytest.mark.asyncio
async def test_the_aggregate_deadline_bounds_the_whole_walk(monkeypatch) -> None:
    # WHY an aggregate deadline on top of the per-page timeout: single-flight dedupes the
    # DIAL, not the wait, so every concurrent lister queues behind ONE walk — the whole
    # chain therefore needs one wall-clock bound, not just each page.
    monkeypatch.setattr(live_models, "_AGGREGATE_TIMEOUT_S", 0.01)
    client = _CatalogClient({_FIRST: _ok(_body(_rows("claude-opus-5")))}, delay_s=0.2)

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "timeout"


@pytest.mark.asyncio
async def test_an_empty_catalog_fails_rather_than_publishing_nothing() -> None:
    # INVARIANT: an empty catalog is indistinguishable from a broken read, so it must not
    # evict the last good snapshot by being cached as a fresh, legitimately-empty listing.
    client = _CatalogClient({_FIRST: _ok(_body([]))})

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "model_catalog_empty"


@pytest.mark.asyncio
async def test_the_walk_only_ever_dials_the_allowlisted_anthropic_origin() -> None:
    client = _CatalogClient({_FIRST: _ok(_body(_rows("claude-opus-5")))})

    await _fetch(client)

    for url in client.dialed:
        assert url.startswith("https://api.anthropic.com/v1/models?")


@pytest.mark.asyncio
async def test_a_parser_promising_more_without_a_cursor_fails_closed(monkeypatch) -> None:
    """The walk does not trust its own parser's consistency.

    # WHY this guard is worth a test rather than an assert: if a later change let
    # ``parse_catalog_page`` return ``has_more=True`` with no cursor, the walk would
    # otherwise re-dial page one forever or silently publish a short catalog. Failing the
    # refresh closed keeps the last good snapshot serving instead.
    """
    monkeypatch.setattr(
        live_models, "parse_catalog_page", lambda payload: (("claude-opus-5",), True, None)
    )
    client = _CatalogClient({_FIRST: _ok(_body(_rows("claude-opus-5")))})

    with pytest.raises(DiscoveryError) as exc:
        await _fetch(client)

    assert exc.value.reason == "malformed_json"
    assert client.dialed == [_FIRST]

"""PRD test 23, the part an example grid cannot reach: EVERY "which optional field is None" case.

FEATURE: cache-entry metadata end to end
(spec ``docs/spec/2026-09-28-aigateway-cache-hit-metadata.md``
§3.3).
STORY: as the next agent changing the block codec or the hit mapping, I learn from one failing
combination — not from a production row — that some field stopped surviving the round trip when a
neighbour was ``None``.

WHY an exhaustive walk and not a property test: ``hypothesis`` is not a dependency of this stack,
and adding one is an owner decision (spec Q2). The ``None`` space is finite — two states per
optional field — so the standard library can walk ALL of it. What this does NOT give is shrinking
or random VALUES; the value traps (scientific notation, precision, line separators) stay pinned by
the example matrix in ``test_cache_entry_metadata_reference.py``. PRD test 23 at ``level:
property`` therefore stays open.

AIDEV-NOTE: every "present" value is chosen to be FALSY where the type allows it (latency ``0``,
reasoning ``0``), so a ``value or None`` / ``if value:`` slip anywhere on the path fails here.
"""

from __future__ import annotations

import itertools
import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from aigateway.core.request_cache.entry_metadata import CacheEntryMetadata, MetadataStatus
from aigateway.plugins.taxonomy import DirectCost, InputTokenUsage, OutputTokenUsage, TokenUsage
from aigateway.plugins.taxonomy.entry_metadata import cache_reference_from_entry_metadata
from aigateway.plugins.taxonomy.render import render_aigw_metadata

# name -> the value used when the field is PRESENT.
_OPTIONAL_BLOCK_FIELDS: dict[str, Any] = {
    "observed_at": "2026-09-13T12:00:00Z",
    "response_model": "anthropic/claude-fable-5",
    "provider_latency_ms": 0,
}
_OPTIONAL_USAGE_COUNTS: dict[str, int] = {
    "input.total": 10,
    "input.uncached": 4,
    "input.cache_read": 3,
    "input.cache_write": 3,
    "output.total": 5,
    "output.reasoning": 0,
}
_COSTS = (
    DirectCost.reported(amount="0.012345", unit="openrouter_credits", source="s").as_json(),
    DirectCost.unavailable().as_json(),
)
_STATUSES: tuple[MetadataStatus, ...] = ("complete", "partial", "archive_paired")
_CERTIFYING = {"complete", "archive_paired"}
_OPTIONAL_COUNT = len(_OPTIONAL_BLOCK_FIELDS) + len(_OPTIONAL_USAGE_COUNTS)
_SPACE = len(_STATUSES) * len(_COSTS) * 2**_OPTIONAL_COUNT


def _usage(present: dict[str, bool]) -> dict[str, Any]:
    def count(name: str) -> int | None:
        return _OPTIONAL_USAGE_COUNTS[name] if present[name] else None

    # Built through the value object, exactly as the write path builds it: a subset combination
    # the invariants call contradictory is downgraded to `partial` here, not by the test.
    return TokenUsage(
        status="complete",
        source="provider_raw_response",
        input=InputTokenUsage(
            total=count("input.total"),
            uncached=count("input.uncached"),
            cache_read=count("input.cache_read"),
            cache_write=count("input.cache_write"),
        ),
        output=OutputTokenUsage(total=count("output.total"), reasoning=count("output.reasoning")),
    ).as_json()


def _combinations() -> list[tuple[MetadataStatus, dict[str, Any], dict[str, Any], dict[str, bool]]]:
    names = [*_OPTIONAL_BLOCK_FIELDS, *_OPTIONAL_USAGE_COUNTS]
    cases = []
    for status, cost, flags in itertools.product(
        _STATUSES, _COSTS, itertools.product((False, True), repeat=len(names))
    ):
        present = dict(zip(names, flags, strict=True))
        cases.append((status, cost, _usage(present), present))
    return cases


def _block(
    status: MetadataStatus, cost: dict[str, Any], usage: dict[str, Any], present: dict[str, bool]
) -> CacheEntryMetadata:
    def optional(name: str) -> Any:
        return _OPTIONAL_BLOCK_FIELDS[name] if present[name] else None

    return CacheEntryMetadata(
        metadata_status=status,
        observed_at=optional("observed_at"),
        response_model=optional("response_model"),
        usage=usage,
        direct_cost=cost,
        provider_latency_ms=optional("provider_latency_ms"),
    )


def test_the_walk_covers_the_whole_none_space() -> None:
    # Guards the walk itself: a field added to the tables above must grow the space, and a
    # refactor that collapses the product cannot pass quietly.
    assert len(_combinations()) == _SPACE == 3 * 2 * 2**9


def test_every_none_combination_round_trips_through_json_exactly() -> None:
    for status, cost, usage, present in _combinations():
        meta = _block(status, cost, usage, present)
        restored = CacheEntryMetadata.parse(meta.serialize())

        assert restored == meta, (status, cost["status"], present)
        assert restored is not None
        assert restored.as_json_dict() == meta.as_json_dict(), (status, present)


def test_every_none_combination_maps_to_a_faithful_hit_reference() -> None:
    validator = Draft202012Validator(
        json.loads(
            files("aigateway.plugins.taxonomy")
            .joinpath("usage_accounting.schema.json")
            .read_text(encoding="utf-8")
        )
    )
    for status, cost, usage, present in _combinations():
        case = (status, cost["status"], present)
        meta = _block(status, cost, usage, present)
        reference = cache_reference_from_entry_metadata(meta)
        payload = reference.as_json()

        # INVARIANT: the stored usage comes back verbatim, re-labelled only as cached evidence.
        assert payload["usage"] == {**usage, "source": "cached_converted_response"}, case
        # INVARIANT: only a certifying capture may certify a price (ERD §3.5).
        expected_cost = cost if status in _CERTIFYING else DirectCost.unavailable().as_json()
        assert payload["direct_cost"] == expected_cost, case
        # INVARIANT: each optional field is returned verbatim, or it is ABSENT — never a null.
        for name, key in (("response_model", "response_model"), ("observed_at", "observed_at")):
            if present[name]:
                assert payload[key] == _OPTIONAL_BLOCK_FIELDS[name], case
            else:
                assert key not in payload, case
        if present["provider_latency_ms"]:
            assert payload["latency"] == {"provider_latency_ms": 0}, case
        else:
            assert "latency" not in payload, case

        validator.validate(
            render_aigw_metadata(
                collector=None,
                supported=True,
                cache_status="hit",
                gateway_call_id="call_" + "a" * 32,
                cache_reference=reference,
            )
        )

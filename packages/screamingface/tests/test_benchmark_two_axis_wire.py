"""OME-1257 — catalogue rows carry the two grouping axes: difficulty and interaction.

Mental model: the Engine prints two more lines on each exam's cover sheet — how hard
it is (``difficulty``) and how the candidate is exercised (``interaction``). The SDK
carries both verbatim onto its public ``Benchmark`` value so the listing can group by
them; an older Engine that never printed the lines still decodes, with both ``None``.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

import screamingface as sf
from screamingface.discovery import Benchmark
from screamingface.errors import PlanningError


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="https://engine.example",
        http_transport=httpx.MockTransport(handler),
    )


def _entry(board_id: str, **extra: object) -> dict[str, object]:
    return {
        "id": board_id,
        "object": "benchmark",
        "title": f"{board_id} title",
        "description": f"{board_id} description.",
        "revision": "rev0000000000000",
        "case_count": 30,
        "href": f"/v1/benchmarks/{board_id}",
        **extra,
    }


def _catalogue(*entries: dict[str, object]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/benchmarks":
            return httpx.Response(200, json={"object": "list", "data": list(entries)})
        return httpx.Response(404)

    return handler


def test_both_axes_flow_from_the_wire() -> None:
    """INVARIANT: the served ``difficulty`` and ``interaction`` reach the public
    Benchmark verbatim — the listing groups on the Engine's word, never a guess."""

    with _client(
        _catalogue(_entry("draco", difficulty="hard", interaction="single_shot"))
    ) as client:
        benchmarks = client.benchmarks.list()

    assert benchmarks[0].difficulty == "hard"
    assert benchmarks[0].interaction == "single_shot"


def test_axes_default_to_none_for_older_engines() -> None:
    """INVARIANT: an Engine predating OME-1257 serves neither key; the SDK decodes
    ``None`` — unlike ``origin`` there is no true-fact default to state, because a
    tier nobody assigned is not a tier."""

    with _client(_catalogue(_entry("draco"))) as client:
        benchmarks = client.benchmarks.list()

    assert benchmarks[0].difficulty is None
    assert benchmarks[0].interaction is None


def test_unknown_axis_values_still_decode() -> None:
    """INVARIANT: the SDK never validates the axes against the Engine's closed sets —
    an older SDK must not brick against a newer Engine that ships a new tier or a new
    interaction shape (the origin tolerance doctrine, OME-1114)."""

    with _client(
        _catalogue(_entry("draco", difficulty="impossible", interaction="agentic_tool_use"))
    ) as client:
        benchmarks = client.benchmarks.list()

    assert benchmarks[0].difficulty == "impossible"
    assert benchmarks[0].interaction == "agentic_tool_use"


@pytest.mark.parametrize("field", ["difficulty", "interaction"])
@pytest.mark.parametrize("bad_value", ["", "   ", 7])
def test_blank_or_nonstring_axis_value_is_a_catalogue_defect(field: str, bad_value: object) -> None:
    # WHY: a PRESENT key with an unusable value is Engine data corruption, not an old
    # Engine — surface it, never coerce it to None (silent-absence would hide the defect).
    with _client(_catalogue(_entry("draco", **{field: bad_value}))) as client:
        with pytest.raises(PlanningError) as caught:
            client.benchmarks.list()

    assert caught.value.code == "invalid_catalogue"


@pytest.mark.parametrize("field", ["difficulty", "interaction"])
def test_benchmark_value_refuses_a_blank_axis_string(field: str) -> None:
    # None means "the Engine never said"; a blank string means nothing and is refused.
    with pytest.raises(ValueError, match=field):
        Benchmark(
            id="draco",
            title="DRACO",
            description="A tiny probe tier.",
            revision="rev0000000000000",
            case_count=30,
            **{field: "   "},  # type: ignore[arg-type]
        )

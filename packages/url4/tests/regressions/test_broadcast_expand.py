"""Broadcast over an expanded source applies the intent once per element.

Spec B §5.3.12.4 rule 3: each element of an expanded source "becomes an independent
source"; §6.1.2: the broadcast intent runs "once per *resolved* source". Expanded
elements take renumbered positions (§5.3.12.4 rule 4) and the names ``name[i]`` /
``src[i]`` (§5.3.12.5).
"""

from __future__ import annotations

import json

import pytest

from url4.core.context import Context
from url4.dag import run
from url4.io.static import StaticIOLayer


def _io() -> StaticIOLayer:
    return StaticIOLayer(fetch_map={"https://a": "A", "https://rows": '["r1","r2"]'})


async def _echo(sources: str, intent: str | None, scope: Context) -> str:
    return f"{intent}:{sources}"


@pytest.mark.asyncio
async def test_broadcast_runs_the_intent_once_per_expanded_element() -> None:
    out = await run("(https://rows;expand, https://a)!*'go'", _io(), process=_echo)
    assert json.loads(out) == [
        {"source_position": 1, "source_name": "src[0]", "result": "go:r1"},
        {"source_position": 2, "source_name": "src[1]", "result": "go:r2"},
        {"source_position": 3, "source_name": None, "result": "go:A"},
    ]


@pytest.mark.asyncio
async def test_named_expanded_elements_take_indexed_names() -> None:
    out = await run("(rows=https://rows;expand, https://a)!*'$current'", _io(), process=_echo)
    rows = json.loads(out)
    assert [(r["source_position"], r["source_name"]) for r in rows] == [
        (1, "rows[0]"),
        (2, "rows[1]"),
        (3, None),
    ]
    # $current is the element, not the joined list.
    assert [r["result"] for r in rows] == ["r1:r1", "r2:r2", "A:A"]

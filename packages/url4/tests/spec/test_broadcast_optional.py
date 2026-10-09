"""`O6` — a failed ``;optional`` source in an LLM broadcast makes no call and no row.

# FEATURE: broadcast over resolved sources (Spec B §6.1.3)
#
# STORY: as a url4 author, `(a='1', b=/nope;optional, c='3')!*'T $current'` asks the model once
# per source that resolved, so a source that failed to resolve costs no model call and adds no
# row to the result.
#
# INVARIANT: a failed optional source's broadcast part never reaches the process hook, and its
# result row is omitted; the surviving rows keep their source positions.
"""

from __future__ import annotations

import json

import pytest

from url4.core.context import Context
from url4.core.errors import ResolutionError
from url4.dag import ProcessFn, run
from url4.peer.server import Url4Node


@pytest.fixture()
def node() -> Url4Node:
    return Url4Node("t")


@pytest.fixture()
def hook_calls() -> list[tuple[str, str | None]]:
    return []


def _recording_process(hook_calls: list[tuple[str, str | None]]) -> ProcessFn:
    async def process(sources: str, intent: str | None, scope: Context) -> str:
        hook_calls.append((sources, intent))
        return f"got:{sources}"

    return process


@pytest.mark.asyncio
async def test_failed_optional_source_in_broadcast_makes_no_process_call_and_no_row(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: Spec B §6.1.3 — broadcast applies across resolved sources; a failed optional source
    # is not a source to ask about, so the hook is called for positions 1 and 3 only, and never
    # with an empty source. Mirrors CodePointerNode(broadcast_part=True) in
    # dag/nodes/code_pointer.py.
    result = await run(
        "(a='1', b=/nope;optional, c='3')!*'T $current'",
        node,
        process=_recording_process(hook_calls),
    )
    assert sorted(hook_calls) == [("1", "T 1"), ("3", "T 3")]
    assert json.loads(result) == [
        {"source_position": 1, "source_name": "a", "result": "got:1"},
        {"source_position": 3, "source_name": "c", "result": "got:3"},
    ]


@pytest.mark.asyncio
async def test_failed_required_source_in_broadcast_fails_the_run(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: Spec B §6.1.3 — only an optional failure is tolerated; a required source that fails
    # still fails the whole run. Parts are independent, so no call count is asserted here.
    with pytest.raises(ResolutionError) as err:
        await run(
            "(a='1', b=/nope, c='3')!*'T $current'",
            node,
            process=_recording_process(hook_calls),
        )
    assert err.value.code == "endpoint_not_found"


@pytest.mark.asyncio
async def test_single_failed_optional_source_in_broadcast_makes_no_process_call(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: Spec B §6.1.3 — with the only source failed there is no resolved source, so the hook
    # is never called and the collection is empty.
    result = await run(
        "(b=/nope;optional)!*'T $current'",
        node,
        process=_recording_process(hook_calls),
    )
    assert hook_calls == []
    assert json.loads(result) == []


@pytest.mark.asyncio
async def test_failed_optional_source_in_broadcast_with_structured_intent_makes_no_row(
    node: Url4Node, hook_calls: list[tuple[str, str | None]]
) -> None:
    # WHY: a struct intent is not text, so it is a shared `intent` dependency of each MergeNode
    # (dag/_wiring.py `_broadcast_graph`) rather than a template. The failed optional source
    # still produces no row and no call with an empty source.
    result = await run(
        "(a='1', b=/nope;optional, c='3')!*{k:'v'}",
        node,
        process=_recording_process(hook_calls),
    )
    assert sorted(sources for sources, _ in hook_calls) == ["1", "3"]
    assert json.loads(result) == [
        {"source_position": 1, "source_name": "a", "result": "got:1"},
        {"source_position": 3, "source_name": "c", "result": "got:3"},
    ]

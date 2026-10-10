"""A7 [F3-7] — ``ctx.collected_errors`` counts exactly the error objects the caller sees.

Each map row counts its captured errors on its own tally. The map adds a row's count
to the run only when the row's result is kept: an aborted (``fail``) map adds nothing,
``skip`` drops the failed rows' counts, ``collect`` adds one per failed row. Ported
from the audit probe ``evidence/F3-semantics/probes/probe_tally.py`` (fixed model:
``model/map_modes_fixed.py``).
"""

from __future__ import annotations

import json

import pytest

from url4.core.errors import ResolutionError
from url4.core.nodes import Iteration, IterationDirectives, OnErrorPolicy, Url
from url4.dag import ExecutionContext, run
from url4.io.static import StaticIOLayer


def _step(context: str, intent: str) -> str:
    if context == "bad":
        raise ResolutionError("inner bad")
    return f"s-{context}"


def _reducer_down(context: str, intent: str) -> str:
    raise ResolutionError("row reducer down")


def _io() -> StaticIOLayer:
    return StaticIOLayer(
        fetch_map={
            "https://outer": '["A","B"]',
            "/coll/A": '["x","bad"]',
            "/coll/B": '["y","bad"]',
        },
        routes={"/s": _step, "/red": _reducer_down},
    )


# Each outer row runs a nested collect-mode map that captures one inner error.
_NESTED = "/coll/$item*(/s($item)!'g')!'p'"


def _errors_in(out: str) -> int:
    """Error objects anywhere in the (possibly nested) JSON result."""
    count = 0

    def walk(value: object) -> None:
        nonlocal count
        if isinstance(value, str) and value[:1] in "[{":
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return
        if isinstance(value, dict):
            count += "error" in value
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(out)
    return count


async def _run(body: str, on_error: OnErrorPolicy) -> tuple[str | None, int]:
    ctx = ExecutionContext(_io())
    node = Iteration(
        collection=Url("https://outer"),
        body=body,
        directives=IterationDirectives(on_error=on_error, concurrency=1),
    )
    try:
        out = await run(node, ctx=ctx)
    except ResolutionError:
        return None, ctx.collected_errors
    return out, ctx.collected_errors


@pytest.mark.asyncio
async def test_failed_map_leaves_no_count():
    # Row A's nested map captures an error; row B's collection is missing, so the map fails.
    ctx = ExecutionContext(
        StaticIOLayer(
            fetch_map={"https://outer": '["A","B"]', "/coll/A": '["x","bad"]'},
            routes={"/s": _step},
        )
    )
    node = Iteration(
        collection=Url("https://outer"),
        body=_NESTED,
        directives=IterationDirectives(on_error="fail", concurrency=1),
    )
    with pytest.raises(ResolutionError):
        await run(node, ctx=ctx)
    assert ctx.collected_errors == 0


@pytest.mark.asyncio
async def test_collect_counts_only_the_errors_in_the_output():
    # Each row's nested map captures one error, then the row's reducer fails: the nested
    # errors are gone with the row, and the output holds one error object per row.
    out, count = await _run(f"({_NESTED})!/red(all)!'r'", "collect")
    assert out is not None
    assert count == _errors_in(out) == 2


@pytest.mark.asyncio
async def test_collect_keeps_nested_errors_of_kept_rows():
    out, count = await _run(_NESTED, "collect")
    assert out is not None
    assert count == _errors_in(out) == 2


@pytest.mark.asyncio
async def test_skip_counts_only_kept_rows():
    out, count = await _run(f"({_NESTED})!/red(all)!'r'", "skip")
    assert out is not None
    assert count == _errors_in(out) == 0


@pytest.mark.asyncio
async def test_fail_mode_success_keeps_nested_counts():
    out, count = await _run(_NESTED, "fail")
    assert out is not None
    assert count == _errors_in(out) == 2

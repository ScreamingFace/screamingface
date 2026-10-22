"""Code mounts (url4 2.0 RDS mode, contracts C2): registration, lookup, invocation.

STORY: as a node author I mount a handler at a code path, and a code-pointer intent
runs it in-process. The same path stays out of the endpoint table and out of HTTP
reach, so a code handler never becomes a processor candidate.
"""

from __future__ import annotations

from typing import cast

import pytest

from url4 import Request, Url4Node
from url4.core.code import CodeCall, CodeHandler, invoke_mounted
from url4.core.errors import ErrorCode, Url4Error
from url4.io.static import StaticIOLayer


def _combine(call: CodeCall) -> str:
    return f"combined {call.pointer}"


async def _async_combine(call: CodeCall) -> str:
    return f"async {call.pointer}"


def _endpoint(request: Request) -> str:
    return "endpoint"


def _populated_node() -> Url4Node:
    node = Url4Node("test")
    node.endpoint("/ep")(_endpoint)
    node.data("/rows", "[]")
    node.code("/cm")(_combine)
    return node


# --- invoke_mounted (core) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_mounted_returns_the_handler_result() -> None:
    mounts = {"/c": _combine}
    assert await invoke_mounted(mounts, CodeCall("/c", {}, ())) == "combined /c"


@pytest.mark.asyncio
async def test_invoke_mounted_returns_the_raw_non_str_result() -> None:
    # The DAG node checks the type (Spec C §13.6); the helper does not.
    mounts = {"/c": cast(CodeHandler, lambda call: 42)}
    assert await invoke_mounted(mounts, CodeCall("/c", {}, ())) == 42


@pytest.mark.asyncio
async def test_invoke_mounted_without_a_handler_is_a_permanent_intent_error() -> None:
    with pytest.raises(Url4Error) as info:
        await invoke_mounted({}, CodeCall("/c", {}, ()))
    assert info.value.code == ErrorCode.INTENT_ERROR
    assert info.value.permanent is True
    assert str(info.value) == "no code mount at '/c'"


# --- registration on a node -----------------------------------------------------------


def test_code_registers_a_mount() -> None:
    node = Url4Node("test")

    @node.code("/ensemble/combine/v1")
    def combine(call: CodeCall) -> str:
        return "ok"

    assert node.has_code("/ensemble/combine/v1")


def test_has_code_is_false_for_unknown_endpoint_and_data_paths() -> None:
    node = _populated_node()
    assert not node.has_code("/unknown")
    assert not node.has_code("/ep")
    assert not node.has_code("/rows")


@pytest.mark.parametrize(
    "path",
    [
        "/ep",
        "/rows",
        "/cm",
        "/v1",
        "/v1/x",
        "/c?x=1",
        "/c/$x",
        "/reduce()",
    ],
)
def test_code_refuses_an_invalid_or_taken_path(path: str) -> None:
    node = _populated_node()
    with pytest.raises(ValueError):
        node.code(path)


def test_endpoint_refuses_a_code_mount_path() -> None:
    node = _populated_node()
    with pytest.raises(ValueError):
        node.endpoint("/cm")


def test_data_refuses_a_code_mount_path() -> None:
    node = _populated_node()
    with pytest.raises(ValueError):
        node.data("/cm", "x")


# --- invocation ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_code_runs_a_sync_handler() -> None:
    node = Url4Node("test")
    node.code("/c")(_combine)
    assert await node.invoke_code(CodeCall("/c", {}, ())) == "combined /c"


@pytest.mark.asyncio
async def test_invoke_code_runs_an_async_handler() -> None:
    node = Url4Node("test")
    node.code("/a")(_async_combine)
    assert await node.invoke_code(CodeCall("/a", {}, ())) == "async /a"


@pytest.mark.asyncio
async def test_invoke_code_on_an_unmounted_pointer_is_a_permanent_intent_error() -> None:
    node = Url4Node("test")
    with pytest.raises(Url4Error) as info:
        await node.invoke_code(CodeCall("/c", {}, ()))
    assert info.value.code == ErrorCode.INTENT_ERROR
    assert info.value.permanent is True


@pytest.mark.asyncio
async def test_a_code_mount_is_not_an_http_endpoint() -> None:
    node = Url4Node("test")
    node.code("/c")(_combine)
    for target in ("/c?x=1", "/c"):
        with pytest.raises(Url4Error) as info:
            await node.fetch(target, relative=True)
        assert info.value.code == ErrorCode.ENDPOINT_NOT_FOUND


def test_processor_routes_does_not_list_code_mounts() -> None:
    node = _populated_node()
    assert node.processor_routes() == ["/ep"]


def test_repr_counts_code_mounts() -> None:
    node = _populated_node()
    assert "1 code mount" in repr(node)


# --- StaticIOLayer test double ---------------------------------------------------------


@pytest.mark.asyncio
async def test_static_io_layer_mounts_code_handlers() -> None:
    io = StaticIOLayer(code={"/c": _combine})
    assert io.has_code("/c")
    assert not io.has_code("/d")
    assert await io.invoke_code(CodeCall("/c", {}, ())) == "combined /c"


@pytest.mark.asyncio
async def test_static_io_layer_unmounted_pointer_is_an_intent_error() -> None:
    with pytest.raises(Url4Error) as info:
        await StaticIOLayer().invoke_code(CodeCall("/c", {}, ()))
    assert info.value.code == ErrorCode.INTENT_ERROR


def test_default_static_io_layer_has_no_code_mounts() -> None:
    assert not StaticIOLayer().has_code("/c")


# --- name keys (row 29, owner decision Q6) ----------------------------------------------


def test_code_registers_a_name_key() -> None:
    node = Url4Node("t", outbound=StaticIOLayer({}))
    node.code("score_v1")(_combine)
    assert node.has_code("score_v1")
    assert not node.has_code("/score_v1")


@pytest.mark.parametrize("name", ["two words", "a$b", "x!y", "'q'", "score_v1"])
def test_code_refuses_an_invalid_or_taken_name(name: str) -> None:
    node = Url4Node("t", outbound=StaticIOLayer({}))
    node.code("score_v1")(_combine)
    with pytest.raises(ValueError):
        node.code(name)


def test_has_data_names_only_registered_data_routes() -> None:
    # STORY: an installer that runs once per run in local mode skips a data route it already
    # registered, without reaching into the node's private tables.
    node = _populated_node()
    assert node.has_data("/rows")
    assert not node.has_data("/ep")
    assert not node.has_data("/cm")
    assert not node.has_data("/unknown")

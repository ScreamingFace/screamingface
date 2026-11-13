"""``run(Graph | DagNode)`` FAILS CLOSED on any attachment-capable source, with zero I/O.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543``; PR #1587 review finding 3,
owner decision Sergey 2026-11-04: fail closed).
STORY: as an engine caller, a pre-built graph cannot prove a safe frozen attachment manifest (it has
no source AST), so one that names an attachment opt-in, a blob ref, a ``url4://`` blob ref, a
non-literal attachment target or a malformed opt-in context is refused before any fetch or model
call (an opt-in keeps the ``x.source_not_static`` it already failed with, since round 7) — never run
with ``attachments=()`` or a raw context shipped to the route. A text-only graph runs exactly as
before.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, Url4Error
from url4.dag import compile_expression
from url4.dag._run import run
from url4.dag.nodes.web_attach import NotStaticNode
from url4.io.layer import FetchRequest
from url4.io.media import FetchedBytes
from url4.io.static import StaticIOLayer

IMG = "https://img.example/a.png"
PNG = b"\x89PNG\r\n\x1a\n-prebuilt"
HEX = hashlib.sha256(PNG).hexdigest()


class _Io(StaticIOLayer):
    def __init__(self) -> None:
        super().__init__(
            {IMG: PNG, f"/blob/sha256/{HEX}": PNG, "https://a.example/x": "text"},
            routes={"/m": lambda context, intent: f"route got {context}"},
            media_types={IMG: "image/png", f"/blob/sha256/{HEX}": "image/png"},
        )
        self.calls: list[str] = []

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.calls.append(f"fetch {target}")
        return await super().fetch(target, relative=relative)

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.calls.append(f"fetch_bytes {request.target}")
        return await super().fetch_bytes(request)


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.calls += 1
        return "ok"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (f"(src={IMG};accept=image/png)!'d'", ErrorCode.SOURCE_NOT_STATIC),
        (f"(src=/blob/sha256/{HEX})!'d'", ErrorCode.MALFORMED_SOURCE),
        (f"(img:src=blob:sha256/{HEX})!'d'", ErrorCode.MALFORMED_SOURCE),
        (f"(/blob/sha256/{HEX}*($item)!'d')!'r'", ErrorCode.MALFORMED_SOURCE),
        (f"(src=url4://n2/blob/sha256/{HEX})!'d'", ErrorCode.REMOTE_BLOB_UNSUPPORTED),
        ("(src=/files/$name;accept=image/png)!'d'", ErrorCode.SOURCE_NOT_STATIC),
        ("(v='x', src=$v;accept=image/png)!'d'", ErrorCode.SOURCE_NOT_STATIC),
        (f"(/m(note: run 1, src={IMG};accept=image/png)!'d')!'r'", ErrorCode.MALFORMED_SOURCE),
        (f"(/m(src={IMG};;accept=image/png)!'d')!'r'", ErrorCode.MALFORMED_SOURCE),
        (f"(/m(src={IMG};accept=image/png)!'d')!'r'", ErrorCode.SOURCE_NOT_STATIC),  # ctx slot
        (f"(('a')*(src={IMG};accept=image/png)!'d')!'r'", ErrorCode.SOURCE_NOT_STATIC),  # row body
        ("(('a')*(src=$item;accept=image/png)!'d')!'r'", ErrorCode.SOURCE_NOT_STATIC),
        (f"(x=(src={IMG};accept=image/png)!'p', $x)!'r'", ErrorCode.SOURCE_NOT_STATIC),  # lazy
    ],
)
@pytest.mark.parametrize("as_node", [False, True])
@pytest.mark.asyncio
async def test_a_prebuilt_graph_with_an_attachment_capable_source_is_refused_with_no_io(
    text: str, code: str, as_node: bool
) -> None:
    graph = compile_expression(text)
    io, model = _Io(), _Model()
    with pytest.raises(Url4Error) as caught:
        await run(graph.sink if as_node else graph, io, process=model)
    assert caught.value.code == code
    assert caught.value.permanent is True
    assert io.calls == [] and model.calls == 0


@pytest.mark.parametrize(
    "text",
    [
        "(https://a.example/x, 'q')!'d'",
        "(src=https://a.example/x)!'d'",  # an https source with no attachment ;accept= is text
        "(src=https://a.example/x;accept=text/plain)!'d'",
        "(/m(note: run 1, , 'x')!'d')!'r'",  # prose context with no opt-in
        "(('a', 'b')*($item)!'d')!'r'",
    ],
)
@pytest.mark.asyncio
async def test_a_text_only_prebuilt_graph_runs_as_before(text: str) -> None:
    io, model = _Io(), _Model()
    expected = await run(text, _Io(), process=_Model())
    assert await run(compile_expression(text), io, process=model) == expected
    assert not any(call.startswith("fetch_bytes") for call in io.calls)


@pytest.mark.asyncio
async def test_the_string_form_of_the_same_graph_still_attaches() -> None:
    io, model = _Io(), _Model()
    assert await run(f"(src={IMG};accept=image/png)!'d'", io, process=model) == "ok"
    assert io.calls == [f"fetch_bytes {IMG}"]


@pytest.mark.asyncio
async def test_a_non_literal_attachment_target_never_reads_as_text_even_outside_run() -> None:
    # INVARIANT (owner decision C): ``src=$v;accept=image/png`` is refused, never read as text —
    # the lowered node itself refuses, so an executor that bypasses run() fails closed too.
    graph = compile_expression("(v='x', src=$v;accept=image/png)!'d'")
    nodes = [node for node in graph.walk() if isinstance(node, NotStaticNode)]
    assert [node.target for node in nodes] == ["$v"]
    from url4.dag import ExecutionContext

    with pytest.raises(Url4Error) as caught:
        await nodes[0].resolve({}, ExecutionContext(_Io()))
    assert caught.value.code == ErrorCode.SOURCE_NOT_STATIC

"""Run attachments reach every model-calling node family, unchanged (the ``OME-1543`` acceptance).

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543`` sub-issue A; plan §3 U4).
STORY: as an ensemble author I name a file once; every member, the reducer, each map row, each
broadcast application, a pipeline stage and a retried call all receive the same attachments,
and a text-only DAG behaves byte-for-byte as before.

INVARIANT (F2): no node family needs code for this — the run-scoped side-channel reaches them
all — and nothing scans a payload: a member that WRITES ref-shaped text adds no attachment.
"""

from __future__ import annotations

import hashlib

import pytest

from url4.core.errors import ErrorCode, ResolutionError
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments
from url4.io.static import StaticIOLayer

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-propagate"
HEX = hashlib.sha256(PNG).hexdigest()
REF = f"/blob/sha256/{HEX}"
IMG = Attachment(f"sha256:{HEX}", "image/png", PNG)
OTHER = "c" * 64


class _World(StaticIOLayer):
    """A store plus recording routes and a recording ``process`` hook.

    ``calls`` holds ``(who, attachments)`` for every model-calling step, in call order.
    """

    def __init__(self, routes: tuple[str, ...] = ("/a", "/b", "/c", "/claude")) -> None:
        self.calls: list[tuple[str, tuple[Attachment, ...]]] = []
        self.targets: list[str] = []
        self.reducer_intents: list[str] = []
        super().__init__(
            {REF: PNG, "/list": '["r1", "r2"]'},
            {path: self._route(path) for path in routes},
            media_types={REF: "image/png", "/list": "application/json"},
        )

    def _route(self, path: str):
        def handle(context: str, intent: str) -> str:
            self.calls.append((path, current_attachments()))
            if path == "/claude":
                self.reducer_intents.append(intent)
            return f"{path}-out"

        return handle

    async def process(self, sources: str, intent: str | None, scope: object) -> str:
        self.calls.append((f"process:{intent}", current_attachments()))
        return f"processed:{intent}"

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.targets.append(target)
        return await super().fetch(target, relative=relative)


async def _run(world: _World, text: str, attachments: tuple[Attachment, ...] = ()) -> str:
    return await run(
        text, world, process=world.process, processor="/claude", attachments=attachments
    )


def _who(world: _World) -> list[str]:
    return [who for who, _ in world.calls]


def _all_carry(world: _World, expected: tuple[Attachment, ...] = (IMG,)) -> bool:
    return bool(world.calls) and all(seen == expected for _, seen in world.calls)


@pytest.mark.asyncio
async def test_fanout_ref_reaches_all_three_members() -> None:
    world = _World()
    await _run(world, f"(/a(src={REF})!'x', /b(src={REF})!'y', /c(src={REF})!'z')!'combine'")
    members = [seen for who, seen in world.calls if who in {"/a", "/b", "/c"}]
    assert members == [(IMG,), (IMG,), (IMG,)]


@pytest.mark.asyncio
async def test_fanout_reducer_receives_the_same_attachments() -> None:
    world = _World()
    await _run(world, f"(/a(src={REF})!'x', /b()!'y', /c()!'z')!'combine'")
    assert "/claude" in _who(world)
    assert _all_carry(world)


@pytest.mark.asyncio
async def test_row_reduce_reducer_receives_the_attachments() -> None:
    world = _World()
    await _run(world, f"((src={REF}, /list*($item)!'row')!'peri')!'across'")
    assert "process:across" in _who(world)
    assert _all_carry(world)


@pytest.mark.asyncio
async def test_process_node_merge_receives_the_attachments() -> None:
    world = _World()
    assert await _run(world, f"(src={REF}, 'q')!'go'") == "processed:go"
    assert world.calls == [("process:go", (IMG,))]


@pytest.mark.asyncio
async def test_broadcast_each_application_receives_the_attachments() -> None:
    world = _World()
    await _run(world, f"(src={REF}, 'a', /list;expand)!*'each'")
    assert len(world.calls) >= 3
    assert _all_carry(world)


@pytest.mark.asyncio
async def test_map_rows_receive_the_attachments() -> None:
    world = _World()
    await _run(world, f"(src={REF}, /list*($item)!'row')!'go'")
    assert _who(world).count("process:row") == 2
    assert _all_carry(world)


@pytest.mark.asyncio
async def test_pipeline_stage_and_nested_local_expression_receive_the_attachments() -> None:
    world = _World()
    await _run(world, f"((src={REF}, 'q')!'stage1', /a(('n')!'nested')!'x')!'stage2'")
    assert {"process:stage1", "process:nested", "/a", "process:stage2"} <= set(_who(world))
    assert _all_carry(world)


@pytest.mark.asyncio
async def test_guard_retry_resends_identical_attachments() -> None:
    world = _World()
    attempts: list[tuple[Attachment, ...]] = []

    def flaky(context: str, intent: str) -> str:
        attempts.append(current_attachments())
        if len(attempts) == 1:
            raise ResolutionError("transient", code=ErrorCode.RESOLUTION_FAILED)
        return "ok"

    world._routes["/flaky"] = flaky
    await _run(world, f"(src={REF}, /flaky()!'x';retry=2)!'go'")
    assert attempts == [(IMG,), (IMG,)]


@pytest.mark.asyncio
async def test_member_output_containing_blob_text_adds_no_attachment() -> None:
    world = _World()

    def writes_a_ref(context: str, intent: str) -> str:
        world.calls.append(("/a", current_attachments()))
        return f"see blob:sha256/{OTHER} and /blob/sha256/{OTHER}"

    world._routes["/a"] = writes_a_ref
    await _run(world, f"(/a(src={REF})!'x', /b()!'y')!'combine'")
    assert _all_carry(world)  # still exactly (IMG,): the written refs never became files
    assert not any(t.startswith(f"/blob/sha256/{OTHER}") for t in world.targets)


@pytest.mark.asyncio
async def test_reducer_text_is_unchanged_by_attachments() -> None:
    plain, carried = _World(), _World()
    text = "(/a()!'x', /b()!'y')!'combine'"
    await _run(plain, text)
    await _run(carried, text, attachments=(IMG,))
    assert carried.reducer_intents == plain.reducer_intents
    assert carried.reducer_intents and all(seen == (IMG,) for _, seen in carried.calls)


@pytest.mark.asyncio
async def test_text_only_dag_is_byte_identical() -> None:
    world = _World()
    text = "(/a('ctx')!'x', /b()!'y', /list*($item)!'row')!'combine'"
    result = await _run(world, text)
    # Golden recorded on the #1482 base (no run-start resolution): same io, same result.
    assert result == "processed:combine"
    assert world.targets == GOLDEN_TARGETS
    assert all(seen == () for _, seen in world.calls)


# WHY a literal: recorded by running this exact DAG on the #1482 base (origin/OME-1539, before
# this unit), so any io added by run-start resolution on a text-only run turns this red.
GOLDEN_TARGETS: list[str] = ["/list", "/a?q=(ctx)!%27x%27", "/b?q=()!%27y%27"]

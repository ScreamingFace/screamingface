"""The run-scoped ``attachments[]`` side-channel and its per-run file cache.

FEATURE: image and PDF inputs (epic ``OME-1529``, unit ``OME-1543`` sub-issue A; plan
``docs/plan/2026-10-21-OME-1543-file-refs-carry-plan.md`` §3 U1–U3).
STORY: as an ensemble author I name a file once in a url4 source, and every model call the
run makes (members, reducer, map rows, retries) receives the same ordered attachments, while
the payload text stays exactly what it was.

INVARIANT (F2 / D2): attachments come from structure — the run's AST or the Case — fixed
before execution; nothing scans a payload string, and a node cannot add, drop or reorder.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import re

import pytest

from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import current_attachments, current_run_files
from url4.io.static import StaticIOLayer

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR-carry"
PDF = b"%PDF-1.7 carry"


def _att(body: bytes, media_type: str) -> Attachment:
    return Attachment(f"sha256:{hashlib.sha256(body).hexdigest()}", media_type, body)


IMG = _att(PNG, "image/png")
DOC = _att(PDF, "application/pdf")


class _Recorder:
    """A ``process`` hook that records the attachments every model call sees."""

    def __init__(self) -> None:
        self.seen: list[tuple[Attachment, ...]] = []

    async def __call__(self, sources: str, intent: str | None, scope: object) -> str:
        self.seen.append(current_attachments())
        return "ok"


def _io() -> StaticIOLayer:
    return StaticIOLayer({})


# -- U1: one value type ---------------------------------------------------------------------


def test_attachment_is_defined_once() -> None:
    # INVARIANT (plan §2.1): #1482's Attachment is the only definition; no second type.
    hits = [
        path
        for path in SRC.rglob("*.py")
        if re.search(r"^class Attachment\b", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert [p.relative_to(SRC).as_posix() for p in hits] == ["url4/dag/attachment.py"]


# -- U2: the run-scoped carrier and file cache ------------------------------------------------


def test_current_attachments_is_empty_outside_a_run() -> None:
    assert current_attachments() == ()


@pytest.mark.asyncio
async def test_run_without_attachments_binds_empty_tuple() -> None:
    hook = _Recorder()
    assert await run("('a', 'b')!'go'", _io(), process=hook) == "ok"
    assert hook.seen == [()]


@pytest.mark.asyncio
async def test_run_binds_case_attachments_in_given_order() -> None:
    hook = _Recorder()
    await run("('a')!'go'", _io(), process=hook, attachments=[DOC, IMG])
    assert hook.seen == [(DOC, IMG)]
    assert isinstance(hook.seen[0], tuple)


@pytest.mark.asyncio
async def test_attachments_are_unbound_after_run_returns_or_raises() -> None:
    await run("('a')!'go'", _io(), process=_Recorder(), attachments=[IMG])
    assert current_attachments() == ()

    async def boom(sources: str, intent: str | None, scope: object) -> str:
        raise RuntimeError("model down")

    with pytest.raises(RuntimeError):
        await run("('a')!'go'", _io(), process=boom, attachments=[IMG])
    assert current_attachments() == ()
    assert current_run_files() is None


@pytest.mark.asyncio
async def test_concurrent_runs_each_see_their_own_attachments() -> None:
    first, second = _Recorder(), _Recorder()
    arrived: list[str] = []
    both_inside = asyncio.Event()

    async def slow(hook: _Recorder, files: list[Attachment]) -> str:
        async def model(sources: str, intent: str | None, scope: object) -> str:
            # WHY a barrier: both runs are provably in flight at once when they record.
            arrived.append(sources)
            if len(arrived) == 2:
                both_inside.set()
            await both_inside.wait()
            return await hook(sources, intent, scope)

        return await run("('a', 'b')!'go'", _io(), process=model, attachments=files)

    await asyncio.gather(slow(first, [IMG]), slow(second, [DOC]))
    assert first.seen == [(IMG,)]
    assert second.seen == [(DOC,)]


@pytest.mark.asyncio
async def test_nested_run_inherits_outer_attachments_unchanged() -> None:
    inner = _Recorder()

    async def outer_model(sources: str, intent: str | None, scope: object) -> str:
        # A nested local evaluation (the engine's local-eval path) passes no attachments.
        return await run("('x')!'inner'", _io(), process=inner)

    await run("('a')!'go'", _io(), process=outer_model, attachments=[IMG, DOC])
    assert inner.seen == [(IMG, DOC)]


@pytest.mark.asyncio
async def test_nested_run_binding_a_different_set_is_refused() -> None:
    async def outer_model(sources: str, intent: str | None, scope: object) -> str:
        return await run("('x')!'inner'", _io(), process=_Recorder(), attachments=[DOC])

    with pytest.raises(ValueError, match="attachments"):
        await run("('a')!'go'", _io(), process=outer_model, attachments=[IMG])


@pytest.mark.asyncio
async def test_nested_run_restating_the_same_set_is_allowed() -> None:
    inner = _Recorder()

    async def outer_model(sources: str, intent: str | None, scope: object) -> str:
        return await run("('x')!'inner'", _io(), process=inner, attachments=[IMG])

    await run("('a')!'go'", _io(), process=outer_model, attachments=[IMG])
    assert inner.seen == [(IMG,)]


@pytest.mark.asyncio
async def test_run_file_cache_is_discarded_when_run_exits() -> None:
    caches: list[object] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        files = current_run_files()
        assert files is not None
        files.cache["k"] = IMG
        caches.append(files)
        return "ok"

    await run("('a')!'go'", _io(), process=model)
    assert current_run_files() is None
    second: list[object] = []

    async def again(sources: str, intent: str | None, scope: object) -> str:
        files = current_run_files()
        assert files is not None
        second.append(dict(files.cache))
        return "ok"

    await run("('a')!'go'", _io(), process=again)
    assert second == [{}]

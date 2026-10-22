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

from url4.core.errors import ErrorCode, ResolutionError
from url4.core.grammar import parse
from url4.dag._run import run
from url4.dag.attachment import Attachment
from url4.dag.attachments import collect_file_refs, current_attachments, current_run_files
from url4.dag.node import ExecutionContext
from url4.dag.nodes.blob import BlobRefNode
from url4.io.layer import FetchRequest, FetchResult
from url4.io.media import FetchedBytes
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
        files.cache["k"] = "cached text"
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


# -- U3: collect and resolve url4 refs at run start -------------------------------------------

PNG_HEX = hashlib.sha256(PNG).hexdigest()
PDF_HEX = hashlib.sha256(PDF).hexdigest()
ROWS = '["row a", "row b"]'
ROWS_HEX = hashlib.sha256(ROWS.encode()).hexdigest()
OTHER_HEX = "b" * 64


class _Store(StaticIOLayer):
    """A fake node store that counts every bytes fetch and every text fetch it serves."""

    def __init__(self, blobs: dict[str, bytes | str], media: dict[str, str] | None = None) -> None:
        super().__init__(dict(blobs), media_types=media or {})
        self.byte_targets: list[str] = []
        self.text_targets: list[str] = []

    async def fetch_bytes(self, request: FetchRequest) -> FetchedBytes:
        self.byte_targets.append(request.target)
        return await super().fetch_bytes(request)

    async def fetch(self, target: str, *, relative: bool) -> str:
        self.text_targets.append(target)
        return await super().fetch(target, relative=relative)

    async def fetch_ex(self, request: FetchRequest) -> FetchResult:
        self.text_targets.append(request.target)
        return await super().fetch_ex(request)

    @property
    def calls(self) -> int:
        return len(self.byte_targets) + len(self.text_targets)


def _store() -> _Store:
    return _Store(
        {
            f"/blob/sha256/{PNG_HEX}": PNG,
            f"/blob/sha256/{PDF_HEX}": PDF,
            f"/blob/sha256/{ROWS_HEX}": ROWS,
            "/list": '["x", "y"]',
        },
        {
            f"/blob/sha256/{PNG_HEX}": "image/png",
            f"/blob/sha256/{PDF_HEX}": "application/pdf",
            f"/blob/sha256/{ROWS_HEX}": "application/json",
            "/list": "application/json",
        },
    )


def _refs(text: str) -> list[tuple[str, bool]]:
    return [(ref.address.ref, ref.collection) for ref in collect_file_refs(parse(text))]


def test_collects_refs_in_source_order_across_sources_and_iteration_bodies() -> None:
    text = (
        f"('q', (src=/blob/sha256/{PNG_HEX})!x, /list*(src=blob:sha256/{PDF_HEX}, $item)!d,"
        f" /m(src=/blob/sha256/{ROWS_HEX})!e)!r"
    )
    assert _refs(text) == [
        (f"/blob/sha256/{PNG_HEX}", False),
        (f"blob:sha256/{PDF_HEX}", False),
        (f"/blob/sha256/{ROWS_HEX}", False),
    ]


def test_collects_both_local_forms() -> None:
    text = f"(src=/blob/sha256/{PNG_HEX}, img:src=blob:sha256/{PDF_HEX})!d"
    got = collect_file_refs(parse(text))
    assert [(r.address.form, r.address.digest) for r in got] == [
        ("path", PNG_HEX),
        ("token", PDF_HEX),
    ]


def test_quoted_blob_text_is_not_collected() -> None:
    assert _refs(f"('blob:sha256/{PNG_HEX}', img:'/blob/sha256/{PDF_HEX}')!d") == []


def test_refs_inside_a_remote_nested_expression_are_not_collected() -> None:
    text = f"(url4://other/m(src=blob:sha256/{PNG_HEX})!d, src=/blob/sha256/{PDF_HEX})!r"
    assert _refs(text) == [(f"/blob/sha256/{PDF_HEX}", False)]


def test_duplicate_digest_is_collected_once_at_its_first_position() -> None:
    text = f"(src=blob:sha256/{PDF_HEX}, src=/blob/sha256/{PNG_HEX}, src=/blob/sha256/{PDF_HEX})!d"
    assert _refs(text) == [(f"blob:sha256/{PDF_HEX}", False), (f"/blob/sha256/{PNG_HEX}", False)]


@pytest.mark.asyncio
async def test_case_attachments_precede_url4_refs() -> None:
    hook = _Recorder()
    case = _att(b"case-bytes", "image/jpeg")
    await run(
        f"(src=/blob/sha256/{PNG_HEX}, src=/blob/sha256/{PDF_HEX})!'d'",
        _store(),
        process=hook,
        attachments=[case, DOC],
    )
    # DOC is both a Case part and a url4 ref: kept once, at its Case position.
    assert hook.seen == [(case, DOC, IMG)]
    assert [a.body for a in hook.seen[0]] == [b"case-bytes", PDF, PNG]


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["other.node", "me", "me:8080", "user@me"])
async def test_remote_blob_ref_fails_remote_blob_unsupported_with_no_io(authority: str) -> None:
    io, hook = _store(), _Recorder()
    text = f"(src=/blob/sha256/{PNG_HEX}, src=url4://{authority}/blob/sha256/{PDF_HEX})!'d'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=hook)
    assert caught.value.code == ErrorCode.REMOTE_BLOB_UNSUPPORTED
    assert caught.value.permanent
    assert io.calls == 0  # INVARIANT (D1): refused before ANY I/O, even of the local ref
    assert hook.seen == []


@pytest.mark.asyncio
async def test_url4_blob_ref_naming_the_own_node_is_also_remote_blob_unsupported() -> None:
    # WHY no node fixture: v1 never compares the authority to the node's own name (D1), so
    # the self spelling is refused exactly like any other, by the same pre-I/O check.
    io = _store()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src=url4://self.local/blob/sha256/{PNG_HEX})!'d'", io)
    assert caught.value.code == ErrorCode.REMOTE_BLOB_UNSUPPORTED
    assert io.calls == 0


@pytest.mark.asyncio
async def test_digest_mismatch_fails_blob_digest_mismatch_permanent() -> None:
    io, hook = _Store({f"/blob/sha256/{PNG_HEX}": PDF}, {}), _Recorder()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src=/blob/sha256/{PNG_HEX}, 'x')!'d'", io, process=hook)
    assert caught.value.code == ErrorCode.BLOB_DIGEST_MISMATCH
    assert caught.value.permanent
    assert hook.seen == []


@pytest.mark.asyncio
async def test_missing_blob_fails_source_not_found_before_any_process_call() -> None:
    io, hook = _store(), _Recorder()
    text = f"((src=/blob/sha256/{PNG_HEX})!'a', (src=/blob/sha256/{OTHER_HEX})!'b')!'r'"
    with pytest.raises(ResolutionError) as caught:
        await run(text, io, process=hook)
    assert caught.value.code == ErrorCode.SOURCE_NOT_FOUND
    assert hook.seen == []


@pytest.mark.asyncio
async def test_failed_optional_blob_source_fails_the_whole_run() -> None:
    hook = _Recorder()
    with pytest.raises(ResolutionError) as caught:
        await run(f"(src=/blob/sha256/{OTHER_HEX};optional, 'x')!'d'", _store(), process=hook)
    assert caught.value.code == ErrorCode.SOURCE_NOT_FOUND  # D5: never dropped from the list
    assert hook.seen == []


@pytest.mark.asyncio
async def test_blob_in_collection_position_is_text_and_not_attached() -> None:
    io = _store()
    payloads: list[str] = []
    hook = _Recorder()

    async def model(sources: str, intent: str | None, scope: object) -> str:
        payloads.append(sources)
        return await hook(sources, intent, scope)

    await run(f"(/blob/sha256/{ROWS_HEX}*($item)!'d')!'r'", io, process=model)
    assert all(seen == () for seen in hook.seen)
    assert any("row a" in p for p in payloads) and any("row b" in p for p in payloads)
    assert io.byte_targets == [f"/blob/sha256/{ROWS_HEX}"]


@pytest.mark.asyncio
async def test_blob_ref_payload_is_the_plain_ref_text_and_fetches_once() -> None:
    io = _store()
    payloads: list[str] = []
    hook = _Recorder()

    async def model(sources: str, intent: str | None, scope: object) -> str:
        payloads.append(sources)
        return await hook(sources, intent, scope)

    await run(f"(img:src=blob:sha256/{PNG_HEX})!'Describe'", io, process=model)
    assert len(payloads) == 1
    assert type(payloads[0]) is str
    assert f"blob:sha256/{PNG_HEX}" in payloads[0]
    assert PNG.decode("latin-1") not in payloads[0]
    assert hook.seen == [(IMG,)]
    assert io.byte_targets == [f"/blob/sha256/{PNG_HEX}"]


@pytest.mark.asyncio
async def test_each_file_is_fetched_and_verified_once_per_run_across_fanout_rows_and_retries() -> (
    None
):
    io, hook = _store(), _Recorder()
    ref = f"blob:sha256/{PNG_HEX}"
    text = (
        f"((src={ref})!'a', (src={ref})!'b', (src={ref})!'c',"
        f" /list*(src={ref}, $item)!'d', (src=/blob/sha256/{PDF_HEX})!'e')!'r'"
    )
    assert await run(text, io, process=hook) == "ok"
    assert sorted(io.byte_targets) == sorted([f"/blob/sha256/{PNG_HEX}", f"/blob/sha256/{PDF_HEX}"])
    # 3 members + 2 map rows + the row-group reduce + e + the outer reduce, all the same list
    assert len(hook.seen) >= 7
    assert all(seen == (IMG, DOC) for seen in hook.seen)


@pytest.mark.asyncio
async def test_blob_node_outside_a_run_still_fetches_on_a_cache_miss() -> None:
    io = _store()
    node = BlobRefNode.token(f"blob:sha256/{PNG_HEX}")
    ctx = ExecutionContext(io)
    assert await node.resolve({}, ctx) == f"blob:sha256/{PNG_HEX}"
    assert (await node.attachment(ctx)) == IMG
    assert io.byte_targets == [f"/blob/sha256/{PNG_HEX}"] * 2


def test_a_prose_or_holdings_context_contributes_no_refs() -> None:
    # Prose fails to parse as a source-list and ships verbatim; an "@" context is the
    # receiving route's business (never resolved caller-side).
    prose = f"(/m(note: run 1, , 'x')!'d', /h(@, src=/blob/sha256/{PNG_HEX})!'e')!'r'"
    assert _refs(prose) == []


def test_a_ref_read_in_collection_and_scalar_position_is_attached_at_its_first_position() -> None:
    text = f"(/blob/sha256/{ROWS_HEX}*($item)!'d', 'q', src=/blob/sha256/{ROWS_HEX})!'r'"
    assert _refs(text) == [(f"/blob/sha256/{ROWS_HEX}", False)]
    assert _refs(f"(/blob/sha256/{ROWS_HEX}*($item)!'d')!'r'") == [
        (f"/blob/sha256/{ROWS_HEX}", True)
    ]


def test_expand_source_is_collection_position() -> None:
    assert _refs(f"(*src=/blob/sha256/{ROWS_HEX})!'go'") == [(f"/blob/sha256/{ROWS_HEX}", True)]


# -- U3 item 9: a blob binding read in collection position (``$x*(…)``) -----------------------


@pytest.mark.asyncio
async def test_bound_blob_in_collection_position_is_read_as_text() -> None:
    io = _store()
    payloads: list[str] = []

    async def model(sources: str, intent: str | None, scope: object) -> str:
        payloads.append(sources)
        return "ok"

    await run(f"(x=/blob/sha256/{ROWS_HEX}, $x*($item)!'d')!'r'", io, process=model)
    # The rows are the blob's JSON items (D4), not the ref text read as one scalar item.
    assert any("row a" in p for p in payloads) and any("row b" in p for p in payloads)
    assert io.byte_targets == [f"/blob/sha256/{ROWS_HEX}"]
    assert io.text_targets == []


@pytest.mark.asyncio
async def test_bound_png_blob_in_collection_position_fails_unsupported_content_type() -> None:
    with pytest.raises(ResolutionError) as caught:
        await run(f"(x=blob:sha256/{PNG_HEX}, $x*($item)!'d')!'r'", _store(), process=_Recorder())
    assert caught.value.code == ErrorCode.UNSUPPORTED_CONTENT_TYPE  # C8


@pytest.mark.asyncio
async def test_bound_blob_used_scalar_and_in_collection_is_attached_once_and_fetched_once() -> None:
    io, hook = _store(), _Recorder()
    rows = _att(ROWS.encode(), "application/json")
    text = f"(x=/blob/sha256/{ROWS_HEX}, $x*($item)!'d', (src=$x)!'e')!'r'"
    await run(text, io, process=hook)
    assert hook.seen and all(seen == (rows,) for seen in hook.seen)
    assert io.byte_targets == [f"/blob/sha256/{ROWS_HEX}"]

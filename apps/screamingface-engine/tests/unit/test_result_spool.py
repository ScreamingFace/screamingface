"""The run's result spool (memory fix 3, OME-1835, unit 1).

WHY these tests: the spool replaces build_result's one-shot encode of the whole result, so it
must give the SAME verdict for every size (inline, spill, too large), with the same message,
while it never holds more than the inline cap in memory. The other tests pin the ticket rules:
a reference redeems only through the spool that issued it, any other body fails closed after
an issue, and close stops the writer at the next chunk and leaves no file behind.
"""

import hashlib
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from screamingface_engine.artifacts.delivery import (
    ResultDelivery,
    allowed_result_bytes,
    decide_result_delivery,
)
from screamingface_engine.artifacts.filesystem import FilesystemArtifactStore
from screamingface_engine.artifacts.ports import ArtifactSink
from screamingface_engine.artifacts.spool import (
    REFERENCE_SCHEMA,
    ResultSpool,
    ResultSpoolClosed,
    ResultSpoolError,
    ResultTooLarge,
    UnredeemedResultReference,
    WriteBody,
    binding_result_spool,
    bound_result_spool,
)
from screamingface_engine.runner.executor import _RunState
from url4.core.errors import ResolutionError
from url4.streaming.protocol.signals import ResultArtifact

_KEY = re.compile(r"^[0-9a-f]{32}$")


def _text(size: int) -> str:
    """A text of exactly `size` UTF-8 bytes, with a two-byte character in it."""

    return "é" * (size // 2) + "x" * (size % 2)


def _writer(text: str, pieces: int = 5) -> WriteBody:
    """A body writer that writes `text` in `pieces` slices."""

    step = max(1, -(-len(text) // pieces))

    def write_body(write: Callable[[str], None]) -> None:
        for start in range(0, len(text), step):
            write(text[start : start + step])

    return write_body


def _names(art: Path) -> list[str]:
    return sorted(p.name for p in art.iterdir()) if art.exists() else []


def _spool(art: Path, *, inline_cap: int, hard_cap: int, with_store: bool = True) -> ResultSpool:
    store = FilesystemArtifactStore(art) if with_store else None
    return ResultSpool(store, inline_cap=inline_cap, hard_cap=hard_cap)


def _spill(spool: ResultSpool, size: int = 300) -> str:
    return spool.deliver(_writer(_text(size)))


def _check_spill(spool: ResultSpool, art: Path, ref: str, text: str) -> None:
    parsed = json.loads(ref)
    assert list(parsed) == ["schema", "key"]
    assert parsed["schema"] == REFERENCE_SCHEMA
    assert _KEY.match(parsed["key"])
    artifact = spool.redeem(ref)
    assert artifact is not None
    encoded = text.encode()
    assert artifact.size_bytes == len(encoded)
    assert artifact.sha256 == hashlib.sha256(encoded).hexdigest()
    assert (art / artifact.id).read_bytes() == encoded
    assert _names(art) == [artifact.id]


@pytest.mark.parametrize("with_store", [True, False])
@pytest.mark.parametrize("size", [99, 100, 101, 999, 1000, 1001])
@pytest.mark.parametrize(("inline_cap", "hard_cap"), [(100, 1000), (1000, 100)])
def test_the_spool_gives_the_same_verdict_as_decide_result_delivery(
    tmp_path: Path, inline_cap: int, hard_cap: int, size: int, with_store: bool
) -> None:
    art = tmp_path / "art"
    spool = _spool(art, inline_cap=inline_cap, hard_cap=hard_cap, with_store=with_store)
    text = _text(size)
    assert len(text.encode()) == size
    expected = decide_result_delivery(
        size, inline_cap=inline_cap, hard_cap=hard_cap, spill_available=with_store
    )
    if expected is ResultDelivery.TOO_LARGE:
        with pytest.raises(ResultTooLarge) as caught:
            spool.deliver(_writer(text))
        allowed = allowed_result_bytes(inline_cap, hard_cap, spill_available=with_store)
        assert str(caught.value) == f"result is {size} bytes, cap is {allowed} bytes"
        assert _names(art) == []
    elif expected is ResultDelivery.INLINE:
        assert spool.deliver(_writer(text)) == text
        assert _names(art) == []
    else:
        _check_spill(spool, art, spool.deliver(_writer(text)), text)


def test_the_too_large_message_matches_build_result(tmp_path: Path) -> None:
    text = _text(200)
    with pytest.raises(ResolutionError) as old:
        _RunState().build_result(
            text, inline_cap=100, hard_cap=150, store=FilesystemArtifactStore(tmp_path / "held")
        )
    spool = _spool(tmp_path / "art", inline_cap=100, hard_cap=150)
    with pytest.raises(ResultTooLarge) as new:
        spool.deliver(_writer(text))
    assert str(old.value) == str(new.value)
    assert (new.value.size, new.value.allowed) == (200, 150)


def test_redeem_is_none_when_nothing_was_issued(tmp_path: Path) -> None:
    assert _spool(tmp_path / "art", inline_cap=100, hard_cap=1000).redeem("{}") is None


def test_an_issued_reference_redeems_and_any_other_body_fails_closed(tmp_path: Path) -> None:
    spool = _spool(tmp_path / "art", inline_cap=100, hard_cap=1000)
    ref = _spill(spool)
    artifact = spool.redeem(ref)
    assert isinstance(artifact, ResultArtifact)
    with pytest.raises(UnredeemedResultReference):
        spool.redeem('{"a":1}')
    with pytest.raises(UnredeemedResultReference):
        spool.redeem("x" * 5000)


def test_another_spool_does_not_redeem_a_reference(tmp_path: Path) -> None:
    first = _spool(tmp_path / "a", inline_cap=100, hard_cap=1000)
    second = _spool(tmp_path / "b", inline_cap=100, hard_cap=1000)
    ref = _spill(first)
    assert second.redeem(ref) is None
    _spill(second, 400)
    with pytest.raises(UnredeemedResultReference):
        second.redeem(ref)


def test_two_deliveries_issue_two_random_references(tmp_path: Path) -> None:
    spool = _spool(tmp_path / "art", inline_cap=100, hard_cap=1000)
    ref1 = _spill(spool, 300)
    ref2 = _spill(spool, 400)
    assert ref1 != ref2
    first = spool.redeem(ref1)
    second = spool.redeem(ref2)
    assert first is not None and second is not None
    assert (first.size_bytes, second.size_bytes) == (300, 400)


def test_close_inside_the_body_stops_the_next_chunk_and_aborts_the_sink(tmp_path: Path) -> None:
    art = tmp_path / "art"
    spool = _spool(art, inline_cap=100, hard_cap=1000)

    def write_body(write: Callable[[str], None]) -> None:
        write(_text(300))
        spool.close()
        write("more")

    with pytest.raises(ResultSpoolClosed):
        spool.deliver(write_body)
    assert _names(art) == []


def _deliver_recording(
    spool: ResultSpool, write_body: WriteBody, errors: list[BaseException], done: threading.Event
) -> None:
    """Thread target: deliver, record what it raised, and always set `done` (no hang)."""

    try:
        spool.deliver(write_body)
    except BaseException as exc:
        errors.append(exc)
    finally:
        done.set()


def test_close_from_another_thread_stops_the_writer(tmp_path: Path) -> None:
    art = tmp_path / "art"
    spool = _spool(art, inline_cap=100, hard_cap=1000)
    started = threading.Event()
    proceed = threading.Event()
    errors: list[BaseException] = []

    def write_body(write: Callable[[str], None]) -> None:
        write(_text(300))
        started.set()
        proceed.wait()
        write("more")

    thread = threading.Thread(target=_deliver_recording, args=(spool, write_body, errors, started))
    thread.start()
    started.wait()
    spool.close()
    proceed.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], ResultSpoolClosed)
    assert _names(art) == []


def test_deliver_after_close_raises_closed(tmp_path: Path) -> None:
    art = tmp_path / "art"
    spool = _spool(art, inline_cap=100, hard_cap=1000)
    spool.close()
    spool.close()  # idempotent
    with pytest.raises(ResultSpoolClosed):
        spool.deliver(_writer("ok"))
    assert _names(art) == []


def test_a_lone_surrogate_fails_the_delivery(tmp_path: Path) -> None:
    art = tmp_path / "art"
    spool = _spool(art, inline_cap=1, hard_cap=1000)
    with pytest.raises(UnicodeEncodeError):
        spool.deliver(_writer("ok\ud800"))
    assert _names(art) == []


class _FullDiskSink:
    def __init__(self) -> None:
        self.aborted = False

    def write(self, chunk: bytes) -> None:
        raise OSError("disk full")

    def commit(self) -> ResultArtifact:  # pragma: no cover - write fails first
        raise AssertionError("commit after a failed write")

    def abort(self) -> None:
        self.aborted = True


class _FullDiskStore:
    def __init__(self) -> None:
        self.sink = _FullDiskSink()

    def open_sink(self) -> ArtifactSink:
        return self.sink


def test_a_sink_failure_propagates_as_itself() -> None:
    store = _FullDiskStore()
    spool = ResultSpool(store, inline_cap=100, hard_cap=1000)
    with pytest.raises(OSError, match="disk full") as caught:
        spool.deliver(_writer(_text(300)))
    assert not isinstance(caught.value, ResultSpoolError)
    assert store.sink.aborted


def test_the_binding_is_scoped(tmp_path: Path) -> None:
    spool = _spool(tmp_path / "art", inline_cap=100, hard_cap=1000)
    assert bound_result_spool() is None
    with binding_result_spool(spool):
        assert bound_result_spool() is spool
    assert bound_result_spool() is None

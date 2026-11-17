"""The filesystem adapter's streaming sink (memory fix 3, OME-1835).

WHY these tests: a streamed result must land under the SAME id as a whole-buffer write of the
same bytes, or a ticket minted on one path would not redeem on the other. Each test names one
rule of the sink's lifecycle: commit publishes, abort cleans up, and a closed sink refuses.
"""

import hashlib
import os
import re
import time
from pathlib import Path

import pytest

from screamingface_engine.artifacts import (
    ArtifactSink,
    FilesystemArtifactStore,
    StreamingArtifactWriter,
)


def test_a_committed_sink_holds_the_content_under_its_sha256(tmp_path: Path) -> None:
    root = tmp_path / "art"
    sink = FilesystemArtifactStore(root).open_sink()
    parts = [b"hello ", "wörld 😀".encode()]
    for part in parts:
        sink.write(part)
    artifact = sink.commit()
    joined = b"".join(parts)
    assert artifact.id == hashlib.sha256(joined).hexdigest() == artifact.sha256
    assert artifact.size_bytes == len(joined)
    assert (root / artifact.id).read_bytes() == joined
    assert sorted(p.name for p in root.iterdir()) == [artifact.id]


def test_the_ticket_equals_write_bytes_for_the_same_content(tmp_path: Path) -> None:
    data = "wörld 😀 and some more text".encode()
    sink = FilesystemArtifactStore(tmp_path / "a").open_sink()
    sink.write(data[:5])
    sink.write(data[5:])
    streamed = sink.commit()
    whole = FilesystemArtifactStore(tmp_path / "b").write_bytes(data)
    assert streamed == whole


def test_a_dedup_hit_restamps_mtime_and_leaves_no_temp_file(tmp_path: Path) -> None:
    data = b"already here"
    store = FilesystemArtifactStore(tmp_path / "art")
    artifact = store.write_bytes(data)
    root = tmp_path / "art"
    os.utime(root / artifact.id, (1000, 1000))
    sink = store.open_sink()
    sink.write(data)
    sink.commit()
    assert (root / artifact.id).stat().st_mtime > 1000
    assert sorted(p.name for p in root.iterdir()) == [artifact.id]


def test_the_temp_file_lives_in_the_store_root_while_writing(tmp_path: Path) -> None:
    root = tmp_path / "art"
    store = FilesystemArtifactStore(root)
    sink = store.open_sink()
    sink.write(b"x")
    names = [p.name for p in root.iterdir()]
    assert len(names) == 1 and re.fullmatch(r"\.[0-9a-f]{32}\.tmp", names[0])
    sink.abort()


def test_abort_leaves_no_object_and_no_temp_file(tmp_path: Path) -> None:
    root = tmp_path / "art"
    sink = FilesystemArtifactStore(root).open_sink()
    sink.write(b"never published")
    sink.abort()
    sink.abort()
    assert list(root.iterdir()) == []


def test_write_or_commit_after_commit_or_abort_raises(tmp_path: Path) -> None:
    root = tmp_path / "art"
    store = FilesystemArtifactStore(root)

    committed = store.open_sink()
    committed.write(b"kept")
    artifact = committed.commit()
    with pytest.raises(ValueError):
        committed.write(b"more")
    with pytest.raises(ValueError):
        committed.commit()
    committed.abort()
    assert (root / artifact.id).read_bytes() == b"kept"

    aborted = store.open_sink()
    aborted.write(b"dropped")
    aborted.abort()
    with pytest.raises(ValueError):
        aborted.write(b"more")
    with pytest.raises(ValueError):
        aborted.commit()


def test_an_empty_sink_cannot_commit(tmp_path: Path) -> None:
    root = tmp_path / "art"
    sink = FilesystemArtifactStore(root).open_sink()
    with pytest.raises(ValueError):
        sink.commit()
    assert list(root.iterdir()) == []


def test_the_sweeper_reaps_an_abandoned_sink_temp_file(tmp_path: Path) -> None:
    root = tmp_path / "art"
    store = FilesystemArtifactStore(root)
    sink = store.open_sink()
    sink.write(b"x")
    assert store.sweep(0, now=time.time() + 10) == 1
    assert list(root.iterdir()) == []
    sink.abort()


def test_the_store_satisfies_the_streaming_port(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path / "art")
    assert isinstance(store, StreamingArtifactWriter)
    sink = store.open_sink()
    assert isinstance(sink, ArtifactSink)
    sink.abort()

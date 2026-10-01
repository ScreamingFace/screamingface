from __future__ import annotations

import errno
import io
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

import pytest

from screamingface._atomic_file import write_atomic


@contextmanager
def umask(value: int) -> Iterator[None]:
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


_UMASK = 0o022


def _content(data: bytes) -> Callable[[BinaryIO], None]:
    def write(fp: BinaryIO) -> None:
        fp.write(data)

    return write


def _siblings(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


def test_write_atomic_writes_a_new_file_and_returns_its_path(tmp_path: Path) -> None:
    target = tmp_path / "report.json"

    final = write_atomic(target, _content(b"new"))

    assert final == Path(os.path.realpath(target))
    assert target.read_bytes() == b"new"
    assert _siblings(tmp_path) == ["report.json"]


def test_write_atomic_replaces_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"old content that is longer")

    write_atomic(target, _content(b"new"))

    assert target.read_bytes() == b"new"
    assert _siblings(tmp_path) == ["report.json"]


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("boom"), OSError(errno.ENOSPC, "No space left on device")],
    ids=["runtime-error", "disk-full"],
)
def test_write_atomic_keeps_the_old_file_and_removes_the_temp_file_on_failure(
    tmp_path: Path,
    failure: Exception,
) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"previous complete content")

    def write(fp: BinaryIO) -> None:
        fp.write(b"partial")
        raise failure

    with pytest.raises(type(failure)) as raised:
        write_atomic(target, write)

    assert raised.value is failure
    assert target.read_bytes() == b"previous complete content"
    assert _siblings(tmp_path) == ["report.json"]


def test_write_atomic_failure_without_an_old_file_leaves_nothing(tmp_path: Path) -> None:
    target = tmp_path / "report.json"

    def write(fp: BinaryIO) -> None:
        fp.write(b"partial")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        write_atomic(target, write)

    assert _siblings(tmp_path) == []


def test_write_atomic_names_the_temp_file_as_a_hidden_sibling(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    seen: list[str] = []

    def write(fp: BinaryIO) -> None:
        seen.extend(_siblings(tmp_path))

    write_atomic(target, write)

    assert len(seen) == 1
    assert seen[0].startswith(".report.json.")
    assert seen[0].endswith(".tmp")


def test_write_atomic_replaces_the_symlink_target_and_keeps_the_link(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    real = data / "out.json"
    real.write_bytes(b"old")
    link = tmp_path / "report.json"
    link.symlink_to(real)

    final = write_atomic(link, _content(b"new"))

    assert link.is_symlink()
    assert real.read_bytes() == b"new"
    assert final == Path(os.path.realpath(real))
    assert _siblings(data) == ["out.json"]
    assert _siblings(tmp_path) == ["data", "report.json"]


def test_write_atomic_gives_a_new_file_the_default_mode_for_the_umask(tmp_path: Path) -> None:
    target = tmp_path / "report.json"

    with umask(_UMASK):
        write_atomic(target, _content(b"new"))

    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~_UMASK


def test_write_atomic_keeps_the_mode_of_the_file_it_replaces(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"old")
    target.chmod(0o640)

    with umask(_UMASK):
        write_atomic(target, _content(b"new"))

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_write_atomic_copies_only_permission_bits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY observed through os.chmod: the kernel clears setuid on a later write, so the
    # final mode alone cannot show whether the bit was ever copied.
    target = tmp_path / "report.json"
    target.write_bytes(b"old")
    target.chmod(0o4644)
    assert stat.S_IMODE(target.stat().st_mode) == 0o4644
    requested: list[int] = []
    real_chmod = os.chmod

    def recording_chmod(path: Path, mode: int) -> None:
        requested.append(mode)
        real_chmod(path, mode)

    monkeypatch.setattr(os, "chmod", recording_chmod)

    write_atomic(target, _content(b"new"))

    assert requested
    assert all(mode & 0o7000 == 0 for mode in requested)
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_write_atomic_private_file_is_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_bytes(b"old")
    target.chmod(0o644)

    with umask(_UMASK):
        write_atomic(target, _content(b"new"), private=True)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


class _FullDiskWriter(io.BufferedWriter):
    """A buffered writer whose flush, and so its close, fails like a full disk."""

    def flush(self) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")


def test_write_atomic_failure_cleanup_never_replaces_the_original_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "report.json"
    target.write_bytes(b"previous complete content")

    def full_disk_fdopen(fd: int, mode: str, buffering: int) -> io.BufferedWriter:
        return _FullDiskWriter(io.FileIO(fd, mode), buffering)

    monkeypatch.setattr(os, "fdopen", full_disk_fdopen)

    def write(fp: BinaryIO) -> None:
        fp.write(b"x" * (2 * 1024 * 1024))
        raise ValueError("the real cause")

    with pytest.raises(ValueError, match="the real cause"):
        write_atomic(target, write)

    assert target.read_bytes() == b"previous complete content"
    assert _siblings(tmp_path) == ["report.json"]

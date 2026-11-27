"""Local blob files are private: directories 0700, files 0600, a root owned by another user refused.

INVARIANT (RR-S13): each directory below the blob root and the root are 0700, each file 0600,
whatever the umask. A root owned by another user stops the start before any write.
WHY POSIX only: the modes and the owner check are POSIX concepts.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.artifacts.blob_objects import BlobRootNotPrivate, FilesystemBlobObjects
from screamingface_engine.artifacts.wiring import blob_objects_from_values

pytestmark = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.parametrize("mask", [0o000, 0o022, 0o077], ids=["umask-000", "umask-022", "umask-077"])
def test_blob_dirs_are_0700_and_files_0600_for_each_umask(tmp_path: Path, mask: int) -> None:
    old = os.umask(mask)
    try:
        root = tmp_path / "store"
        objects = FilesystemBlobObjects(root)
        objects.put("blobs/aa/bb/one", b"x")
        assert objects.create("blobs/aa/cc/two", b"y") is True
    finally:
        os.umask(old)

    for directory in (
        root,
        root / "blobs",
        root / "blobs/aa",
        root / "blobs/aa/bb",
        root / "blobs/aa/cc",
    ):
        assert _mode(directory) == 0o700, directory
    assert _mode(root / "blobs/aa/bb/one") == 0o600
    assert _mode(root / "blobs/aa/cc/two") == 0o600
    assert list(root.rglob("*.tmp")) == []


def test_a_wide_root_is_narrowed(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    os.chmod(root, 0o755)

    FilesystemBlobObjects(root)

    assert _mode(root) == 0o700


def test_a_foreign_root_is_refused_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    monkeypatch.setattr(os, "geteuid", lambda: root.stat().st_uid + 1)

    with pytest.raises(BlobRootNotPrivate):
        FilesystemBlobObjects(root)
    assert list(root.iterdir()) == []

    # WHY the wiring case too: local mode must not start when the root is foreign.
    with pytest.raises(BlobRootNotPrivate):
        blob_objects_from_values({job_env.BLOB_STORE: "filesystem", job_env.BLOBS_DIR: str(root)})


def test_a_missing_root_is_made_private_on_first_write(tmp_path: Path) -> None:
    root = tmp_path / "store"

    objects = FilesystemBlobObjects(root)
    objects.put("blobs/aa/bb/one", b"x")

    assert _mode(root) == 0o700

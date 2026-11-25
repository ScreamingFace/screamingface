"""A blob root that appears after construction is checked before the first write (RR-S13).

INVARIANT (RR-S13): a root owned by another user is refused at construction and before each write
into a root that already exists. A root made after the start is narrowed to 0700 at the first write.
WHY POSIX only: the modes and the owner check are POSIX concepts.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from screamingface_engine.artifacts.blob_objects import BlobRootNotPrivate, FilesystemBlobObjects

pytestmark = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_a_root_made_after_start_is_narrowed_at_the_first_write(tmp_path: Path) -> None:
    root = tmp_path / "store"
    objects = FilesystemBlobObjects(root)

    root.mkdir()
    os.chmod(root, 0o755)
    objects.put("blobs/aa/bb/one", b"x")

    assert _mode(root) == 0o700


def test_a_foreign_root_made_after_start_is_refused_before_the_first_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "store"
    objects = FilesystemBlobObjects(root)

    root.mkdir()
    monkeypatch.setattr(os, "geteuid", lambda: root.stat().st_uid + 1)

    with pytest.raises(BlobRootNotPrivate):
        objects.put("blobs/aa/bb/one", b"x")
    assert list(root.iterdir()) == []

    with pytest.raises(BlobRootNotPrivate):
        objects.create("blobs/aa/cc/two", b"y")
    assert list(root.iterdir()) == []

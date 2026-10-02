"""Replace a file only when its new content was written completely."""

from __future__ import annotations

import contextlib
import os
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

_WRITE_BUFFER_BYTES = 1024 * 1024


def write_atomic(
    target: Path,
    write: Callable[[BinaryIO], None],
    *,
    private: bool = False,
) -> Path:
    """Write `target` through a sibling temp file; replace it only on success.

    Returns the final (symlink-resolved) path. Parent directories are the caller's job.
    """
    # WHY resolve first: replacing a symlink path would swap the link for a regular file.
    # Resolving makes the link's target get the new content and the link stay a link.
    final = Path(os.path.realpath(target))
    temporary = final.parent / f".{final.name}.{uuid.uuid4().hex}.tmp"
    # WHY the creation mode and no os.umask: the kernel applies the umask to 0o666 for us,
    # and os.umask is process-global, so changing it here would race other threads.
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o666)
    fp = os.fdopen(fd, "wb", buffering=_WRITE_BUFFER_BYTES)
    try:
        _match_mode(temporary, final, private=private)
        write(fp)
        fp.flush()
        os.fsync(fp.fileno())
        fp.close()
        os.replace(temporary, final)
        # INVARIANT: on POSIX, persist the directory entry after the file's data.
        # A failure here means replacement happened but durability is unconfirmed.
        _sync_directory(final.parent)
    except BaseException:
        # INVARIANT: cleanup never raises over the original error. Closing a buffered file
        # flushes it, so on a full disk the close itself can fail and would replace the cause.
        with contextlib.suppress(OSError):
            fp.close()
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise
    return final


def _sync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _match_mode(temporary: Path, final: Path, *, private: bool) -> None:
    if private:
        os.chmod(temporary, 0o600)
        return
    try:
        existing = os.stat(final).st_mode
    except FileNotFoundError:
        return
    # WHY only the permission bits: a copied setuid or setgid bit would grant new privilege
    # to content the old file's owner never vouched for.
    os.chmod(temporary, stat.S_IMODE(existing) & 0o777)


__all__: list[str] = []

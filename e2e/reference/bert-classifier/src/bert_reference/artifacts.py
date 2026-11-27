"""Offline artifact verification."""

import hashlib
import io
import os
import re
import stat
from collections.abc import Generator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import cast

from ._json import decode_object

ARTIFACT_ROOT = "SF_BERT_REFERENCE_ARTIFACT_ROOT"
MANIFEST_SHA256 = "SF_BERT_REFERENCE_MANIFEST_SHA256"
_MANIFEST = "manifest.json"
_HASH = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_IDENTITY = {
    "schema": "screamingface.bert-reference-artifacts.v1",
    "model": "distilbert/distilbert-base-uncased-finetuned-sst-2-english",
    "revision": "714eb0fa89d2f80546fda750413ed43d93601a13",
    "license": "Apache-2.0",
}


class ArtifactError(ValueError):
    """A snapshot failed verification."""


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    size_bytes: int
    sha256: str


def _file_entry(row: object) -> FileEntry:
    if not isinstance(row, dict):
        raise ArtifactError("invalid manifest file entry")
    record = cast(dict[str, object], row)
    if record.keys() != {"path", "size_bytes", "sha256"}:
        raise ArtifactError("invalid manifest file keys")
    path, size, digest = record["path"], record["size_bytes"], record["sha256"]
    if not isinstance(path, str) or not _NAME.fullmatch(path) or path == _MANIFEST:
        raise ArtifactError("invalid artifact filename")
    if type(size) is not int or not 0 <= size <= 2**63 - 1:
        raise ArtifactError("invalid artifact size")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ArtifactError("invalid artifact digest")
    return FileEntry(path, size, digest)


def parse_manifest(data: bytes) -> tuple[FileEntry, ...]:
    try:
        document = decode_object(data)
    except (ValueError, RecursionError):
        raise ArtifactError("invalid artifact manifest JSON") from None
    if document.keys() != _IDENTITY.keys() | {"files"} or any(
        document[key] != value for key, value in _IDENTITY.items()
    ):
        raise ArtifactError("invalid artifact manifest identity or keys")
    rows = document["files"]
    if not isinstance(rows, list) or not rows:
        raise ArtifactError("invalid artifact file list")
    entries = tuple(_file_entry(row) for row in cast(list[object], rows))
    names = [entry.path for entry in entries]
    if names != sorted(set(names)):
        raise ArtifactError("manifest paths must be unique and sorted")
    return entries


@contextmanager
def _open_root(path: str) -> Generator[int]:
    parts = PurePosixPath(path).parts
    if not parts or parts[0] != "/" or ".." in parts or "\0" in path:
        raise ArtifactError("artifact root must be an absolute directory")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    # INVARIANT: no intermediate path component may alias a directory outside the chosen tree.
    with ExitStack() as stack:
        directory = os.open("/", flags)
        stack.callback(os.close, directory)
        for part in parts[1:]:
            directory = os.open(part, flags, dir_fd=directory)
            stack.callback(os.close, directory)
        yield directory


def _read_verified(directory: int, name: str, digest: str, size: int | None = None) -> bytes:
    initial = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if not stat.S_ISREG(initial.st_mode):
        raise ArtifactError("artifact must be a regular file")
    # WHY NONBLOCK: a file replaced by a FIFO between stat and open must not hang startup.
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(initial, opened):
            raise ArtifactError("artifact changed while opening")
        expected_size = opened.st_size if size is None else size
        if opened.st_size != expected_size:
            raise ArtifactError("artifact size mismatch")
        # INVARIANT: hash the exact bytes retained for loading, never reopen the source by path.
        buffer = io.BytesIO()
        hasher = hashlib.sha256()
        remaining = expected_size
        while chunk := os.read(fd, min(remaining + 1, 1024 * 1024)):
            remaining -= len(chunk)
            if remaining < 0:
                raise ArtifactError("artifact size mismatch")
            hasher.update(chunk)
            buffer.write(chunk)
        if remaining or hasher.hexdigest() != digest:
            raise ArtifactError("artifact size or digest mismatch")
        return buffer.getvalue()
    finally:
        os.close(fd)


def verify_snapshot(environment: Mapping[str, str]) -> Mapping[str, bytes]:
    """Return immutable, verified file bytes without exposing the source path to the loader."""
    path = environment.get(ARTIFACT_ROOT, "")
    digest = environment.get(MANIFEST_SHA256, "")
    if not _HASH.fullmatch(digest):
        raise ArtifactError("missing or invalid expected manifest digest")
    try:
        with _open_root(path) as directory:
            entries = parse_manifest(_read_verified(directory, _MANIFEST, digest))
            inventory = {_MANIFEST, *(entry.path for entry in entries)}
            if set(os.listdir(directory)) != inventory:
                raise ArtifactError("artifact inventory mismatch")
            files = {
                entry.path: _read_verified(directory, entry.path, entry.sha256, entry.size_bytes)
                for entry in entries
            }
            if set(os.listdir(directory)) != inventory:
                raise ArtifactError("artifact inventory changed during verification")
    except OSError:
        raise ArtifactError("artifact tree cannot be read safely") from None
    return MappingProxyType(files)

"""The content check runs only on bytes whose digest is right.

FEATURE: chat-run erd §1.1 - the policy content check (a full JSON and pydantic parse) runs only
after the cheap media type, signature, size and digest checks pass (F11).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from screamingface_engine.artifacts.blob_objects import FilesystemBlobObjects
from screamingface_engine.artifacts.blob_schema import (
    BlobContentMismatch,
    BlobDigestMismatch,
    BlobPolicy,
)
from screamingface_engine.artifacts.blobs import BlobScope, BlobStore

RUN = "a" * 64
JSON_TYPE = "application/json"


def test_ingest_checks_the_digest_before_the_content(tmp_path: Path) -> None:
    seen: list[bytes] = []

    def refuse(body: bytes) -> bool:
        seen.append(body)
        return False

    policy = BlobPolicy(max_bytes=1024, media_types=frozenset({JSON_TYPE}), content_check=refuse)
    store = BlobStore(FilesystemBlobObjects(tmp_path), policy)
    scope = BlobScope.for_caller(None, RUN)
    body = b"{}"

    with pytest.raises(BlobDigestMismatch):
        store.ingest(scope, "0" * 64, JSON_TYPE, body)
    assert seen == []

    with pytest.raises(BlobContentMismatch):
        store.ingest(scope, hashlib.sha256(body).hexdigest(), JSON_TYPE, body)
    assert seen == [body]

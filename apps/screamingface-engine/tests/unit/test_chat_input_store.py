"""The chat-input store: a second blob store for CHAT_INPUT records only (chat-run erd §1.1).

FEATURE: chat-run. The App ingests a chat input, the Runner reads it back, and both halves
build the store through one function, so they cannot disagree on the policy.

INVARIANT: the attachment policy is unchanged. A chat input is accepted only when its bytes
parse as a CHAT_INPUT record, and an attachment media type is refused by the chat-input store.
"""

from __future__ import annotations

import hashlib

import pytest

from screamingface_engine import job_env
from screamingface_engine.artifacts.blob_objects import FilesystemBlobObjects
from screamingface_engine.artifacts.blob_schema import (
    ATTACHMENT_MEDIA_TYPES,
    BlobContentMismatch,
    BlobPolicy,
    BlobScope,
    BlobTooLarge,
    BlobUnsupportedMediaType,
)
from screamingface_engine.artifacts.blobs import ScopedBlobReader
from screamingface_engine.artifacts.chat_inputs import chat_input_store
from screamingface_engine.artifacts.wiring import (
    BlobStoreNotConfigured,
    chat_input_reader_from_env,
    chat_input_store_from_values,
)
from screamingface_engine.chat.input import (
    CHAT_INPUT_MEDIA_TYPE,
    CHAT_INPUT_SCHEMA,
    MAX_CHAT_INPUT_BYTES,
    decode_chat_input,
    encode_chat_input,
)
from screamingface_engine.chat.wire import canonical_json

RUN = "a" * 64
PDF_TYPE = "application/pdf"


def _record() -> bytes:
    value = {"schema": CHAT_INPUT_SCHEMA, "messages": [{"role": "user", "content": "hi"}]}
    return encode_chat_input(decode_chat_input(canonical_json(value)))


def test_chat_input_over_cap_after_encoding_is_refused_at_ingest(tmp_path) -> None:
    store = chat_input_store(FilesystemBlobObjects(tmp_path))
    body = b"x" * (MAX_CHAT_INPUT_BYTES + 1)
    sha = hashlib.sha256(body).hexdigest()

    with pytest.raises(BlobTooLarge):
        store.ingest(BlobScope.for_caller(None, RUN), sha, CHAT_INPUT_MEDIA_TYPE, body)


@pytest.mark.asyncio
async def test_chat_input_store_round_trips_a_valid_record(tmp_path) -> None:
    store = chat_input_store(FilesystemBlobObjects(tmp_path))
    scope = BlobScope.for_caller(None, RUN)
    body = _record()
    sha = hashlib.sha256(body).hexdigest()

    blob, created = store.ingest(scope, sha, CHAT_INPUT_MEDIA_TYPE, body)

    assert created is True
    assert blob.size_bytes == len(body)
    assert await ScopedBlobReader(store, scope).read("sha256:" + sha) == body


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"schema": "screamingface.chat-input.v9",'
        b' "messages": [{"role": "user", "content": "hi"}]}',
        b"[1, 2]",
    ],
    ids=["not-json", "unknown-schema", "json-array"],
)
def test_chat_input_store_refuses_a_body_that_is_not_a_chat_input(tmp_path, body: bytes) -> None:
    store = chat_input_store(FilesystemBlobObjects(tmp_path))
    sha = hashlib.sha256(body).hexdigest()

    with pytest.raises(BlobContentMismatch):
        store.ingest(BlobScope.for_caller(None, RUN), sha, CHAT_INPUT_MEDIA_TYPE, body)


def test_chat_input_store_refuses_attachment_media_types(tmp_path) -> None:
    store = chat_input_store(FilesystemBlobObjects(tmp_path))
    body = b"%PDF-1.7\n" + b"x" * 20
    sha = hashlib.sha256(body).hexdigest()

    with pytest.raises(BlobUnsupportedMediaType):
        store.ingest(BlobScope.for_caller(None, RUN), sha, PDF_TYPE, body)


def test_the_attachment_policy_is_unchanged() -> None:
    assert BlobPolicy().content_check is None
    assert CHAT_INPUT_MEDIA_TYPE not in ATTACHMENT_MEDIA_TYPES


@pytest.mark.asyncio
async def test_chat_input_reader_from_env_reads_the_shared_store(tmp_path) -> None:
    writer_env = {job_env.BLOB_STORE: "filesystem", job_env.BLOBS_DIR: str(tmp_path)}
    body = _record()
    sha = hashlib.sha256(body).hexdigest()
    chat_input_store_from_values(writer_env).ingest(
        BlobScope.for_caller(None, RUN), sha, CHAT_INPUT_MEDIA_TYPE, body
    )

    reader = chat_input_reader_from_env({**writer_env, job_env.TOPIC: RUN})

    assert await reader.read("sha256:" + sha) == body
    with pytest.raises(BlobStoreNotConfigured):
        chat_input_reader_from_env({})

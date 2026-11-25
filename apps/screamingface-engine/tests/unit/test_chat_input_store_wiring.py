"""The chat-input store is wired into the App and the Runner, and the local App defaults to disk.

FEATURE: chat-run (erd §1.1, contracts C4 and C6, plan D3). The App and the Runner build the
chat-input store through one function, the public PUT /blob keeps the attachment store, and the
local App sets a filesystem blob store that both halves read.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from test_blob_routes import _app, _client, _put

from screamingface_engine import job_env
from screamingface_engine.app import create_app
from screamingface_engine.artifacts.blob_schema import BlobDigestMismatch, BlobScope
from screamingface_engine.artifacts.wiring import (
    blob_reader_from_env,
    chat_input_reader_from_env,
)
from screamingface_engine.chat.input import (
    CHAT_INPUT_MEDIA_TYPE,
    CHAT_INPUT_SCHEMA,
    decode_chat_input,
    encode_chat_input,
)
from screamingface_engine.chat.wire import canonical_json
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.testing import InMemoryEventStream

RUN = "a" * 64
EMAIL = "alice@example.org"


def _record() -> bytes:
    value = {"schema": CHAT_INPUT_SCHEMA, "messages": [{"role": "user", "content": "hi"}]}
    return encode_chat_input(decode_chat_input(canonical_json(value)))


@pytest.mark.asyncio
async def test_public_put_refuses_chat_input_media_type(tmp_path: Path) -> None:
    body = _record()
    sha = hashlib.sha256(body).hexdigest()
    app = _app(tmp_path)

    async with _client(app) as client:
        response = await _put(
            client,
            body=body,
            path=f"/blob/sha256/{sha}",
            media_type=CHAT_INPUT_MEDIA_TYPE,
        )

    assert response.status_code == 415
    assert response.json()["code"] == "x.blob_unsupported_media_type"


@pytest.mark.asyncio
async def test_runner_reads_chat_input_written_by_app_store(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "jwt_secret": "s",
            "blob_store": "filesystem",
            "blobs_dir": str(tmp_path),
            "artifacts_dir": str(tmp_path / "artifacts"),
        }
    )
    app = create_app(settings, stream=InMemoryEventStream())
    body = _record()
    sha = hashlib.sha256(body).hexdigest()
    store = app.state.chat_input_store
    store.ingest(BlobScope.for_caller(EMAIL, RUN), sha, CHAT_INPUT_MEDIA_TYPE, body)
    env = {
        job_env.BLOB_STORE: "filesystem",
        job_env.BLOBS_DIR: str(tmp_path),
        job_env.TOPIC: RUN,
        **job_env.identity_to_env({"X-User-Email": EMAIL}),
    }

    assert await chat_input_reader_from_env(env).read("sha256:" + sha) == body
    with pytest.raises(BlobDigestMismatch):
        await blob_reader_from_env(env).read("sha256:" + sha)


def test_the_app_has_no_chat_input_store_without_a_blob_store() -> None:
    app = create_app(Settings(jwt_secret="s"), stream=InMemoryEventStream())

    assert app.state.chat_input_store is None


def test_local_app_defaults_to_a_filesystem_blob_store(tmp_path: Path) -> None:
    app = create_local_app(
        Settings.model_validate({"jwt_secret": "s", "blobs_dir": str(tmp_path)}), env={}
    )

    base_env = app.state.job_runner._base_env  # noqa: SLF001 - the run env is the contract
    assert app.state.blob_store is not None
    assert app.state.chat_input_store is not None
    assert base_env[job_env.BLOB_STORE] == "filesystem"
    assert base_env[job_env.BLOBS_DIR] == str(tmp_path)


def test_local_app_mirrors_an_explicit_blob_store_into_the_run_env(tmp_path: Path) -> None:
    app = create_local_app(
        Settings.model_validate(
            {
                "jwt_secret": "s",
                "blob_store": "filesystem",
                "blobs_dir": str(tmp_path),
            }
        ),
        env={job_env.BLOB_STORE: "s3", job_env.BLOB_S3_BUCKET: "other"},
    )

    base_env = app.state.job_runner._base_env  # noqa: SLF001 - the run env is the contract
    assert base_env[job_env.BLOB_STORE] == "filesystem"
    assert base_env[job_env.BLOBS_DIR] == str(tmp_path)
    assert job_env.BLOB_S3_BUCKET not in base_env
    assert app.state.blob_store is not None


def test_the_app_chat_input_store_shares_the_blob_objects(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "jwt_secret": "s",
            "blob_store": "filesystem",
            "blobs_dir": str(tmp_path),
            "artifacts_dir": str(tmp_path / "artifacts"),
        }
    )
    app = create_app(settings, stream=InMemoryEventStream())

    assert app.state.chat_input_store.objects is app.state.blob_store.objects

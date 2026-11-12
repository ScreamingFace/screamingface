"""E5 P2 spec D9a, D9b, §4.4 and R13: one contract over both `RunResultStore` adapters.

FEATURE: a detached Run (OME-1837). STORY: as a researcher reattaching from another machine, I
fetch every Candidate's result and my Run's context from the Engine, for the Run's 30 days.

The S3 adapter runs against `httpx.MockTransport`, so a test asserts on the request actually
sent, as `test_s3_artifact_store.py` does; the filesystem adapter against a temporary folder.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from screamingface_engine.artifacts import LocalFile, RemoteStream
from screamingface_engine.artifacts.run_results import (
    FilesystemRunResultStore,
    RunResultStore,
    RunResultStoreUnavailable,
    S3RunResultStore,
    context_key,
    result_key,
    result_prefix,
    write_result,
)
from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config
from screamingface_engine.artifacts.sigv4 import Credentials

RUN = "run_" + "a" * 32
BODY = b'{"answer": "B", "score": 1.0}'
DIGEST = hashlib.sha256(BODY).hexdigest()


class _FakeS3:
    """Objects keyed by their whole path, and the requests it saw."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.failures = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            self.failures -= 1
            return httpx.Response(503, text="<Code>SlowDown</Code>")
        return getattr(self, f"_{request.method.lower()}")(request.url.path, request)

    def _put(self, path: str, request: httpx.Request) -> httpx.Response:
        self.objects[path] = request.content
        return httpx.Response(200)

    def _delete(self, path: str, _request: httpx.Request) -> httpx.Response:
        self.objects.pop(path, None)
        return httpx.Response(204)

    def _head(self, path: str, _request: httpx.Request) -> httpx.Response:
        if path not in self.objects:
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-length": str(len(self.objects[path]))})

    def _get(self, path: str, _request: httpx.Request) -> httpx.Response:
        if path not in self.objects:
            return httpx.Response(404)
        return httpx.Response(200, content=self.objects[path])


def _s3(fake: _FakeS3) -> S3RunResultStore:
    config = S3Config(
        endpoint_url="http://garage.svc:3900",
        bucket="run-results",
        credentials=Credentials(access_key="GKtest", secret_key="secret", region="garage"),
    )
    return S3RunResultStore(
        S3ArtifactStore(
            config,
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(fake.handle)),
            async_client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(fake.handle)
            ),
        )
    )


@pytest.fixture(params=["s3", "filesystem"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> RunResultStore:
    if request.param == "s3":
        return _s3(_FakeS3())
    return FilesystemRunResultStore(tmp_path / "run-results")


async def _read(store: RunResultStore, key: str) -> bytes | None:
    content = store.open(key)
    if content is None:
        return None
    if isinstance(content, LocalFile):
        return content.path.read_bytes()
    assert isinstance(content, RemoteStream)
    return b"".join([chunk async for chunk in content.stream])


def test_the_keys_are_the_apps() -> None:
    """D9a: the App builds every key from the Run, the index and the checksum."""
    assert result_prefix(RUN, 3) == f"runs/{RUN}/3"
    assert result_key(result_prefix(RUN, 3), DIGEST) == f"runs/{RUN}/3/{DIGEST}"
    assert context_key(RUN) == f"runs/{RUN}/context"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/runs/x",
        f"runs/{RUN}/../other",
        f"runs/{RUN}/3/{DIGEST}/extra",
        f"runs/{RUN}/3/notachecksum",
        f"runs/run_bad/3/{DIGEST}",
        f"runs/{RUN}/-1/{DIGEST}",
    ],
)
def test_a_key_outside_the_grammar_is_refused_before_any_io(
    store: RunResultStore, key: str
) -> None:
    with pytest.raises(ValueError, match="key"):
        store.put(key, BODY)
    with pytest.raises(ValueError, match="key"):
        store.open(key)


@pytest.mark.asyncio
async def test_a_put_result_reads_back(store: RunResultStore) -> None:
    key = result_key(result_prefix(RUN, 0), DIGEST)

    store.put(key, BODY)

    assert await _read(store, key) == BODY


@pytest.mark.asyncio
async def test_a_missing_key_reads_as_absent(store: RunResultStore) -> None:
    assert store.open(result_key(result_prefix(RUN, 0), DIGEST)) is None


@pytest.mark.asyncio
async def test_delete_removes_the_named_keys_and_nothing_else(store: RunResultStore) -> None:
    kept = result_key(result_prefix(RUN, 1), DIGEST)
    gone = result_key(result_prefix(RUN, 0), DIGEST)
    store.put(kept, BODY)
    store.put(gone, BODY)
    store.put(context_key(RUN), b"context")

    store.delete([gone, context_key(RUN), result_key(result_prefix(RUN, 9), DIGEST)])

    assert store.open(gone) is None
    assert store.open(context_key(RUN)) is None
    assert await _read(store, kept) == BODY


def test_the_s3_put_is_one_signed_put_of_the_body() -> None:
    fake = _FakeS3()
    key = result_key(result_prefix(RUN, 0), DIGEST)

    _s3(fake).put(key, BODY)

    (request,) = fake.requests
    assert request.method == "PUT"
    assert request.url.path == f"/run-results/{key}"
    assert request.headers["x-amz-content-sha256"] == DIGEST
    assert request.headers["content-length"] == str(len(BODY))


def test_s3_leaves_age_to_the_buckets_rule() -> None:
    """R13: the bucket's 31-day rule removes what no record names; nothing is listed."""
    fake = _FakeS3()

    assert _s3(fake).delete_older_than(datetime.now(UTC)) == 0
    assert fake.requests == []


def test_the_folder_removes_by_age_what_the_buckets_rule_would(tmp_path: Path) -> None:
    store = FilesystemRunResultStore(tmp_path)
    old = result_key(result_prefix(RUN, 0), DIGEST)
    new = result_key(result_prefix(RUN, 1), DIGEST)
    store.put(old, BODY)
    store.put(new, BODY)
    now = datetime.now(UTC)
    stale = (now - timedelta(days=32)).timestamp()
    os.utime(tmp_path / old, (stale, stale))

    assert store.delete_older_than(now - timedelta(days=31)) == 1

    assert store.open(old) is None
    assert store.open(new) is not None
    assert not (tmp_path / result_prefix(RUN, 0)).exists()


def test_write_result_retries_a_failing_store_and_keys_by_checksum() -> None:
    fake = _FakeS3()
    fake.failures = 2
    sleeps: list[float] = []

    written = write_result(
        _s3(fake), result_prefix(RUN, 0), BODY, budget_s=60, sleep=sleeps.append, clock=_clock()
    )

    assert written == DIGEST
    assert fake.objects[f"/run-results/runs/{RUN}/0/{DIGEST}"] == BODY
    assert len(sleeps) == 2


def test_write_result_gives_up_after_its_budget() -> None:
    """R5: the run then ends `failed` with `result_store_unavailable`, not permanent."""
    fake = _FakeS3()
    fake.failures = 10_000
    clock = _clock(step=7.0)

    with pytest.raises(RunResultStoreUnavailable):
        write_result(
            _s3(fake), result_prefix(RUN, 0), BODY, budget_s=60, sleep=lambda _: None, clock=clock
        )
    assert clock() < 200


def _clock(step: float = 1.0) -> Callable[[], float]:
    now = [0.0]

    def tick() -> float:
        now[0] += step
        return now[0]

    return tick

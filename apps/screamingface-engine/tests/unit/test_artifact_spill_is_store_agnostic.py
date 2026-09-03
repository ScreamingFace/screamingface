"""The spill decision is the executor's; WHERE it spills is the store's (OME-929).

FEATURE: over-cap results survive the Runner Job on a multi-pod deployment.

INVARIANT: `build_result` decides inline-vs-spill from byte counts alone. Swapping the
filesystem store for the object store must not move the boundary by a single byte, and must
not change what a failed deposit does. OME-892 pinned this boundary against the filesystem;
this file pins the SAME boundary against object storage, so the two adapters cannot drift.

WHY that matters: the executor's cap logic is what keeps small runs byte-identical on the
wire. A store that quietly shifted the threshold would change the wire shape of every small
run on the hosted Engine only — the hardest class of bug to see from a test suite that runs
one adapter.
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest

from screamingface_engine.artifacts.s3 import S3ArtifactStore, S3Config, S3StorageError
from screamingface_engine.artifacts.sigv4 import Credentials
from screamingface_engine.runner.executor import Url4Executor
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.streaming.interfaces import Completed

RESULT_BYTES = 50


class _FixedResultNode:
    """Resolves to exactly `RESULT_BYTES` ASCII bytes, so the cap can be aimed precisely."""

    deps: dict = {}

    async def resolve(self, inputs: object, ctx: object) -> str:
        return "X" * RESULT_BYTES


class _Bucket:
    def __init__(self, *, fail: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self._fail = fail

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self._fail:
            return httpx.Response(500, text="InternalError")
        key = request.url.path.rsplit("/", 1)[-1]
        if request.method == "PUT":
            self.objects[key] = request.content
            return httpx.Response(200)
        return self._read(key, head=request.method == "HEAD")

    def _read(self, key: str, *, head: bool) -> httpx.Response:
        body = self.objects.get(key)
        if body is None:
            return httpx.Response(404)
        if head:
            return httpx.Response(200, headers={"content-length": str(len(body))})
        return httpx.Response(200, content=body)

    def store(self) -> S3ArtifactStore:
        transport = httpx.MockTransport(self.handle)
        return S3ArtifactStore(
            S3Config(
                endpoint_url="http://garage.svc:3900",
                bucket="artifacts",
                credentials=Credentials(access_key="GK", secret_key="s", region="garage"),
            ),
            client_factory=lambda: httpx.Client(transport=transport),
            async_client_factory=lambda: httpx.AsyncClient(transport=transport),
        )


async def _drain(executor: Url4Executor, node: object) -> list[object]:
    return [frame async for frame in executor.execute(cast("str", node))]


@pytest.mark.parametrize(
    ("cap", "spills"),
    [
        (RESULT_BYTES - 1, True),  # cap-1: one byte too small, must spill
        (RESULT_BYTES, False),  # exactly at cap: the largest result that stays inline
        (RESULT_BYTES + 1, False),  # cap+1: comfortably inline
    ],
    ids=["one-under-cap-spills", "exactly-at-cap-inline", "one-over-cap-inline"],
)
@pytest.mark.asyncio
async def test_the_cap_boundary_is_identical_on_object_storage(cap: int, spills: bool) -> None:
    """The threshold is `> cap` spills, `<= cap` stays inline — same as the filesystem."""
    bucket = _Bucket()
    executor = Url4Executor(StaticIOLayer(), result_cap=cap, artifact_store=bucket.store())

    frames = await _drain(executor, _FixedResultNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    if spills:
        assert completed.result.body is None
        assert completed.result.artifact is not None
    else:
        assert completed.result.body == "X" * RESULT_BYTES
        assert completed.result.artifact is None
        # Nothing was deposited: an inline result must not also leave an object behind.
        assert bucket.objects == {}


@pytest.mark.asyncio
async def test_a_spilled_result_is_deposited_whole_and_the_ticket_addresses_it() -> None:
    bucket = _Bucket()
    executor = Url4Executor(
        StaticIOLayer(), result_cap=RESULT_BYTES - 1, artifact_store=bucket.store()
    )

    frames = await _drain(executor, _FixedResultNode())

    completed = frames[-1]
    assert isinstance(completed, Completed)
    ref = completed.result.artifact
    assert ref is not None
    assert ref.size_bytes == RESULT_BYTES
    # The COMPLETE result reached the bucket under the address the ticket names — nothing cut.
    assert bucket.objects[ref.id] == b"X" * RESULT_BYTES


@pytest.mark.asyncio
async def test_a_refused_deposit_fails_the_run_instead_of_ticketing_nothing() -> None:
    """INVARIANT (the ordering that matters): the object is stored BEFORE any frame promises
    it. So a store that refuses the write ends the run loudly, here — it can never publish a
    successful terminal frame carrying a ticket that redeems to a 404 minutes later, after
    the whole run has been paid for. That late 404 is precisely the OME-929 failure.
    """
    bucket = _Bucket(fail=True)
    executor = Url4Executor(
        StaticIOLayer(), result_cap=RESULT_BYTES - 1, artifact_store=bucket.store()
    )

    with pytest.raises((S3StorageError, ResolutionError)):
        await _drain(executor, _FixedResultNode())

    assert bucket.objects == {}

"""The App and every worker run one revision of the world config (OME-1770 review).

FEATURE: hosted BYOM, Unit 2. One private world config is mounted into the App and the runner
pool, and the two Deployments roll independently.

INVARIANT: a run executes only under the world config of the App that accepted it.
- The App reads the file once: its catalog, the private set, the mounts and the digest `/healthz`
  reports all come from the same bytes.
- The App stamps that digest on every queued run. A worker serving a different file refuses the
  run with a named, retryable failure and starts no child. An unstamped message runs as before, so
  a rollout from an App that predates the stamp keeps working.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from test_chart_render_world_config import _container, _deployments, _render

from screamingface_engine import job_env
from screamingface_engine.adapters.factory import build_job_runner
from screamingface_engine.adapters.queue_runner import QueueJobRunner
from screamingface_engine.catalog import build_executable_catalog_service
from screamingface_engine.catalog.port import Credential, ModelNotInstalled
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.worker.loop import Worker
from screamingface_engine.worker.supervisor import WORLD_CONFIG_MISMATCH
from screamingface_engine.world.config import WorldConfigError, read_world_file
from screamingface_engine.world.publication import private_model_ids
from screamingface_engine.world.serving import derive_mount_table

_ENDPOINT = "byom_" + "0123456789abcdef" * 2
_PRIVATE = f"{_ENDPOINT}/model_v1"
_PUBLIC = "anthropic/claude-haiku-4-5"
_WORLD = f"""
[aigateway]
base_url = "http://aigateway.test"
default_route = "/{_PUBLIC}"

[[aigateway.models]]
id = "{_PRIVATE}"
web_search = false
public_schema = false
"""


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "url4.toml"
    path.write_text(_WORLD)
    return path


# --- the App reads the file once ------------------------------------------------------------


def test_one_read_gives_the_world_and_the_digest_of_the_same_bytes(tmp_path: Path) -> None:
    path = _write(tmp_path)

    world = read_world_file({job_env.RUNNER_CONFIG: str(path)})

    assert world.digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert private_model_ids(world.config) == frozenset({_PRIVATE})


def test_an_unreadable_world_file_is_a_world_config_error(tmp_path: Path) -> None:
    with pytest.raises(WorldConfigError):
        read_world_file({job_env.RUNNER_CONFIG: str(tmp_path / "missing.toml")})


@pytest.mark.asyncio
async def test_the_catalog_takes_the_apps_one_read_not_the_file(tmp_path: Path) -> None:
    """WHY: a second read of a live-updated mount could see a different file than the mounts."""
    world = read_world_file({job_env.RUNNER_CONFIG: str(_write(tmp_path))})
    gone = {job_env.RUNNER_CONFIG: str(tmp_path / "missing.toml")}

    service = build_executable_catalog_service(
        Settings(aigateway_base_url="http://aigateway.test"),
        gone,
        world=world.config,
        client_factory=lambda base_url: httpx.AsyncClient(
            base_url=base_url,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(400, json={"detail": f"unknown provider: {_ENDPOINT}"})
            ),
        ),
    )

    assert service is not None
    source = service.model_parameter_source
    assert source is not None
    with pytest.raises(ModelNotInstalled):
        await source.fetch_model_parameters(Credential.derive(), _PRIVATE)
    await service.aclose()


@pytest.mark.asyncio
async def test_the_mount_table_takes_the_apps_one_read_and_its_digest(tmp_path: Path) -> None:
    world = read_world_file({job_env.RUNNER_CONFIG: str(_write(tmp_path))})
    gone = {job_env.RUNNER_CONFIG: str(tmp_path / "missing.toml")}

    table = await derive_mount_table(env=gone, engine_routes=(), world=world)

    assert table.config_digest == world.digest
    private = [mount.path for mount in table.mounts if not mount.public_schema]
    assert private == [f"/{_PRIVATE}"]


# --- the App stamps every queued run ----------------------------------------------------------


def test_a_queue_message_carries_the_apps_digest_only_when_stamped() -> None:
    stamped = decode_message(encode_message("t", "'hi'", 60, world_digest="d1"))
    unstamped = decode_message(encode_message("t", "'hi'", 60))

    assert stamped[job_env.WORLD_DIGEST] == "d1"
    assert job_env.WORLD_DIGEST not in unstamped
    assert job_env.WORLD_DIGEST in job_env.WRITTEN_BY_APP


class _Queue:
    def __init__(self) -> None:
        self.published: list[bytes] = []

    async def publish(self, message: bytes, *, identity: Mapping[str, str] | None = None) -> None:
        self.published.append(message)

    async def depth(self) -> int:
        return 0

    async def oldest_age(self) -> float | None:
        return None


class _NoFrames:
    async def last_frame(self, topic: str) -> Any:
        return None


@pytest.mark.asyncio
async def test_the_queue_runner_stamps_every_run_it_publishes() -> None:
    queue = _Queue()
    runner = QueueJobRunner(
        queue=queue,  # type: ignore[arg-type]
        publisher=_NoFrames(),  # type: ignore[arg-type]
        control=SimpleNamespace(),  # type: ignore[arg-type]
        clock=lambda: datetime.now(UTC),
        capability_lifetime_s=600.0,
        world_digest="d1",
    )

    await runner.schedule("t-1", "'hi'", 60)
    await runner.schedule("t-2", "'hi'", 60, shape="direct")

    assert [decode_message(m)[job_env.WORLD_DIGEST] for m in queue.published] == ["d1", "d1"]


def test_the_factory_hands_the_apps_digest_to_the_queue_runner() -> None:
    runner = build_job_runner(Settings(runner="queue"), world_digest="d1")

    assert isinstance(runner, QueueJobRunner)
    assert runner._world_digest == "d1"  # noqa: SLF001


# --- the worker refuses a run from another revision ---------------------------------------


class _Msg:
    def __init__(self, topic: str, digest: str | None) -> None:
        body = {
            job_env.TOPIC: topic,
            job_env.EXPRESSION: "'hi'",
            job_env.JOB_DEADLINE_S: "60",
            job_env.STREAM_GRACE_S: "0",
        }
        if digest is not None:
            body[job_env.WORLD_DIGEST] = digest
        self.data = json.dumps(body).encode()
        self.metadata = SimpleNamespace(timestamp=datetime.now(UTC))
        self.headers = None
        self.acked = False

    async def ack(self) -> None:
        self.acked = True

    async def in_progress(self) -> None:
        pass


class _Publisher:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def last_frame(self, topic: str) -> Any:
        return self.published[-1] if self.published else None

    async def ensure_stream(self, topic: str) -> None:
        pass

    async def publish(self, topic: str, event: Any) -> None:
        self.published.append(event)

    async def flush(self) -> None:
        pass


class _ExitedProc:
    returncode = 0
    stdout = stderr = None

    async def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


class _Launcher:
    def __init__(self) -> None:
        self.launched: list[str] = []

    async def launch(self, env: Mapping[str, str], *, io_budget: Any) -> Any:
        self.launched.append(env[job_env.TOPIC])
        return _ExitedProc()


def _worker(publisher: _Publisher, launcher: _Launcher, *, world_digest: str | None) -> Worker:
    worker = Worker(
        queue=SimpleNamespace(),  # type: ignore[arg-type]
        publisher=publisher,  # type: ignore[arg-type]
        slots=1,
        drain_grace_s=0.1,
        io_capacity=4,
        memory_budget_bytes=1024**3,
        spawn=lambda *a, **k: None,  # type: ignore[arg-type,return-value]
        deadline_margin_s=0.05,
        kill_grace_s=0.05,
        world_digest=world_digest,
    )
    worker._supervisor._launcher = launcher  # noqa: SLF001 - the seam under test
    return worker


@pytest.mark.asyncio
async def test_a_worker_on_another_revision_refuses_the_run_and_starts_no_child() -> None:
    """STORY: as a caller during a rollout, my run fails with a named, retryable error instead of
    running under a world config the App that accepted it never served."""
    publisher, launcher = _Publisher(), _Launcher()
    msg = _Msg("t-old", digest="old")

    await _worker(publisher, launcher, world_digest="new")._supervisor.supervise(msg)  # type: ignore[arg-type]

    assert launcher.launched == []
    assert msg.acked
    [frame] = publisher.published
    assert frame.data.status == "failed"
    assert (frame.data.error.code, frame.data.error.permanent) == (WORLD_CONFIG_MISMATCH, False)
    assert "old" not in frame.data.error.message and "new" not in frame.data.error.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stamp", "own"),
    [("same", "same"), (None, "same"), ("same", None)],
    ids=["same-revision", "unstamped-message", "worker-without-digest"],
)
async def test_a_run_the_worker_cannot_prove_stale_still_runs(
    stamp: str | None, own: str | None
) -> None:
    publisher, launcher = _Publisher(), _Launcher()

    await _worker(publisher, launcher, world_digest=own)._supervisor.supervise(_Msg("t", stamp))  # type: ignore[arg-type]

    assert launcher.launched == ["t"]
    assert [f.data.error.code for f in publisher.published if f.data.error] != [
        WORLD_CONFIG_MISMATCH
    ]


# --- the first upgrade to the stamp check goes readers first ----------------------------------
#
# WHY: a worker of an earlier version ignores the stamp and starts the run under its own file
# (OME-1770 second review). The chart README therefore upgrades the pool alone first, with the
# world file the release already runs, and the App only once no older worker is left. Each step
# must move one Deployment and leave the other exactly as it was.

_JWT = "auth.jwtSecret=" + "s" * 32


@pytest.mark.skipif(shutil.which("helm") is None, reason="needs the helm CLI")
def test_the_readers_first_upgrade_moves_one_deployment_per_step() -> None:
    before = _deployments(_render(_JWT, "image.tag=running"))
    pool_first = _deployments(_render(_JWT, "image.tag=running", "runner.image.tag=new"))
    app_next = _deployments(_render(_JWT, "image.tag=new", "runner.image.tag="))

    assert pool_first["control-plane"] == before["control-plane"]
    assert _container(pool_first["runner"])["image"].endswith("-benchmark:new")
    assert app_next["runner"] == pool_first["runner"]
    assert _container(app_next["control-plane"])["image"].endswith(":new")

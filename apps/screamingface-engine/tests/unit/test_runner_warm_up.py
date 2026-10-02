"""The run child's warm phase (uniform executor PRD 03).

The warm phase runs BEFORE the child's run is known, so it may read per-PROCESS configuration
only. A per-run key read there would give the run another caller's identity or topic
(risk R7) — or, in the warm pool, no value at all.
"""

from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.runner.main import warm_up

pytestmark = pytest.mark.asyncio

PER_RUN_KEYS = job_env.WRITTEN_BY_APP | {job_env.IO_CONCURRENCY}


class _SentinelEnv(Mapping[str, str]):
    """A process environment in which every per-run key raises when it is read."""

    def __init__(self, base: Mapping[str, str]) -> None:
        self._base = {**base, **dict.fromkeys(PER_RUN_KEYS, "SENTINEL")}
        self.read_per_run: list[str] = []

    def __getitem__(self, key: str) -> str:
        if key in PER_RUN_KEYS:
            self.read_per_run.append(key)
            raise AssertionError(f"the warm phase read per-run key {key}")
        return self._base[key]

    def __iter__(self) -> Iterator[str]:
        # Iterating the environment would expose the per-run keys wholesale.
        raise AssertionError("the warm phase iterated the environment")

    def __len__(self) -> int:
        return len(self._base)

    def __contains__(self, key: object) -> bool:
        if key in PER_RUN_KEYS:
            self.read_per_run.append(str(key))
            raise AssertionError(f"the warm phase probed per-run key {key}")
        return key in self._base


class _Publisher:
    def __init__(self, url: str) -> None:
        self.url = url
        self.connected = False

    async def ensure_stream(self, topic: str) -> None:
        self.connected = True


def _world_file(tmp_path: Path) -> Path:
    """A world that builds: the warm phase builds it ahead (a gateway world; never dialled)."""
    path = tmp_path / "url4.toml"
    path.write_text(
        '[aigateway]\nbase_url = "http://aigateway.invalid"\n'
        'default_route = "/anthropic/claude-haiku-4-5"\n'
    )
    return path


async def test_warm_phase_reads_no_per_run_key(tmp_path: Path) -> None:
    """WRM-4 / WC-D1."""
    env = _SentinelEnv(
        {
            job_env.NATS_URL: "nats://broker:4222",
            job_env.RUNNER_CONFIG: str(_world_file(tmp_path)),
        }
    )
    state = await warm_up(env, publisher_factory=_Publisher)
    assert env.read_per_run == []
    assert isinstance(state.publisher, _Publisher)
    assert state.publisher.url == "nats://broker:4222"
    assert state.publisher.connected


async def test_a_world_config_error_is_reported_not_raised(tmp_path: Path) -> None:
    """WC-D3: an unreadable world still reaches READY (with world "error"); the run then fails
    with its own terminal frame, as today."""
    env = {job_env.RUNNER_CONFIG: str(tmp_path / "missing.toml")}
    state = await warm_up(env, publisher_factory=_Publisher)
    assert state.world_ok is False
    ok = await warm_up(
        {job_env.RUNNER_CONFIG: str(_world_file(tmp_path))}, publisher_factory=_Publisher
    )
    assert ok.world_ok is True


async def test_the_warm_phase_builds_the_world_ahead(tmp_path: Path) -> None:
    """kind B4 finding: the per-run world build was most of a simple call's latency. The warm
    phase builds it (from per-process config only) and hands it to the one run."""
    state = await warm_up(
        {job_env.RUNNER_CONFIG: str(_world_file(tmp_path))}, publisher_factory=_Publisher
    )
    try:
        assert state.world_ok and state.shared is not None
        assert state.shared.section is not None  # the [aigateway] section it was built from
    finally:
        assert state.world_aclose is not None
        await state.world_aclose()

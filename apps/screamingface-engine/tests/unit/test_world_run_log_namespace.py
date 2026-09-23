"""The per-run world-shape line: main's line, written by the RUN, once per run (FX-68).

The "runner world topic=…" INFO line predates F1 and was emitted on logger
`screamingface_engine.runner.main`. A logger-name or format change is an observable change on the
ensemble path (log routing keyed on the name), and prd/01 AC1's bar is byte-for-byte parity.

FX-68 (U1-L5): the line states the RUN's cache policy, and the world carries no caller state, so
the run producer (`runner.main`) writes it — never `build_world`. That also makes it once per
RUN on the shared node: local mode used to write it once at startup, with `topic=None`, and never
for the runs that followed. Building a world, the node tier or local mode's shared node writes
no line at all.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.runner.main import build_executor
from screamingface_engine.world.config import WorldConfig, parse_config
from screamingface_engine.world.factory import build_world
from screamingface_engine.world.models.registry import EMPTY_MODEL_WORLD
from url4.streaming.interfaces import Completed

pytestmark = pytest.mark.asyncio

_RUN_LOGGER = "screamingface_engine.runner.main"
_AIGATEWAY = """
[aigateway]
default_route = "/m"
models = ["m"]
"""


def _config() -> WorldConfig:
    return parse_config(tomllib.loads(_AIGATEWAY), {}, registry=EMPTY_MODEL_WORLD)


def _world_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith("runner world topic=")]


async def _run(env: dict[str, str]) -> None:
    async with httpx.AsyncClient() as client:
        executor = build_executor(env, _config(), client=client)
        async for _ in executor.execute("'hello'"):
            pass


async def test_the_per_run_world_shape_line_is_mains_line_on_its_runner_logger(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger=_RUN_LOGGER):
        await _run({job_env.TOPIC: "t-ns"})

    (record,) = _world_lines(caplog)
    assert record.name == _RUN_LOGGER
    assert record.getMessage() == (
        "runner world topic=t-ns models=1 default_model=m web_tools=disabled "
        "cache=not-stated outbound=allowed"
    )


async def test_the_line_states_the_runs_cache_policy_and_the_web_tools_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = {job_env.TOPIC: "t-k", job_env.TAVILY_API_KEY: "key", job_env.CACHE_PARTICIPATE: "false"}
    with caplog.at_level(logging.INFO, logger=_RUN_LOGGER):
        await _run(env)

    (record,) = _world_lines(caplog)
    assert "web_tools=enabled cache=stated" in record.getMessage()


async def test_a_blank_web_tools_key_is_no_key(caplog: pytest.LogCaptureFixture) -> None:
    """The flag comes from the world's own key normalization, so it agrees with the world."""
    with caplog.at_level(logging.INFO, logger=_RUN_LOGGER):
        await _run({job_env.TOPIC: "t-blank", job_env.TAVILY_API_KEY: "   "})

    (record,) = _world_lines(caplog)
    assert "web_tools=disabled" in record.getMessage()


async def test_building_a_world_writes_no_run_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient() as client:
            _io, aclose = await build_world(env={}, config=_config(), client=client)
        if aclose is not None:
            await aclose()

    assert _world_lines(caplog) == []


async def test_building_the_node_tier_writes_no_run_line(caplog: pytest.LogCaptureFixture) -> None:
    from test_node_tier import _KEY, _NEVER_SPILLS

    from screamingface_engine.world.node_tier import NodeTierSettings, build_node_tier

    with caplog.at_level(logging.INFO):
        async with httpx.AsyncClient() as client:
            tier = await build_node_tier(
                env={},
                config=_config(),
                client=client,
                settings=NodeTierSettings(request_timeout_s=5.0, aigateway_timeout_s=4.0),
                artifact_store=_NEVER_SPILLS,
                artifact_signing_key=_KEY,
            )
            await tier.aclose()

    assert _world_lines(caplog) == []


async def test_each_local_run_on_the_shared_node_writes_its_own_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Startup builds the shared node and writes no line; each run then writes one, naming its
    own topic — the shape every run had on `main`, when each built its own world."""
    config = tmp_path / "url4.toml"
    config.write_text(
        '[aigateway]\nbase_url = "http://aigateway.test"\n'
        'default_route = "/anthropic/claude-haiku-4-5"\n'
    )
    app = create_local_app(Settings(jwt_secret="s" * 32), env={job_env.RUNNER_CONFIG: str(config)})

    with caplog.at_level(logging.INFO):
        async with app.router.lifespan_context(app):
            assert _world_lines(caplog) == [], "the shared node's build wrote a run line"
            runner = app.state.job_runner
            runner._extra_models = lambda: []  # noqa: SLF001 - no catalog dial
            for topic in ("t-a", "t-b"):
                env = runner._env(topic, "'hello'", 60, None, None)  # noqa: SLF001
                executor = runner._factory(env)  # noqa: SLF001
                async for _ in executor.execute("'hello'"):
                    pass

    lines = [r.getMessage() for r in _world_lines(caplog)]
    assert [line.split()[2] for line in lines] == ["topic=t-a", "topic=t-b"], lines
    assert all(r.name == _RUN_LOGGER for r in _world_lines(caplog))


async def test_a_run_on_the_shared_node_survives_the_config_file_breaking_after_startup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A run on the shared node must not re-read `url4.toml` for its world line (item 1).

    Startup resolves the config once, to build the shared node. A run that follows must not
    read the file again just to log — a file broken or changed after startup would otherwise
    fail every later run, or log a shape that no longer matches what the node actually serves.
    """
    config = tmp_path / "url4.toml"
    config.write_text(
        '[aigateway]\nbase_url = "http://aigateway.test"\n'
        'default_route = "/anthropic/claude-haiku-4-5"\n'
    )
    app = create_local_app(Settings(jwt_secret="s" * 32), env={job_env.RUNNER_CONFIG: str(config)})

    with caplog.at_level(logging.INFO):
        async with app.router.lifespan_context(app):
            runner = app.state.job_runner
            runner._extra_models = lambda: []  # noqa: SLF001 - no catalog dial
            config.write_text("this is not valid toml [[[")
            env = runner._env("t-broken", "'hello'", 60, None, None)  # noqa: SLF001
            executor = runner._factory(env)  # noqa: SLF001
            steps = [step async for step in executor.execute("'hello'")]

    assert isinstance(steps[-1], Completed)
    (record,) = _world_lines(caplog)
    assert record.getMessage() == (
        "runner world topic=t-broken models=117 default_model=anthropic/claude-haiku-4-5 "
        "web_tools=disabled cache=not-stated outbound=allowed"
    )

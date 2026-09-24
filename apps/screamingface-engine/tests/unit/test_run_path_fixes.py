"""FX-30, FX-39, FX-40 (04-review-fixes B2): the run path is the regression oracle.

# WHY this file exists. Unit 3 let local runs share the node the App serves, and unit 1 moved the
# answer-seed parse into the request scope. Both changed what a RUN does — and the run path must
# match `main` (contracts.md C9). These tests pin the three places the reviews found it did not:
#
# - FX-30: a model admitted after startup (the `URL4_CLOUD_EXTRA_MODELS` overlay) is not a route on
#   the shared node, so a local run addressing it failed. It now builds its own world, as on main.
# - FX-39: every run log line gained an `origin=run` prefix; run lines are byte-identical again.
# - FX-40: a malformed `ANSWER_SEED` is refused before the world is built (summary `None`), and an
#   empty world ignores it, as on main.

Offline throughout: aigateway is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from screamingface_engine import job_env
from screamingface_engine.config import Settings
from screamingface_engine.local import create_local_app
from screamingface_engine.logs import APP_LOGGER, configure, run_scope
from screamingface_engine.request_scope import current_scope
from screamingface_engine.runner import main as runner_main
from screamingface_engine.runner.fair_share import FairShareIOLayer
from screamingface_engine.runner.main import RunnerConfigError, build_executor
from screamingface_engine.world.config import (
    AigatewaySection,
    ModelSpec,
    WorldConfig,
    WorldConfigError,
    extra_model_ids,
)
from screamingface_engine.world.factory import SharedWorld, build_world, shared_world_serves
from url4.io.static import StaticIOLayer
from url4.streaming.interfaces import Completed

_DEFAULT = "anthropic/claude-haiku-4-5"
# Not in the compiled model world: only the admitted overlay can make it a route.
_ADMITTED = "openrouter/qwen/qwen2.5-7b-instruct"
_WORLD = f'[aigateway]\nbase_url = "http://aigateway.test"\ndefault_route = "/{_DEFAULT}"\n'
_TRACE_ID = "a" * 32


class _Gateway:
    """A canned aigateway that records the model id of every call."""

    def __init__(self) -> None:
        self.models: list[str] = []

    def client(self) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.models.append(json.loads(request.content)["model"])
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        return httpx.AsyncClient(
            base_url="http://aigateway.test", transport=httpx.MockTransport(handle)
        )


def _config(tmp_path: Path) -> str:
    path = tmp_path / "url4.toml"
    path.write_text(_WORLD)
    return str(path)


def _overlay(*ids: str) -> dict[str, str]:
    return job_env.extra_models_to_env(list(ids))


# --- FX-30: shared_world_serves ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_run_with_no_overlay_is_served_by_the_shared_world(tmp_path: Path) -> None:
    world, aclose = await build_world(env={job_env.RUNNER_CONFIG: _config(tmp_path)})
    try:
        assert shared_world_serves(world, {}) is True
        assert shared_world_serves(world, _overlay(_DEFAULT)) is True
    finally:
        assert aclose is not None
        await aclose()


@pytest.mark.asyncio
async def test_an_overlay_route_the_shared_world_lacks_is_not_served(tmp_path: Path) -> None:
    world, aclose = await build_world(env={job_env.RUNNER_CONFIG: _config(tmp_path)})
    try:
        assert shared_world_serves(world, _overlay(_ADMITTED)) is False
        assert shared_world_serves(world, _overlay(_DEFAULT, _ADMITTED)) is False
    finally:
        assert aclose is not None
        await aclose()


@pytest.mark.asyncio
async def test_a_malformed_overlay_is_left_to_the_per_run_world(tmp_path: Path) -> None:
    """False, not a raise: the per-run world then refuses it with its own loud error."""
    world, aclose = await build_world(env={job_env.RUNNER_CONFIG: _config(tmp_path)})
    try:
        assert shared_world_serves(world, {job_env.EXTRA_MODELS: "not json"}) is False
    finally:
        assert aclose is not None
        await aclose()


def test_the_overlay_has_one_parser_in_world_config() -> None:
    """B2 review: `shared_world_serves` reuses the config parser, and a refusal there is False."""
    assert extra_model_ids(_overlay(_DEFAULT, _ADMITTED)) == tuple(sorted((_DEFAULT, _ADMITTED)))
    assert extra_model_ids({}) == ()
    for bad in ("not json", '{"a": 1}', '["has:colon"]'):
        with pytest.raises(WorldConfigError):
            extra_model_ids({job_env.EXTRA_MODELS: bad})
        assert shared_world_serves(StaticIOLayer(), {job_env.EXTRA_MODELS: bad}) is False


def test_a_world_that_is_not_a_node_serves_no_overlay() -> None:
    assert shared_world_serves(StaticIOLayer(), {}) is True
    assert shared_world_serves(StaticIOLayer(), _overlay(_DEFAULT)) is False


# --- FX-30: the local run path, end to end ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_local_run_on_a_model_admitted_after_startup_completes(tmp_path: Path) -> None:
    """repro_extra: the shared node has no route for the admitted id; the run builds its own."""
    app = create_local_app(
        Settings(jwt_secret="s" * 32), env={job_env.RUNNER_CONFIG: _config(tmp_path)}
    )
    gateway = _Gateway()
    expression = f"/{_ADMITTED}('hi')!'answer'"

    async with app.router.lifespan_context(app):
        runner = app.state.job_runner
        runner._extra_models = lambda: [_ADMITTED]  # noqa: SLF001 - admitted after startup
        env = runner._env("t-admitted", expression, 60, None, None)  # noqa: SLF001
        async with gateway.client() as client:
            executor = runner._factory(env, client=client)  # noqa: SLF001
            steps = [step async for step in executor.execute(expression)]

        assert executor._inner._io is not app.state.node_world  # noqa: SLF001

    assert isinstance(steps[-1], Completed)
    assert gateway.models == [_ADMITTED]


@pytest.mark.asyncio
async def test_the_per_run_world_of_an_admitted_model_run_is_closed_after_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-run world owns its teardown; the shared node is never closed by a run."""
    app = create_local_app(
        Settings(jwt_secret="s" * 32), env={job_env.RUNNER_CONFIG: _config(tmp_path)}
    )
    closed: list[str] = []
    real_build = runner_main.build_world

    async def _recording_build(**kwargs: Any) -> Any:
        io_layer, aclose = await real_build(**kwargs)
        assert aclose is not None

        async def _close() -> None:
            closed.append("per-run")
            await aclose()

        return io_layer, _close

    monkeypatch.setattr(runner_main, "build_world", _recording_build)
    expression = f"/{_ADMITTED}('hi')!'answer'"

    async with app.router.lifespan_context(app):
        runner = app.state.job_runner
        runner._extra_models = lambda: [_ADMITTED]  # noqa: SLF001
        env = runner._env("t-close", expression, 60, None, None)  # noqa: SLF001
        async with _Gateway().client() as client:
            executor = runner._factory(env, client=client)  # noqa: SLF001
            steps = [step async for step in executor.execute(expression)]
        assert closed == ["per-run"]
        # The shared node still serves after the run closed its own world.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://app.test"
        ) as http:
            assert (await http.get("/v1", params={"q": "'hello'"})).text == "hello"

    assert isinstance(steps[-1], Completed)


@pytest.mark.asyncio
async def test_a_local_run_the_shared_node_serves_still_uses_the_shared_node(
    tmp_path: Path,
) -> None:
    app = create_local_app(
        Settings(jwt_secret="s" * 32), env={job_env.RUNNER_CONFIG: _config(tmp_path)}
    )

    async with app.router.lifespan_context(app):
        runner = app.state.job_runner
        runner._extra_models = lambda: [_DEFAULT]  # noqa: SLF001
        env = runner._env("t-shared", "'hello'", 60, None, None)  # noqa: SLF001
        executor = runner._factory(env)  # noqa: SLF001
        inner = executor._inner  # noqa: SLF001
        await inner._resolve_world()  # noqa: SLF001

        # The run's io is the shared node, wrapped per run for fair-share I/O (OME-908).
        assert isinstance(inner._io, FairShareIOLayer)  # noqa: SLF001
        assert inner._io._inner is app.state.node_world  # noqa: SLF001
        assert inner._world_aclose is None  # noqa: SLF001 - never closes the shared node


# --- FX-39: run log lines are main's lines ----------------------------------------------------


@pytest.fixture
def _app_logger() -> Iterator[io.StringIO]:
    logger = logging.getLogger(APP_LOGGER)
    handlers = list(logger.handlers)
    level, propagate = logger.level, logger.propagate
    logger.handlers.clear()
    stream = io.StringIO()
    configure(stream)
    try:
        yield stream
    finally:
        logger.handlers.clear()
        logger.handlers.extend(handlers)
        logger.setLevel(level)
        logger.propagate = propagate


def test_a_run_line_is_byte_identical_to_main(_app_logger: io.StringIO) -> None:
    with run_scope("cap-topic", _TRACE_ID):
        logging.getLogger("screamingface_engine.ws.bridge").info("run started")

    assert _app_logger.getvalue() == (
        f"INFO:     screamingface_engine.ws.bridge topic=cap-topic trace_id={_TRACE_ID} "
        "run started\n"
    )


def test_a_sync_line_still_names_its_origin(_app_logger: io.StringIO) -> None:
    with run_scope(None, _TRACE_ID, origin="sync"):
        logging.getLogger("screamingface_engine.world").info("sync request")

    assert _app_logger.getvalue() == (
        f"INFO:     screamingface_engine.world origin=sync trace_id={_TRACE_ID} sync request\n"
    )


# --- FX-40: a malformed ANSWER_SEED, in main's order -------------------------------------------


def _declared() -> WorldConfig:
    return WorldConfig(
        aigateway=AigatewaySection(
            base_url="http://aigateway.test",
            default_model=_DEFAULT,
            models=(ModelSpec(id=_DEFAULT),),
        )
    )


@pytest.mark.asyncio
async def test_a_malformed_seed_does_not_fail_a_run_on_an_empty_world() -> None:
    """main never parsed the seed for a world with no `[aigateway]`: no model call reads it."""
    executor = build_executor({job_env.ANSWER_SEED: "lucky"}, WorldConfig())

    steps = [step async for step in executor.execute("'hello'")]

    assert isinstance(steps[-1], Completed)


@pytest.mark.asyncio
async def test_a_malformed_seed_is_refused_before_the_world_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[object] = []

    async def _spy(**kwargs: object) -> object:
        built.append(kwargs)
        raise AssertionError("the world must not be built for a malformed seed")

    monkeypatch.setattr(runner_main, "build_world", _spy)
    executor = build_executor({job_env.ANSWER_SEED: "lucky"}, _declared())

    with pytest.raises(RunnerConfigError, match=job_env.ANSWER_SEED):
        async for _ in executor.execute(f"/{_DEFAULT}('ctx')!'go'"):
            pass

    assert built == []
    assert executor.last_summary() is None


@pytest.mark.asyncio
async def test_a_valid_seed_is_still_bound_in_the_runs_scope() -> None:
    """F2 unchanged: the seed travels in the scope bound around the run, not on the world."""
    seen: list[int | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        # The handler runs inside the run's driving task, so it sees the scope the run bound.
        seen.append(current_scope().answer_seed)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    async with httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(handle)
    ) as client:
        executor = build_executor({job_env.ANSWER_SEED: "7"}, _declared(), client=client)
        steps = [step async for step in executor.execute(f"/{_DEFAULT}('ctx')!'go'")]

    assert isinstance(steps[-1], Completed)
    assert seen == [7]


# --- FX-40 on both world shapes (B2 review): the four cases, against main ----------------------
#
# main built a per-run world for every run, so its behaviour is the oracle for both shapes:
# an empty world ignores a malformed seed and completes; a declared world refuses the run before
# any run step, so `last_summary()` is `None`.


async def _declared_world(tmp_path: Path) -> Any:
    world, _aclose = await build_world(env={job_env.RUNNER_CONFIG: _config(tmp_path)})
    return world


@pytest.mark.asyncio
async def test_a_malformed_seed_on_an_empty_shared_world_completes() -> None:
    shared = StaticIOLayer()
    provider = lambda: SharedWorld(io=shared, section=None)  # noqa: E731 - binding read
    executor = build_executor({job_env.ANSWER_SEED: "lucky"}, shared_world_provider=provider)

    steps = [step async for step in executor.execute("'hello'")]

    assert isinstance(steps[-1], Completed)


@pytest.mark.asyncio
async def test_a_malformed_seed_on_a_declared_shared_world_is_refused_before_the_run(
    tmp_path: Path,
) -> None:
    shared = await _declared_world(tmp_path)
    provider = lambda: SharedWorld(io=shared, section=None)  # noqa: E731 - binding read
    executor = build_executor({job_env.ANSWER_SEED: "lucky"}, shared_world_provider=provider)

    with pytest.raises(RunnerConfigError, match=job_env.ANSWER_SEED):
        async for _ in executor.execute(f"/{_DEFAULT}('ctx')!'go'"):
            pass

    assert executor.last_summary() is None


@pytest.mark.asyncio
async def test_a_valid_seed_on_a_shared_world_is_bound_and_the_world_is_not_closed(
    tmp_path: Path,
) -> None:
    seen: list[int | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(current_scope().answer_seed)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    async with httpx.AsyncClient(
        base_url="http://aigateway.test", transport=httpx.MockTransport(handle)
    ) as client:
        shared, aclose = await build_world(
            env={job_env.RUNNER_CONFIG: _config(tmp_path)}, client=client
        )
        # item 1 (B6 review): a run on the shared node no longer re-reads its config for the
        # world line — it logs from the `SharedWorld.section` the caller hands in below, which
        # here is `None` (this test does not assert the world line); each run env still carries
        # the config path, as every local run env does (`local._with_runner_config`), because a
        # run WITHOUT a shared world still builds and resolves its own.
        run_env = {job_env.RUNNER_CONFIG: _config(tmp_path)}
        provider = lambda: SharedWorld(io=shared, section=None)  # noqa: E731 - binding read
        executor = build_executor(
            {**run_env, job_env.ANSWER_SEED: "7"}, shared_world_provider=provider
        )
        steps = [step async for step in executor.execute(f"/{_DEFAULT}('ctx')!'go'")]
        # A second run on the same shared world still works: the first did not close it.
        again = build_executor(run_env, shared_world_provider=provider)
        steps_again = [step async for step in again.execute(f"/{_DEFAULT}('ctx')!'go'")]
        assert aclose is not None
        await aclose()

    assert isinstance(steps[-1], Completed)
    assert isinstance(steps_again[-1], Completed)
    assert seen == [7, None]

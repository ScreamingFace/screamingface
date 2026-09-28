"""OME-880: the queue codec and the inprocess adapter carry the admitted overlay into a run's
environment.

FEATURE: run any OpenRouter model (OME-878). An admitted model is only real if
the RUN can route it — the runner builds its world from the run's env, so the
App writes the overlay's ids onto every scheduled run as
`URL4_CLOUD_EXTRA_MODELS` (a provider callable, read at SCHEDULE time so a
model admitted a second ago reaches the very next run).

INVARIANT: the two renderings are ONE contract — a key one writes and the
other omits is a local run that silently diverges from a deployed one.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.runner_queue import decode_message, encode_message
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import ExecStep, Executor, TraceContext

_TARGET = "openrouter/qwen/qwen2.5-7b-instruct"


def _codec_env_of(extra_models: tuple[str, ...] = ()) -> dict[str, str]:
    return decode_message(encode_message("t", "gpt(hi)", 60, extra_models=extra_models))


def test_the_queue_codec_writes_the_overlay_onto_the_run() -> None:
    assert json.loads(_codec_env_of((_TARGET,))[job_env.EXTRA_MODELS]) == [_TARGET]


def test_an_empty_overlay_writes_a_neutralizing_empty_entry() -> None:
    # INVARIANT (review F4): the key is ALWAYS written explicitly — an explicit env
    # entry beats `envFrom`, so an empty value is what keeps a stale
    # URL4_CLOUD_EXTRA_MODELS left in the Helm ConfigMap out of every run.
    assert _codec_env_of(())[job_env.EXTRA_MODELS] == ""


def test_no_overlay_provider_still_neutralizes_the_ambient_key() -> None:
    # A deployment wired without a catalog (no admission) must be just as immune
    # to a leftover ConfigMap value as one with an empty overlay.
    assert _codec_env_of()[job_env.EXTRA_MODELS] == ""


class _NeverExecutor(Executor):
    """Never executed — these tests assert the env the runner BUILDS."""

    async def execute(  # type: ignore[override]
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:  # pragma: no cover - the run is never started
        raise NotImplementedError
        yield  # pragma: no cover - unreachable; makes this an async generator


def test_the_inprocess_adapter_renders_the_same_key() -> None:
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
        extra_models=lambda: (_TARGET,),
    )

    env = runner._env("t", "gpt(hi)", 60, None, None, None, None)  # noqa: SLF001

    assert json.loads(env[job_env.EXTRA_MODELS]) == [_TARGET]


def test_the_overlay_is_read_at_schedule_time_not_construction_time() -> None:
    # WHY: a model admitted AFTER the app booted must reach the very next run.
    overlay: list[str] = []
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
        extra_models=lambda: tuple(overlay),
    )

    before = runner._env("t", "gpt(hi)", 60, None, None, None, None)  # noqa: SLF001
    overlay.append(_TARGET)
    after = runner._env("t", "gpt(hi)", 60, None, None, None, None)  # noqa: SLF001

    assert job_env.EXTRA_MODELS not in before
    assert json.loads(after[job_env.EXTRA_MODELS]) == [_TARGET]


def test_an_ambient_extra_models_value_is_replaced_not_inherited() -> None:
    # INVARIANT: same reset rule as identity/cache policy — `_base_env` is one
    # dict shared by every local run, so a stale overlay value must never leak
    # into a run scheduled after the provider changed.
    stale = {job_env.EXTRA_MODELS: json.dumps(["openrouter/stale/model"])}
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
        base_env=stale,
        extra_models=lambda: (),
    )

    env = runner._env("t", "gpt(hi)", 60, None, None, None, None)  # noqa: SLF001

    assert job_env.EXTRA_MODELS not in env

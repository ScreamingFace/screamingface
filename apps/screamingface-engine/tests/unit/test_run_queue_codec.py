"""The queue message codec (OME-1088): ONE encoding, through `job_env`.

The message body is exactly the per-run env mapping the App writes onto a run — topic,
expression, deadline, stream grace, validated traceparent, profile, identity headers,
cache policy, extra models, io budget. Both sides render through `job_env`, so there is
no second encoding to drift; these tests pin the codec against the inprocess adapter's
rendering of the same contract.

The two renderings differ in exactly three deliberate ways, each pinned here:

- the codec always writes `STREAM_GRACE_S` (the worker's hard wall derives from it);
  local mode never writes it (its deadline is enforced in-process);
- the codec always writes `EXTRA_MODELS`, empty when there is no overlay (an explicit
  env entry beats `envFrom`); local mode writes it only when a provider exists;
- the codec always writes `IO_CONCURRENCY` (the deployed worker writes the per-run
  budget by env); local mode pops it in favour of the fair-share gate.
"""

from collections.abc import AsyncIterator

from screamingface_engine import job_env
from screamingface_engine.adapters.inprocess import InProcessJobRunner
from screamingface_engine.runner_queue import decode_message, encode_message, topic_of_message
from screamingface_engine.testing import InMemoryEventStream
from url4.streaming.interfaces import ExecStep, Executor, TraceContext
from url4.streaming.protocol import CachePolicy

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

# The codec's always-on keys that local mode deliberately does not write.
_CODEC_ONLY = {job_env.STREAM_GRACE_S, job_env.EXTRA_MODELS, job_env.IO_CONCURRENCY}


class _NeverExecutor(Executor):
    """Never executed — these tests assert the env the runner BUILDS, not what it then runs."""

    async def execute(  # type: ignore[override]
        self, url4: str, *, trace: TraceContext | None = None
    ) -> AsyncIterator[ExecStep]:  # pragma: no cover - the run is never started
        raise NotImplementedError
        yield  # pragma: no cover - unreachable; makes this an async generator


def _inprocess_env(
    expression: str = "'hi'!'go'",
    *,
    traceparent: str | None = None,
    identity: dict[str, str] | None = None,
    cache: CachePolicy | None = None,
    extra_models: tuple[str, ...] | None = None,
) -> dict[str, str]:
    runner = InProcessJobRunner(
        stream=InMemoryEventStream(),
        executor_factory=lambda env: _NeverExecutor(),
        extra_models=(lambda: extra_models) if extra_models is not None else None,
    )
    return runner._env(  # noqa: SLF001
        "topic-a", expression, 60, traceparent, None, identity, cache
    )


def _codec_env(
    expression: str = "'hi'!'go'",
    *,
    traceparent: str | None = None,
    identity: dict[str, str] | None = None,
    cache: CachePolicy | None = None,
    io_concurrency: int = 4,
    extra_models: tuple[str, ...] = (),
) -> dict[str, str]:
    return decode_message(
        encode_message(
            "topic-a",
            expression,
            60,
            traceparent=traceparent,
            identity=identity,
            cache=cache,
            io_concurrency=io_concurrency,
            extra_models=extra_models,
        )
    )


def _assert_same_contract(codec: dict[str, str], local: dict[str, str]) -> None:
    """The codec and the inprocess adapter render ONE contract: every key local mode writes
    is written identically by the codec, and the codec's only extras are the three pinned
    always-on keys."""
    shared = {k: v for k, v in codec.items() if k not in _CODEC_ONLY}
    assert shared == local, (
        "the codec and the inprocess adapter diverged: "
        f"codec-only={sorted(set(codec) - set(local))} "
        f"local-only={sorted(set(local) - set(codec))}"
    )


def test_a_queue_message_round_trips_to_the_job_env_mapping() -> None:
    """The queue message decodes to the same per-run env mapping the inprocess adapter
    renders — the codec and the adapter must never drift into a second encoding."""
    codec = _codec_env(
        traceparent=TRACEPARENT,
        identity={"X-User-Email": "a@b.c"},
        cache=CachePolicy(participate=True, max_age=300),
        io_concurrency=7,
    )
    local = _inprocess_env(
        traceparent=TRACEPARENT,
        identity={"X-User-Email": "a@b.c"},
        cache=CachePolicy(participate=True, max_age=300),
    )

    _assert_same_contract(codec, local)
    assert codec[job_env.IO_CONCURRENCY] == "7"
    assert topic_of_message(encode_message("topic-a", "'hi'!'go'", 60)) == "topic-a"


def test_an_invalid_traceparent_is_dropped_like_the_inprocess_path_drops_it() -> None:
    codec = _codec_env(expression="'hi'", traceparent="not-a-traceparent")
    local = _inprocess_env(expression="'hi'", traceparent="not-a-traceparent")

    _assert_same_contract(codec, local)
    assert job_env.TRACEPARENT not in codec


def test_an_unstated_cache_policy_renders_nothing_like_the_inprocess_path() -> None:
    codec = _codec_env(expression="'hi'")
    local = _inprocess_env(expression="'hi'")

    _assert_same_contract(codec, local)
    assert job_env.CACHE_PARTICIPATE not in codec


def test_the_io_budget_and_extra_models_reach_the_message() -> None:
    """The per-run budget and the admitted-model overlay are part of the codec, exactly as
    they are part of the inprocess adapter's env."""
    codec = _codec_env(
        io_concurrency=9,
        extra_models=("openrouter/qwen/qwen2.5-7b-instruct",),
    )
    local = _inprocess_env(extra_models=("openrouter/qwen/qwen2.5-7b-instruct",))

    assert codec[job_env.IO_CONCURRENCY] == "9"
    assert "openrouter/qwen/qwen2.5-7b-instruct" in codec[job_env.EXTRA_MODELS]
    assert "openrouter/qwen/qwen2.5-7b-instruct" in local[job_env.EXTRA_MODELS]

"""The App writes a run's per-run env; `screamingface-engine run` reads it back.
This pins that round trip.

Both halves ship in one distribution now, so the pair of tests that existed only to
catch two hand-synced `job_env.py` copies drifting are gone — there is one module,
and nothing to drift from. What remains is what the merge did NOT make free: the
App must write every REQUIRED name, must write nothing the run mode does not read,
must never inline a secret, and must leave the deploy-time names to Helm.

The deployed rendering of the per-run env is the queue message codec
(`runner_queue.encode_message`, OME-1088): the message body IS the per-run env
mapping, decoded by the worker and merged into the child's environment. The
inprocess adapter renders the same contract for local mode. These tests pin the
codec's output against `job_env`'s contract sets.
"""

from typing import Any

import pytest

from screamingface_engine import job_env
from screamingface_engine.runner.main import RunnerConfigError, params_from_env
from screamingface_engine.runner_queue import decode_message, encode_message
from url4.streaming.protocol import CachePolicy

TOPIC = "cap-topic"
EXPRESSION = "/model('x')!'go'"
NATS_URL = "nats://nats:4222"


def _scheduled_env(**extra: Any) -> dict[str, str]:
    """The per-run env mapping the App writes for one run, via the queue codec."""
    return decode_message(
        encode_message(
            TOPIC,
            EXPRESSION,
            60,
            traceparent=extra.get("traceparent"),
            profile=extra.get("profile", "prof"),
            identity=extra.get("identity"),
            cache=extra.get("cache"),
            io_concurrency=extra.get("io_concurrency", 4),
            extra_models=extra.get("extra_models", ()),
        )
    )


def test_every_variable_the_app_writes_is_one_the_runner_reads() -> None:
    written = set(_scheduled_env())
    orphans = written - job_env.WRITTEN_BY_APP
    assert not orphans, (
        f"the App writes {sorted(orphans)} into the run's env, but the Runner reads none of "
        f"them — either consume them there and add them to job_env.WRITTEN_BY_APP, or stop "
        f"writing them"
    )


def test_the_required_variables_are_always_written() -> None:
    written = set(_scheduled_env())
    assert job_env.REQUIRED <= written, f"missing {sorted(job_env.REQUIRED - written)}"


def test_the_runner_parses_exactly_what_the_app_wrote() -> None:
    env = _scheduled_env()

    params = params_from_env(env)

    assert params.topic == TOPIC
    assert params.url4 == EXPRESSION


def test_the_runner_takes_its_nats_url_from_the_charts_env_not_the_app() -> None:
    """The App stopped writing it; the chart's runner-env ConfigMap supplies it, and the
    Runner cannot tell the source.

    Pinned from both directions so the fallback cannot quietly become the real behavior in
    prod: App-written env ALONE yields the loopback default, and the chart-injected value
    wins.
    """
    app_written = _scheduled_env()

    assert job_env.NATS_URL not in app_written
    assert params_from_env(app_written).nats_url == job_env.DEFAULT_NATS_URL

    from_chart = {**app_written, job_env.NATS_URL: NATS_URL}
    assert params_from_env(from_chart).nats_url == NATS_URL


def test_the_runner_rejects_an_env_missing_a_required_variable() -> None:
    env = dict.fromkeys(job_env.REQUIRED, "x")
    del env[job_env.TOPIC]
    with pytest.raises(RunnerConfigError, match=job_env.TOPIC):
        params_from_env(env)


def test_no_secret_valued_variable_is_ever_written_by_the_app() -> None:
    """The codec writes no secret: a run carries no aigateway credential, and the deploy-time
    credentials (Tavily, object storage) travel by Secret reference from the chart's
    `envFrom`, never as a literal in the run's env."""
    written = set(_scheduled_env())

    assert not (written & job_env.SECRET), (
        f"the App writes {sorted(written & job_env.SECRET)} as literals — a run's env is not "
        f"a secret; deploy-time credentials must travel by Secret reference from the chart"
    )


def test_the_two_env_populations_stay_disjoint() -> None:
    """Per-run and deploy-time are written by different parties; a name in both has two writers.

    Merging the packages removed the copies but not this hazard: `job_env` now declares both
    populations side by side, so a name added to the wrong frozenset is a one-character mistake
    that would have the App write a value Helm also writes — with the explicit env silently
    winning over `envFrom` and the chart's value never taking effect.
    """
    overlap = job_env.WRITTEN_BY_APP & job_env.DEPLOY_TIME
    assert not overlap, (
        f"{sorted(overlap)} is declared both per-run and deploy-time — the App's env shadows "
        f"the chart's `envFrom`, so Helm's value would be silently ignored"
    )


def test_deploy_time_variables_are_not_written_by_the_app() -> None:
    """Helm owns these end-to-end; the App naming one would be two sources of truth again."""
    written = set(_scheduled_env())

    assert not (written & job_env.DEPLOY_TIME), (
        f"the App writes {sorted(written & job_env.DEPLOY_TIME)} directly, but the chart "
        f"injects them via envFrom — remove them from the codec so Helm stays the only writer"
    )


def test_the_codec_renders_the_full_per_run_contract() -> None:
    """The codec's output for a fully-specified run is exactly the per-run contract: the
    required names plus the optional per-run ones, and nothing else."""
    env = _scheduled_env(
        traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        identity={"X-User-Email": "a@b.c"},
        cache=CachePolicy(participate=True, max_age=300),
        io_concurrency=7,
        extra_models=("openrouter/qwen/qwen2.5-7b-instruct",),
    )

    assert set(env) == {
        job_env.TOPIC,
        job_env.EXPRESSION,
        job_env.JOB_DEADLINE_S,
        job_env.STREAM_GRACE_S,
        job_env.TRACEPARENT,
        job_env.AIGATEWAY_PROFILE,
        job_env.IDENTITY_HEADER_ENV["X-User-Email"],
        job_env.CACHE_PARTICIPATE,
        job_env.CACHE_MAX_AGE_S,
        job_env.EXTRA_MODELS,
        job_env.IO_CONCURRENCY,
    }

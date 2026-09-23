"""The `screamingface-engine run` entrypoint: reads its Job env, wires the executor
and NATS publisher, and drives one url4 run end to end via
``url4.streaming.lifecycle.run``.

Reached from :func:`screamingface_engine.cli.main` — the same console script that serves the control
plane, entered with a different subcommand. Nothing here imports the serving half; see the
layering note in :mod:`screamingface_engine.runner`.
"""

import asyncio
import functools
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from screamingface_engine import job_env
from screamingface_engine.adapters.jetstream import JetStreamPublisher
from screamingface_engine.artifacts import ArtifactWriter
from screamingface_engine.artifacts.wiring import result_writer_from_env
from screamingface_engine.benchmarks import EMPTY_BENCHMARKS, BenchmarkRegistry
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.client_provenance import (
    CLIENT_VERSION_ENV,
    ProvenanceExecutor,
    valid_version,
)
from screamingface_engine.logs import run_scope
from screamingface_engine.observations import ObserverFactory
from screamingface_engine.request_scope import RequestScope
from screamingface_engine.runner.executor import Url4Executor
from screamingface_engine.runner.fair_share import FairShareGate, FairShareIOLayer
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.runner.summary import RunSummary
from screamingface_engine.tracing.relay import SpanRelay, SpanSink, otlp_configured
from screamingface_engine.world.config import WorldConfig, load_config
from screamingface_engine.world.factory import (
    World,
    build_world,
    shared_world_serves,
    world_reads_answer_seed,
)
from url4.streaming.interfaces import EventPublisher
from url4.streaming.lifecycle import run
from url4.streaming.trace import parse_traceparent

logger = logging.getLogger(__name__)


class _SummarizingExecutor(Protocol):
    """The executor surface the runner's terminal logging needs beyond the port.

    A Protocol rather than the concrete wrapper so `_log_terminal` is testable with a fake
    that records a summary and nothing else — the function needs exactly this accessor.
    """

    def last_summary(self) -> RunSummary | None: ...


class RunnerConfigError(ValueError):
    """The per-run Job environment is missing or malformed."""


def request_scope_from_env(env: Mapping[str, str]) -> RequestScope:
    """Producer 1 (F2, AC6): the child boot's caller state, read off its Job environment.

    One run has exactly one caller, so every value the connector used to pin on the handler is
    here instead, resolved once before the world is built and bound around the run by
    `Url4Executor`. The identity and profile are optional (absent means anonymous / the
    gateway's default); the cache policy is total; the seed is the one value that REFUSES the
    run when malformed.

    Raises:
        RunnerConfigError: ``ANSWER_SEED`` is present but not an integer. This is the same
            refusal `job_env.answer_seed_from_env` always produced — a run silently executed
            without its declared seed would publish a score claiming a sitting it never had.
    """

    try:
        answer_seed = job_env.answer_seed_from_env(env)
    except ValueError as exc:
        raise RunnerConfigError(str(exc)) from exc
    return RequestScope(
        identity_headers=job_env.identity_from_env(env),
        profile=env.get(job_env.AIGATEWAY_PROFILE),
        answer_seed=answer_seed,
        cache=job_env.cache_policy_from_env(env),
        origin="run",
    )


def stream_grace_s(env: Mapping[str, str]) -> float:
    """The drain grace before a finished run's stream is reclaimed.

    INVARIANT: never raises. A typo in this env var must not take down every Job at teardown —
    the cost of the default being wrong is a slightly late reclamation, the cost of raising is
    a leaked stream on every run.
    """
    raw = env.get(job_env.STREAM_GRACE_S)
    if raw is None:
        return job_env.DEFAULT_STREAM_GRACE_S
    try:
        return float(raw)
    except ValueError:
        logger.warning("ignoring unparseable %s=%r", job_env.STREAM_GRACE_S, raw)
        return job_env.DEFAULT_STREAM_GRACE_S


def _int_from_env(env: Mapping[str, str], name: str, default: int) -> int:
    """One deploy-time integer, tolerantly. INVARIANT: never raises — same reasoning as
    `stream_grace_s`: a typo'd knob must not take down every Job, and running with the
    shipped default is the cheap wrong answer."""
    raw = env.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("ignoring unparseable %s=%r", name, raw)
        return default


def bridge_budget_from_env(env: Mapping[str, str]) -> int:
    """The Runner's event-bridge memory budget: the bytes the backlog may cost before the
    run fails with ``BridgeOverflowError`` (OME-906).

    Deploy-time like the result caps, tolerant fallback the same: of the two wrong answers
    to an unparseable value ("crash every run at boot" vs "run with the shipped default")
    the default is the one that costs nothing.
    """
    return _int_from_env(
        env, job_env.BRIDGE_MEMORY_BUDGET_BYTES, job_env.DEFAULT_BRIDGE_MEMORY_BUDGET_BYTES
    )


def result_delivery_from_env(env: Mapping[str, str]) -> tuple[int, int, ArtifactWriter]:
    """The Runner's result-delivery wiring: (inline cap, hard cap, spill store).

    FEATURE: deliver large results in full instead of cutting them off at 1 MiB (OME-892),
    and have them survive this Job's own disk (OME-929).

    Reads the same URL4_CLOUD_* names the App's `Settings` serve side reads, so the writer and
    the `GET /artifacts/{id}` server resolve ONE store by construction.

    INVARIANT: an object store selected but not fully configured raises HERE. That surfaces as
    a Terminated(failed) frame on the run's topic — loudly, before any model call — rather than
    as a claim ticket that redeems to a 404 once the whole run has been paid for.

    AIDEV-NOTE: the caps fall back tolerantly (a byte count has a safe default) while the
    STORE does not. That asymmetry is the OME-929 lesson: an unwritten value falls back
    silently, and only some fallbacks are harmless.
    """
    inline_cap = _int_from_env(
        env, job_env.RESULT_INLINE_CAP_BYTES, job_env.DEFAULT_RESULT_INLINE_CAP_BYTES
    )
    hard_cap = _int_from_env(
        env, job_env.RESULT_HARD_CAP_BYTES, job_env.DEFAULT_RESULT_HARD_CAP_BYTES
    )
    # The store construction is SHARED with the node tier's spill path (unit 3): both call
    # `result_writer_from_env`, so the run path and the sync tier cannot park into two places.
    return inline_cap, hard_cap, result_writer_from_env(env)


async def run_and_reclaim(
    publisher: JetStreamPublisher,
    topic: str,
    run_once: Callable[[], Awaitable[None]],
    *,
    grace_s: float = job_env.DEFAULT_STREAM_GRACE_S,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Drive one run, then reclaim its stream.

    WHY the runner owns this: `DELETE /` is the only other path that reclaims a stream, and it
    needs a capability token — those expire `iat_window_s` (60s) after minting and cannot be
    re-issued for an existing topic, so any run longer than a minute could never tear its own
    stream down. Every such run leaked a stream holding a full `max_bytes` reservation until the
    store was full and every new run failed with 10047.

    INVARIANT: the reclamation is in a `finally`. A run that raised is precisely the run whose
    stream would otherwise be left behind.
    """
    try:
        await run_once()
    finally:
        # WHY the delay: `delete_stream` destroys the stream AND its consumers. Deleting the
        # instant the terminal frame is published races a client that has not drained yet, which
        # would never see the terminal frame and would hang until its own timeout.
        await sleep(grace_s)
        try:
            await publisher.delete_stream(topic)
        except Exception:
            # INVARIANT: nothing here may escape. Teardown is best-effort by design and
            # `_sweep_orphans` is the stated backstop, so the cost of swallowing is a late
            # reclamation. The cost of raising is far worse in BOTH directions: on the success
            # path it reports a run that published `Terminated(succeeded)` as a Failed Job, and
            # on the failure path a raise inside `finally` SUPERSEDES the exception already
            # propagating, erasing the real cause of the failure from the Job's logs.
            #
            # WHY not `except APIError`: `delete_stream` connects lazily, so it also raises
            # `NoServersError`, `ConnectionClosedError` and `nats.errors.TimeoutError` — none of
            # which are `APIError`. A broker blip is exactly when reclamation fails, so the
            # narrow clause missed the cases that actually happen.
            logger.warning("could not reclaim stream for topic %s", topic, exc_info=True)


@dataclass(frozen=True)
class RunnerParams:
    """The per-run values read off the Job's env — topic, expression, NATS URL, deadline."""

    topic: str
    url4: str
    nats_url: str
    deadline_s: float | None = None
    client_version: str | None = None


def _deadline_from_env(environ: Mapping[str, str]) -> float | None:
    """Parse the run's deadline; absent means unbounded.

    WHY the run enforces this itself when k8s already sets ``activeDeadlineSeconds``: the
    substrate's deadline kills the POD, which ends the process before it can publish anything —
    leaving the topic with no terminal frame and every subscriber waiting. Self-terminating first
    is what turns the deadline into a ``Terminated(timed_out)`` a client can actually observe.
    A malformed value is refused rather than silently treated as unbounded.
    """
    raw = environ.get(job_env.JOB_DEADLINE_S)
    if raw is None:
        return None
    try:
        deadline = float(raw)
    except ValueError as exc:
        raise RunnerConfigError(f"{job_env.JOB_DEADLINE_S} is not a number: {raw!r}") from exc
    if deadline <= 0:
        raise RunnerConfigError(f"{job_env.JOB_DEADLINE_S} must be positive, got {deadline}")
    return deadline


def params_from_env(environ: Mapping[str, str]) -> RunnerParams:
    """Read required per-run env vars, turning a missing one into ``RunnerConfigError``."""
    try:
        topic = environ[job_env.TOPIC]
        url4 = environ[job_env.EXPRESSION]
    except KeyError as exc:
        raise RunnerConfigError(f"missing required runner env var: {exc.args[0]}") from exc
    return RunnerParams(
        topic=topic,
        url4=url4,
        nats_url=environ.get(job_env.NATS_URL, job_env.DEFAULT_NATS_URL),
        deadline_s=_deadline_from_env(environ),
        client_version=valid_version(environ.get(CLIENT_VERSION_ENV)),
    )


def _seeded_world(
    env: Mapping[str, str],
    config: WorldConfig | None,
    shared_io: Any,
    build: Callable[[WorldConfig], Awaitable[World]],
) -> tuple[Callable[[], Awaitable[World]], Callable[[], RequestScope]]:
    """The run's world factory and its request-scope producer, sharing ONE seed parse.

    FEATURE (F2, prd/01): the child boot's caller state is resolved by the scope producer when
    the run starts, and bound around the run by `Url4Executor` — so the world carries nothing
    per-request and the stateless connector reads the caller's own values (AC2). Both callables
    are LAZY for the same reason the world is: a malformed seed must fail the run (a Terminated
    frame on the topic), not take down the scheduling caller before the stream exists.

    INVARIANT (FX-40, contracts.md C9): a malformed ANSWER_SEED behaves exactly as on `main`,
    for BOTH world shapes. `main` parsed the seed inside the world factory, after the empty-world
    early return and before the model world was built. So a world with no model route never reads
    the seed and the run completes; a world with model routes refuses the run in its world
    factory — before anything is built or run — so `last_summary()` is `None`. The scope is
    memoized, so the refusal and the bound scope are the same parse, whichever runs first.

    ``shared_io`` is local mode's shared world, or ``None`` for a per-run world. A shared world
    comes back with NO teardown: its owner closes it, never a run.
    """

    @functools.cache
    def resolved() -> WorldConfig:
        return config if config is not None else load_config(env, include_extra_models=True)

    def reads_seed() -> bool:
        if shared_io is not None:
            return world_reads_answer_seed(shared_io)
        return resolved().aigateway is not None

    @functools.cache
    def scope() -> RequestScope:
        if reads_seed():
            return request_scope_from_env(env)
        return request_scope_from_env(
            {name: value for name, value in env.items() if name != job_env.ANSWER_SEED}
        )

    async def world() -> World:
        scope()  # FX-40: refuse a malformed seed before the world is built or run
        if shared_io is not None:
            return shared_io, None
        return await build(resolved())

    return world, scope


def build_executor(
    env: Mapping[str, str],
    config: WorldConfig | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
    benchmark_assets_root: Path | None = None,
    io_gate: FairShareGate | None = None,
    observers: tuple[ObserverFactory, ...] = (),
    io_provider: Callable[[], Any] | None = None,
) -> OperationCapturingExecutor:
    """Wire an executor over the DECLARED world — without building it yet.

    The world is resolved on first ``execute`` (see ``Url4Executor._resolve_world``), so a bad
    config or an unreachable gateway surfaces as a Terminated(failed) frame on the topic
    rather than as a silent Job crash before the stream exists.

    ``client`` and ``tavily_client`` are test-only injection seams: production callers leave
    them ``None`` and let ``build_aigateway_world`` construct its own ``httpx.AsyncClient``(s);
    tests pass a fake/mocked client to avoid real network calls.

    ``job_env.TAVILY_API_KEY`` is an operator secret, handled the same way as
    ``AIGATEWAY_SECRET_KEY`` — never logged. It is read here and forwarded to
    ``build_aigateway_world`` as ``tavily_api_key``; when it is unset, the built world disables
    the web-search/web-fetch tool loop entirely (deny-by-default — see
    ``web_tools.build_client``), rather than leaving it half-configured.

    ``observers`` are per-execution factories supplied by composition. The empty default
    leaves execution without observers; optional telemetry policy belongs to its adapter.

    The concrete return type (not the ``Executor`` port) is deliberate: the composition root
    reads the run's process-level summary back off the wrapper after the run (OME-1069), and
    the wrapper is the only executor this function ever builds.
    """

    inline_cap, hard_cap, artifact_store = result_delivery_from_env(env)

    # FEATURE (OME-908): the run's downstream admission policy. `io_gate` is LOCAL mode's
    # shared fair-share gate; when present, the run's world io is wrapped into it under the
    # run's TOPIC key and `url4_run` states `concurrency=None` explicitly (the gate replaces
    # the per-run bound). Deployed mode passes no gate and instead reads the static budget the
    # App wrote onto the Job; `None` from a clean env omits the kwarg and URL4's default holds.
    run_key = env.get(job_env.TOPIC)
    # WHY `Any` and not `IOLayer`: `runner.main` is not an engine-importing module
    # (pinned by `test_only_engine_extensions_import_url4`); the callable's precise
    # type lives where it is defined, in `runner.executor`.
    io_wrap: Callable[[Any], Any] | None = None
    if io_gate is not None and run_key:
        io_wrap = lambda io: FairShareIOLayer(io, io_gate, run_key)  # noqa: E731 - binding read
    # FEATURE (unit 3, prd/03 C8): LOCAL mode builds ONE world, mounts it as the node's ASGI
    # surface, and runs every in-process run against that same world. `io_provider` is how a
    # caller hands that shared world in WITHOUT building it here: it is read at executor BUILD
    # time (once per run) rather than captured, because local mode builds the world in the App's
    # startup hook, after this factory exists. A provider rather than the world itself also keeps
    # `build_executor`'s `partial` shape intact — the local composition's `benchmarks` and
    # `observers` keywords are read by tests, and a bespoke callable would erase them.
    #
    # INVARIANT: `None` (the deployed Job, and every non-local caller) leaves the per-run world
    # factory in place, byte-identical to before. The shared world's own teardown belongs to
    # whoever built it, so its factory returns NO teardown — a run must not close a world it does
    # not own.
    shared_io = io_provider() if io_provider is not None else None
    # FEATURE (FX-30, OME-880): a model admitted after the shared node was built is not a route
    # on it. Such a run builds its own per-run world, exactly as before the shared node existed,
    # and that world owns its own teardown.
    if shared_io is not None and not shared_world_serves(shared_io, env):
        shared_io = None

    async def _build(resolved: WorldConfig) -> World:
        # FEATURE (F1, prd/01): building the world lives in the shared world package, because
        # both halves build one. This closure supplies only the run mode's per-Job wiring — the
        # Job's own env, its optional test clients, and the run key the world log names. The
        # factory stays LAZY so a bad config or unreachable gateway surfaces as a Terminated
        # frame on the topic rather than crashing the scheduling caller before the stream exists.
        return await build_world(
            env=env,
            config=resolved,
            client=client,
            tavily_client=tavily_client,
            benchmarks=benchmarks,
            benchmark_assets_root=benchmark_assets_root,
            run_key=run_key,
        )

    world_factory, scope_factory = _seeded_world(env, config, shared_io, _build)
    return OperationCapturingExecutor(
        Url4Executor(
            world_factory=world_factory,
            request_scope_factory=scope_factory,
            result_cap=inline_cap,
            hard_cap=hard_cap,
            memory_budget=bridge_budget_from_env(env),
            artifact_store=artifact_store,
            io_wrap=io_wrap,
            io_concurrency=None if io_wrap is not None else job_env.io_concurrency_from_env(env),
        ),
        observers=observers,
    )


def span_sink(env: Mapping[str, str]) -> SpanSink | None:
    """The run's span sink, or ``None`` when this deployment configured no OTLP endpoint.

    WHY the import is LAZY. `tracing.otlp` pulls the OTel SDK, protobuf and `requests` —
    measured at ~62 ms of this module's ~227 ms import time, which every Job would otherwise
    pay whether or not it exports anything. `check_layering.py` protects a Job's cold start
    from the engine's OWN modules; nothing protects it from a third-party dependency, so this
    is the same discipline applied by hand. `cli.py` and `worker_composition` import their
    heavy halves the same way, for the same reason.

    INVARIANT: never raises. A broken exporter config must not stop a run from happening — the
    whole point of the relay is that telemetry degrades alone. An unreachable collector is
    already handled downstream (the exporter drops); this covers the boot-time half.
    """
    if not otlp_configured(env):
        return None
    try:
        from screamingface_engine.tracing.otlp import sink_from_env

        return sink_from_env(env)
    except Exception:
        logger.warning("span export is configured but could not be started", exc_info=True)
        return None


def _nats_host(url: str) -> str:
    """The NATS host for a log line — never the userinfo, which may carry credentials."""

    if "://" in url:
        return urlsplit(url).hostname or url
    return url.rsplit("@", 1)[-1]


def _log_boot(params: RunnerParams, traceparent: str | None) -> None:
    """The Job's first line: what this run is, sanitized.

    The expression itself is never logged — it is the caller's and may carry prompts; its
    LENGTH is enough to tell a large Evaluation from a smoke run (the control plane's own
    precedent). The NATS URL is reduced to its host for the same reason.
    """

    logger.info(
        "runner boot topic=%s url4_chars=%d deadline_s=%s nats_host=%s traceparent=%s",
        params.topic,
        len(params.url4),
        params.deadline_s,
        _nats_host(params.nats_url),
        "present" if traceparent else "absent",
    )


def _log_terminal(executor: _SummarizingExecutor, topic: str, started: float) -> None:
    """The run's process-level outcome and summary — the operator's one-stop answer.

    Exact-only, like the stream's own cost frames: a failed run states no cost and no cache
    counts, because neither is exact. The summary's `trace_id` is the one the executor
    received from `lifecycle.run` — exactly the id on the stream frames.
    """

    summary = executor.last_summary()
    duration_s = time.monotonic() - started
    if summary is None:
        logger.warning(
            "run ended without an executor summary topic=%s duration_s=%.1f",
            topic,
            duration_s,
        )
        return
    code = f" code={summary.error_code}" if summary.error_code is not None else ""
    error_type = f" type={summary.error_type}" if summary.error_type is not None else ""
    logger.info(
        "run finished topic=%s outcome=%s%s%s duration_s=%.1f",
        topic,
        summary.outcome,
        code,
        error_type,
        duration_s,
    )
    if summary.outcome != "succeeded":
        # FEATURE (OME-940): a FAILED run leaves the evidence line too. This used to `return`
        # here, so the only line carrying `trace_id` was emitted for successes — inverted from
        # the point of durable evidence, since the failed run is the one whose record is needed
        # after the frame stream's 60 s reclamation. The cost/cache fields stay success-only
        # (they are not exact for a failure, and a partial figure reads as a complete one), so
        # this states identity and outcome and stops there.
        error = " ".join(
            part
            for part in (
                f"code={summary.error_code}" if summary.error_code is not None else "",
                f"type={summary.error_type}" if summary.error_type is not None else "",
            )
            if part
        )
        logger.info(
            "run summary topic=%s trace_id=%s outcome=%s duration_s=%.1f%s",
            topic,
            summary.trace_id or "none",
            summary.outcome,
            duration_s,
            f" {error}" if error else "",
        )
        return
    cost = (
        "unpriced"
        if summary.pricing_version == "unpriced"
        else (f"{summary.cost_usd}" if summary.cost_usd is not None else "unknown")
    )
    fields = [
        f"topic={topic}",
        f"trace_id={summary.trace_id or 'none'}",
        f"outcome={summary.outcome}",
        f"duration_s={duration_s:.1f}",
        f"cost_usd={cost}",
        f"pricing={summary.pricing_version or 'unknown'}",
    ]
    fields.extend(f"{key}={value}" for key, value in (summary.cache_attributes or {}).items())
    fields.append(f"dropped_logs={summary.dropped_logs}")
    fields.append(f"high_water={summary.high_water}")
    logger.info("run summary %s", " ".join(fields))


async def _run_and_log(
    executor: OperationCapturingExecutor,
    publisher: EventPublisher,
    params: RunnerParams,
    traceparent: str | None,
) -> None:
    """Drive one run, then log its terminal outcome and summary from the executor's record.

    `lifecycle.run` publishes the terminal frame and returns normally on failure, so the
    outcome is read back from the executor rather than inferred from an exception.
    """

    started = time.monotonic()
    try:
        await run(
            publisher,
            ProvenanceExecutor(executor, params.client_version),
            params.topic,
            params.url4,
            traceparent=traceparent,
            deadline_s=params.deadline_s,
        )
    finally:
        _log_terminal(executor, params.topic, started)


def main() -> None:  # pragma: no cover - real NATS + event loop (INFRA rule)
    async def _main() -> None:
        params = params_from_env(os.environ)
        # WHY: entry-point composition owns plugin registration; the executor stays optional.
        from screamingface_engine.observation_plugins import observation_factories

        executor = build_executor(
            os.environ,
            benchmarks=BUILTIN_BENCHMARKS,
            observers=observation_factories(os.environ),
        )
        traceparent = os.environ.get(job_env.TRACEPARENT)
        publisher = JetStreamPublisher(params.nats_url)
        _log_boot(params, traceparent)
        # The trace id the run's own frames will carry: parsed from the App-forwarded
        # traceparent, or None when the caller sent none (the stream then mints one, which
        # the executor records and the summary line reports). Bound for the whole run so
        # every process log line inside it carries topic and trace id.
        trace_id = parse_traceparent(traceparent)
        # FEATURE (OME-1130): the run's spans, exported to a tracing backend so SigNoz shows a
        # WATERFALL instead of a log search. The relay wraps the run's own publisher — the one
        # path every frame of every run travels, attached client or not — and is a pure
        # passthrough when no OTLP endpoint is configured, which is the default everywhere.
        #
        # `with`, not a hand-written `finally`: this process is short-lived, and an unflushed
        # batch loses the tail of every trace including its root span. See `tracing.relay`.
        #
        # `run_and_reclaim` keeps the RAW publisher: it needs `delete_stream`, which is
        # JetStream's, not the wire port's — the relay only stands where frames are published.
        with (
            run_scope(params.topic, trace_id),
            SpanRelay(publisher, span_sink(os.environ)) as relay,
        ):
            await run_and_reclaim(
                publisher,
                params.topic,
                lambda: _run_and_log(executor, relay, params, traceparent),
                grace_s=stream_grace_s(os.environ),
            )

    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()

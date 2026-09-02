"""The `screamingface-engine run` entrypoint: reads its Job env, wires the executor
and NATS publisher, and drives one url4 run end to end via
``url4.streaming.lifecycle.run``.

Reached from :func:`screamingface_engine.cli.main` — the same console script that serves the control
plane, entered with a different subcommand. Nothing here imports the serving half; see the
layering note in :mod:`screamingface_engine.runner`.
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from screamingface_engine import job_env
from screamingface_engine.adapters.jetstream import JetStreamPublisher
from screamingface_engine.artifacts import ArtifactStore, ArtifactWriter, S3ArtifactStore
from screamingface_engine.artifacts.wiring import s3_config_from_values
from screamingface_engine.benchmarks import EMPTY_BENCHMARKS, BenchmarkRegistry, assets_root
from screamingface_engine.benchmarks.builtins import BUILTIN_BENCHMARKS
from screamingface_engine.benchmarks.candidate_adapter import install_candidate_invocation
from screamingface_engine.benchmarks.ensemble import install_corrective_runtime
from screamingface_engine.logs import run_scope
from screamingface_engine.runner.connector import AigatewayConfig, build_aigateway_world
from screamingface_engine.runner.executor import Url4Executor, World, deny_by_default_world
from screamingface_engine.runner.fair_share import FairShareGate, FairShareIOLayer
from screamingface_engine.runner.operation_capture import OperationCapturingExecutor
from screamingface_engine.runner.summary import RunSummary
from screamingface_engine.world_config import WorldConfig, WorldConfigError, load_config
from url4.streaming.lifecycle import run
from url4.streaming.protocol import CachePolicy
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
    if (env.get(job_env.ARTIFACT_STORE) or "filesystem").strip() == "s3":
        return inline_cap, hard_cap, S3ArtifactStore(s3_config_from_values(env))
    artifacts_dir = env.get(job_env.ARTIFACTS_DIR) or job_env.DEFAULT_ARTIFACTS_DIR
    return inline_cap, hard_cap, ArtifactStore(Path(artifacts_dir))


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
    )


def build_executor(
    env: Mapping[str, str],
    config: WorldConfig | None = None,
    *,
    client: httpx.AsyncClient | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    benchmarks: BenchmarkRegistry = EMPTY_BENCHMARKS,
    benchmark_assets_root: Path | None = None,
    io_gate: FairShareGate | None = None,
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

    The concrete return type (not the ``Executor`` port) is deliberate: the composition root
    reads the run's process-level summary back off the wrapper after the run (OME-1069), and
    the wrapper is the only executor this function ever builds.
    """

    async def _world() -> World:
        # `include_extra_models`: the Runner boot is the ONE parse that reads the
        # Job-scoped URL4_CLOUD_EXTRA_MODELS overlay (review F3) — this env IS the
        # Job's own, written by the App at schedule time.
        resolved = config if config is not None else load_config(env, include_extra_models=True)
        section = resolved.aigateway
        if section is None:
            if len(benchmarks):
                raise WorldConfigError(
                    "installed Benchmarks require a declared aigateway model world"
                )
            # WHY: a world with no [aigateway] table is a legitimate empty world; the node itself
            # denies everything undeclared.
            return deny_by_default_world(), None
        # WHY: no credential check here; aigateway runs `cloudflare_headers` when deployed
        # and `disabled` locally, and NEITHER mode reads `Authorization` — so there is no token to
        # demand. Identity is forwarded when present and simply absent locally, where every caller
        # is anonymous. The old unconditional token requirement made every deployed run fail
        # before it issued a single request, because a deployed caller has no way to obtain one.
        cache = job_env.cache_policy_from_env(env)
        world = await build_aigateway_world(
            AigatewayConfig(
                base_url=section.base_url,
                default_model=section.default_model,
                models=section.models,
                allow_outbound=section.allow_outbound,
                timeout_s=section.timeout_s,
                web_tool_max_iterations=section.web_tool_max_iterations,
            ),
            profile=env.get(job_env.AIGATEWAY_PROFILE),
            identity_headers=job_env.identity_from_env(env),
            # Read back per RUN, from this run's own environment — never folded into the
            # `AigatewayConfig` above, which describes the WORLD and is shared by every run the
            # process serves. `cache_policy_from_env` is total, so an env that states nothing
            # yields a policy that states nothing, which the connector sends as no `cache` field
            # at all — participation, without this half re-deciding what silence means.
            cache=cache,
            client=client,
            tavily_api_key=env.get(job_env.TAVILY_API_KEY),
            tavily_client=tavily_client,
        )
        if len(benchmarks):
            # WHY: installation can fail through any concrete Benchmark adapter. AsyncExitStack
            # guarantees the already-open model world closes without a catch-all exception clause.
            async with AsyncExitStack() as cleanup:
                cleanup.push_async_callback(world.aclose)
                install_candidate_invocation(world.node)
                # The corrective loop's generic gate/select/answer endpoints are
                # engine capability, not benchmark surface — installed once beside
                # the candidate invocation for every world that runs benchmarks.
                install_corrective_runtime(world.node)
                benchmarks.install(
                    world.node,
                    assets_root=(
                        benchmark_assets_root
                        if benchmark_assets_root is not None
                        else assets_root(env)
                    ),
                )
                cleanup.pop_all()
        # FEATURE (OME-1069): the world's resolved shape, logged once per run. The topic comes
        # from the run's own env (`run_key`); the trace id is appended by the run-context
        # filter, which is bound by the time the world is built. Model ids are public catalog
        # names; `web_tools` is derived from the PRESENCE of the Tavily key, never the key
        # itself; `cache` states whether the run declared a policy, not the policy's content.
        logger.info(
            "runner world topic=%s models=%d default_model=%s web_tools=%s cache=%s outbound=%s",
            run_key,
            len(section.models),
            section.default_model,
            "enabled" if world.web_tools_enabled else "disabled",
            _cache_stated(cache),
            "allowed" if section.allow_outbound else "denied",
        )
        return world.node, world.aclose

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
    return OperationCapturingExecutor(
        Url4Executor(
            world_factory=_world,
            result_cap=inline_cap,
            hard_cap=hard_cap,
            memory_budget=bridge_budget_from_env(env),
            artifact_store=artifact_store,
            io_wrap=io_wrap,
            io_concurrency=None if io_wrap is not None else job_env.io_concurrency_from_env(env),
        )
    )


def _cache_stated(policy: CachePolicy) -> str:
    """Whether a run's cache policy stated anything — 'stated' or 'not-stated'.

    Its own token rather than the rendered policy: "did not declare" and "declared an
    all-unset policy" are different statements, and the world log only needs the first.
    """

    if policy.participate is not None or policy.max_age is not None:
        return "stated"
    return "not-stated"


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
    publisher: JetStreamPublisher,
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
            executor,
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
        executor = build_executor(os.environ, benchmarks=BUILTIN_BENCHMARKS)
        traceparent = os.environ.get(job_env.TRACEPARENT)
        publisher = JetStreamPublisher(params.nats_url)
        _log_boot(params, traceparent)
        # The trace id the run's own frames will carry: parsed from the App-forwarded
        # traceparent, or None when the caller sent none (the stream then mints one, which
        # the executor records and the summary line reports). Bound for the whole run so
        # every process log line inside it carries topic and trace id.
        trace_id = parse_traceparent(traceparent)
        with run_scope(params.topic, trace_id):
            await run_and_reclaim(
                publisher,
                params.topic,
                lambda: _run_and_log(executor, publisher, params, traceparent),
                grace_s=stream_grace_s(os.environ),
            )

    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    main()

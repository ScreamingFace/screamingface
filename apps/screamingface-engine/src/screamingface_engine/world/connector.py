"""Builds the aigateway-backed :class:`~url4.io.layer.IOLayer` world: a `Url4Node` whose
endpoints are declared models routed to aigateway's chat-completions API, plus an optional
Tavily-backed web-search/web-fetch tool loop. This is the world `executor.Url4Executor`
resolves and runs an expression against.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import NoReturn

import httpx

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA, CANDIDATE_MESSAGE_ROLES
from screamingface_engine.candidate_scope import in_candidate_invocation
from screamingface_engine.model_outcomes import bind_model_outcome, record_model_outcome
from screamingface_engine.observations import ModelCall, current_model_call
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    combine_operation_accounting,
)
from screamingface_engine.operation_calls import operation_call_identity, record_operation_call
from screamingface_engine.request_scope import RequestScope, RequestScopeError, current_scope
from screamingface_engine.retrieval_policy import (
    RetrievalPolicy,
    current_retrieval_policy,
)
from screamingface_engine.trace_scope import current_traceparent
from screamingface_engine.world.accounting import (
    CallAccounting,
    avoided_usd_for_outcome,
    read_aigw,
    retained_operation_accounting,
)
from screamingface_engine.world.cache import policy_to_body_field
from screamingface_engine.world.cache_readback import (
    CacheOutcome,
    read_cache_outcome,
    requires_revalidation,
)
from screamingface_engine.world.config import ModelSpec, WorldConfigError, provider_of, routes_for
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.model_response import (
    Choice,
    parse_choice,
    raise_if_unusable,
)
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.request_parameters import (
    WEB_SEARCH_PARAM,
    apply_answer_seed,
    apply_retrieval_policy,
    caller_exclusions,
    model_params,
    wants_web_search,
)
from screamingface_engine.world.web_tools import (
    WEB_TOOLS,
    WebToolRuntime,
    append_tool_results,
    build_client,
    build_runtime,
    truncate_tool_result,
)
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.observe import current_log_sink, current_response_sink, current_usage_sink
from url4.peer.server import Request, Url4Node
from url4.streaming.protocol import CachePolicy

_COMPLETIONS_PATH = "/v1/chat/completions"
_truncate_tool_result = truncate_tool_result
# WHY the pre-refactor name, not `__name__` (FX-19): this module moved from `runner/` to
# `world/` in unit 1, and operators filter the runtime log by logger name. Keeping the old name
# keeps every model-call lifecycle line byte-identical to `main`.
logger = logging.getLogger("screamingface_engine.runner.connector")

# Transport-retry policy for the aigateway hop (OME-1016). A transport failure
# (connection reset, read error, timeout) is transient by nature, so the connector
# retries it with exponential backoff + jitter before surfacing a retryable
# ResolutionError. Module-level so tests can zero them; the benchmark's own ``retry=``
# (url4) remains a second layer for HTTP-status failures and for a sustained outage.
_TRANSPORT_RETRIES = 1  # one retry → two attempts; url4's retry= adds more if needed
_TRANSPORT_BACKOFF_BASE_S = 0.5
_TRANSPORT_BACKOFF_MAX_S = 8.0
_TRANSPORT_BACKOFF_JITTER_S = 0.25

# How long a gateway round trip may sit quiet before the log says so (OME-1126). Long
# enough that ordinary reasoning turns stay silent; short enough that a stalled provider
# endpoint is visible while it stalls rather than only after the run dies. Each later
# beat waits twice as long (capped) so a 20-minute reasoning marathon costs ~5 lines,
# not 20 — the log stays legible while still proving the call is alive.
_IN_FLIGHT_HEARTBEAT_S = 60.0
_IN_FLIGHT_HEARTBEAT_MAX_S = 600.0


async def _in_flight_heartbeat(model_id: str, started: float) -> None:
    """Announce a still-running round trip until the caller cancels this task."""
    wait = _IN_FLIGHT_HEARTBEAT_S
    while True:
        await asyncio.sleep(wait)
        logger.info(
            "model call in flight model=%s elapsed=%.0fs",
            model_id,
            time.monotonic() - started,
        )
        wait = min(wait * 2, _IN_FLIGHT_HEARTBEAT_MAX_S)


async def _logged_round_trip(
    http_client: httpx.AsyncClient,
    *,
    real_model_id: str,
    headers: dict[str, str],
    body: dict[str, object],
    cache: CachePolicy,
    max_tokens: object | None,
    operation_accounting: list[OperationAccounting | None],
) -> Choice:
    # FEATURE: OME-1161 exposes execution facts to optional, node-associated observers.
    async with ModelCall(real_model_id, current_log_sink()) as observation:
        return await _observed_round_trip(
            http_client,
            real_model_id=real_model_id,
            headers=headers,
            body=body,
            cache=cache,
            max_tokens=max_tokens,
            operation_accounting=operation_accounting,
            observation=observation,
        )


async def _observed_round_trip(
    http_client: httpx.AsyncClient,
    *,
    real_model_id: str,
    headers: dict[str, str],
    body: dict[str, object],
    cache: CachePolicy,
    max_tokens: object | None,
    operation_accounting: list[OperationAccounting | None],
    observation: ModelCall,
) -> Choice:
    """One gateway round trip with its lifecycle in the log.

    FEATURE: model-call lifecycle observability (OME-1126). One line per round trip's
    terminal outcome and a heartbeat while it is in flight, so the runtime log can tell
    "still thinking" from "dead" — model id, duration, and finish_reason/error code
    ONLY, never prompt or response text (OME-990).
    """
    started = time.monotonic()
    heartbeat = asyncio.create_task(_in_flight_heartbeat(real_model_id, started))
    try:
        resp, outcome = await _fetch_completion(
            http_client, headers=headers, body=body, cache=cache
        )
        data = _json_or_raise(resp)
        _report_usage(real_model_id, data.get("usage"), data.get("_aigw"), outcome)
        retained = _retained_operation_accounting(
            request_model=real_model_id,
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
            aigw=data.get("_aigw"),
            cache=outcome,
        )
        operation_accounting.append(retained)
        choice = parse_choice(data)
        # INVARIANT: report BEFORE classifying. A refused turn is the case a reviewer most
        # needs to audit, and raising first would lose exactly the event OME-679 exists to
        # capture.
        _report_response(choice, outcome, data.get("_aigw"))
        _raise_if_unusable_with_accounting(
            choice,
            max_tokens=max_tokens,
            accounting=operation_accounting,
        )
    except (RunnerRequestError, ResolutionError) as exc:
        observation.failed(exc.code)
        logger.warning(
            "model call failed model=%s duration=%.1fs code=%s",
            real_model_id,
            time.monotonic() - started,
            exc.code,
        )
        raise
    except asyncio.CancelledError:
        # WHY (FX-18): a sync timeout or a dropped caller cancels the call. Without this line the
        # log shows a dispatch and then nothing. It is not a failure of the call, so the
        # observation is not told `failed`; the observer sees the cancellation on scope exit.
        logger.warning(
            "model call cancelled model=%s duration=%.1fs",
            real_model_id,
            time.monotonic() - started,
        )
        raise
    finally:
        # INVARIANT: return or cancellation leaves no operator heartbeat task behind.
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
    logger.info(
        "model call completed model=%s duration=%.1fs finish_reason=%s",
        real_model_id,
        time.monotonic() - started,
        choice.finish_reason,
    )
    observation.completed(choice.finish_reason)
    return choice


@dataclass(frozen=True)
class AigatewayConfig:
    """The resolved aigateway world settings a run needs — routes, timeouts, and the optional
    Tavily tool loop."""

    base_url: str = "http://127.0.0.1:9105"
    default_model: str = "claude-haiku-4-5"
    # WHY: DECLARED, never discovered — see `config.routes_for`. Empty is a config error, not a
    # signal to go ask the gateway what it serves. Each entry carries its own capability
    # (`web_search`), so a route's behavior is declared beside the route.
    models: tuple[ModelSpec, ...] = ()
    # WHY: absolute-URL sources are a real url4 feature, so the default preserves the behavior a
    # `Url4Node` world has always had. Set False to hand the node a denying outbound layer.
    allow_outbound: bool = True
    timeout_s: float = 60.0
    tavily_base_url: str = "https://api.tavily.com"
    tavily_search_depth: str = "advanced"
    tavily_max_results: int = 5
    tavily_timeout_s: float = 30.0
    web_tool_max_iterations: int = 5
    # INVARIANT: the iteration count alone does NOT bound this loop's cost. Two other dimensions
    # have to be bounded or a single expression can run away:
    #
    # - a tool result is appended to `messages` and RE-SENT on every later iteration, so an
    #   uncapped `raw_content` from one `web_fetch` is paid for repeatedly and can exceed the
    #   model's context window outright (a 400 the loop turns into a permanent failure);
    # - the model chooses how many tool calls one turn contains, and they are dispatched
    #   concurrently, so an unbounded fan-out is an unbounded burst of upstream requests.
    web_tool_max_result_bytes: int = 32_768
    web_tool_max_calls_per_turn: int = 8


@dataclass
class AigatewayWorld:
    """The resolved world: the `Url4Node` plus the HTTP client(s) `aclose` must tear down."""

    node: Url4Node
    _client: httpx.AsyncClient
    _owns_client: bool
    _tavily_client: httpx.AsyncClient | None = None
    _owns_tavily_client: bool = False

    @property
    def web_tools_enabled(self) -> bool:
        """Whether this world CAN serve web tools at all — i.e. a Tavily key was configured.

        Derived, not stored: a Tavily client exists exactly when a key was configured, so a
        separate flag could only ever agree with `_tavily_client` — or drift from it.

        This is the world-level capability, NOT a promise that any given call sends tools:
        a route sends them only when its own `ModelSpec.uses_web_tools` is true. Both must hold.
        """
        return self._tavily_client is not None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        if self._tavily_client is not None and self._owns_tavily_client:
            await self._tavily_client.aclose()


class _ModelEndpoint:
    """The handler registered on every declared route.

    A class rather than a closure: the node holds this for the whole run either way, so the
    `__slots__` fields below are retained for the run's duration just as a closure would retain
    them; that is not what the class buys. What it avoids is pinning
    `build_aigateway_world`'s *other* frame locals along with them — e.g. `owns_client`,
    `client`, `tavily_client` — which a closure would keep alive for the whole run even though
    `__call__` never touches them, but this class holds only the fields it actually needs.

    FEATURE (F2, prd/01): the handler is STATELESS with respect to the caller. Identity,
    profile, cache policy and answer seed are read from `current_scope()` per call, so one world
    can serve many callers without letting one request's values reach another's (AC2). Anything
    added here must be world-level (a route, an HTTP client), never per-request.
    """

    __slots__ = (
        "_cfg",
        "_http_client",
        "_routes",
        "_tavily_api_key",
        "_tavily_http",
    )

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        cfg: AigatewayConfig,
        routes: dict[str, ModelSpec],
        tavily_http: httpx.AsyncClient | None,
        tavily_api_key: str | None,
    ) -> None:
        self._http_client = http_client
        self._cfg = cfg
        self._routes = routes
        self._tavily_http = tavily_http
        self._tavily_api_key = tavily_api_key

    async def __call__(self, request: Request) -> str:
        # The route resolves to its whole spec, so the id and the capabilities it was declared
        # with travel together — the call can never run one route's model under another's flags.
        try:
            spec = self._routes[request.path]
            # INVARIANT (F2): the caller's state is read HERE, per call, from the request scope —
            # never held on `self`. Two concurrent callers through this one handler each observe
            # their own scope because each runs in its own context (AC2), and a spawned model
            # call inherits the scope of the task that created it (AC4).
            scope = current_scope()
            retrieval_policy = current_retrieval_policy()
            params = apply_retrieval_policy(request.params, retrieval_policy)
            # FEATURE (OME-1038): the run's declared answer seed, stamped AFTER the retrieval
            # ceiling, ONLY inside the Candidate invocation (answering, never benchmark-authored
            # grading — a judge whose pinned params carry no seed must not be re-keyed per
            # sitting), and only onto calls that pin no seed of their own. None is a no-op, so
            # an undeclared run's egress stays byte-identical to today's.
            #
            # FEATURE (prd/03 F2, unit 3): the SYNC surface is its own answering context and has
            # no benchmark-authored judge to protect (D1 — a direct mount hit never runs the DAG),
            # so its declared seed applies on `origin == "sync"` even outside a Candidate
            # invocation. Without this the caller's `X-Answer-Seed` would reach the node tier and
            # be silently dropped at the one hop that must forward it.
            ambient_seed = (
                (None if scope.answer_seed is None else str(scope.answer_seed))
                if in_candidate_invocation() or scope.origin == "sync"
                else None
            )
            params = apply_answer_seed(params, ambient_seed)
            # WHY: the identity is the REQUEST's path and params (pre-policy), because
            # OME-843 attribution matches them against the candidate expression's own
            # source text — the policy-applied set may differ from what was written.
            with operation_call_identity(
                request.path,
                request.params,
                context=request.context,
                intent=request.intent,
            ):
                return await _chat_completion_loop(
                    http_client=self._http_client,
                    cfg=self._cfg,
                    scope=scope,
                    messages=_messages(request.context, request.intent),
                    params=params,
                    spec=spec,
                    tavily_http=self._tavily_http,
                    tavily_api_key=self._tavily_api_key,
                    retrieval_policy=retrieval_policy,
                )
        except RunnerRequestError as exc:
            error = ResolutionError(str(exc), code=exc.code, permanent=exc.permanent)
            if exc.outcome is not None:
                bind_model_outcome(error, exc.outcome)
            raise error from exc


async def build_aigateway_world(
    cfg: AigatewayConfig,
    *,
    client: httpx.AsyncClient | None = None,
    tavily_api_key: str | None = None,
    tavily_client: httpx.AsyncClient | None = None,
) -> AigatewayWorld:
    """Build the `Url4Node` world: one endpoint per declared model, routed to aigateway.

    The world carries NO caller state (F2). Identity, profile, cache policy and answer seed are
    per-request values read from the `request_scope` ContextVar by `_ModelEndpoint.__call__`, so
    the same world can be shared by every caller in the process without one request's values
    reaching another's. A producer binds the scope before any handler runs — the child run path
    in `runner.main.request_scope_from_env`, the sync surface per request (unit 3).

    ``client``, ``tavily_api_key`` and ``tavily_client`` remain build-time inputs because they
    are world-level: one HTTP client and one optional tool credential serve every request.

    Raises:
        WorldConfigError: no models are declared, or `default_model` is not among them.
    """
    if not cfg.models:
        raise WorldConfigError(
            "aigateway declares no models — the runner's endpoints are declared in url4.toml, "
            "not discovered from the gateway catalog"
        )
    declared_ids = [model.id for model in cfg.models]
    if cfg.default_model not in declared_ids:
        raise WorldConfigError(
            f"default_model {cfg.default_model!r} is not a declared model {declared_ids!r}"
        )

    owns_client = client is None
    http_client = (
        client
        if client is not None
        else httpx.AsyncClient(base_url=cfg.base_url, timeout=cfg.timeout_s)
    )
    routes = routes_for(cfg.models)

    normalized_tavily_key = tavily_api_key.strip() if tavily_api_key else None
    normalized_tavily_key = normalized_tavily_key or None
    tavily_http, owns_tavily_client = build_client(
        cfg,
        normalized_tavily_key,
        tavily_client,
    )

    call_model = _ModelEndpoint(
        http_client=http_client,
        cfg=cfg,
        routes=routes,
        tavily_http=tavily_http,
        tavily_api_key=normalized_tavily_key,
    )

    # WHY: `outbound=StaticIOLayer()` denies every absolute-URL fetch: an unmapped target raises
    # instead of reaching HttpIOLayer. Left None, the node lazily builds HttpIOLayer and can
    # fetch any URL — which is what a token-bearing run has always been able to do.
    node = Url4Node(
        "aigateway",
        default_processor="/" + cfg.default_model,
        outbound=None if cfg.allow_outbound else StaticIOLayer(),
    )
    for path in routes:
        node.endpoint(path)(call_model)
    return AigatewayWorld(
        node=node,
        _client=http_client,
        _owns_client=owns_client,
        _tavily_client=tavily_http,
        _owns_tavily_client=owns_tavily_client,
    )


def _report_response(choice: Choice, cache: CacheOutcome, aigw: object = None) -> None:
    """Report how one model round trip ended — whether the gateway served it from its response
    cache, and what that hit avoided — onto the currently-resolving node's span.

    Null-safe exactly like `_report_usage`: outside a run, or with no observer attached, the
    sink is absent and this is a no-op.

    INVARIANT: reported BESIDE `_report_usage`, for the same call, or the two disagree. A hit
    costs nothing upstream while `_report_usage` bills it as a fresh call, so a span that
    carries the tokens without the outcome states a cost that was never paid — an error in the
    direction that hides savings, and therefore one nobody reports.

    INVARIANT: the saved cost is derived from `aigw` — the accounting of the round trip whose
    outcome `cache` describes — and never from a discarded one. `_fetch_completion` may refuse a
    hit and re-issue the call, returning the SECOND trip's outcome; deriving from that same
    returned pair is what keeps the discarded hit's cost out of the run total (PRD test 17).

    INVARIANT: a hit whose round trip was RETRIED is never priced. A transport retry can follow
    an attempt the provider already processed and billed, so pricing the hit would report money
    saved that was in fact spent — the one direction of error this whole feature exists to
    remove.
    """
    sink = current_response_sink()
    if sink is None:
        return
    saved = avoided_usd_for_outcome(aigw, cache)
    sink(
        finish_reason=choice.finish_reason,
        refusal=choice.refusal,
        cache_status=cache.status,
        cache_reason=cache.reason,
        cache_saved_cost_usd=saved.usd,
        cache_saved_cost_provenance=saved.provenance,
    )


def _token_count(*candidates: object) -> int:
    """The first candidate that is a real non-negative count, else 0.

    `bool` is refused explicitly: it is an `int` subclass, so a stray `True` would count as one
    token. Zero is the last resort because the wire's `TokenUsage` has no way to say "unknown".
    """
    for candidate in candidates:
        if not isinstance(candidate, bool) and isinstance(candidate, int) and candidate >= 0:
            return candidate
    return 0


def _report_served_from_cache(model: str, call: CallAccounting | None, *, retried: bool) -> None:
    """Report a cache hit: zero tokens consumed, and priced at zero unless a retry preceded it.

    WHY zero rather than the numbers the response carries: a hit replays a STORED response, whose
    body still contains the original call's `usage`. aigateway says so explicitly — it labels the
    cache reference `incurred_in_current_request: false` and publishes no attempts — and
    `accounting.usd_from_aigw` already honours that boundary by refusing to price the reference.
    Counting the same reference's tokens as freshly consumed treats one piece of evidence two
    opposite ways, and inflates every consumption figure a cache-heavy run reports.

    WHY explicit zeros rather than `None`: `None` means "the gateway did not report it". Here the
    gateway reported something definite — nothing was consumed — and a run total must be able to
    add that in rather than treat it as a gap.

    INVARIANT: an UNRETRIED hit stays `Decimal("0")` and never `None`. Zero is a real claim about
    a real saving; a dash would hide it. `usd_from_aigw` derives it from the SAME hit, so the two
    agree.

    INVARIANT: a RETRIED hit is `None` — "not priced" — because nobody can know what it cost.
    `_post_completion` retries a lost reply, and the attempt whose reply was lost may already have
    been processed and billed upstream, in which case the row this attempt hit is the very one it
    paid for and wrote. `avoided_usd_for_outcome` already withdraws the SAVING on exactly this
    evidence; withdrawing the saving while still asserting a spend of zero would state two
    opposite confidences about one ambiguous fact, and the zero is the more misleading half —
    a run total sums it in as certainty. `_fold_usage` latches the run UNPRICED on it instead.

    AIDEV-NOTE: scoped to the HIT path deliberately. A retried MISS carries the gateway's own
    attempt accounting and keeps its provider-authored price; that figure is a lower bound rather
    than a false zero, and widening the withdrawal to every retried round trip would cost every
    run its cost total on a single transport blip. Revisit only with that trade stated.

    AIDEV-NOTE: hit-ness is decided by the caller from the published `CacheOutcome` (the response
    headers), NOT from `_aigw`. That is deliberate — an older gateway emits the header and no
    accounting block at all, and it keeps these token counts consistent with the `cache_status`
    published beside them on the same span.
    """
    sink = current_usage_sink()
    if sink is None:
        return
    sink(
        provider=call.provider if call is not None and call.provider else provider_of(model),
        model=model,
        input_tokens=0,
        output_tokens=0,
        response_model=call.response_model if call is not None else None,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        cost_usd=None if retried else _hit_cost(call),
    )


def _hit_cost(call: CallAccounting | None) -> Decimal:
    """A non-retried hit's price: the gateway's own figure, or an explicit zero when it reported
    no accounting at all. Never `None` — see the invariant above."""
    return call.cost_usd if call is not None and call.cost_usd is not None else Decimal(0)


def _report_usage(
    model: str, usage: dict | None, aigw: object = None, cache: CacheOutcome | None = None
) -> None:
    """Report one gateway round trip's token and cost evidence onto the calling node's span.

    FEATURE: per-run cost reporting (OME-849). Prefers aigateway's `_aigw` accounting, which states
    the provider and the served model authoritatively and carries the cache/reasoning token classes
    plus a provider-authored cost. Falls back to the provider's own `usage` object when no
    accounting is present — the pre-`_aigw` behaviour, which an older gateway still produces.

    INVARIANT: reported per ROUND TRIP, not per turn. A tool loop is several gateway calls against
    one span and each carries its own accounting, so the span accumulates them (see
    `executor._RunState._fold_usage`).

    INVARIANT (OME-868): a published `cache_status` of `hit` and a non-zero token count are a
    CONTRADICTION, and this is the seam that keeps them consistent. A hit is served from the
    gateway's store, so the provider consumed nothing this request — see
    `_report_served_from_cache`.
    """
    sink = current_usage_sink()
    if sink is None:
        return
    call = read_aigw(aigw)
    if call is None and usage is None:
        return
    if cache is not None and cache.status == "hit":
        _report_served_from_cache(model, call, retried=cache.retried)
        return
    reported = usage or {}
    sink(
        # INVARIANT: `_aigw` is authoritative for the provider. `provider_of` is the shared catalog
        # rule — an unprefixed id is Anthropic's — and it is the ONLY source when a cache hit means
        # there are no attempts to read a provider off. Never re-derive that rule locally.
        provider=call.provider if call is not None and call.provider else provider_of(model),
        model=model,
        # A cache hit carries no attempts, so its token counts come from the cached provider body.
        input_tokens=_token_count(
            call.input_tokens if call is not None else None, reported.get("prompt_tokens")
        ),
        output_tokens=_token_count(
            call.output_tokens if call is not None else None, reported.get("completion_tokens")
        ),
        response_model=call.response_model if call is not None else None,
        cache_read_tokens=call.cache_read_tokens if call is not None else None,
        cache_creation_tokens=call.cache_creation_tokens if call is not None else None,
        reasoning_tokens=call.reasoning_tokens if call is not None else None,
        cost_usd=call.cost_usd if call is not None else None,
    )


async def _post_completion(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
) -> tuple[httpx.Response, bool]:
    """One chat-completions POST: retry transport failures, then translate to a retryable error.

    WHY (OME-1016): a transport failure (connection reset, read error, timeout) is
    transient by nature — aigateway may be restarting or a pooled keep-alive connection
    went stale. Left raw, an ``httpx.ReadError`` bypasses the benchmark's declared
    ``retry=`` policy (url4 retries only ``Url4Error``) and carries no error ``code``,
    so the report falls back to the opaque benchmark default (``draco_grading_failed``)
    with a useless ``ReadError('')`` message. This retries the transport failure with
    exponential backoff + jitter (so concurrent judge calls that fail together do not
    retry in lockstep), then raises a retryable ``ResolutionError`` that names the real
    cause. ``HTTPStatusError`` is deliberately NOT caught — ``_raise_for_status``
    handles non-2xx after the post returns.

    Returns the response and WHETHER A RETRY PRECEDED IT. A retried attempt may already have
    been processed and billed with only its reply lost, so accounting must not treat the
    attempt that finally answered as the whole operation.

    FEATURE (04-review-fixes §2.1, FX-1): when the bound request scope carries a ``deadline``
    (the sync surface), each attempt's timeout is ``min(configured, time left)``, and a retry is
    not started when the backoff plus one full attempt no longer fits. With no deadline (the
    ensemble path) the post is the one this function has always made.

    FEATURE (§2.2b): when the BUDGET is what ran out — an attempt timed out at the time-left
    bound, the time left was already gone, or a retry did not fit — the transient code is
    ``aigateway_deadline_exceeded`` (still a 502), so the R7 signal stays countable. With no
    deadline the codes are unchanged.
    """
    deadline = _current_deadline()
    # WHY the READ timeout is "the configured timeout": it bounds how long one attempt waits for
    # aigateway's answer, which is what a slow model spends. The world builds its client with
    # `httpx.Timeout(timeout_s)`, which sets all four parts to that one value.
    configured = http_client.timeout.read
    last: httpx.TransportError | None = None
    for attempt in range(_TRANSPORT_RETRIES + 1):
        timeout = _attempt_timeout(deadline, configured, last)
        try:
            response = await _post_attempt(http_client, headers=headers, body=body, timeout=timeout)
        except httpx.TransportError as exc:
            last = exc
            if isinstance(exc, httpx.TimeoutException) and _deadline_bound(timeout, configured):
                raise _deadline_exceeded(exc) from exc
            if attempt < _TRANSPORT_RETRIES:
                delay = _transport_backoff(attempt)
                if deadline is not None and not _retry_fits(deadline, delay, configured):
                    raise _deadline_exceeded(exc) from exc
                observation = current_model_call()
                if observation is not None:
                    observation.retry(attempt=attempt + 2, delay_seconds=delay)
                await asyncio.sleep(delay)
            continue
        return response, attempt > 0
    assert last is not None  # every path out of the loop that did not return set it
    raise ResolutionError(
        f"aigateway request failed at the transport layer: {_transport_detail(last)}",
        code="aigateway_transport_error",
        permanent=False,
    ) from last


def _current_deadline() -> float | None:
    """The bound request's deadline, or None when no request budget applies.

    WHY an unbound read means "no deadline" and does not raise: `_post_completion` worked with no
    scope bound before FX-1, and a missing deadline must keep it byte-identical. The loud AC5
    refusal stays where it matters — `_ModelEndpoint` reads the caller's identity through
    `current_scope()`, which still raises when nothing is bound.
    """
    try:
        return current_scope().deadline
    except RequestScopeError:
        return None


def _attempt_timeout(
    deadline: float | None, configured: float | None, last: httpx.TransportError | None
) -> float | None:
    """The next attempt's timeout: None (the client's own) with no deadline, else the time left
    capped by ``configured``.

    Raises:
        ResolutionError: ``aigateway_deadline_exceeded`` when no time is left for an attempt.
    """
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _deadline_exceeded(last)
    return remaining if configured is None else min(configured, remaining)


def _deadline_bound(timeout: float | None, configured: float | None) -> bool:
    """Whether an attempt ran under the time-left bound rather than the configured timeout."""
    return timeout is not None and (configured is None or timeout < configured)


def _deadline_exceeded(cause: httpx.TransportError | None) -> ResolutionError:
    """The transient refusal for a request whose budget ran out upstream (§2.2b)."""
    detail = _transport_detail(cause) if cause is not None else "no time left for an attempt"
    return ResolutionError(
        f"aigateway request ran out of the request budget: {detail}",
        code="aigateway_deadline_exceeded",
        permanent=False,
    )


async def _post_attempt(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
    timeout: float | None,
) -> httpx.Response:
    """One POST under ``timeout``, or under the client's own timeout when it is None.

    INVARIANT: with no deadline the POST passes no ``timeout`` — the client's own configured
    timeout applies, byte-identical to the ensemble path before FX-1.
    """
    if timeout is None:
        return await http_client.post(_COMPLETIONS_PATH, headers=headers, json=body)
    return await http_client.post(_COMPLETIONS_PATH, headers=headers, json=body, timeout=timeout)


def _retry_fits(deadline: float, delay: float, configured: float | None) -> bool:
    """Whether the backoff plus one full attempt still ends before ``deadline``.

    WHY the CONFIGURED timeout and not the time left: an attempt capped to the time left is the
    attempt the wrapper would cut off — billed and useless (NT-H1). With no configured read
    timeout, only the backoff itself has to fit.
    """
    return deadline - time.monotonic() >= delay + (configured or 0.0)


def _transport_backoff(attempt: int) -> float:
    """Exponential backoff plus jitter for the next transport retry.

    ``attempt`` is the zero-based index of the attempt that just failed, so the first
    retry waits ``base``, the second ``2*base``, capped at ``backoff_max_s``; jitter
    de-synchronises concurrent siblings that failed together.
    """
    delay = min(_TRANSPORT_BACKOFF_BASE_S * 2**attempt, _TRANSPORT_BACKOFF_MAX_S)
    return delay + random.uniform(0.0, _TRANSPORT_BACKOFF_JITTER_S)


def _transport_detail(exc: httpx.TransportError) -> str:
    """A stable one-line description of a transport failure, even when ``str()`` is empty.

    ``httpx.ReadError('')`` stringifies to an empty string; the class name alone is
    still actionable, and a non-empty message keeps ``_error_payload`` from falling
    back to ``repr(exc)``.
    """
    detail = str(exc).strip()
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


async def _fetch_completion(
    http_client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    body: dict,
    cache: CachePolicy,
) -> tuple[httpx.Response, CacheOutcome]:
    """One chat-completions round trip under this run's cache policy, plus what the gateway
    reported about the cache — re-issued without the cache when the answer cannot be served.

    The re-issue is D11's honouring half (spec §3.5). A caller that stated `max-age` gets an
    answer it can trust: a hit whose age the gateway cannot establish is refused rather than
    served, since the corpus is global and never expires, so "how old is this" has no bound at
    all. It costs one extra round trip and a discarded body, and ONLY on a hit — a miss or a
    bypass was generated just now and satisfies every bound already (`requires_revalidation`).

    INVARIANT: the discarded response is read for its headers and nothing else. Its usage is
    never reported, or the turn would be billed twice — the exact error class this read-back
    exists to prevent.

    Returns:
        The response to consume, and the cache outcome of the round trip that produced IT — not
        of the one that was discarded, whose only remaining trace is that it happened.
    """
    resp, retried = await _post_completion(
        http_client,
        headers=headers,
        # `policy_to_body_field` yields an EMPTY dict for a run that participates, so an ordinary
        # run's body is byte-identical to the one this connector has always sent — which is also
        # the smallest surface exposed to the gateway's closed cache grammar, where one
        # unrecognised key silently costs every hit (spec §1.0).
        body={**body, **policy_to_body_field(cache)},
    )
    _raise_for_status(resp)
    outcome = read_cache_outcome(resp.headers, retried=retried)
    if not requires_revalidation(cache, outcome):
        return resp, outcome
    # An explicit opt-out, built here rather than derived from `cache`: the run's own policy
    # PARTICIPATES (a bound is not a refusal), and the re-issue must state the one thing the
    # closed grammar understands — `use-cache: false` — and nothing else.
    resp, reissue_retried = await _post_completion(
        http_client,
        headers=headers,
        body={**body, **policy_to_body_field(CachePolicy(participate=False))},
    )
    _raise_for_status(resp)
    return resp, read_cache_outcome(resp.headers, retried=reissue_retried)


async def _chat_completion_loop(
    *,
    http_client: httpx.AsyncClient,
    cfg: AigatewayConfig,
    scope: RequestScope,
    messages: list[dict],
    spec: ModelSpec,
    params: Mapping[str, str],
    tavily_http: httpx.AsyncClient | None,
    tavily_api_key: str | None,
    retrieval_policy: RetrievalPolicy | None = None,
) -> str:
    """Drive one `_ModelEndpoint` call: post to aigateway, execute any requested tool calls,
    and repeat until the model answers with content instead of another tool call.

    Tools are offered only when the route's mechanism resolves to `ModelSpec.uses_web_tools`
    and the world can serve them through Tavily. A configured key alone must never change a
    model request, an explicit ``web_search=false`` disables retrieval, and benchmark-required
    search fails closed when Tavily is unavailable.

    INVARIANT: the cache policy is re-applied on EVERY round trip, not merged once before the
    loop. One turn is several independently-keyed gateway calls, and a policy that lapsed after
    the first would serve the tool-augmented continuation — the most context-specific call of the
    turn — from a shared corpus the caller had just refused.

    Raises:
        ResolutionError: the loop exceeds `cfg.web_tool_max_iterations` without a final
            answer — the model keeps calling tools instead of returning content.
    """
    # WHY decoded once, here: `spec.id` is ALWAYS the url4-route form (OME-873) — decoding is a
    # no-op for the 88 ids with no colon, so this is safe unconditionally. Everything past this
    # line that reaches aigateway or reports what aigateway actually billed uses `real_model_id`;
    # error messages below keep `spec.id` (the route form), since that's what the caller wrote.
    real_model_id = decode_route_id(spec.id)
    tools, extra = _retrieval_request(
        cfg=cfg,
        spec=spec,
        params=params,
        tavily_http=tavily_http,
        tavily_api_key=tavily_api_key,
        retrieval_policy=retrieval_policy,
    )
    sampling = model_params(params)
    headers = _headers(scope)
    operation_accounting: list[OperationAccounting | None] = []
    for _ in range(cfg.web_tool_max_iterations):
        body = {"model": real_model_id, "messages": messages, **sampling, **extra}
        choice = await _logged_round_trip(
            http_client,
            real_model_id=real_model_id,
            headers=headers,
            body=body,
            cache=scope.cache,
            max_tokens=sampling.get("max_tokens"),
            operation_accounting=operation_accounting,
        )
        content, tool_calls = choice.content, choice.tool_calls
        if not tool_calls:
            # Recorded HERE, not per round trip: a tool loop is several round trips serving ONE
            # logical model call, and only this one is terminal. Publishing the intermediate
            # `tool_calls` rounds too would leave a consumer unable to tell a call that progressed
            # from two calls that disagreed (`_terminal_outcome` in `benchmarks/candidate.py`).
            record_model_outcome(choice.finish_reason, choice.refusal)
            record_operation_call(
                content or "",
                choice.finish_reason,
                combine_operation_accounting(operation_accounting),
            )
            return content or ""
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        await append_tool_results(messages, tool_calls, tools, cfg)
    raise ResolutionError(
        f"web tool loop exceeded {cfg.web_tool_max_iterations} iterations",
        code="web_tool_loop_limit",
        permanent=False,
    )


def _retained_operation_accounting(
    *,
    request_model: str,
    usage: Mapping[str, object] | None,
    aigw: object,
    cache: CacheOutcome,
) -> OperationAccounting | None:
    """Fail-open projection of untrusted Gateway accounting onto the strict retained contract."""

    try:
        return retained_operation_accounting(
            request_model=request_model,
            usage=usage,
            aigw=aigw,
            cache=cache,
        )
    except Exception as exc:
        # INVARIANT: accounting is optional bookkeeping over an already-consumed response. No
        # malformed accounting field may replace a successful answer/refusal with a run failure,
        # and diagnostics disclose only the phase plus exception type — never Gateway payloads.
        logger.warning("operation accounting unavailable after %s", type(exc).__name__)
        return None


def _raise_if_unusable_with_accounting(
    choice: Choice,
    *,
    max_tokens: object,
    accounting: list[OperationAccounting | None],
) -> None:
    """Classify one response while retaining a consumed provider refusal."""

    try:
        raise_if_unusable(choice, max_tokens=max_tokens)
    except RunnerRequestError as exc:
        if exc.code == "provider_refusal":
            # INVARIANT: a refusal remains a terminal Candidate outcome. Record its consumed
            # accounting before the typed failure exits; the invocation adapter then retains it.
            record_operation_call(
                "",
                choice.finish_reason,
                combine_operation_accounting(accounting),
            )
        raise


def _retrieval_request(
    *,
    cfg: AigatewayConfig,
    spec: ModelSpec,
    params: Mapping[str, str],
    tavily_http: httpx.AsyncClient | None,
    tavily_api_key: str | None,
    retrieval_policy: RetrievalPolicy | None,
) -> tuple[WebToolRuntime | None, dict[str, object]]:
    if (
        retrieval_policy is not None
        and params.get(WEB_SEARCH_PARAM) == "true"
        and not spec.web_search
    ):
        raise ResolutionError(
            f"model route {spec.id!r} declares web_search = false",
            code="benchmark_retrieval_unavailable",
            permanent=True,
        )
    wants_search = wants_web_search(params, spec)
    tools = build_runtime(
        spec=spec,
        wants_search=wants_search,
        tavily_http=tavily_http,
        tavily_api_key=tavily_api_key,
        config=cfg,
        policy=retrieval_policy,
        params=params,
    )
    if wants_search and spec.uses_native_web_search:
        extra: dict[str, object] = {"web_search": True}
        exclusions = caller_exclusions(params)
        if exclusions:
            extra["web_search_excluded_domains"] = list(exclusions)
        return tools, extra
    if tools is not None:
        return tools, {"tools": WEB_TOOLS, "tool_choice": "auto"}
    return tools, {}


def _messages(context: str | None, intent: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if intent:
        messages.append({"role": "system", "content": intent})
    native = _native_messages(context)
    if native is None:
        messages.append({"role": "user", "content": context or ""})
    else:
        messages.extend(native)
    return messages


def _native_messages(context: str | None) -> list[dict[str, str]] | None:
    envelope = _candidate_input_envelope(context)
    if envelope is None:
        return None
    return _candidate_messages(envelope["messages"])


def _candidate_input_envelope(context: str | None) -> dict[str, object] | None:
    value = _json_object(context)
    if value is None:
        return None
    schema = value.get("schema")
    if schema == CANDIDATE_INPUT_SCHEMA:
        if set(value) != {"schema", "messages"}:
            _invalid_candidate_input("the chat envelope must contain only schema and messages")
        return value
    if isinstance(schema, str) and schema.startswith("screamingface.candidate-input."):
        _invalid_candidate_input(f"unsupported schema {schema!r}")
    return None


def _json_object(context: str | None) -> dict[str, object] | None:
    if not context:
        return None
    try:
        value = json.loads(context)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _candidate_messages(raw_messages: object) -> list[dict[str, str]]:
    if not isinstance(raw_messages, list) or not raw_messages:
        _invalid_candidate_input("messages must be a non-empty array")
    return [_candidate_message(index, value) for index, value in enumerate(raw_messages)]


def _candidate_message(index: int, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"role", "content"}:
        _invalid_candidate_input(f"message {index} must contain exactly role and content")
    role = value.get("role")
    content = value.get("content")
    if not isinstance(role, str) or role not in CANDIDATE_MESSAGE_ROLES:
        _invalid_candidate_input(f"message {index} has unsupported role {role!r}")
    if not isinstance(content, str):
        _invalid_candidate_input(f"message {index} content must be text")
    return {"role": role, "content": content}


def _invalid_candidate_input(detail: str) -> NoReturn:
    raise ResolutionError(
        f"invalid Candidate chat input: {detail}",
        code="invalid_candidate_input",
        permanent=True,
    )


def _headers(scope: RequestScope) -> dict[str, str]:
    """The outgoing aigateway headers: the caller's identity, then the values this world owns.

    INVARIANT: the gateway-owned header is written LAST. `scope.identity_headers` reaches here
    from an inbound request, and although Envoy guarantees a client cannot forge the identity
    header itself, nothing guarantees the mapping holds ONLY that key — so `X-Profile` is applied
    over it rather than under it, and no inbound value can displace this run's routing choice.
    Same ordering rule the aigateway provider plugins apply to their own gateway-owned headers.

    WHY no `Authorization`: aigateway runs `cloudflare_headers` when deployed and `disabled`
    locally. Neither mode reads a bearer token, and a deployed caller cannot obtain one, so the
    run carries none at all.

    FEATURE (OME-1119): `traceparent` is gateway-owned for the same reason `X-Profile` is, and is
    written under the same rule — the run's own trace must win over anything that arrived in the
    identity mapping. Absent (no bound run) the key is OMITTED rather than sent empty: a
    well-formed header carrying a zero or invented id would parse everywhere, join nothing, and
    look correct in every log it reached.

    INVARIANT (F2): identity, profile and seed come from the REQUEST SCOPE, never from `self`, so
    a shared world renders each caller's own values (AC2). The scope's `traceparent` wins when a
    producer set one (the sync surface, unit 3); the ensemble run keeps sourcing it from
    `run_trace_scope`, which url4's lifecycle binds inside the driving task.
    """
    headers = dict(scope.identity_headers)
    if scope.profile is not None:
        headers["X-Profile"] = scope.profile
    traceparent = scope.traceparent if scope.traceparent is not None else current_traceparent()
    if traceparent is not None:
        headers["traceparent"] = traceparent
    return headers


def _json_or_raise(resp: httpx.Response) -> dict:
    """Decode a 2xx body, naming the failure when it is not JSON at all.

    A fronting access proxy (CF Access) answers with an HTML login page under a 200, which
    `resp.json()` would surface as a bare JSONDecodeError — an unnamed `internal_error` in the
    run's terminal frame instead of something an operator can act on.
    """
    try:
        return resp.json()
    except ValueError as exc:
        # WHY: an empty completed reply supplies no evidence of malformed content or
        # interception. Permit a later retry without replaying a paid call here.
        if not resp.content:
            raise ResolutionError(
                "model request returned an empty response body; the request may be retried",
                code="aigateway_empty_response",
                permanent=False,
            ) from exc
        raise ResolutionError(
            "aigateway returned a non-JSON response body — a proxy or access gateway in front "
            "of aigateway is intercepting the request",
            code="aigateway_bad_response",
            permanent=True,
        ) from exc


def _raise_for_status(resp: httpx.Response) -> None:
    """Turn a non-2xx (or redirected) aigateway response into a `ResolutionError`.

    A redirect is treated as an interception by a fronting proxy, not a real aigateway response.
    For a 4xx/5xx, the error `code`/`message` prefer the response's own `detail` payload when
    present; `permanent` is `False` only for 429 and 5xx, so those (and only those) are
    eligible for retry upstream.
    """
    if 300 <= resp.status_code < 400:
        raise ResolutionError(
            f"aigateway returned an unexpected redirect (status {resp.status_code}) — a proxy "
            "or access gateway in front of aigateway is intercepting the request",
            code="aigateway_bad_response",
            permanent=True,
        )
    if resp.status_code < 400:
        return
    code = f"aigateway_http_{resp.status_code}"
    message = f"aigateway request failed with status {resp.status_code}"
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            code = detail.get("code", code)
            message = detail.get("message", message)
    permanent = not (resp.status_code == 429 or 500 <= resp.status_code < 600)
    raise ResolutionError(message, code=code, permanent=permanent)


__all__ = ["AigatewayConfig", "AigatewayWorld", "build_aigateway_world"]

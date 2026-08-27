"""Builds the aigateway-backed :class:`~url4.io.layer.IOLayer` world: a `Url4Node` whose
endpoints are declared models routed to aigateway's chat-completions API, plus an optional
Tavily-backed web-search/web-fetch tool loop. This is the world `executor.Url4Executor`
resolves and runs an expression against.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import NoReturn

import httpx

from screamingface_engine.benchmarks.contract import CANDIDATE_INPUT_SCHEMA, CANDIDATE_MESSAGE_ROLES
from screamingface_engine.model_outcomes import bind_model_outcome, record_model_outcome
from screamingface_engine.models.registry import decode_route_id
from screamingface_engine.operation_calls import operation_call_identity, record_operation_call
from screamingface_engine.retrieval_policy import (
    RetrievalPolicy,
    current_retrieval_policy,
)
from screamingface_engine.runner.accounting import CallAccounting, read_aigw
from screamingface_engine.runner.cache import policy_to_body_field
from screamingface_engine.runner.cache_readback import (
    CacheOutcome,
    read_cache_outcome,
    requires_revalidation,
)
from screamingface_engine.runner.errors import RunnerRequestError
from screamingface_engine.runner.model_response import (
    Choice,
    parse_choice,
    raise_if_unusable,
)
from screamingface_engine.runner.request_parameters import (
    WEB_SEARCH_PARAM,
    apply_retrieval_policy,
    caller_exclusions,
    model_params,
    wants_web_search,
)
from screamingface_engine.runner.web_tools import (
    WEB_TOOLS,
    WebToolRuntime,
    append_tool_results,
    build_client,
    build_runtime,
    truncate_tool_result,
)
from screamingface_engine.world_config import ModelSpec, WorldConfigError, provider_of, routes_for
from url4.core.errors import ResolutionError
from url4.io.static import StaticIOLayer
from url4.observe import current_response_sink, current_usage_sink
from url4.peer.server import Request, Url4Node
from url4.streaming.protocol import CachePolicy

_COMPLETIONS_PATH = "/v1/chat/completions"
_truncate_tool_result = truncate_tool_result

# Transport-retry policy for the aigateway hop (OME-1016). A transport failure
# (connection reset, read error, timeout) is transient by nature, so the connector
# retries it with exponential backoff + jitter before surfacing a retryable
# ResolutionError. Module-level so tests can zero them; the benchmark's own ``retry=``
# (url4) remains a second layer for HTTP-status failures and for a sustained outage.
_TRANSPORT_RETRIES = 1  # one retry → two attempts; url4's retry= adds more if needed
_TRANSPORT_BACKOFF_BASE_S = 0.5
_TRANSPORT_BACKOFF_MAX_S = 8.0
_TRANSPORT_BACKOFF_JITTER_S = 0.25


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
    """

    __slots__ = (
        "_cache",
        "_cfg",
        "_http_client",
        "_identity_headers",
        "_profile",
        "_routes",
        "_tavily_api_key",
        "_tavily_http",
    )

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        cfg: AigatewayConfig,
        profile: str | None,
        routes: dict[str, ModelSpec],
        tavily_http: httpx.AsyncClient | None,
        tavily_api_key: str | None,
        identity_headers: Mapping[str, str] | None = None,
        cache: CachePolicy,
    ) -> None:
        self._http_client = http_client
        self._cfg = cfg
        self._profile = profile
        self._routes = routes
        self._tavily_http = tavily_http
        self._tavily_api_key = tavily_api_key
        self._identity_headers = identity_headers
        # INVARIANT: held HERE and not on `cfg`. This object is built once per RUN, while `cfg` is
        # the world every run in the process shares — and in local mode those runs share an event
        # loop, so a policy parked on `cfg` is the previous caller's answer applied to this one.
        self._cache = cache

    async def __call__(self, request: Request) -> str:
        # The route resolves to its whole spec, so the id and the capabilities it was declared
        # with travel together — the call can never run one route's model under another's flags.
        try:
            spec = self._routes[request.path]
            retrieval_policy = current_retrieval_policy()
            params = apply_retrieval_policy(request.params, retrieval_policy)
            # WHY: the identity is the REQUEST's path and params (pre-policy), because
            # OME-843 attribution matches them against the candidate expression's own
            # source text — the policy-applied set may differ from what was written.
            with operation_call_identity(request.path, request.params):
                return await _chat_completion_loop(
                    http_client=self._http_client,
                    cfg=self._cfg,
                    profile=self._profile,
                    messages=_messages(request.context, request.intent),
                    params=params,
                    spec=spec,
                    tavily_http=self._tavily_http,
                    tavily_api_key=self._tavily_api_key,
                    retrieval_policy=retrieval_policy,
                    identity_headers=self._identity_headers,
                    cache=self._cache,
                )
        except RunnerRequestError as exc:
            error = ResolutionError(str(exc), code=exc.code, permanent=exc.permanent)
            if exc.outcome is not None:
                bind_model_outcome(error, exc.outcome)
            raise error from exc


async def build_aigateway_world(
    cfg: AigatewayConfig,
    *,
    profile: str | None = None,
    client: httpx.AsyncClient | None = None,
    tavily_api_key: str | None = None,
    tavily_client: httpx.AsyncClient | None = None,
    identity_headers: Mapping[str, str] | None = None,
    cache: CachePolicy | None = None,
) -> AigatewayWorld:
    """Build the `Url4Node` world: one endpoint per declared model, routed to aigateway.

    ``identity_headers`` is the caller's verified identity (canonical header name →
    value, see `screamingface_engine.job_env.IDENTITY_HEADER_ENV`), rendered onto
    every chat-completions request this world makes. It is per-RUN rather than
    per-call: one run has exactly one caller, so the endpoint holds it for the run's
    duration exactly as it holds `profile`.

    ``cache`` is that run's cache policy, and it is a PARAMETER of this call rather than a field of
    `cfg` for exactly one reason: `cfg` is the world, one description of the gateway shared by
    every run in the process, and a per-run value there is a value one run reads out of another's.
    ``None`` means nothing was stated, which reaches the wire as no `cache` field at all — the
    gateway's own default — so this half never has to re-decide what silence means.

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
        profile=profile,
        routes=routes,
        tavily_http=tavily_http,
        tavily_api_key=normalized_tavily_key,
        identity_headers=identity_headers or None,
        # `is not None`, not `or`: a policy is a pydantic model and always truthy, but spelling the
        # fallback explicitly says what it is — an unstated policy, not a stated default.
        cache=cache if cache is not None else CachePolicy(),
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


def _report_response(choice: Choice, cache: CacheOutcome) -> None:
    """Report how one model round trip ended — and whether the gateway served it from its
    response cache — onto the currently-resolving node's span.

    Null-safe exactly like `_report_usage`: outside a run, or with no observer attached, the
    sink is absent and this is a no-op.

    INVARIANT: reported BESIDE `_report_usage`, for the same call, or the two disagree. A hit
    costs nothing upstream while `_report_usage` bills it as a fresh call, so a span that
    carries the tokens without the outcome states a cost that was never paid — an error in the
    direction that hides savings, and therefore one nobody reports.
    """
    sink = current_response_sink()
    if sink is None:
        return
    sink(
        finish_reason=choice.finish_reason,
        refusal=choice.refusal,
        cache_status=cache.status,
        cache_reason=cache.reason,
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


def _report_served_from_cache(model: str, call: CallAccounting | None) -> None:
    """Report a cache hit: priced at zero, and zero tokens consumed.

    WHY zero rather than the numbers the response carries: a hit replays a STORED response, whose
    body still contains the original call's `usage`. aigateway says so explicitly — it labels the
    cache reference `incurred_in_current_request: false` and publishes no attempts — and
    `accounting.usd_from_aigw` already honours that boundary by refusing to price the reference.
    Counting the same reference's tokens as freshly consumed treats one piece of evidence two
    opposite ways, and inflates every consumption figure a cache-heavy run reports.

    WHY explicit zeros rather than `None`: `None` means "the gateway did not report it". Here the
    gateway reported something definite — nothing was consumed — and a run total must be able to
    add that in rather than treat it as a gap.

    INVARIANT: the price stays `Decimal("0")` and never `None`. Zero is a real claim about a real
    saving; a dash would hide it. `usd_from_aigw` derives it from the SAME hit, so the two agree.

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
        cost_usd=call.cost_usd if call is not None else Decimal(0),
    )


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
        _report_served_from_cache(model, call)
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
) -> httpx.Response:
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
    """
    last: httpx.TransportError | None = None
    for attempt in range(_TRANSPORT_RETRIES + 1):
        try:
            return await http_client.post(_COMPLETIONS_PATH, headers=headers, json=body)
        except httpx.TransportError as exc:
            last = exc
            if attempt < _TRANSPORT_RETRIES:
                await asyncio.sleep(_transport_backoff(attempt))
    assert last is not None  # the loop always runs at least once
    raise ResolutionError(
        f"aigateway request failed at the transport layer: {_transport_detail(last)}",
        code="aigateway_transport_error",
        permanent=False,
    ) from last


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
    resp = await _post_completion(
        http_client,
        headers=headers,
        # `policy_to_body_field` yields an EMPTY dict for a run that participates, so an ordinary
        # run's body is byte-identical to the one this connector has always sent — which is also
        # the smallest surface exposed to the gateway's closed cache grammar, where one
        # unrecognised key silently costs every hit (spec §1.0).
        body={**body, **policy_to_body_field(cache)},
    )
    _raise_for_status(resp)
    outcome = read_cache_outcome(resp.headers)
    if not requires_revalidation(cache, outcome):
        return resp, outcome
    # An explicit opt-out, built here rather than derived from `cache`: the run's own policy
    # PARTICIPATES (a bound is not a refusal), and the re-issue must state the one thing the
    # closed grammar understands — `use-cache: false` — and nothing else.
    resp = await _post_completion(
        http_client,
        headers=headers,
        body={**body, **policy_to_body_field(CachePolicy(participate=False))},
    )
    _raise_for_status(resp)
    return resp, read_cache_outcome(resp.headers)


async def _chat_completion_loop(
    *,
    http_client: httpx.AsyncClient,
    cfg: AigatewayConfig,
    profile: str | None,
    messages: list[dict],
    spec: ModelSpec,
    params: Mapping[str, str],
    tavily_http: httpx.AsyncClient | None,
    tavily_api_key: str | None,
    retrieval_policy: RetrievalPolicy | None = None,
    identity_headers: Mapping[str, str] | None = None,
    cache: CachePolicy,
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
    headers = _headers(profile, identity_headers)
    for _ in range(cfg.web_tool_max_iterations):
        body = {"model": real_model_id, "messages": messages, **sampling, **extra}
        resp, outcome = await _fetch_completion(
            http_client, headers=headers, body=body, cache=cache
        )
        data = _json_or_raise(resp)
        _report_usage(real_model_id, data.get("usage"), data.get("_aigw"), outcome)
        choice = parse_choice(data)
        # INVARIANT: report BEFORE classifying. A refused turn is the case a reviewer most needs
        # to audit, and raising first would lose exactly the event OME-679 exists to capture.
        _report_response(choice, outcome)
        raise_if_unusable(choice, max_tokens=sampling.get("max_tokens"))
        content, tool_calls = choice.content, choice.tool_calls
        if not tool_calls:
            # Recorded HERE, not per round trip: a tool loop is several round trips serving ONE
            # logical model call, and only this one is terminal. Publishing the intermediate
            # `tool_calls` rounds too would leave a consumer unable to tell a call that progressed
            # from two calls that disagreed (`_terminal_outcome` in `benchmarks/candidate.py`).
            record_model_outcome(choice.finish_reason, choice.refusal)
            record_operation_call(content or "", choice.finish_reason)
            return content or ""
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        await append_tool_results(messages, tool_calls, tools, cfg)
    raise ResolutionError(
        f"web tool loop exceeded {cfg.web_tool_max_iterations} iterations",
        code="web_tool_loop_limit",
        permanent=False,
    )


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


def _headers(
    profile: str | None, identity_headers: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The outgoing aigateway headers: the caller's identity, then the values this world owns.

    INVARIANT: the gateway-owned header is written LAST. `identity_headers` reaches here from an
    inbound request, and although Envoy guarantees a client cannot forge the identity header
    itself, nothing guarantees the mapping holds ONLY that key — so `X-Profile` is applied over it
    rather than under it, and no inbound value can displace this run's routing choice. Same
    ordering rule the aigateway provider plugins apply to their own gateway-owned headers.

    WHY no `Authorization`: aigateway runs `cloudflare_headers` when deployed and `disabled`
    locally. Neither mode reads a bearer token, and a deployed caller cannot obtain one, so the
    run carries none at all.
    """
    headers = dict(identity_headers or {})
    if profile is not None:
        headers["X-Profile"] = profile
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

"""Builds the aigateway-backed :class:`~url4.io.layer.IOLayer` world: a `Url4Node` whose
endpoints are declared models routed to aigateway's chat-completions API, plus an optional
Tavily-backed web-search/web-fetch tool loop. This is the world `executor.Url4Executor`
resolves and runs an expression against.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn
from weakref import WeakKeyDictionary

import httpx

from screamingface_engine import engine_version, job_env
from screamingface_engine.benchmarks.candidate_input import (
    CandidateInputError,
    CandidateMessage,
    ContentPart,
    parse_candidate_input,
)
from screamingface_engine.benchmarks.case_context import (
    current_case_attempt,
)
from screamingface_engine.benchmarks.picture_admission import (
    admit_run_attachments,
    register_model_sight,
)
from screamingface_engine.candidate_scope import in_candidate_invocation
from screamingface_engine.capture_outcomes import (
    FROZEN_COPIES_PATH,
    seal_path,
)
from screamingface_engine.grading_call_scope import current_grading_case
from screamingface_engine.model_outcomes import bind_model_outcome, record_model_outcome
from screamingface_engine.network_policy import is_numeric_loopback_url
from screamingface_engine.operation_accounting import (
    OperationAccounting,
    ReplyLogprobs,
    SignalAccounting,
    combine_operation_accounting,
    combine_signal_accounting,
)
from screamingface_engine.operation_calls import operation_call_identity, record_operation_call
from screamingface_engine.operation_provenance import outcome_of
from screamingface_engine.request_scope import RequestScope, current_scope
from screamingface_engine.retrieval_policy import (
    RetrievalPolicy,
    current_retrieval_policy,
)
from screamingface_engine.world import gateway_transport
from screamingface_engine.world.attachment_parts import (
    AttachmentPartError,
    attachment_parts,
    place_on_last_user_message,
)
from screamingface_engine.world.attempt_facts import AttemptObserver, observed_call
from screamingface_engine.world.cache import attempt_body_field
from screamingface_engine.world.config import ModelSpec, WorldConfigError, provider_of, routes_for
from screamingface_engine.world.errors import RunnerRequestError
from screamingface_engine.world.fresh_judge_retry import scope_for_this_send
from screamingface_engine.world.fusion_context import fusion_picture_messages
from screamingface_engine.world.models.registry import decode_route_id
from screamingface_engine.world.refused_key_stop import (
    STOP_CODE,
    KeyRefused,
    note_answer,
    note_refusal,
)
from screamingface_engine.world.request_parameters import (
    OPERATION_BINDING_PARAM,
    WEB_SEARCH_PARAM,
    apply_answer_seed,
    apply_retrieval_policy,
    attempt_egress,
    caller_exclusions,
    model_params,
    wants_web_search,
)
from screamingface_engine.world.tavily_retrieval_cache import TavilyRetrievalCache
from screamingface_engine.world.web_tools import (
    WEB_TOOLS,
    FrozenToolResults,
    WebToolRuntime,
    append_tool_results,
    build_client,
    build_runtime,
    tavily_key,
    truncate_tool_result,
)
from url4 import Attachment
from url4.core.errors import ErrorCode, ResolutionError
from url4.dag import GuardRetry, current_guard_retry
from url4.io.static import StaticIOLayer
from url4.peer.server import Request, Url4Node

_truncate_tool_result = truncate_tool_result
# WHY the pre-refactor name, not `__name__` (FX-19): this module moved from `runner/` to
# `world/` in unit 1, and operators filter the runtime log by logger name. Keeping the old name
# keeps every model-call lifecycle line byte-identical to `main`.
logger = logging.getLogger("screamingface_engine.runner.connector")


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
    queue_timeout_s: float | None = None
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

    def __post_init__(self) -> None:
        for value in (self.timeout_s, self.queue_timeout_s):
            if isinstance(value, bool) or (
                value is not None and (not math.isfinite(value) or value <= 0)
            ):
                raise WorldConfigError("Gateway timeout budgets must be finite and positive")

    @property
    def admission_timeout_s(self) -> float:
        return self.timeout_s if self.queue_timeout_s is None else self.queue_timeout_s

    @property
    def transport_timeout_s(self) -> float:
        # Leave time for the Gateway to serialize its classified timeout response.
        return (
            self.admission_timeout_s + self.timeout_s + gateway_transport._GATEWAY_RESPONSE_MARGIN_S
        )


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


async def admit_run_files(
    http_client: httpx.AsyncClient,
    cfg: AigatewayConfig,
    routes: Mapping[str, ModelSpec],
    attachments: Sequence[Attachment],
) -> None:
    """OME-1809: admit the run's files once for the whole run (``admit_run_attachments``).

    Every model call awaits it before it is sent, and so does a Router's ADMIT (C4) before it
    accepts, so a Router's classifier reaches no provider before the run's files are admitted. A
    grading call keeps its own refusal (judges read text only, spec D6).

    WHY a reader built here rather than held: `_GatewayModelSight` is stateless over the
    world-level client and routes the caller already holds, and the run's one shared check (not
    the reader) is what keeps the model list to one read per run. The model handler's slots stay
    the world-level allowlist (`test_request_scope_hardening`).
    """
    if not attachments or current_grading_case() is not None:
        return
    sight = _GatewayModelSight(
        http_client, {path: decode_route_id(spec.id) for path, spec in routes.items()}
    )
    await admit_run_attachments(
        sight,
        attachments,
        default_route="/" + cfg.default_model,
        private_routes=frozenset(path for path, spec in routes.items() if not spec.public_schema),
    )


class _ModelEndpoint:
    """The handler registered on every declared route.

    A class rather than a closure: the node holds this for the whole run either way, so the
    `__slots__` fields below are retained for the run's duration just as a closure would retain
    them; that is not what the class buys. What it avoids is pinning
    `build_aigateway_world`'s *other* frame locals along with them — e.g. `owns_client`,
    `client`, `tavily_client` — which a closure would keep alive for the whole run even though
    `__call__` never touches them, but this class holds only the fields it actually needs.

    FEATURE (F2, prd/01): the handler is STATELESS with respect to the caller. Identity,
    identity, cache policy and answer seed are read from `current_scope()` per call, so one world
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
        # FEATURE (C8): a bound call's outcome, the reply or the error url4 rows, at its boundary.
        binding = request.params.get(OPERATION_BINDING_PARAM)
        return await outcome_of(binding, request.path, self._answer(request))

    async def _answer(self, request: Request) -> str:
        # The route resolves to its whole spec, so the id and the capabilities it was declared
        # with travel together — the call can never run one route's model under another's flags.
        spec = self._routes[request.path]
        try:
            # INVARIANT (F2): the caller's state is read HERE, per call, from the request scope —
            # never held on `self`. Two concurrent callers through this one handler each observe
            # their own scope because each runs in its own context (AC2), and a spawned model
            # call inherits the scope of the task that created it (AC4).
            # OME-1533: a re-ask of a Judge whose last reply was unusable runs under the same
            # scope opted out of the gateway cache, which would otherwise serve the stored
            # garbled reply again; every other call keeps the caller's scope.
            retry: GuardRetry | None = current_guard_retry()
            scope = scope_for_this_send(
                current_scope(), None if retry is None else retry.failure_code
            )
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
            # invocation. Without this the caller's `X-Answer-Seed` would reach the sync surface
            # and be silently dropped at the one hop that must forward it.
            ambient_seed = (
                (None if scope.answer_seed is None else str(scope.answer_seed))
                if in_candidate_invocation() or scope.origin == "sync"
                else None
            )
            # FEATURE (OME-1458): Attempt 2 and later of a Case must not be a copy of Attempt 1
            # — a derived seed when the run's seed applies, else the Attempt number for the
            # gateway's cache. Read only inside the Candidate Invocation, so a judge never is.
            egress = attempt_egress(
                params,
                ambient_seed,
                current_case_attempt() if in_candidate_invocation() else None,
            )
            params = apply_answer_seed(params, egress.answer_seed)
            # FEATURE (OME-1809): a url4 run's files are admitted ONCE for the whole run before
            # any call is sent: one blind model fails the run by name, nothing paid. A grading
            # call keeps its own refusal below (judges read text only, spec D6).
            await admit_run_files(self._http_client, self._cfg, self._routes, request.attachments)
            # FEATURE (OME-1545, spec F2/F3): the run's url4 files, read and verified before the
            # request is formed; empty for a text-only call, which then stays byte-identical.
            parts = await _attachment_parts(request)
            # WHY: the identity is the REQUEST's path and params (pre-policy), because
            # OME-843 attribution matches them against the candidate expression's own
            # source text — the policy-applied set may differ from what was written.
            with (
                operation_call_identity(
                    request.path,
                    request.params,
                    context=request.context,
                    intent=request.intent,
                ),
                # FEATURE (C8): a bound call's attempt fact, published when the call ends.
                observed_call(request.params.get(OPERATION_BINDING_PARAM)) as observer,
            ):
                # OME-1989: tell the Case's refusal watch that this call answered.
                return note_answer(
                    spec.id,
                    await _chat_completion_loop(
                        http_client=self._http_client,
                        cfg=self._cfg,
                        scope=scope,
                        messages=place_on_last_user_message(
                            _messages(request.context, request.intent), parts
                        ),
                        params=params,
                        spec=spec,
                        tavily_http=self._tavily_http,
                        tavily_api_key=self._tavily_api_key,
                        retrieval_policy=retrieval_policy,
                        cache_attempt=egress.cache_attempt,
                        observer=observer,
                    ),
                )
        except gateway_transport._GatewayRefusal as exc:
            # FEATURE (OME-1989): record the refusal in the Case's refusal watch, which decides
            # when the Case ends whether it caused the Case to fail. This call still raises its
            # own error below.
            note_refusal(spec.id, status=exc.status, code=exc.code)
            # INVARIANT (OME-1770 review): the Gateway refuses an ungranted account a private
            # target as an unknown provider. Relayed, that refusal tells the caller this Engine
            # declares the route; url4's own answer for an undeclared route does not.
            if spec.public_schema or not exc.refuses_provider(provider_of(spec.id)):
                raise
            raise _undeclared_route(request.path) from None
        except RunnerRequestError as exc:
            error = ResolutionError(str(exc), code=exc.code, permanent=exc.permanent)
            if exc.outcome is not None:
                bind_model_outcome(error, exc.outcome)
            raise error from exc


_NODE_NAME = "aigateway"
"""The world node's name, which url4's undeclared-route error quotes."""


def _undeclared_route(path: str) -> ResolutionError:
    """url4's own error for a path the node does not declare (`url4.peer._dispatch`), verbatim."""
    return ResolutionError(
        f"node {_NODE_NAME!r} has no endpoint, eval path, or data route at {path!r}",
        code=ErrorCode.ENDPOINT_NOT_FOUND,
        permanent=True,
    )


_GATEWAY_CLIENTS: WeakKeyDictionary[Url4Node, httpx.AsyncClient] = WeakKeyDictionary()
"""The aigateway client of each world node, keyed by the node itself.

WHY a side table (the idiom of `world.factory._DIRECT_MOUNTS`): the executor drives a run on the
node the world factory returned and owns no client, yet a capture run must open and seal its copy
on the SAME client and headers as the run's chat calls. An engine-owned table read through
:func:`open_frozen_copy` keeps the node's own type unwidened and the `World` tuple unchanged.
"""


async def build_aigateway_world(
    cfg: AigatewayConfig,
    *,
    client: httpx.AsyncClient | None = None,
    tavily_api_key: str | None = None,
    tavily_client: httpx.AsyncClient | None = None,
) -> AigatewayWorld:
    """Build the `Url4Node` world: one endpoint per declared model, routed to aigateway.

    The world carries NO caller state (F2). Identity, cache policy and answer seed are
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
        else httpx.AsyncClient(
            base_url=cfg.base_url,
            timeout=httpx.Timeout(cfg.timeout_s, read=cfg.transport_timeout_s),
            trust_env=not is_numeric_loopback_url(cfg.base_url),
        )
    )
    routes = routes_for(cfg.models)

    normalized_tavily_key = tavily_key(tavily_api_key)
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
        _NODE_NAME,
        default_processor="/" + cfg.default_model,
        outbound=None if cfg.allow_outbound else StaticIOLayer(),
    )
    for path in routes:
        node.endpoint(path)(call_model)
    _GATEWAY_CLIENTS[node] = http_client
    register_model_sight(
        node,
        _GatewayModelSight(
            http_client, {path: decode_route_id(spec.id) for path, spec in routes.items()}
        ),
    )
    return AigatewayWorld(
        node=node,
        _client=http_client,
        _owns_client=owns_client,
        _tavily_client=tavily_http,
        _owns_tavily_client=owns_tavily_client,
    )


async def open_frozen_copy(node: object) -> str | None:
    """Open the frozen copy a capture run stores into, on ``node``'s gateway client.

    FEATURE: OME-1307 (design §5.2 item 1). Sent with the run's identity headers, as the chat calls
    are. Total: a node with no gateway client, any failure (`Exception`, never a cancellation) and
    a body without a copy id all return ``None``, and the run goes on uncaptured and partial.
    Names the error type only in the log, never a body.

    INVARIANT: the id goes into every later URL path, so it must be a UUID or it is refused.
    """
    client = _gateway_client(node)
    if client is None:
        return None
    try:
        response = await client.post(
            FROZEN_COPIES_PATH, headers=gateway_transport._headers(current_scope())
        )
        response.raise_for_status()
        body = response.json()
        copy_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(copy_id, str) or job_env.FROZEN_COPY_ID.fullmatch(copy_id) is None:
            raise ValueError("the gateway named no frozen copy")
    except Exception as exc:  # noqa: BLE001 - best effort: nothing here may fail the run
        logger.warning("frozen copy open failed error=%s", type(exc).__name__)
        return None
    return copy_id


async def seal_frozen_copy(node: object, copy_id: str) -> bool:
    """Seal ``copy_id``. ``True`` only when the gateway confirms it is sealed; total, like the open.

    A sealed copy is what a replay reads; an open one is refused as unavailable.

    FEATURE: E14 Q28. The seal states the engine version, so the copy records what captured it.
    A source tree with no installed version seals with no body (the gateway stores no provenance).
    """
    client = _gateway_client(node)
    if client is None:
        return False
    version = engine_version()
    try:
        response = await client.post(
            seal_path(copy_id),
            headers=gateway_transport._headers(current_scope()),
            json={"provenance": {"engine_version": version}} if version else None,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # noqa: BLE001 - best effort, as the open: a failed seal is `partial`
        logger.warning("frozen copy seal failed error=%s", type(exc).__name__)
        return False
    return isinstance(body, dict) and body.get("status") == "sealed"


def _gateway_client(node: object) -> httpx.AsyncClient | None:
    return _GATEWAY_CLIENTS.get(node) if isinstance(node, Url4Node) else None


_MODEL_LIST_PATH = "/v1/models"
_MODEL_LIST_UNREADABLE = (
    "the gateway's model list could not be read, so this run cannot check that its models "
    "take its pictures or PDFs; nothing was sent to a model"
)


class _GatewayModelSight:
    """Read each declared model's input types from aigateway's ``/v1/models``, as the caller.

    FEATURE (OME-1548): the `ModelSightReader` a picture Benchmark's Cases route asks before any
    paid call (`benchmarks/picture_admission.py`). Read once per picture run, never cached: the
    list is per caller, and one local node serves many callers' runs.

    INVARIANT (trust): sent with the run's own identity headers, as its chat calls are, so a caller
    is checked against the models the gateway lists for THEM.
    """

    __slots__ = ("_client", "_routes")

    def __init__(self, client: httpx.AsyncClient, routes: Mapping[str, str]) -> None:
        self._client = client
        self._routes = routes

    def model_routes(self) -> Mapping[str, str]:
        """The world's declared model routes (``"/" + route id``), each to its gateway id."""
        return self._routes

    async def input_modalities(self) -> Mapping[str, Sequence[str]]:
        """Each listed model's input types, keyed by gateway id; retryable when unreadable."""
        try:
            response = await self._client.get(
                _MODEL_LIST_PATH, headers=gateway_transport._headers(current_scope())
            )
            response.raise_for_status()
            body: object = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # WHY retryable (owner, 2026-10-28): nothing was spent, and a later run may find the
            # gateway answering. The error type only, never a body (the open_frozen_copy rule).
            logger.warning("model list read failed error=%s", type(exc).__name__)
            raise ResolutionError(
                _MODEL_LIST_UNREADABLE, code=ErrorCode.RESOLUTION_FAILED, permanent=False
            ) from exc
        rows: object = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise ResolutionError(
                _MODEL_LIST_UNREADABLE, code=ErrorCode.RESOLUTION_FAILED, permanent=False
            )
        modalities: dict[str, tuple[str, ...]] = {}
        for row in rows:
            model_id: object = row.get("id") if isinstance(row, dict) else None
            listed: object = row.get("input_modalities") if isinstance(row, dict) else None
            if isinstance(model_id, str) and isinstance(listed, list):
                modalities[model_id] = tuple(value for value in listed if isinstance(value, str))
        return modalities


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
    cache_attempt: int | None = None,
    observer: AttemptObserver | None = None,
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
    headers = {
        **gateway_transport._headers(scope),
        **gateway_transport.timeout_headers(cfg.timeout_s, cfg.admission_timeout_s),
    }
    tools, extra = _retrieval_request(
        cfg=cfg,
        spec=spec,
        params=params,
        tavily_http=tavily_http,
        tavily_api_key=tavily_api_key,
        retrieval_policy=retrieval_policy,
        # FEATURE (OME-1045): the retrieval cache rides the SAME aigateway client and headers as
        # the chat calls — no new pool, base URL or setting.
        cache=TavilyRetrievalCache(http_client, headers),
        frozen=_frozen_tool_results(http_client, headers, scope),
    )
    sampling = model_params(params)
    operation_accounting: list[OperationAccounting | None] = []
    signal_accounting: list[SignalAccounting] = []
    reply_rounds: list[ReplyLogprobs | None] = []
    for _ in range(cfg.web_tool_max_iterations):
        # FEATURE (OME-1458): Attempt 2+ names itself to the gateway's cache on every round
        # trip of the turn; Attempt 1 adds nothing, so its body is byte-identical to before.
        body = {
            "model": real_model_id,
            "messages": messages,
            **sampling,
            **extra,
            **attempt_body_field(cache_attempt),
        }
        choice = await gateway_transport.round_trip(
            http_client,
            real_model_id=real_model_id,
            headers=headers,
            body=body,
            cache=scope.cache,
            max_tokens=sampling.get("max_tokens"),
            operation_accounting=operation_accounting,
            replay_frozen_copy=scope.replay_frozen_copy,
            signal_accounting=signal_accounting,
            reply_logprobs=reply_rounds,
            # WHY one observer for every round trip of the tool loop: they serve ONE logical call.
            observer=observer,
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
                combine_signal_accounting(signal_accounting),
                reply_logprobs=reply_rounds[-1] if reply_rounds else None,
            )
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
    cache: TavilyRetrievalCache,
    frozen: FrozenToolResults | None,
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
        cache=cache,
        frozen=frozen,
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


def _frozen_tool_results(
    http_client: httpx.AsyncClient, headers: dict[str, str], scope: RequestScope
) -> FrozenToolResults | None:
    """The tool-result routes of this run's frozen copy, or ``None`` for a run with no copy.

    Rides the SAME aigateway client and headers as the chat calls — no new pool or setting.
    """
    if scope.replay_frozen_copy is not None:
        return FrozenToolResults(http_client, headers, scope.replay_frozen_copy, replay=True)
    target = gateway_transport._capture_target()
    if target is None:
        return None
    return FrozenToolResults(http_client, headers, target[1], replay=False)


def _messages(context: str | None, intent: str | None) -> list[dict[str, Any]]:
    if not context and intent:
        # FIX (OME-1808): a default-route reduce with no attachments has an empty context, and
        # `system=<intent>` + `user=""` is a 400 on Anthropic ("at least one message is
        # required": the system message is lifted out and the empty turn dropped). The intent is
        # then the only content, so it travels as the one user turn. A non-empty context keeps
        # today's bytes exactly; the request identity hashes context and intent, not messages.
        return [{"role": "user", "content": intent}]
    messages: list[dict[str, Any]] = []
    if intent:
        messages.append({"role": "system", "content": intent})
    native = _native_messages(context)
    if native is None:
        messages.append({"role": "user", "content": context or ""})
    else:
        # WHY a shallow copy of each message: the gateway loop's chat is wider than a Case's (it
        # appends assistant tool calls and tool results), so it holds plain dicts.
        messages.extend(dict(message) for message in native)
    return messages


async def _attachment_parts(request: Request) -> list[ContentPart]:
    """The run's url4 files as content parts for this call; ``[]`` when it carries none."""
    if not request.attachments:
        return []
    # INVARIANT (spec §2.7 gate 2, D6; F2 Judge): under OME-1271 v1 the grader receives no files,
    # so a grading call that would carry one is refused by name, before any byte is read.
    if current_grading_case() is not None:
        _invalid_candidate_input("a grading call carries a picture or file; judges read text only")
    try:
        return await attachment_parts(request.attachments)
    except AttachmentPartError as exc:
        raise ResolutionError(str(exc), code=exc.code, permanent=True) from exc


def _native_messages(context: str | None) -> list[CandidateMessage] | None:
    """The Case's own chat messages, or ``None`` when its input is a plain prompt.

    FEATURE (OME-1678): the candidate-input envelope module owns the rules, so this connector and
    the inspect plugin read one rule. A v2 Case's pictures come back as content parts and travel
    to the gateway verbatim.

    FEATURE (OME-1679): a Fusion's synthesizer context is not an envelope but holds one under
    ``input``; on a picture Case the synthesizer gets the same pictures as the members.
    """
    try:
        messages: list[CandidateMessage] | None = parse_candidate_input(context)
        # WHY under grading too: a Fusion context holding a picture Case must reach the refusal
        # below, not a judge as base64 text; a text-only one still comes back None.
        if messages is None:
            messages = fusion_picture_messages(context)
    except CandidateInputError as exc:
        _invalid_candidate_input(str(exc))
    # INVARIANT (spec D6): a judge grades the text answer only. A picture reaching a grading call
    # is refused by name here, not dropped by whichever judge writer happens to read text.
    if (
        messages is not None
        and current_grading_case() is not None
        and any(not isinstance(message["content"], str) for message in messages)
    ):
        _invalid_candidate_input("a grading call carries a picture or file; judges read text only")
    return messages


def _invalid_candidate_input(detail: str) -> NoReturn:
    raise ResolutionError(
        f"invalid Candidate chat input: {detail}",
        code="invalid_candidate_input",
        permanent=True,
    )


@contextmanager
def key_refusal_as_url4_error() -> Iterator[None]:
    """Raise a run the refused key stopped (OME-1989) to url4 as its run-stopped error.

    WHY here: `refused_key_stop` never imports the url4 engine, so this allowlisted adapter
    turns its `KeyRefused` into url4's `ResolutionError` — for a Case refused by a stopped run
    (the Candidate adapter), and around the whole run (the executor). Permanent, because the
    same key is refused again.
    """
    try:
        yield
    except KeyRefused as stopped:
        raise ResolutionError(stopped.message, code=STOP_CODE, permanent=True) from stopped


__all__ = [
    "AigatewayConfig",
    "AigatewayWorld",
    "build_aigateway_world",
    "key_refusal_as_url4_error",
    "open_frozen_copy",
    "seal_frozen_copy",
]

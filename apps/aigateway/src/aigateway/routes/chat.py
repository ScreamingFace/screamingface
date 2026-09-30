"""POST /v1/chat/completions — resolves provider access and dispatches via LiteLLM.

Credentials come from ONE place: the ``core.provider_access`` port (OME-1207, A2 of
OME-1138). This route resolves a ``CredentialTarget``, derives the auth mode and authorizes
through that port; it never touches a legacy Profile row, a Connection row or the profile
index. Its typed refusals become HTTP through the single edge table in
``provider_access_http``.

INVARIANT (OME-1323, D2): request parameters are the caller's. The route reads no stored
Profile defaults and merges nothing into the body — system instructions arrive as
system-role messages — so the cache key and the dispatch both describe exactly what the
caller sent.

The remaining helper seams are sibling modules (OME-428 Phase 1 split): ``chat_dispatch``
(backpressure, error mapping, streaming) and ``chat_cache_stage`` (the global cache's
route-facing stage). This module keeps only the router and the request orchestration.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, assert_never

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnprocessableEntityError,
    UnsupportedParamsError,
)

from ..core.auth.middleware import CurrentAccount
from ..core.auth.models import BaseAccount
from ..core.cache_versions import CaptureKey
from ..core.parameter_projection import (
    IncompatibleParametersError,
    UnsupportedParametersError,
    classify_and_project_chat_parameters,
)
from ..core.profile_models import AuthMode
from ..core.provider_access import (
    CredentialTarget,
    ProviderAccess,
    Selector,
    apply_authorization,
    provider_access_for,
)
from ..core.registry import ProviderRegistry
from ..core.request_cache.entry_metadata import CacheEntryMetadata
from ..core.request_cache.global_controls import parse_global_cache_controls
from ..core.request_hardening import chat_body_shape_error, strip_dispatch_controls
from .chat_accounting import (
    accounting_handler,
    attach_hit_metadata,
    attach_success_metadata,
    begin_accounting,
    bound_dispatch,
    dispatch_body_with_accounting,
    finalize_provider_evidence,
    note_conversion_failure,
    note_dispatch_failure,
    safe_request_view,
)
from .chat_cache_stage import (
    CacheStatus,
    GlobalCacheOutcome,
    WriteStatus,
    global_cache_headers,
    look_up_global_cache,
    store_global_response,
)
from .chat_capture_stage import AnsweredBy, begin_capture, capture_outcome, record_capture
from .chat_dispatch import (
    _dispatch_with_backpressure,
    _litellm_http_exception,
    _safe_dispatch_failure_response,
    _stream,
    _unknown_provider_exception,
    convert_provider_response,
)
from .chat_replay_stage import ReplayOutcome, replay_caller, replay_headers, resolve_replay
from .provider_access_http import refusals_as_http, selector_from_request

logger = logging.getLogger(__name__)
router = APIRouter()


async def _resolve_credential_target(
    access: ProviderAccess,
    *,
    account_id: str,
    provider: str,
    selector: Selector,
    plugin: Any,
) -> tuple[CredentialTarget, AuthMode]:
    """Ops 2–3: the one target this selector names, and the mode it is matched against.

    # INVARIANT: both refusals render through the ONE edge table, so the 404/409/401 bodies
    # and the 400 for an undeclared mode stay byte-identical to the pre-port route.
    """
    with refusals_as_http():
        target = await access.resolve(account_id, provider, selector, plugin=plugin)
        return target, access.auth_mode(target, plugin)


async def _authorize_and_seal(
    access: ProviderAccess,
    target: CredentialTarget,
    *,
    plugin: Any,
    provider: str,
    body: dict[str, Any],
) -> None:
    """Op 4 plus the pure sealing step.

    # INVARIANT: every storage side effect of authorization (strategy build and refresh,
    # error marking, session invalidation, the Connection last-used touch) is the port's;
    # writing the returned headers into the body is the only part the route owns.
    """
    with refusals_as_http():
        authorization = await access.authorize(target, plugin=plugin, provider=provider)
    apply_authorization(body, authorization.headers)


async def _dispatch_and_finalize_accounting(
    request: Request,
    *,
    plugin: Any,
    provider: str,
    body: dict[str, Any],
    accounting: Any,
    account_id: str,
    profile_name: str,
    target: CredentialTarget,
) -> Any:
    """Dispatch once through the provider and finalize any observed accounting evidence."""
    accounting_request_view = safe_request_view(body)
    dispatch_body = dispatch_body_with_accounting(body, accounting, accounting_handler(request))
    on_dispatch = accounting.note_dispatch if accounting is not None else None
    try:
        with bound_dispatch(accounting):
            provider_response = await _dispatch_with_backpressure(
                request, plugin, provider, dispatch_body, on_dispatch=on_dispatch
            )
    except HTTPException as exc:
        if getattr(exc, "aigw_response_conversion_error", False):
            note_conversion_failure(accounting)
        else:
            note_dispatch_failure(
                accounting,
                exc,
                provider_error_after_response=bool(getattr(exc, "aigw_provider_body_error", False)),
            )
        finalize_provider_evidence(
            accounting, plugin=plugin, request_body=accounting_request_view, final_response=None
        )
        raise await _safe_dispatch_failure_response(
            request,
            exc,
            plugin=plugin,
            provider=provider,
            account_id=account_id,
            profile_name=profile_name,
            target=target,
        ) from None
    except (
        RateLimitError,
        UnsupportedParamsError,
        BadRequestError,
        AuthenticationError,
        PermissionDeniedError,
        NotFoundError,
        UnprocessableEntityError,
        InternalServerError,
        APIError,
        APIConnectionError,
        ServiceUnavailableError,
        Timeout,
    ) as exc:
        note_dispatch_failure(accounting, exc)
        finalize_provider_evidence(
            accounting, plugin=plugin, request_body=accounting_request_view, final_response=None
        )
        raise await _safe_dispatch_failure_response(
            request,
            _litellm_http_exception(exc),
            plugin=plugin,
            provider=provider,
            account_id=account_id,
            profile_name=profile_name,
            target=target,
            error_type=type(exc).__name__,
        ) from None
    except Exception as exc:
        # WHY (OME-428 third-review blocker B): the two branches above enumerate
        # the curated HTTPException and the KNOWN litellm exception families. Any
        # OTHER escape (a RuntimeError, a ValueError, a new litellm type, a
        # malformed-conversion error) must still render a sanitized status — never
        # an uncontrolled ASGI 500 whose traceback leaks the raw provider
        # message/prompt.
        # INVARIANT: an unclassified exception always yields a fixed sanitized
        # 502 `provider_error`; arbitrary attributes/chains are not trusted and
        # cannot trigger credential invalidation.
        # OME-968: the class name rides into the ONE terminal record the funnel below emits.
        error_type = type(exc).__name__
        note_dispatch_failure(accounting, exc)
        finalize_provider_evidence(
            accounting, plugin=plugin, request_body=accounting_request_view, final_response=None
        )
        raise await _safe_dispatch_failure_response(
            request,
            _unknown_provider_exception(),
            plugin=plugin,
            provider=provider,
            account_id=account_id,
            profile_name=profile_name,
            target=target,
            error_type=error_type,
        ) from None

    try:
        result = convert_provider_response(provider_response, accounting, provider=provider)
    except HTTPException:
        finalize_provider_evidence(
            accounting, plugin=plugin, request_body=accounting_request_view, final_response=None
        )
        raise

    finalize_provider_evidence(
        accounting,
        plugin=plugin,
        request_body=accounting_request_view,
        final_response=result if isinstance(result, dict) else None,
    )
    return result


def _classify_and_validate_body(
    body: dict[str, Any], *, plugin: Any, provider: str, model: str, auth_mode: AuthMode
) -> dict[str, Any]:
    """Classify and project the caller's parameters, then check the cross-field combination.

    # AIDEV-NOTE: moved out of `chat_completions` UNCHANGED (OME-1307, GW-replay): the route sat one
    # statement under the ruff `max-statements` limit, so STAGE 0 needed room. Same order, same
    # refusals, same bodies.
    """
    rules = tuple(plugin.chat_parameter_rules(model=model, auth_type=auth_mode))
    try:
        body = classify_and_project_chat_parameters(
            body,
            rules=rules,
            auth_mode=auth_mode,
        )
    except UnsupportedParametersError as exc:
        # Every classified path is the caller's own (OME-1323, D2), so the rejection is
        # reported whole. Reason codes only — the classifier never carries raw values.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_parameters",
                "provider": provider,
                "rejected": exc.rejected,
                "message": (
                    "one or more parameters are not enabled for this model; "
                    "see the model parameter contract"
                ),
            },
        ) from None

    # OME-640: a per-path rule cannot say "these two accepted fields cannot travel
    # together on THIS model under THIS auth mode", so the provider gets one seam
    # to say it — on the projected body, still ahead of provider preparation,
    # cache planning, credential access and dispatch. The default accepts
    # everything, so a provider that states no cross-field constraint is unaffected.
    try:
        plugin.validate_chat_parameter_combination(body, model=model, auth_mode=auth_mode)
    except IncompatibleParametersError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "incompatible_parameters",
                "provider": provider,
                "conflict": list(exc.paths),
                "message": exc.reason,
            },
        ) from None
    return body


@dataclass(frozen=True, slots=True)
class ChatAnswer:
    """How one chat call was answered: the single value each exit of the route stage returns.

    INVARIANT: the route records capture ONCE, from this value, before it renders. So every exit
    says how it answered, and the type checker proves it: a stage cannot return without a source.
    ``body`` is the sanitized provider-compatible answer, BEFORE any metadata block. A stream has
    no body: the sealed request body never rides here.
    """

    answered_by: AnsweredBy
    replay: ReplayOutcome | None
    cache: GlobalCacheOutcome | None = None  # None only for a version hit
    write_status: WriteStatus | None = None
    body: Any = None
    entry_metadata: CacheEntryMetadata | None = None  # hits only
    stream: AsyncIterator[str] | None = None  # provider_stream only

    @property
    def cache_status(self) -> CacheStatus | None:
        return self.cache.status if self.cache is not None else None


def _stored_answer(
    request: Request,
    answered_by: Literal["version", "global_cache"],
    stored: dict[str, Any],
    *,
    replay: ReplayOutcome | None,
    cache: GlobalCacheOutcome | None,
    entry_metadata: CacheEntryMetadata | None,
) -> ChatAnswer:
    """A hit: the stored answer, sanitized. ``stored`` is the store's replayed row (not mutated)."""
    return ChatAnswer(
        answered_by,
        replay,
        cache=cache,
        body=request.app.state.taxonomy_plugin.sanitize_provider_response(stored),
        entry_metadata=entry_metadata,
    )


def _answer_headers(answer: ChatAnswer) -> dict[str, str]:
    """Every response header of an answered call, in one place: the global set, then the replay set.

    WHY a mapping: the streaming path returns a FRESH ``StreamingResponse``, and FastAPI does not
    merge the injected ``Response`` object's headers into a response the handler returns itself.
    """
    global_headers = (
        global_cache_headers(answer.cache, write_status=answer.write_status)
        if answer.cache is not None
        else {}
    )
    return {**global_headers, **replay_headers(answer.replay)}


def _render_answer(response: Response, answer: ChatAnswer, *, accounting: Any, plugin: Any) -> Any:
    """Render an answered call. Capture has already been written from the CLEAN ``answer.body``."""
    headers = _answer_headers(answer)
    match answer.answered_by:
        case "provider_stream":
            assert answer.stream is not None  # a stream answer carries its stream
            return StreamingResponse(answer.stream, media_type="text/event-stream", headers=headers)
        case "version" | "global_cache":
            # OME-303: a hit dispatched nothing, so `attempts` is empty and
            # `observed_new_attempts` is 0. Limited cached-final-response evidence
            # is explicitly not current spend. Metadata goes on a COPY: `answer.body` is the
            # store's replayed row, sanitized.
            # C4/ERD §5.5: the stored block travels with the hit. ``attach_hit_metadata``
            # prefers it and falls back to the provider's own mapper when it is absent.
            rendered = attach_hit_metadata(
                answer.body,
                accounting,
                plugin=plugin,
                entry_metadata=answer.entry_metadata,
            )
        case "provider":
            # OME-303 INVARIANT (§6): metadata is attached to a COPY, and STRICTLY AFTER the
            # store (STAGE 3 of ``_answer_call``). The cache row must stay provider-compatible
            # for every future replay, and `store_global_response` measures
            # `response_size_bytes` against what it is handed — attaching first could push an
            # otherwise cacheable response over the cap.
            rendered = answer.body
            cache_status = answer.cache_status
            if cache_status is not None and isinstance(answer.body, dict):
                rendered = attach_success_metadata(
                    answer.body, accounting, cache_status=cache_status
                )
        case _:
            assert_never(answer.answered_by)
    response.headers.update(headers)
    return rendered


async def _answer_call(
    request: Request,
    *,
    account: BaseAccount,
    selector: Selector,
    body: dict[str, Any],
    plugin: Any,
    provider: str,
    model: str,
    streaming: bool,
    cache_controls: Any,
    accounting: Any,
    capture_key: CaptureKey | None,
) -> ChatAnswer:
    """Answer one call: STAGE 0 (frozen version), 1 (global cache), 2 (dispatch), 3 (fill)."""
    # ==================================================================
    # STAGE 0 — replay from a frozen cache version, BEFORE the global cache.
    # ==================================================================
    # FEATURE: OME-1307 (E14) — a call that carries a replay grant is answered from the
    # frozen version when the version holds its key. An invalid grant is a 403 here and
    # never falls through to a live call (CV-E4).
    # INVARIANT: STAGE 0 runs before STAGE 1 and before any credential is resolved; a version
    # hit reads no credential and dispatches nothing (CV-H4).
    replay = await resolve_replay(
        request,
        caller=replay_caller(request.app.state.settings, account),
        body=body,
        plugin=plugin,
        capture_key=capture_key,
    )
    if replay is not None and replay.hit is not None:
        hit = replay.hit
        if accounting is not None:
            accounting.cache_status = "hit"
        return _stored_answer(
            request,
            "version",
            hit.response,
            replay=replay,
            cache=None,
            entry_metadata=(
                CacheEntryMetadata.parse(hit.metadata_json) if hit.metadata_json else None
            ),
        )

    # ==================================================================
    # STAGE 1 — the global cache, BEFORE any CREDENTIAL is resolved.
    # ==================================================================
    # INVARIANT (the ticket's central inversion): no auth mode, no provider credential
    # and no OAuth connection has been resolved at this point, and a hit returns
    # without resolving any of them. That is what lets one stored response serve every
    # caller who sends the identical request — including one whose provider is not
    # connected, or whose profile is PENDING or ERRORED.
    #
    # OME-1323 (D2) retired the OME-305 §57 pre-cache read of stored Profile defaults: the
    # key covers the caller's hardened body and nothing else, so no profile index is read
    # here and a hit decrypts nothing at all.
    # AIDEV-NOTE: availability change — an unreadable profile index no longer forces a
    # cache bypass, since nothing here reads it. It can still fail credential resolution
    # on a miss (Stage 2).
    # INVARIANT: this ONE body feeds both the key and the dispatch, so the two cannot
    # describe different requests.
    # AIDEV-NOTE: do not wrap this in ``in_transaction()``. On Postgres, a failed
    # cache SELECT or hit-metadata UPDATE aborts the outer transaction even though
    # this stage converts the failure to a bypass, poisoning later route statements.
    cache_outcome = await look_up_global_cache(
        request, body=body, plugin=plugin, controls=cache_controls
    )
    if accounting is not None:
        accounting.cache_status = cache_outcome.status
    if cache_outcome.is_hit and cache_outcome.response is not None:
        # ACCEPTED CONSEQUENCE (decision 2): a hit skips the auth-mode-specific
        # parameter validation a miss would run. Deliberate and approved — the
        # auth-INDEPENDENT half (schema validity, unknown fields, mode-restricted
        # paths) is enforced inside the key builder, so what a hit skips is only the
        # per-mode validation, and the response being served was produced by a real
        # dispatch of this exact call. Do not add a credential read here to "check"
        # it: that would defeat the entire purpose of the inversion.
        # "This exact call" is the caller's own body (OME-1323, D2): no stored Profile
        # default is merged, so the key describes everything the provider is asked.
        return _stored_answer(
            request,
            "global_cache",
            cache_outcome.response,
            replay=replay,
            cache=cache_outcome,
            entry_metadata=cache_outcome.metadata,
        )
    # ==================================================================
    # STAGE 2 — a miss or a bypass: resolve identity and dispatch.
    # ==================================================================
    # AIDEV-NOTE: this stays HERE, after the cache stage. It raises 404/409/401, so
    # hoisting it would let those preempt a cache hit. The target's historical
    # ``defaults`` are NOT merged (OME-1323, D2): the dispatch must be the request the
    # key describes.
    access = provider_access_for(request.app)
    account_id = str(account.id)
    target, auth_mode = await _resolve_credential_target(
        access, account_id=account_id, provider=provider, selector=selector, plugin=plugin
    )

    # OME-479 §4.5: classify every optional parameter against the provider's enabled
    # rule set for the REAL (never caller-declared) auth mode, and project accepted
    # fields into a fresh normalized body. This runs before provider normalization,
    # cache planning, and (crucially) credential injection — so unknown, disabled,
    # wrong-auth, malformed and duplicate-channel parameters fail closed with
    # HTTP-safe paths before any credential is read or any provider is dispatched.
    body = _classify_and_validate_body(
        body, plugin=plugin, provider=provider, model=model, auth_mode=auth_mode
    )

    # INVARIANT: provider
    # reconstruction failures precede ALL cache planning. Stage 1 runs BEFORE
    # `prepare_chat_body`, so that ordering is now upheld inside the projection
    # instead: OpenRouter's `global_cache_projection` calls the same
    # `build_provider_policy` reconstruction and returns `CacheBypass` when it raises,
    # so a body whose routing policy cannot be rebuilt performs no read and no write
    # and reaches its existing 503 rather than being answered 200 from cache.
    body = plugin.prepare_chat_body(body)

    if streaming and not plugin.supports_chat_streaming():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "streaming_not_supported",
                "provider": provider,
                "message": f"{provider} does not support streaming through this gateway yet",
            },
        )

    await _authorize_and_seal(access, target, plugin=plugin, provider=provider, body=body)

    # NOTE: overload retry covers the non-streaming path only; streaming responses
    # commit a 200 status before dispatch, so a mid-stream 429/503 cannot be retried.
    if streaming:
        # INVARIANT: reaching here means ``stream`` is truthy, and a truthy ``stream``
        # is a structural bypass in the eligibility layer — so the outcome is always a
        # bypass and no write can follow. The headers therefore come from the SAME
        # outcome the non-streaming path publishes rather than being hand-spelled;
        # The old dispatch-side cache hardcoded ``bypass`` here with an ``or "stream"``
        # fallback, not distinguish "streaming" from "the operator disabled the cache".
        return ChatAnswer(
            "provider_stream",
            replay,
            cache=cache_outcome,
            stream=_stream(plugin, body, provider=provider),
        )

    # OME-303: inject the gateway's observed LiteLLM client for an accounted request
    # whose provider declared `litellm_async_http`; then normalize each observed
    # send's OWN raw provider evidence before success OR error metadata can render.
    result = await _dispatch_and_finalize_accounting(
        request,
        plugin=plugin,
        provider=provider,
        body=body,
        accounting=accounting,
        account_id=account_id,
        profile_name=selector.name,
        target=target,
    )
    result = request.app.state.taxonomy_plugin.sanitize_provider_response(result)

    # STAGE 3 — fill the global entry this request missed on.
    # INVARIANT: only a MISS on an eligible request writes (``should_store``). A
    # bypass never writes, and neither does a read that failed — see
    # ``GlobalCacheOutcome.should_store``.
    # INVARIANT: the write cannot fail this request. ``store_global_response`` never
    # raises, and a lost race leaves the FIRST stored response in place, so the value
    # returned to this caller is always the one their own dispatch produced.
    write_status = None
    if cache_outcome.should_store:
        write_status = await store_global_response(
            request, outcome=cache_outcome, result=result, accounting=accounting
        )
    # FEATURE: OME-1307 (E14) — `result` rides the answer BEFORE `attach_success_metadata`: the
    # provider-compatible form that the cache stores, and that the capture row keeps.
    return ChatAnswer(
        "provider", replay, cache=cache_outcome, write_status=write_status, body=result
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, response: Response, current: CurrentAccount) -> Any:
    # INVARIANT: authentication has already succeeded before this route-level boundary parses every
    # repeated header value; refusal therefore precedes body, cache, credential and dispatch work.
    with refusals_as_http():
        selector = selector_from_request(request)

    try:
        body = await request.json()
    except ValueError:
        # Malformed JSON is untrusted input, not a server fault (OME-428 D6).
        begin_accounting(request, plugin=None, provider="unresolved", model="")
        raise HTTPException(status_code=400, detail="request body must be valid JSON") from None
    streaming = isinstance(body, dict) and body.get("stream") is True
    shape_error = chat_body_shape_error(body)
    if shape_error is not None:
        if not streaming:
            begin_accounting(request, plugin=None, provider="unresolved", model="")
        raise HTTPException(status_code=400, detail=shape_error)

    # Popped immediately so the control object can never reach providers.
    # ``{"cache": {"use-cache": false}}`` opts out; absent, empty and an explicit
    # opt-in all participate. `ttl`, `s-maxage`, `no-cache` and `no-store` bypass as
    # `unsupported_control` rather than being silently honoured.
    try:
        cache_controls = parse_global_cache_controls(body)
        # The gateway owns upstream routing and credentials. Caller-supplied
        # LiteLLM control-plane fields (api_key/api_base/base_url/fallbacks/
        # model_list/...) would let LiteLLM send the injected credential to an
        # arbitrary host or bend dispatch behavior (SF-244 audit F03, OME-428 D6).
        # Providers that need an api_base (ollama) set their own in
        # prepare_chat_body; the gateway credential is injected after this strip.
        body = strip_dispatch_controls(body)
    except HTTPException:
        if not streaming:
            begin_accounting(request, plugin=None, provider="unresolved", model="")
        raise

    model = body.get("model", "")
    provider = model.split("/", 1)[0] if "/" in model else None
    if not provider:
        if not streaming:
            begin_accounting(
                request,
                plugin=None,
                provider="unresolved",
                model=model,
            )
        raise HTTPException(status_code=400, detail="model must be provider-prefixed")

    registry: ProviderRegistry = request.app.state.providers
    plugin = registry.get(provider)
    if plugin is None:
        if not streaming:
            begin_accounting(
                request,
                plugin=None,
                provider="unresolved",
                model=model,
            )
        raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")

    # OME-479 §4.5 tier (a): neutralize this provider's own LiteLLM control-plane
    # fields (caching/guardrails/prompt-management/named-credential selectors)
    # BEFORE classification, so they are authorized structurally instead of being
    # rejected as unknown model params. Pairs with the provider-neutral
    # strip_dispatch_controls already applied at ingress; the default is identity.
    #
    # OME-305: MOVED ahead of the pre-cache stage. These fields are provider control
    # plane, not part of the caller's model call, and the global key adjudicates every
    # surviving field — so left in place they would make every request of an affected
    # provider bypass on an unknown field. OpenRouter alone carries eleven of them,
    # including ``litellm_credential_name``, a CREDENTIAL SELECTOR: keyed it would be
    # a plan §10 stop condition, and ignored it would be a wrong-hit collision class.
    # Stripping first is what makes it neither.
    body = plugin.strip_provider_dispatch_controls(body)

    # OME-303: non-streaming accounting is gateway-owned and default-on. Streaming
    # bypasses it until SSE usage can be observed without consuming or delaying the stream.
    # This branch runs BEFORE the cache stage, so a non-streaming HIT still gets metadata.
    accounting = (
        None
        if streaming
        else begin_accounting(request, plugin=plugin, provider=provider, model=model)
    )

    # FEATURE: OME-1307 (E14) — capture this call when it is traced. `body` is the hardened body
    # that the live cache key also uses (see the INVARIANT below), so the capture key equals the
    # live key.
    capture = begin_capture(request, account_id=str(current.id), body=body, plugin=plugin)

    try:
        answer = await _answer_call(
            request,
            account=current,
            selector=selector,
            body=body,
            plugin=plugin,
            provider=provider,
            model=model,
            streaming=streaming,
            cache_controls=cache_controls,
            accounting=accounting,
            capture_key=capture.key if capture is not None else None,
        )
    except Exception:
        # WHY `Exception` and not only `HTTPException`: the route can also raise
        # `CredentialBlobMutationConflict` (it has its own handler in `main.py`). Every failed call
        # gets an `error` row. NOT `BaseException`: a cancellation must not write a row.
        await record_capture(request, capture, "error")
        raise
    # FEATURE: OME-1307 (E14) — the ONE capture write of an answered call, BEFORE render so the
    # stored row is the clean provider body and never carries `_aigw`.
    await record_capture(
        request,
        capture,
        capture_outcome(
            answer.answered_by, cache_status=answer.cache_status, write_status=answer.write_status
        ),
        response=answer.body,
    )
    return _render_answer(response, answer, accounting=accounting, plugin=plugin)

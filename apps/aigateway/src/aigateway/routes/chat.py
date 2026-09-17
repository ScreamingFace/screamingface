"""POST /v1/chat/completions — resolves provider access + merges defaults, dispatches via LiteLLM.

Credentials come from ONE place: the ``core.provider_access`` port (OME-1207, A2 of
OME-1138). This route reads stored defaults, resolves a ``CredentialTarget``, derives the
auth mode and authorizes through that port; it never touches a legacy Profile row, a
Connection row or the profile index. Its typed refusals become HTTP through the single
edge table in ``provider_access_http``.

The remaining helper seams are sibling modules (OME-428 Phase 1 split): ``chat_dispatch``
(backpressure, error mapping, streaming), ``chat_cache_stage`` (the global cache's
route-facing stage) and ``chat_profile_defaults`` (rejection attribution). This module
keeps only the router and the request orchestration.
"""

from __future__ import annotations

import logging
from typing import Any

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
    apply_defaults,
    provider_access_for,
)
from ..core.registry import ProviderRegistry
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
    defaults_unreadable_bypass,
    global_cache_headers,
    look_up_global_cache,
    set_global_cache_headers,
    store_global_response,
)
from .chat_dispatch import (
    _dispatch_with_backpressure,
    _litellm_http_exception,
    _safe_dispatch_failure_response,
    _stream,
    _unknown_provider_exception,
    convert_provider_response,
)
from .chat_profile_defaults import _parameter_rejection_exception
from .provider_access_http import refusals_as_http

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
        logger.error(
            "unhandled dispatch error type=%s provider=%s account=%s profile=%s",
            type(exc).__name__,
            provider,
            account_id,
            profile_name,
        )
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
        ) from None

    try:
        result = convert_provider_response(provider_response, accounting)
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


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, response: Response, current: CurrentAccount) -> Any:
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

    # INVARIANT (OME-1207): the header is interpreted ONCE, here, by the port's own parser.
    # The route no longer spells the normalisation, so absent/blank/whitespace all mean the
    # implicit default in exactly one place and the Stage D sunset policy has a single seat.
    selector = Selector.from_header(request.headers.get("X-Profile"))
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

    # ==================================================================
    # STAGE 1 — the global cache, BEFORE any CREDENTIAL is resolved.
    # ==================================================================
    # INVARIANT (the ticket's central inversion): no auth mode, no provider credential
    # and no OAuth connection has been resolved at this point, and a hit returns
    # without resolving any of them. That is what lets one stored response serve every
    # caller who sends the identical request — including one whose provider is not
    # connected, or whose profile is PENDING or ERRORED.
    #
    # OME-305 §57: the caller's stored profile DEFAULTS are the one thing now read
    # first, because the key must cover the EFFECTIVE request — see
    # ``chat_profile_defaults`` for why that read is separate and why it may not raise.
    # A hit therefore costs one profile-index read, which is itself a credential_blobs
    # row: one master-key decryption, and no provider credential.
    account_id = str(current.id)
    access = provider_access_for(request.app)
    key_defaults = await access.defaults_for(account_id, provider, selector)
    default_paths: frozenset[str] = frozenset()
    if key_defaults is None:
        cache_outcome = defaults_unreadable_bypass()
    else:
        # OME-638: merge the gateway-trusted profile defaults BEFORE classification, so
        # a stored default is authorized by the same rule set, the same schema and the
        # same resolved auth mode as a caller-supplied value — one pass, one projection,
        # no second validation path to drift. Placed after both control-plane strips so
        # those keep seeing caller input only; ProfileDefaults is a closed model of six
        # typed fields and can carry no dispatch control.
        # INVARIANT: the body still wins per field, so a default occupies only a path
        # the caller omitted — which is what makes ``default_paths`` a sound attribution.
        # INVARIANT (§57): this merged body is the ONE body used for both the key and
        # the dispatch, so the two cannot describe different requests.
        body, default_paths = apply_defaults(body, key_defaults, plugin)
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
        # §57: "this exact call" now means the EFFECTIVE request — the hit was keyed on
        # the caller's body WITH their profile defaults applied, so a stored default
        # that changes what the provider is asked also changes the key.
        set_global_cache_headers(response, cache_outcome)
        # OME-303: a hit dispatched nothing, so `attempts` is empty and
        # `observed_new_attempts` is 0. Limited cached-final-response evidence is
        # explicitly not current spend. Metadata goes on a COPY:
        # `cache_outcome.response` is the store's replayed row.
        cached_response = request.app.state.taxonomy_plugin.sanitize_provider_response(
            cache_outcome.response
        )
        return attach_hit_metadata(cached_response, accounting, plugin=plugin)

    # ==================================================================
    # STAGE 2 — a miss or a bypass: resolve identity and dispatch.
    # ==================================================================
    # AIDEV-NOTE (§57): this stays HERE, after the cache stage, and the defaults it
    # returns are NOT re-merged on the normal path. Two reasons, both load-bearing.
    # It raises 404/409/401, so hoisting it would let those preempt a cache hit; and a
    # second merge would re-read the profile, so a concurrent profile update between
    # the two reads would dispatch a request the key does not describe.
    target, auth_mode = await _resolve_credential_target(
        access, account_id=account_id, provider=provider, selector=selector, plugin=plugin
    )

    if key_defaults is None:
        # The pre-cache read failed, so the merge that feeds the key never ran and the
        # cache already bypassed. Merge here so the request still DISPATCHES with the
        # operator's defaults: a transient index fault must cost a cache hit, never
        # silently drop a stored system prompt. No key exists on this path, so there is
        # nothing for the dispatch body to diverge from.
        body, default_paths = apply_defaults(body, target.defaults, plugin)

    # OME-479 §4.5: classify every optional parameter against the provider's enabled
    # rule set for the REAL (never caller-declared) auth mode, and project accepted
    # fields into a fresh normalized body. This runs before provider normalization,
    # cache planning, and (crucially) credential injection — so unknown, disabled,
    # wrong-auth, malformed and duplicate-channel parameters fail closed with
    # HTTP-safe paths before any credential is read or any provider is dispatched.
    rules = tuple(plugin.chat_parameter_rules(model=model, auth_type=auth_mode))
    try:
        body = classify_and_project_chat_parameters(
            body,
            rules=rules,
            auth_mode=auth_mode,
        )
    except UnsupportedParametersError as exc:
        rejected_defaults = sorted(default_paths & exc.rejected.keys())
        if rejected_defaults:
            # The caller cannot fix a stored default and may never see it (a caller
            # fault outranks it in the response), so it goes to the operator's own
            # channel. Reason codes only — the classifier never carries raw values.
            logger.warning(
                "profile defaults rejected provider=%s account=%s profile=%s paths=%s",
                provider,
                account_id,
                selector.name,
                ",".join(rejected_defaults),
            )
        raise _parameter_rejection_exception(
            exc,
            provider=provider,
            profile_name=selector.name,
            default_paths=default_paths,
        ) from None

    # OME-640: a per-path rule cannot say "these two accepted fields cannot travel
    # together on THIS model under THIS auth mode", so the provider gets one seam
    # to say it — on the projected body, still ahead of provider preparation,
    # cache planning, credential access and dispatch. The default accepts
    # everything, so a provider that states no cross-field constraint is unaffected.
    try:
        plugin.validate_chat_parameter_combination(body, model=model, auth_mode=auth_mode)
    except IncompatibleParametersError as exc:
        if default_paths & set(exc.paths):
            # A stored default can be one half of the conflict, and the caller may
            # not know it exists — so the operator gets their own channel, exactly
            # as for a rejected default. Paths and the provider's own reason only.
            logger.warning(
                "profile defaults in a refused parameter combination "
                "provider=%s account=%s profile=%s paths=%s",
                provider,
                account_id,
                selector.name,
                ",".join(sorted(default_paths & set(exc.paths))),
            )
        raise HTTPException(
            status_code=400,
            detail={
                "code": "incompatible_parameters",
                "provider": provider,
                "conflict": list(exc.paths),
                "message": exc.reason,
            },
        ) from None

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
        # The old dispatch-side cache hardcoded ``bypass`` here with an ``or "stream"`` fallback,
        # not distinguish "streaming" from "the operator disabled the cache".
        return StreamingResponse(
            _stream(plugin, body),
            media_type="text/event-stream",
            headers=global_cache_headers(cache_outcome),
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
        write_status = await store_global_response(request, outcome=cache_outcome, result=result)
    set_global_cache_headers(response, cache_outcome, write_status=write_status)
    # OME-303 INVARIANT (§6): metadata is attached to a COPY, and STRICTLY AFTER the
    # store above. The cache row must stay provider-compatible for every future replay,
    # and `store_global_response` measures `response_size_bytes` against what it is
    # handed — attaching first could push an otherwise cacheable response over the cap.
    if not isinstance(result, dict):
        return result
    return attach_success_metadata(result, accounting, cache_status=cache_outcome.status)

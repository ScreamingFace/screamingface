from __future__ import annotations

import base64
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import logs
from .config import Settings
from .core.api_key_validation_service import ApiKeyValidationService
from .core.auth.bootstrap_admin import ensure_admin_account
from .core.auth.jwt_secret import get_or_create_jwt_secret
from .core.auth.local_only import AuthDisabledLocalOnlyMiddleware
from .core.auth.log_filter import (
    RedactProvisioningTokenFilter,
    install_provisioning_token_redaction,
)
from .core.auth.middleware import ANONYMOUS_ACCOUNT_ID
from .core.credential_blob.store import CredentialBlobMutationConflict, ORMStore
from .core.discovery_runtime import DiscoveryRuntime
from .core.loader import load_plugins
from .core.model_catalog import build_model_catalog
from .core.parameter_discovery import DiscoveryLimits, HttpxDiscoveryClient
from .core.parameter_discovery_cache import (
    CacheLimits,
    ObservationCache,
    SystemMonotonicClock,
)
from .core.pending_auth import PendingAuthTable
from .core.profile_index import ProfileIndexStore
from .core.registry import ProviderRegistry
from .core.request_cache.store import ConfiguredCacheAvailability, TortoiseRequestCacheStore
from .core.request_cache.tavily_store import TavilyRetrievalCacheStore
from .core.request_cache.upload_job import CacheUploadRunner
from .core.secrets.factory import build_secret_store, set_active_secret_store
from .core.usage_accounting.hooks import build_accounting_handler
from .db import close_db, init_db
from .plugins.taxonomy.plugin import TaxonomyPlugin
from .routes import (
    accounts,
    admin,
    admin_cache,
    api_key_validation,
    auth,
    auth_session,
    chat,
    health,
    model_admission,
    model_parameters,
    models,
    oauth_connections,
    providers,
    tavily_retrieval_cache,
)
from .routes.chat_accounting import accounting_error_response

logger = logging.getLogger(__name__)


def _unsigned_jwt(payload: dict) -> str:
    def encode(value: dict | bytes) -> str:
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}.{encode(b'sig')}"


def _attach_log_filter() -> None:
    install_provisioning_token_redaction()
    for name in ("", "uvicorn.access", "uvicorn.error", "aigateway"):
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactProvisioningTokenFilter) for f in target.filters):
            target.addFilter(RedactProvisioningTokenFilter())
        for handler in target.handlers:
            if not any(isinstance(f, RedactProvisioningTokenFilter) for f in handler.filters):
                handler.addFilter(RedactProvisioningTokenFilter())


def _configure_fake_anthropic_oauth(app: FastAPI) -> None:
    if os.getenv("AIGATEWAY_FAKE_ANTHROPIC_OAUTH") != "1":
        return
    import httpx

    fail_mode = os.getenv("AIGATEWAY_FAKE_ANTHROPIC_OAUTH_FAIL") == "1"

    def _fake_handler(req: httpx.Request) -> httpx.Response:
        if req.url.host in (
            "platform.claude.com",
            "console.anthropic.com",
        ) and req.url.path.endswith("/oauth/token"):
            if fail_mode:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(
                200,
                json={
                    "access_token": "fake-tok",
                    "refresh_token": "fake-rt",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(404, json={"error": "unmapped"})

    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(_fake_handler),
            timeout=httpx.Timeout(30.0),
        )

    app.state.anthropic_http_factory = _factory


def _configure_fake_codex_oauth(app: FastAPI) -> None:
    if os.getenv("AIGATEWAY_FAKE_CODEX_OAUTH") != "1":
        return
    import httpx

    fail_mode = os.getenv("AIGATEWAY_FAKE_CODEX_OAUTH_FAIL") == "1"

    def _fake_handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "auth.openai.com" and req.url.path == "/oauth/token":
            if fail_mode:
                return httpx.Response(400, json={"error": "invalid_grant"})
            token_payload = {
                "sub": "codex-sub-1",
                "email": "codex-user@example.com",
                "exp": int(time.time()) + 3600,
                "https://api.openai.com/auth": {"chatgpt_account_id": "acct-codex-1"},
            }
            token = _unsigned_jwt(token_payload)
            return httpx.Response(
                200,
                json={
                    "access_token": token,
                    "refresh_token": "fake-codex-rt",
                    "id_token": token,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(404, json={"error": "unmapped"})

    def _factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(_fake_handler),
            timeout=httpx.Timeout(30.0),
        )

    app.state.codex_http_factory = _factory


@asynccontextmanager
async def _lifespan(app):
    database_url = app.state.settings.database_url.get_secret_value()
    await init_db(database_url)
    try:
        # Install the encryption-at-rest provider BEFORE any credential read/write.
        # The JWT-secret bootstrap and provider bootstrap below both go through the
        # now-encrypting ORMStore, so the active secret store must exist first.
        secret_store = await build_secret_store(
            app.state.settings.secret_provider,
            app.state.settings.secret_key,
        )
        set_active_secret_store(secret_store)
        app.state.secret_store = secret_store

        credential_store = app.state.credential_store
        app.state.jwt_secret = await get_or_create_jwt_secret(
            credential_store,
            app.state.settings.jwt_secret,
        )
        # `auth_mode != "disabled"` is exactly the old `auth_enabled` truth value — the mode is
        # derived from it when only the legacy flag is set (see Settings._reconcile_auth_mode), so
        # this keeps its behavior for `jwt` and extends the same treatment to `cloudflare_headers`.
        authenticating = app.state.settings.auth_mode != "disabled"
        if authenticating or app.state.settings.admin_password is not None:
            # Named `admin_account`, not `admin`: the `admin` ROUTER module is imported at module
            # scope, and a local of that name shadows it for the rest of this function.
            admin_account = await ensure_admin_account(app.state.settings.admin_password)
            bootstrap_account_id = (
                str(admin_account.id) if authenticating else str(ANONYMOUS_ACCOUNT_ID)
            )
        else:
            bootstrap_account_id = str(ANONYMOUS_ACCOUNT_ID)

        # Provider startup bootstrap is opt-in.
        # By default the gateway boots with an empty profile index so the user
        # explicitly authenticates via the UI rather than seeing a "default"
        # profile they did not authorize through the gateway.
        #
        # Bootstrap uses the same DB-backed store as normal runtime credentials.
        if os.getenv("AIGATEWAY_BOOTSTRAP_FROM_CLAUDE_CODE") == "1":
            for plugin in app.state.providers.all():
                try:
                    await plugin.bootstrap_profiles(
                        account_id=bootstrap_account_id,
                        credential_store=credential_store,
                        index_store=app.state.profile_index,
                    )
                except Exception:
                    logger.exception(
                        "bootstrap failed for provider %s; gateway will continue",
                        plugin.custom_llm_provider,
                    )

        # OME-303 U3: ONE app-lifetime observed LiteLLM handler. App-lifetime, not
        # per-request, so connection pooling and the default aiohttp transport are
        # preserved — a handler per call would trade production transport behaviour for
        # accounting, which plan §12 makes a stop condition.
        app.state.usage_accounting_handler = app.state.taxonomy_plugin.start(
            build_accounting_handler
        )

        yield
    finally:
        # §9.12: closed explicitly here rather than left to __del__, which is not
        # guaranteed to run and cannot await. An unclosed handler leaks its connection
        # pool across TestClient lifecycles and across a reload in dev.
        try:
            await app.state.taxonomy_plugin.close()
        except Exception:
            logger.warning("usage accounting handler did not close cleanly")
        app.state.usage_accounting_handler = None
        await auth.close_loopback_callbacks(app)
        # Clear the process-wide active store so it does not leak across app
        # instances (e.g. multiple TestClient lifecycles in one process).
        set_active_secret_store(None)
        await close_db()


async def _redact_validation_errors(_request: Request, exc: Exception) -> JSONResponse:
    """Return 422s without the echoed request body.

    FastAPI's default validation handler includes ``input`` (the raw submitted
    body) in each error. For api-key endpoints that body carries the raw key, so
    echoing it back leaks the secret into error responses and logs (SF-291
    review F1). Strip ``input`` from every error while preserving type/loc/msg."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    cleaned = [{k: v for k, v in err.items() if k != "input"} for err in errors]
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": cleaned}))


async def _accounted_http_exception(request: Request, exc: Exception) -> Response:
    """Render ``_aigw`` beside ``detail`` for an accounted safe terminal error.

    FEATURE (OME-303 §7 U7): a non-streaming chat request gets its evidence back even when
    it fails — that is precisely when "did this cost me anything?" matters most.

    INVARIANT: a strict no-op without an accounting session on ``request.state``. This
    delegates to Starlette's own handler for non-chat and streaming paths. It is registered
    app-wide rather than wrapped around the chat route because safe terminal errors are
    raised from many places, several of them long before dispatch.
    """
    if isinstance(exc, StarletteHTTPException):
        accounted = accounting_error_response(request, cast(HTTPException, exc))
        if accounted is not None:
            return accounted
    return await http_exception_handler(request, cast(StarletteHTTPException, exc))


async def _profile_index_conflict(request: Request, _exc: Exception) -> JSONResponse:
    exc = HTTPException(
        status_code=503,
        detail={
            "code": "profile_index_conflict",
            "message": "Profile metadata update conflicted. Try again.",
        },
    )
    accounted = accounting_error_response(request, exc)
    if accounted is not None:
        return accounted
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _build_discovery_runtime(settings: Settings) -> DiscoveryRuntime | None:
    """Construct the ONE bounded discovery runtime the detailed contract reads from.

    # WHY built here rather than per request: the cache is the whole point. A
    # runtime rebuilt per request would carry an empty cache, turning the TTL into
    # a no-op and re-dialling a public catalog on every contract read.
    # WHY ``None`` when disabled rather than an unbounded stub: the absence of a
    # runtime is the honest "no dynamic evidence", and it leaves no object that
    # could later be handed limits nobody configured.
    # AIDEV-NOTE: ``HttpxDiscoveryClient`` opens (and closes) its connection per
    # fetch, so there is nothing to shut down in the lifespan.
    """
    if not settings.discovery_enabled:
        return None
    return DiscoveryRuntime(
        client=HttpxDiscoveryClient(),
        cache=ObservationCache(
            clock=SystemMonotonicClock(),
            limits=CacheLimits(
                ttl_s=settings.discovery_cache_ttl_seconds,
                stale_ttl_s=settings.discovery_cache_stale_ttl_seconds,
                max_entries=settings.discovery_cache_max_entries,
                failure_ttl_s=settings.discovery_cache_failure_ttl_seconds,
            ),
        ),
        limits=DiscoveryLimits(
            timeout_s=settings.discovery_timeout_seconds,
            max_bytes=settings.discovery_max_bytes,
        ),
    )


def _describe_admin_security(app: FastAPI) -> None:
    """Wrap `app.openapi` so the admin operations declare the identity header they require.

    Wrapping rather than pre-building: FastAPI generates the document lazily on first request and
    caches it on `app.openapi_schema`, so building it here would freeze a schema that later router
    additions could not reach. The cache check keeps this a one-time cost, matching FastAPI's own
    behaviour.
    """
    build = app.openapi

    def openapi_with_admin_security() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = admin.describe_admin_security(build())
        return app.openapi_schema

    app.openapi = openapi_with_admin_security  # type: ignore[method-assign]


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()
    # WHY ordered before _attach_log_filter: the redaction filter is added to
    # the "aigateway" logger's handlers, so our handler must exist first.
    logs.configure()
    _attach_log_filter()
    app = FastAPI(title="aigateway", version="0.1.0", lifespan=_lifespan)
    app.add_exception_handler(RequestValidationError, _redact_validation_errors)
    app.add_exception_handler(CredentialBlobMutationConflict, _profile_index_conflict)
    app.add_exception_handler(StarletteHTTPException, _accounted_http_exception)
    app.state.settings = settings
    app.state.taxonomy_plugin = TaxonomyPlugin()
    app.state.usage_accounting_handler = None
    # Only the `disabled` mode makes every caller anonymous, so only it needs the loopback guard.
    # `cloudflare_headers` authenticates from the injected header and is meant to be reached over
    # network — binding it to loopback would break the deployment it exists for.
    if settings.auth_mode == "disabled":
        app.add_middleware(AuthDisabledLocalOnlyMiddleware)
    elif settings.auth_mode == "cloudflare_headers" and not settings.allowed_networks:
        # WHY refuse to build rather than default to something permissive: in this mode the network
        # IS the authentication boundary, and "which networks?" has no answer the gateway can
        # safely guess. An operator cannot obtain the trust without stating who they trust. The
        # deployment fails here, at import, rather than serving every reachable caller.
        raise ValueError(
            "AIGW_AUTH_MODE=cloudflare_headers trusts the X-User-Email header from any caller that "
            "can reach this port, so the callers allowed to present it must be declared: set "
            "AIGW_ALLOWED_NETWORKS to the CIDR networks of the url4-cloud App and its Runner Pods "
            "(e.g. your cluster's Pod CIDR)"
        )

    registry = ProviderRegistry()
    load_plugins(registry)
    app.state.providers = registry
    app.state.api_key_validation_service = ApiKeyValidationService()

    # Test-only OAuth endpoint hooks are gated by env vars so they only activate
    # in e2e harnesses. Credential storage itself is always DB-backed.
    credential_store = ORMStore()
    app.state.credential_store = credential_store
    app.state.profile_index = ProfileIndexStore(credential_store=credential_store)
    app.state.request_cache_store = TortoiseRequestCacheStore(
        availability=ConfiguredCacheAvailability(settings.request_cache_enabled)
    )
    # OME-1044: the Tavily retrieval lane takes no availability gate — it is unconditional
    # (owner decision), so unlike the response cache above there is nothing to configure.
    app.state.tavily_retrieval_cache_store = TavilyRetrievalCacheStore()

    _configure_fake_anthropic_oauth(app)
    _configure_fake_codex_oauth(app)

    app.state.pending_auth = PendingAuthTable(ttl_seconds=600)
    app.state.discovery_runtime = _build_discovery_runtime(settings)
    # OME-972: the app-lifetime, process-local live model-listing catalog. Same kill switch
    # as the runtime above — AIGW_DISCOVERY_ENABLED=false audits to zero
    # discovery egress of ANY kind. The catalog owns no transport; the models
    # route passes the runtime's client/limits per call.
    app.state.model_catalog = build_model_catalog(enabled=settings.discovery_enabled)
    # OME-952: the admin cache-snapshot upload runner. app-state-only by the same reasoning
    # as `admitted_models` above: job REPORTS are deployment-lifetime, the loaded data and
    # the audit log are the durable truth.
    app.state.cache_upload_runner = CacheUploadRunner(
        max_upload_bytes=settings.cache_upload_max_bytes
    )
    # OME-879: dynamic-admission state. Deliberately app-state-only (deployment
    # lifetime): a restart forgets every admission and nothing is persisted.
    app.state.admitted_models = {}
    app.state.admission_catalog_cache = {}

    for plugin in registry.all():
        auth_router = plugin.auth_router()
        if auth_router is not None:
            app.include_router(auth_router, prefix=f"/v1/auth/{plugin.custom_llm_provider}")

    app.include_router(auth_session.router)
    app.include_router(accounts.router)
    app.include_router(admin.router)
    _describe_admin_security(app)
    app.include_router(admin_cache.router)
    app.include_router(api_key_validation.router)
    app.include_router(auth.router)
    app.include_router(oauth_connections.router)
    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(model_admission.router)
    app.include_router(providers.router)
    app.include_router(model_parameters.router)
    app.include_router(tavily_retrieval_cache.router)
    app.include_router(chat.router)

    logger.info("aigateway ready (port=%d, providers=%d)", settings.port, len(registry.all()))
    return app


app = create_app()

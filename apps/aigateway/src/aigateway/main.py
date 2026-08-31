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
from fastapi.responses import JSONResponse, PlainTextResponse
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
from .core.loader import load_plugins
from .core.pending_auth import PendingAuthTable
from .core.profile_index import ProfileIndexStore
from .core.registry import ProviderRegistry
from .core.request_cache.store import ConfiguredCacheAvailability, TortoiseRequestCacheStore
from .core.request_cache.upload_job import CacheUploadRunner
from .core.secrets.factory import build_secret_store, set_active_secret_store
from .core.usage_accounting.hooks import build_accounting_handler
from .db import close_db, init_db
from .discovery_lifecycle import (
    build_discovery_runtime,
    install_discovery,
    shutdown_discovery,
    start_public_prewarm,
)
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
    oauth_callbacks,
    oauth_connections,
    profile_models,
    profile_routes,
    providers,
)
from .routes.chat_accounting import accounting_error_response
from .routes.private_cache import stamp_private_cache_policy

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

        # OME-1026: warm the PUBLIC catalogs in the background.
        # INVARIANT (non-blocking): startup must not wait on an upstream catalog — a
        # slow or unreachable provider would delay readiness and could fail the boot of
        # a gateway that serves fine from seeds. Every task started here is tracked by
        # the manager, so shutdown cancels and awaits it.
        start_public_prewarm(app)

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
        # OME-1026: stop background discovery before the loop goes away. Cancel AND
        # await, so a task's own cleanup runs and nothing is destroyed while pending.
        await shutdown_discovery(app)
        await auth.close_loopback_callbacks(app)
        # Clear the process-wide active store so it does not leak across app
        # instances (e.g. multiple TestClient lifecycles in one process).
        set_active_secret_store(None)
        await close_db()


async def _redact_validation_errors(request: Request, exc: Exception) -> JSONResponse:
    """Return 422s without the echoed request body.

    FastAPI's default validation handler includes ``input`` (the raw submitted
    body) in each error. For api-key endpoints that body carries the raw key, so
    echoing it back leaks the secret into error responses and logs (SF-291
    review F1). Strip ``input`` from every error while preserving type/loc/msg.

    # OME-1026 adversarial B1: a validation error is raised while FastAPI SOLVES the
    # request, so the private routes' own route class never renders it. The scope
    # marker it left behind is what makes this 422 unshareable; the redaction above is
    # unchanged.
    """
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    cleaned = [{k: v for k, v in err.items() if k != "input"} for err in errors]
    response = JSONResponse(status_code=422, content=jsonable_encoder({"detail": cleaned}))
    return cast(JSONResponse, stamp_private_cache_policy(request, response))


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
            return stamp_private_cache_policy(request, accounted)
    rendered = await http_exception_handler(request, cast(StarletteHTTPException, exc))
    # Belt AND braces (adversarial B1): the route class already merged the policy into
    # ``exc.headers``, but this handler is where the response is actually rendered, and
    # not every renderer above copies those headers. Stamping is idempotent.
    return stamp_private_cache_policy(request, rendered)


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
        return cast(JSONResponse, stamp_private_cache_policy(request, accounted))
    response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return cast(JSONResponse, stamp_private_cache_policy(request, response))


async def _sanitized_server_error(request: Request, _exc: Exception) -> Response:
    """Render the generic 500 INSIDE the application, so its headers are observable.

    # WHY this handler exists (OME-1026 adversarial B1): Starlette renders an unhandled
    # exception in ``ServerErrorMiddleware``, which is installed OUTSIDE every user
    # middleware and writes with the ORIGINAL ``send``. No middleware this app can add
    # will ever see that response, so a private route's 500 was emitted with no cache
    # directives and no ``Vary`` at all. Registering a handler moves the rendering into
    # the app, which is the only place the policy can be applied.
    # INVARIANT: the body is byte-identical to Starlette's default and discloses
    # nothing about ``_exc``; ``ServerErrorMiddleware`` still re-raises afterwards, so
    # logging, uvicorn's traceback, and test propagation are unchanged.
    """
    response = PlainTextResponse("Internal Server Error", status_code=500)
    return stamp_private_cache_policy(request, response)


# Re-exported under its original private name: a PRIOR test imports
# ``aigateway.main._build_discovery_runtime``
# (tests/unit/core/test_parameter_discovery_negative_cache.py, merged in #443) and tests
# are append-only. The implementation moved to ``discovery_lifecycle`` with the rest of
# the discovery wiring (OME-1026 F8).
_build_discovery_runtime = build_discovery_runtime


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
    app.add_exception_handler(Exception, _sanitized_server_error)
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

    _configure_fake_anthropic_oauth(app)
    _configure_fake_codex_oauth(app)

    app.state.pending_auth = PendingAuthTable(ttl_seconds=600)
    # OME-972/OME-1026: every live-discovery object this process holds, built from one
    # kill switch. Requires app.state.providers, set above — the public refresh
    # manager's capacity is the provider count.
    install_discovery(app, settings=settings)
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
    # The profile CRUD and OAuth-callback halves of the auth surface, split out of
    # ``routes.auth`` by responsibility. Registered adjacently and prefix-free, so
    # the served paths are byte-identical to the single-router arrangement.
    app.include_router(profile_routes.router)
    app.include_router(oauth_callbacks.router)
    app.include_router(oauth_connections.router)
    app.include_router(health.router)
    app.include_router(profile_models.router)
    app.include_router(models.router)
    app.include_router(model_admission.router)
    app.include_router(providers.router)
    app.include_router(model_parameters.router)
    app.include_router(chat.router)

    logger.info("aigateway ready (port=%d, providers=%d)", settings.port, len(registry.all()))
    return app


app = create_app()

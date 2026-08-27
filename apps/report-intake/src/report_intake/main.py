"""The FastAPI composition root.

`create_app` is the one place this service's startup guards run. They are here rather than on
`Settings` because each is either a cross-field check or a check on an environment variable
`Settings` does not own — and both kinds fail in the direction that looks like success: a pod
boots, answers its probes, and is wrong about who its callers are.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, logs
from .config import ENV_PREFIX, Settings
from .core.body_limit import BodyLimitMiddleware
from .core.local_only import LoopbackOnlyMiddleware
from .core.problem import install_problem_handlers
from .db import close_db, init_db
from .delivery.dispatch import TicketDispatcher
from .delivery.registry import build_sink, close_sink
from .identity.rate_limit import TokenBucketLimiter
from .identity.turnstile import TURNSTILE_RESPONSE_HEADER, HttpTurnstileVerifier
from .reports.caps import MAX_BODY_BYTES
from .reports.retention import RetentionPurge
from .reports.retry import CLAIM_GRACE, RetryQueue
from .reports.store import STORAGE_TIMEOUT_S, ReportStore
from .reports.store_pipeline import StorePipeline
from .routes import health, ready, reports

# WHY read directly from os.environ, not a Settings field: this is uvicorn's own env var
# (FORWARDED_ALLOW_IPS, deliberately unprefixed), read by uvicorn.Config itself in cli.py's
# uvicorn.run(), never by this app. Checking it here is a startup sanity guard, not a config
# source — which is why it is the one name in this service's environment that is NOT a Settings
# field, and why `Settings` carries a pointer back to this module.
_FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"
# Mirrors uvicorn.config.Config's own fallback, pinned by a test against the installed uvicorn so
# an upgrade that changes its default breaks a test here rather than silently drifting.
_UVICORN_DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1"


def _reject_unknown_environment(environ: Mapping[str, str]) -> None:
    """Refuse to start when a `REPORT_INTAKE_*` variable matches no `Settings` field.

    `extra="ignore"` means a misspelt or renamed variable is accepted, dropped, and never
    mentioned — so the pod starts with the field's DEFAULT. For a name like `AUTH_MODE` that is
    not a cosmetic mismatch: it is a production pod running with authentication disabled, which
    looks identical to a working one until someone forges a request. Fail at boot instead.
    """
    known = {f"{ENV_PREFIX}{name.upper()}" for name in Settings.model_fields}
    unknown = sorted(
        key for key in environ if key.upper().startswith(ENV_PREFIX) and key.upper() not in known
    )
    if not unknown:
        return
    raise ValueError(
        f"{', '.join(unknown)} matches no report-intake setting, so it would be read by nobody "
        f"and this service would run on the default instead. Fix the name to one of: "
        f"{', '.join(sorted(f'{ENV_PREFIX}{name.upper()}' for name in Settings.model_fields))}."
    )


def _classify_forwarded_allow_ips(
    raw: str,
) -> tuple[set[IPv4Network | IPv6Network], set[IPv4Address | IPv6Address]]:
    """Mirror uvicorn's own (undocumented, private) `_TrustedHosts` entry classification:
    comma-split, strip; an entry containing `/` is tried as a CIDR network, else as a bare
    address. Anything failing both becomes an inert literal uvicorn can never match a real peer
    against, so it is silently dropped here too — this predicts uvicorn's forgiving runtime
    behaviour, it does not add strictness of its own (unlike `config.py`'s deliberately strict
    `_parse_allowed_networks`).

    A bare-address entry written in IPv4-mapped-IPv6 form (`::ffff:10.0.0.5`) is normalized to
    its plain IPv4 form: an operator naming the SAME real peer in the form a dual-stack cluster
    reports it must overlap `allowed_networks` the same way the plain form would. Only bare
    addresses are normalized, never declared networks.
    """
    networks: set[IPv4Network | IPv6Network] = set()
    hosts: set[IPv4Address | IPv6Address] = set()
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        if "/" in entry:
            try:
                networks.add(ip_network(entry))
            except ValueError:
                pass
            continue
        try:
            host = ip_address(entry)
        except ValueError:
            continue
        if isinstance(host, IPv6Address) and host.ipv4_mapped is not None:
            host = host.ipv4_mapped
        hosts.add(host)
    return networks, hosts


def _find_forwarded_allow_ips_overlap(
    raw: str, allowed_networks: tuple[IPv4Network | IPv6Network, ...]
) -> tuple[IPv4Network | IPv6Network | IPv4Address | IPv6Address, IPv4Network | IPv6Network] | None:
    """The first (`FORWARDED_ALLOW_IPS` entry, `allowed_networks` entry) pair that overlaps, or
    None. A cross-version pair never overlaps — checked explicitly for readability, though
    `ipaddress`'s own `.overlaps()`/`in` already return False rather than raise.
    """
    trusted_networks, trusted_hosts = _classify_forwarded_allow_ips(raw)
    for allowed in allowed_networks:
        for network in trusted_networks:
            if network.version == allowed.version and network.overlaps(allowed):
                return network, allowed
        for host in trusted_hosts:
            if host.version == allowed.version and host in allowed:
                return host, allowed
    return None


def _check_forwarded_allow_ips(allowed_networks: tuple[IPv4Network | IPv6Network, ...]) -> None:
    """Refuse to start when uvicorn would let a client rewrite the peer address this service
    authenticates on.

    Declaring `allowed_networks` means something is about to trust `request.client.host` — the
    mesh identity header, the rate-limit key, or both. Uvicorn's ProxyHeadersMiddleware (always
    on) OVERWRITES that value from a client-supplied `X-Forwarded-For` whenever the real peer
    falls inside `FORWARDED_ALLOW_IPS`. `"*"` matches every peer, no proxy relationship required,
    so anyone who can reach this port can forge the peer.

    INVARIANT: two conditions, not one. Scoping the value away from `"*"` is NOT sufficient — a
    single deliberately narrow address still lets uvicorn rewrite the peer for exactly the peers
    `allowed_networks` exists to authenticate, if that address falls inside them. The two sets
    must be disjoint.
    """
    if not allowed_networks:
        return
    raw = os.environ.get(_FORWARDED_ALLOW_IPS_ENV, _UVICORN_DEFAULT_FORWARDED_ALLOW_IPS).strip()
    if raw == "*":
        raise ValueError(
            f"REPORT_INTAKE_ALLOWED_NETWORKS conflicts with {_FORWARDED_ALLOW_IPS_ENV}='*' — "
            "uvicorn would trust a client-supplied X-Forwarded-For from ANY peer and overwrite "
            "request.client.host, so the peer check would authenticate whoever asked to be "
            f"authenticated. Scope {_FORWARDED_ALLOW_IPS_ENV} to the real proxy's address(es)."
        )
    overlap = _find_forwarded_allow_ips_overlap(raw, allowed_networks)
    if overlap is None:
        return
    trusted_entry, allowed_entry = overlap
    raise ValueError(
        f"REPORT_INTAKE_ALLOWED_NETWORKS conflicts with {_FORWARDED_ALLOW_IPS_ENV}={raw!r} — its "
        f"entry {trusted_entry} overlaps allowed_networks entry {allowed_entry}. uvicorn would "
        "rewrite request.client.host from a client-supplied X-Forwarded-For for exactly the "
        f"peers allowed_networks exists to authenticate. {_FORWARDED_ALLOW_IPS_ENV} must be "
        "disjoint from REPORT_INTAKE_ALLOWED_NETWORKS, not merely non-'*'."
    )


def _check_auth_mode(settings: Settings) -> None:
    """Refuse to start a `mesh_or_turnstile` app that cannot actually run either half of the gate.

    Both halves have to work, because spec §7's two caller classes are not alternatives an
    operator chooses between — every request is one or the other, and a missing half silently
    turns that class away:

    - **No `allowed_networks`** and `peer_in_networks` denies everything, so no request can ever
      be mesh-verified and every caller — including the mesh's own — is sent to the bot gate.
      There is also no value this service could safely guess: "which networks?" is a fact about
      the deployment, and an operator cannot obtain the trust without stating who they trust.
    - **No `turnstile_secret`** and siteverify rejects our own credentials, which this service
      correctly reads as an unevaluable gate — so every anonymous caller gets a `503` forever
      while the pod reports itself healthy and ready.

    Both fail in the direction that looks like a working deployment, which is why they are boot
    failures rather than warnings.
    """
    if settings.auth_mode != "mesh_or_turnstile":
        return
    if not settings.allowed_networks:
        raise ValueError(
            f"{ENV_PREFIX}AUTH_MODE=mesh_or_turnstile trusts an identity header injected by the "
            f"mesh, so the peers allowed to inject it must be declared: set "
            f"{ENV_PREFIX}ALLOWED_NETWORKS to the CIDR networks of the mesh gateway (e.g. your "
            "cluster's Pod CIDR). Without it nothing can ever be mesh-verified."
        )
    if not settings.turnstile_secret.get_secret_value():
        raise ValueError(
            f"{ENV_PREFIX}AUTH_MODE=mesh_or_turnstile gates anonymous callers on Cloudflare "
            f"Turnstile, so set {ENV_PREFIX}TURNSTILE_SECRET from a Secret. Without it siteverify "
            "rejects this service's own credentials and every anonymous report is answered 503."
        )


def _check_delivery_timeout(settings: Settings) -> None:
    """Refuse to start when the inline attempt can outlast the sweeper's claim grace.

    The two numbers are one relation, held in two modules. `StorePipeline` commits the row —
    `pending`, due at `created_at`, UNLEASED — and only then calls the sink, so for the whole of
    that inline attempt there is a window in which a sweeper on another replica would happily
    claim a report the request path is already delivering. `RetryQueue`'s `CLAIM_GRACE` closes it
    by leaving a due row alone until longer than a whole inline attempt has passed.

    "A whole inline attempt" is the sink deadline plus the two storage deadlines around it. Only
    the first is configurable — `config.deliveryTimeoutS` is a live chart knob — so raising it far
    enough re-opens the double-ticket window with nothing red anywhere. A unit test pinning the
    arithmetic proves it for config.py's DEFAULT and says nothing about the value a deployment
    renders, which is the one that matters.
    """
    inline_worst_case = settings.delivery_timeout_s + 2 * STORAGE_TIMEOUT_S
    if inline_worst_case < CLAIM_GRACE.total_seconds():
        return
    raise ValueError(
        f"{ENV_PREFIX}DELIVERY_TIMEOUT_S={settings.delivery_timeout_s} makes the worst-case "
        f"inline delivery attempt {inline_worst_case}s (the sink deadline plus the two "
        f"{STORAGE_TIMEOUT_S}s storage deadlines around it), which is not shorter than the "
        f"{CLAIM_GRACE.total_seconds()}s grace the retry sweep leaves a due row alone for. The "
        "sweep would claim reports the request path is still delivering and file one bug report "
        f"as two tickets. Lower {ENV_PREFIX}DELIVERY_TIMEOUT_S — spec §2.2's number is 3."
    )


async def _stop(*tasks: asyncio.Task[None]) -> None:
    """Cancel every background loop, then wait for each of them to actually end.

    Cancelled in one pass and awaited in a second, so a slow one does not delay the others'
    cancellation — shutdown has a deadline, and a loop still sweeping while the database closes
    under it logs a failure nobody needs to read.
    """
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the database, run the background loops, close the database.

    INVARIANT: every startup task this service ever grows belongs HERE. Appending one to
    `app.router.on_startup` alongside a `lifespan=` is a silent no-op on the pinned starlette —
    `Router.lifespan_context` is set directly and `router.startup()` is never called — so the
    task would simply never run in production while its unit tests kept passing.

    Both tasks are OWNED: the event loop keeps only a weak reference to a bare `create_task`, so
    a task nobody holds can be garbage-collected mid-sweep.
    """
    settings: Settings = app.state.settings
    await init_db(settings.database_url)
    app.state.retention_purge = asyncio.create_task(
        RetentionPurge(app.state.report_store).run(), name="report-intake-retention-purge"
    )
    app.state.retry_queue = asyncio.create_task(
        RetryQueue(app.state.report_store, app.state.ticket_dispatcher).run(),
        name="report-intake-retry-queue",
    )
    try:
        yield
    finally:
        await _stop(app.state.retention_purge, app.state.retry_queue)
        # Only the verifier THIS app built: a test that swapped its own onto the seam owns it,
        # and calling `aclose` on a fake would make installing one an error at shutdown.
        verifier = app.state.turnstile_verifier
        if isinstance(verifier, HttpTurnstileVerifier):
            await verifier.aclose()
        # Structural, not by class: the composition root goes on not knowing which adapters
        # exist, so `close_sink` closes a sink that has an `aclose` — an HTTP connection pool —
        # and leaves `QueueSink` and every stub a test installed alone.
        await close_sink(app.state.ticket_sink)
        await close_db()


def _install_middleware(app: FastAPI, settings: Settings) -> None:
    """The middleware stack, added innermost first.

    `add_middleware` PREPENDS, so the last one added is the outermost and the order below reads
    inside-out. Both positions are decisions:

    - **The body cap is innermost of the three and still pre-routing**, which is the only place
      it can refuse a body without the app having been handed the stream.
    - **The loopback guard sits outside it**, so a caller `disabled` mode will not serve does not
      get its body buffered first.
    - **CORS is outermost**, so a browser gets the `Access-Control-Allow-Origin` header on the
      `403` and the `413` too. Without it the browser reports a CORS failure and the client never
      sees the status that told it what to do — which is the whole point of spec §2.3's table.
    """
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    if settings.auth_mode == "disabled":
        app.add_middleware(LoopbackOnlyMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            # INVARIANT: never credentials. This endpoint authenticates on a header the mesh
            # injects, never on a cookie, so allowing credentials would grant browsers an ambient
            # authority nothing here uses — and it is what makes a cross-site POST able to file a
            # report as whoever is logged in.
            allow_credentials=False,
            allow_methods=["POST"],
            allow_headers=["Content-Type", "Idempotency-Key", TURNSTILE_RESPONSE_HEADER],
            max_age=600,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = Settings()

    _reject_unknown_environment(os.environ)
    _check_forwarded_allow_ips(settings.allowed_networks)
    _check_auth_mode(settings)
    _check_delivery_timeout(settings)

    # From here, not only from cli.main: a pod's entrypoint is uvicorn importing this module, so
    # configuring logs in the CLI alone leaves every deployed process on `logging.lastResort`.
    logs.configure(settings.log_level)

    app = FastAPI(title="report-intake", version=__version__, lifespan=_lifespan)
    app.state.settings = settings
    # Constructing the store touches no connection — `_lifespan` opens those — so the two seams
    # below can be filled here, where the wiring is visible, rather than inside the lifespan
    # where a request arriving before startup finished would find them empty.
    store = ReportStore(
        idempotency_ttl=timedelta(hours=settings.idempotency_ttl_h),
        retention=timedelta(days=settings.retention_days),
    )
    app.state.report_store = store
    # The readiness seam (plan §2.5). One assignment, and `routes/ready.py` is untouched.
    app.state.readiness_check = store.is_reachable
    # Named, never imported: the composition root asks the registry for the configured adapter and
    # does not know `QueueSink` exists. `build_sink` refuses HERE, at boot, rather than letting a
    # misconfigured service accept reports and file none of them — on an unknown name, and on a
    # `linear` selection whose credential is missing. It is handed the whole `Settings` because an
    # adapter that talks to a third party needs one, and the registry is the module allowed to
    # know which fields that is.
    sink = build_sink(settings)
    app.state.ticket_sink = sink
    # ONE dispatcher, shared by the request path and the retry loop. A retry that built its own
    # would be a second delivery path — a second renderer, a second fail-closed re-check, a second
    # deadline — and the body a sink receives on the sixth attempt would be nobody's reviewed
    # output. It is also why the retry queue needs no timeout setting of its own.
    dispatcher = TicketDispatcher(sink, timeout=settings.delivery_timeout_s)
    app.state.ticket_dispatcher = dispatcher
    # The report pipeline seam. One assignment, and `routes/reports.py` keeps its shape.
    app.state.report_pipeline = StorePipeline(store, dispatcher)
    # Built in every mode so a test can reach it, consulted only for an anonymous caller in a
    # mode that has one. Per process and per app, which is what makes the effective ceiling
    # `replicas × anon_rate_limit` — see the module docstring on why that is enough here.
    app.state.anon_rate_limiter = TokenBucketLimiter(
        limit=settings.anon_rate_limit,
        window_s=settings.anon_rate_window_s,
        burst=settings.anon_rate_burst,
        max_keys=settings.anon_rate_max_keys,
    )
    # `disabled` builds none: it has no anonymous caller class to gate, and constructing an HTTP
    # client for every app a test builds would be a resource nobody closes.
    app.state.turnstile_verifier = (
        HttpTurnstileVerifier(
            secret=settings.turnstile_secret.get_secret_value(),
            verify_url=settings.turnstile_verify_url,
            timeout_s=settings.turnstile_timeout_s,
        )
        if settings.auth_mode == "mesh_or_turnstile"
        else None
    )

    _install_middleware(app, settings)
    install_problem_handlers(app)
    app.include_router(health.router)
    app.include_router(ready.router)
    app.include_router(reports.router)
    return app


app = create_app()

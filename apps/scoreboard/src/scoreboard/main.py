from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .adapters.jws_grant_signer import Ed25519GrantSigner
from .adapters.jws_receipt_verifier import Ed25519ReceiptVerifier
from .adapters.url4_fingerprinter import Url4Fingerprinter
from .config import Settings
from .core.registry import RegistryService
from .db import close_db, init_db
from .logs import configure as configure_logging
from .metrics import build_metrics
from .portal import register_portal
from .routes import health, leaderboard, replay_grants, results, score_metadata, scores
from .scores.baseline_store import BaselineStore
from .scores.cluster_store import ClusterStore
from .scores.metadata_store import ScoreMetadataStore
from .scores.replay_resolver import ReplayPinResolver
from .scores.store import ScoreStore
from .scores.system_registry_store import TortoiseSystemRepository

# WHY read directly from os.environ, not a Settings field: this is uvicorn's own env var
# (FORWARDED_ALLOW_IPS, no SCOREBOARD_ prefix — see charts/scoreboard/values.yaml's
# config.forwardedAllowIps), read by uvicorn.Config itself in cli.py's uvicorn.run(), never
# by this app. Checking it here is purely a startup sanity guard, not a config source.
# AIDEV-NOTE: not discoverable from Settings' field docstrings for the same reason — if you're
# auditing "what must be configured correctly for cloudflare_headers mode" and only read
# config.py, you will miss this. See Settings.auth_mode's docstring for a pointer back here.
_FORWARDED_ALLOW_IPS_ENV = "FORWARDED_ALLOW_IPS"
# Mirrors uvicorn.config.Config's own fallback (os.environ.get("FORWARDED_ALLOW_IPS",
# "127.0.0.1")) — pinned by test_header_mode_starts_with_unset_forwarded_allow_ips against the
# installed uvicorn version, so a future uvicorn upgrade that changes its default breaks a test
# here rather than silently drifting.
_UVICORN_DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1"


def _classify_forwarded_allow_ips(
    raw: str,
) -> tuple[set[IPv4Network | IPv6Network], set[IPv4Address | IPv6Address]]:
    """Mirror uvicorn's own (undocumented, private) `_TrustedHosts` entry classification:
    comma-split, strip; an entry containing `/` is tried as a CIDR network (strict — a
    host-bits-set entry like "10.0.0.5/8" fails to parse and falls through, exactly as it does
    for uvicorn), else tried as a bare address. Anything failing both becomes an inert literal
    uvicorn can never match a real peer against, so it's silently dropped here too — this
    predicts uvicorn's actual forgiving runtime behavior, it does not add new strictness
    (unlike config.py's deliberately strict `_parse_allowed_networks`).

    A bare-address entry written in IPv4-mapped-IPv6 form (e.g. "::ffff:10.0.0.5") is
    normalized to its plain IPv4 form, mirroring `peer_in_networks`'s own unwrapping — an
    operator naming the SAME real peer in the form a dual-stack cluster happens to report it
    must overlap `allowed_networks` the same way the plain form would (found in follow-up
    review of this guard). Only bare addresses are normalized, not CIDR entries — this exactly
    matches `peer_in_networks`'s own scope, which normalizes a single connecting peer, never a
    declared network.

    Pinned against the installed uvicorn version by
    test_uvicorn_parses_a_cidr_forwarded_allow_ips_entry_into_trusted_networks and
    test_uvicorn_parses_a_bare_ip_forwarded_allow_ips_entry_into_trusted_hosts.
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
    """The first (FORWARDED_ALLOW_IPS entry, allowed_networks entry) pair that overlaps, or
    None. A cross-version pair (e.g. an IPv6 FORWARDED_ALLOW_IPS entry against an IPv4-only
    allowed_networks entry) never overlaps — checked explicitly for readability, though
    `ipaddress`'s own `.overlaps()`/`in` already return False rather than raise on a version
    mismatch.
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


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    await init_db(settings.database_url, pool=settings.db_pool)
    try:
        yield
    finally:
        await close_db()


def _wire_clustered_submit(app: FastAPI, settings: Settings) -> None:
    """FEATURE: OME-1307 (E14) — what `POST /v1/scores` needs when clustering is on, and the
    results list route.

    The verifier is built at `create_app`, so a bad receipt key fails at startup. The results router
    is included BEFORE `register_portal`, which mounts `/` last.
    """
    # The system registry. `POST /v1/scores` and the cluster store both read it.
    app.state.system_registry = RegistryService(TortoiseSystemRepository(), Url4Fingerprinter())
    app.state.receipt_verifier = Ed25519ReceiptVerifier.from_config(settings.receipt_public_keys)
    app.state.metrics = build_metrics()
    app.state.cluster_store = ClusterStore(app.state.score_store, app.state.system_registry)
    app.include_router(results.router)
    _wire_replay_grants(app, settings)


def _grant_signer(settings: Settings) -> Ed25519GrantSigner | None:
    """The signer of replay grants, or None when neither variable is set (the route then answers
    503 `replay_unavailable`). One variable without the other, or a bad key, fails at startup.

    INVARIANT: no error message holds key text (`Ed25519GrantSigner.from_config` and the messages
    here name the variable, never the value).
    """
    key, kid = settings.replay_grant_signing_key, settings.replay_grant_signing_kid
    if key is None and not kid:
        return None
    if key is None:
        raise ValueError(
            "SCOREBOARD_REPLAY_GRANT_SIGNING_KID is set but SCOREBOARD_REPLAY_GRANT_SIGNING_KEY "
            "is not"
        )
    if not kid:
        raise ValueError(
            "SCOREBOARD_REPLAY_GRANT_SIGNING_KEY is set but SCOREBOARD_REPLAY_GRANT_SIGNING_KID "
            "is not"
        )
    return Ed25519GrantSigner.from_config(key.get_secret_value(), kid)


def _wire_replay_grants(app: FastAPI, settings: Settings) -> None:
    """FEATURE: OME-1307 (E14) replay grants: the route and what it reads from `app.state`.

    WHY called from `_wire_clustered_submit` and not from `create_app`: the resolver reads the
    cluster store and the registry that function builds, and `create_app` sits at the statement
    limit. The router is still included before `register_portal`, which mounts `/` last.
    """
    app.state.grant_signer = _grant_signer(settings)
    app.state.replay_resolver = ReplayPinResolver(
        app.state.cluster_store, app.state.system_registry
    )
    app.state.clock = lambda: datetime.now(UTC)
    app.include_router(replay_grants.router)


def create_app(settings: Settings | None = None) -> FastAPI:
    # WHY first, and here rather than in cli.main: create_app is the one door every ASGI host
    # goes through (`scoreboard` CLI, a bare `uvicorn scoreboard.main:app`, an embedding
    # process), and uvicorn never configures the `scoreboard` logger (OME-937).
    configure_logging()
    if settings is None:
        settings = Settings()

    # WHY at construction, not left to peer_in_networks' own fail-closed default: this service
    # trusts X-User-Email BECAUSE only declared networks may present it, so a deployment that
    # forgets to set SCOREBOARD_ALLOWED_NETWORKS should fail loudly at startup, not silently
    # 403 every submission in production and leave an operator debugging a "broken" service
    # that is actually just unconfigured (mirrors aigateway's create_app of the same name).
    if settings.auth_mode == "cloudflare_headers" and not settings.allowed_networks:
        raise ValueError(
            "SCOREBOARD_AUTH_MODE=cloudflare_headers requires SCOREBOARD_ALLOWED_NETWORKS to be "
            "set — this service cannot trust X-User-Email without knowing which peers may "
            "present it."
        )

    # WHY: peer_in_networks() trusts request.client.host as the real TCP peer. Uvicorn's
    # ProxyHeadersMiddleware (always on by default) overwrites that value from a
    # client-supplied X-Forwarded-For whenever FORWARDED_ALLOW_IPS matches the peer — and "*"
    # matches every peer, no proxy relationship required. Confirmed by reproduction: with
    # FORWARDED_ALLOW_IPS=* an attacker who can merely reach this port at all (no relation to
    # the real reverse proxy) can forge X-Forwarded-For to satisfy allowed_networks and ride
    # straight through to a forged X-User-Email. "*" is the value apps/scoreboard's chart sets
    # by default for the Traefik-fronted deployment (DEPLOYMENT.md) — safe there because that
    # deployment doesn't use cloudflare_headers mode, but never safe combined with it.
    # INVARIANT: cloudflare_headers mode requires TWO things of FORWARDED_ALLOW_IPS, not one —
    # it must never be "*", AND its trusted set must never overlap allowed_networks at all.
    # Scoping it away from "*" is not sufficient on its own (found in external review of this
    # PR): uvicorn's ProxyHeadersMiddleware overwrites request.client.host from a
    # client-supplied X-Forwarded-For whenever the real peer falls inside FORWARDED_ALLOW_IPS —
    # even a single, deliberately narrow address, not just "*". If that address also falls
    # inside allowed_networks, the exact peers the check exists to authenticate are the ones it
    # can no longer see correctly — a smaller-scoped repeat of the "*" bypass below, not a fix
    # for it. FORWARDED_ALLOW_IPS must be disjoint from SCOREBOARD_ALLOWED_NETWORKS, full stop.
    # AIDEV-NOTE: the "*" check's exact-string comparison is pinned to uvicorn's ACTUAL
    # (undocumented, private) `_TrustedHosts.always_trust` logic, verified against the
    # installed version — not part of uvicorn's public contract. `_classify_forwarded_allow_ips`
    # independently mirrors `_TrustedHosts`'s CIDR/bare-IP parsing for the overlap check below
    # (it can't import the private class itself without depending on it directly) — both are
    # pinned by test_allowed_networks.py's "pinning private uvicorn internals" section, so a
    # future `uv lock --upgrade` that changes either fails a named test rather than silently
    # reopening either bypass. Also: this only inspects the env var uvicorn falls back to — an
    # explicit `--forwarded-allow-ips`/`Config(forwarded_allow_ips=...)` override at the
    # invocation site would bypass this guard entirely. Not reachable via this app's actual
    # startup path today (cli.py's uvicorn.run() passes neither), so documented as a known
    # limitation, not fixed here.
    if settings.auth_mode == "cloudflare_headers":
        forwarded_allow_ips = os.environ.get(
            _FORWARDED_ALLOW_IPS_ENV, _UVICORN_DEFAULT_FORWARDED_ALLOW_IPS
        ).strip()
        if forwarded_allow_ips == "*":
            raise ValueError(
                f"SCOREBOARD_AUTH_MODE=cloudflare_headers conflicts with "
                f"{_FORWARDED_ALLOW_IPS_ENV}='*' — uvicorn would trust a client-supplied "
                "X-Forwarded-For from ANY peer and overwrite request.client.host, defeating "
                "peer_in_networks() entirely. Scope FORWARDED_ALLOW_IPS to the real reverse "
                "proxy's address(es) before enabling this auth mode."
            )
        overlap = _find_forwarded_allow_ips_overlap(forwarded_allow_ips, settings.allowed_networks)
        if overlap is not None:
            trusted_entry, allowed_entry = overlap
            raise ValueError(
                f"SCOREBOARD_AUTH_MODE=cloudflare_headers conflicts with "
                f"{_FORWARDED_ALLOW_IPS_ENV}={forwarded_allow_ips!r} — its entry {trusted_entry} "
                f"overlaps allowed_networks entry {allowed_entry}. uvicorn's "
                "ProxyHeadersMiddleware would trust a client-supplied X-Forwarded-For from "
                "peers in that overlap and "
                "rewrite request.client.host before peer_in_networks() ever runs — for exactly "
                "the peers allowed_networks exists to authenticate. FORWARDED_ALLOW_IPS must be "
                "disjoint from SCOREBOARD_ALLOWED_NETWORKS, not merely non-'*'."
            )

    app = FastAPI(title="scoreboard", version="0.1.1", lifespan=_lifespan)
    app.state.settings = settings
    app.state.score_store = ScoreStore()
    app.state.baseline_store = BaselineStore()
    # FEATURE: OME-1307 (E14a) — the store behind PATCH /v1/scores/{id}.
    app.state.metadata_store = ScoreMetadataStore()

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(health.router)
    app.include_router(leaderboard.router)
    app.include_router(scores.router)
    # FEATURE: OME-1307 (E14a) — edit authors / paper_url, and read the edit history.
    app.include_router(score_metadata.router)
    _wire_clustered_submit(app, settings)
    register_portal(app, settings)
    return app


app = create_app()

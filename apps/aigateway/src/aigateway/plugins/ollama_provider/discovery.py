from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from aigateway.core.input_modalities import InputModality, normalize_input_modalities
from aigateway.core.parameter_discovery import (
    DiscoveryError,
    DiscoveryLimits,
    DiscoveryPostClient,
)
from aigateway.core.plugin_base import ModelDiscoverySource

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
POSITIVE_DISCOVERY_TTL_SECONDS = 10.0
NEGATIVE_DISCOVERY_TTL_SECONDS = 2.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CacheEntry:
    models: list[str]
    expires_at: float


_CACHE: dict[str, _CacheEntry] = {}
_IN_FLIGHT: set[str] = set()
_CACHE_CONDITION = threading.Condition()

# OME-1537: per-(host, model) ``/api/show`` answers. WHY longer than the tag TTL: a
# model's capabilities change only when that tag is re-pulled, and the listing asks
# once per installed model; a failure is retried soon so a cold host recovers.
MODALITIES_POSITIVE_TTL_SECONDS = 60.0
_MODALITIES_CACHE: dict[tuple[str, str], tuple[tuple[InputModality, ...] | None, float]] = {}
# Per-key single-flight: concurrent cold lookups of one (host, model) wait for the
# leader's answer instead of each dialing ``/api/show``.
_MODALITIES_IN_FLIGHT: set[tuple[str, str]] = set()
_MODALITIES_CONDITION = threading.Condition()
# WHY 1 MB: ``/api/show`` carries the modelfile, template, license and metadata —
# tens of KB for real models. The body is streamed and reading STOPS at the cap, so a
# hostile or broken remote host cannot force an unbounded buffer (OME-1537 review).
SHOW_MAX_BYTES = 1_000_000

# OME-1537 review (findings 1-2): the LISTING-time probes run only in the async
# ``model_discovery_source`` below, through the ``ModelCatalog`` — never in
# ``register_models()``, so ``AIGW_DISCOVERY_ENABLED=false`` (no catalog) means zero
# ``/api/show`` calls and the event loop is never blocked by a probe.
# WHY 4: a local Ollama serves ``/api/show`` from disk; four in flight finishes a
# typical install in one or two round trips without letting a remote host with
# dozens of models fan out unbounded.
OLLAMA_SHOW_CONCURRENCY = 4
# WHY 5 s: ONE deadline for the whole round, on top of each probe's own total
# timeout — a host that answers every probe just inside its budget, or dribbles
# bytes, cannot hold a cold ``/v1/models`` open for N x timeout.
OLLAMA_SHOW_DEADLINE_S = 5.0
_SHOW_SOURCE_REVISION = "ollama:api-show:modalities-v1"


def ollama_model_discovery_source(host: str) -> ModelDiscoverySource:
    """The listing source for one resolved Ollama host (OME-1537).

    # WHY host-scoped key: the snapshot is evidence about THAT host's installed
    # models; a host change must not serve the previous host's snapshot.
    # WHY ttl = the tag TTL: the snapshot IS the listing, so a newly pulled model
    # appears as fast as it did before the source existed. Re-asking is cheap —
    # recent per-model answers are reused (``MODALITIES_POSITIVE_TTL_SECONDS``).
    """
    return ModelDiscoverySource(
        key=f"ollama:{host}:api-show",
        revision=_SHOW_SOURCE_REVISION,
        ttl_s=POSITIVE_DISCOVERY_TTL_SECONDS,
        stale_ttl_s=600.0,
        failure_ttl_s=30.0,
    )


# Async per-(host, model) memo of SUCCESSFUL answers only; a failure is never
# memoized — it fails the round and the catalog keeps the last-good snapshot.
# AIDEV-NOTE: no lock — it is touched only on the event loop, and the catalog's
# single-flight refresh already serializes rounds per provider.
_SHOW_MEMO: dict[tuple[str, str], tuple[tuple[InputModality, ...] | None, float]] = {}


async def discover_ollama_show_modalities(
    host: str,
    names: list[str],
    *,
    client: DiscoveryPostClient,
    limits: DiscoveryLimits | None = None,
) -> dict[str, tuple[InputModality, ...] | None]:
    """Every installed model's modalities via bounded async ``POST /api/show``.

    INVARIANT: all-or-nothing. Any failed probe (transport fault, non-200,
    malformed body) or the round deadline raises a sanitized ``DiscoveryError``,
    so the catalog keeps serving its last-good snapshot instead of storing a
    partially text-only listing as fresh.
    """
    bounds = limits if limits is not None else DiscoveryLimits()
    gate = asyncio.Semaphore(OLLAMA_SHOW_CONCURRENCY)
    found: dict[str, tuple[InputModality, ...] | None] = {}

    async def probe(name: str) -> None:
        key = (host, name)
        memo = _SHOW_MEMO.get(key)
        if memo is not None and memo[1] > time.monotonic():
            found[name] = memo[0]
            return
        async with gate:
            response = await client.post(
                f"{host}/api/show",
                json_body={"model": name},
                timeout_s=bounds.timeout_s,
                max_bytes=SHOW_MAX_BYTES,
            )
        modalities = _show_modalities(response.status, response.body)
        _SHOW_MEMO[key] = (modalities, time.monotonic() + MODALITIES_POSITIVE_TTL_SECONDS)
        found[name] = modalities

    try:
        async with asyncio.timeout(OLLAMA_SHOW_DEADLINE_S):
            try:
                async with asyncio.TaskGroup() as group:
                    for name in names:
                        group.create_task(probe(name))
            except* Exception as failed:
                # The first failure cancels its siblings; re-raise it UNWRAPPED so the
                # catalog sees the sanitized ``DiscoveryError`` (or a test tripwire's
                # ``AssertionError``) rather than an opaque ExceptionGroup.
                raise failed.exceptions[0] from None
    except TimeoutError:
        raise DiscoveryError("timeout") from None
    return found


def _show_modalities(status: int, body: str) -> tuple[InputModality, ...] | None:
    """One ``/api/show`` answer -> modalities; a bad answer raises sanitized."""
    if status != 200:
        raise DiscoveryError("bad_status", status=status)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        # RecursionError: a pathologically nested document inside the byte cap.
        raise DiscoveryError("malformed_json") from None
    if not isinstance(payload, dict):
        raise DiscoveryError("malformed_json")
    return ollama_input_modalities(payload.get("capabilities"))


def clear_ollama_discovery_cache() -> None:
    with _CACHE_CONDITION:
        _CACHE.clear()
        _IN_FLIGHT.clear()
        _CACHE_CONDITION.notify_all()
    with _MODALITIES_CONDITION:
        _MODALITIES_CACHE.clear()
        _MODALITIES_IN_FLIGHT.clear()
        _MODALITIES_CONDITION.notify_all()
    _SHOW_MEMO.clear()


def ollama_input_modalities(capabilities: object) -> tuple[InputModality, ...] | None:
    """Ollama ``capabilities`` -> gateway modalities, or ``None`` when unknown.

    INVARIANT: only ``vision`` -> ``image`` is mapped. ``pdf`` is never reported,
    whatever Ollama says: the gateway has no working PDF path to Ollama — at this head
    LiteLLM's Ollama path silently drops file parts, and the explicit refusal lands
    with OME-1641 (PR #1447). Either way, claiming ``pdf`` would be false.
    """
    if not isinstance(capabilities, list):
        return None
    return normalize_input_modalities("image" for c in capabilities if c == "vision")


def discover_ollama_input_modalities(
    host: str,
    name: str,
    *,
    http_client_factory: Callable[[float], httpx.Client] | None = None,
    timeout_seconds: float = 2.0,
) -> tuple[InputModality, ...] | None:
    """One installed model's input modalities via sync ``POST /api/show`` (cached).

    AIDEV-NOTE: no listing path calls this since the OME-1537 review — listing-time
    probes run only in the async ``discover_ollama_show_modalities`` (catalog-gated,
    kill-switch-silenced). Kept, bounded (byte cap + total deadline), because removing
    it means deleting this PR's own tests, which the approved change set did not cover.

    ``/api/tags`` carries no capabilities, so each model is asked once per TTL.
    Every failure (unreachable, non-2xx, malformed) is ``None`` -> text-only.
    """
    key = (host, name)
    while True:
        now = time.monotonic()
        with _MODALITIES_CONDITION:
            cached = _MODALITIES_CACHE.get(key)
            if cached is not None and cached[1] > now:
                return cached[0]
            if key not in _MODALITIES_IN_FLIGHT:
                _MODALITIES_IN_FLIGHT.add(key)
                break
            _MODALITIES_CONDITION.wait()
    try:
        modalities = _fetch_ollama_input_modalities(
            host, name, http_client_factory=http_client_factory, timeout_seconds=timeout_seconds
        )
        ttl = (
            MODALITIES_POSITIVE_TTL_SECONDS
            if modalities is not None
            else NEGATIVE_DISCOVERY_TTL_SECONDS
        )
        with _MODALITIES_CONDITION:
            _MODALITIES_CACHE[key] = (modalities, time.monotonic() + ttl)
        return modalities
    finally:
        with _MODALITIES_CONDITION:
            _MODALITIES_IN_FLIGHT.discard(key)
            _MODALITIES_CONDITION.notify_all()


def _fetch_ollama_input_modalities(
    host: str,
    name: str,
    *,
    http_client_factory: Callable[[float], httpx.Client] | None,
    timeout_seconds: float,
) -> tuple[InputModality, ...] | None:
    factory = http_client_factory or (lambda timeout: httpx.Client(timeout=timeout))
    # WHY a whole-request deadline: httpx's read timeout restarts on every chunk, so
    # a host dribbling one byte at a time would never trip it (OME-1537 review).
    deadline = time.monotonic() + timeout_seconds
    try:
        with (
            factory(timeout_seconds) as client,
            client.stream("POST", f"{host}/api/show", json={"model": name}) as response,
        ):
            if response.status_code < 200 or response.status_code >= 300:
                return None
            body = _read_capped(response, SHOW_MAX_BYTES, deadline=deadline)
    except httpx.HTTPError as exc:
        logger.warning("Ollama /api/show failed for %s at %s: %s", name, host, type(exc).__name__)
        return None
    if body is None:
        logger.warning(
            "Ollama /api/show for %s at %s exceeded %d bytes or %.1f s",
            name,
            host,
            SHOW_MAX_BYTES,
            timeout_seconds,
        )
        return None
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        # RecursionError: a pathologically nested document inside the byte cap.
        return None
    if not isinstance(payload, dict):
        return None
    return ollama_input_modalities(payload.get("capabilities"))


def _read_capped(response: httpx.Response, max_bytes: int, *, deadline: float) -> bytes | None:
    """The streamed body, or ``None`` once it exceeds ``max_bytes`` or passes
    ``deadline`` (a ``time.monotonic()`` instant); reading stops either way."""
    buffer = bytearray()
    for chunk in response.iter_bytes():
        buffer.extend(chunk)
        if len(buffer) > max_bytes or time.monotonic() > deadline:
            return None
    return bytes(buffer)


def resolve_ollama_host(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    raw = env.get("AIGW_OLLAMA_HOST") or env.get("OLLAMA_API_BASE") or DEFAULT_OLLAMA_HOST
    return _normalize_ollama_host(raw, env)


def discover_ollama_models(
    host: str | None = None,
    *,
    http_client_factory: Callable[[float], httpx.Client] | None = None,
    timeout_seconds: float = 2.0,
) -> list[str]:
    resolved_host = _normalize_ollama_host(host, os.environ) if host else resolve_ollama_host()

    while True:
        now = time.monotonic()
        with _CACHE_CONDITION:
            entry = _CACHE.get(resolved_host)
            if entry is not None and entry.expires_at > now:
                return list(entry.models)
            if resolved_host not in _IN_FLIGHT:
                _IN_FLIGHT.add(resolved_host)
                break
            _CACHE_CONDITION.wait()

    try:
        models = _fetch_ollama_models(
            resolved_host,
            http_client_factory=http_client_factory,
            timeout_seconds=timeout_seconds,
        )
        ttl = POSITIVE_DISCOVERY_TTL_SECONDS if models else NEGATIVE_DISCOVERY_TTL_SECONDS
        with _CACHE_CONDITION:
            _CACHE[resolved_host] = _CacheEntry(
                models=list(models),
                expires_at=time.monotonic() + ttl,
            )
        return models
    finally:
        with _CACHE_CONDITION:
            _IN_FLIGHT.discard(resolved_host)
            _CACHE_CONDITION.notify_all()


def _normalize_ollama_host(raw: str | None, environ: Mapping[str, str]) -> str:
    host = (raw or DEFAULT_OLLAMA_HOST).strip().rstrip("/") or DEFAULT_OLLAMA_HOST
    try:
        parsed = urlparse(host)
        parsed.port
    except ValueError:
        logger.warning(
            "Invalid Ollama host %r; falling back to %s",
            raw,
            DEFAULT_OLLAMA_HOST,
        )
        return DEFAULT_OLLAMA_HOST
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        logger.warning(
            "Invalid Ollama host %r; falling back to %s",
            raw,
            DEFAULT_OLLAMA_HOST,
        )
        return DEFAULT_OLLAMA_HOST

    hostname = parsed.hostname
    if _is_loopback_hostname(hostname):
        return host

    if environ.get("AIGW_OLLAMA_ALLOW_REMOTE") == "1":
        logger.warning(
            "Using non-loopback Ollama host %s; prompts and process-owned OLLAMA_API_KEY "
            "may be sent as a bearer token",
            host,
        )
        return host

    logger.warning(
        "Non-loopback Ollama host %s requires AIGW_OLLAMA_ALLOW_REMOTE=1; falling back to %s",
        host,
        DEFAULT_OLLAMA_HOST,
    )
    return DEFAULT_OLLAMA_HOST


def _is_loopback_hostname(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _fetch_ollama_models(
    host: str,
    *,
    http_client_factory: Callable[[float], httpx.Client] | None,
    timeout_seconds: float,
) -> list[str]:
    factory = http_client_factory or (lambda timeout: httpx.Client(timeout=timeout))
    try:
        with factory(timeout_seconds) as client:
            response = client.get(f"{host}/api/tags")
    except (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.RequestError,
        httpx.InvalidURL,
    ) as exc:
        logger.warning(
            "Ollama not reachable at %s; provider loaded with no models: %s",
            host,
            exc,
        )
        return []

    if response.status_code < 200 or response.status_code >= 300:
        logger.warning(
            "Ollama not reachable at %s; provider loaded with no models: status %s",
            host,
            response.status_code,
        )
        return []

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning(
            "Ollama not reachable at %s; provider loaded with no models: malformed JSON: %s",
            host,
            exc,
        )
        return []

    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return _model_names_from_payload(models)


def _model_names_from_payload(models: list[Any]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names

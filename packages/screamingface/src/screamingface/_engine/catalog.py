"""Typed catalogue adapters at the SF Engine HTTP seam."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import NoReturn
from urllib.parse import quote

import httpx

from screamingface._benchmark_identity import benchmark_id as _benchmark_id
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine.benchmark import _engine_url
from screamingface._engine.catalog_contract import (
    _BenchmarkCatalogData,
    _BenchmarkEntry,
    _decode_benchmarks,
    _decode_model_catalog,
    _ModelCatalogData,
)
from screamingface._engine.model_parameters import _decode_model_details
from screamingface._evaluation.operators import _OperatorCatalog, decode_operator_catalog
from screamingface._ui.catalog import _BenchmarkCatalog
from screamingface.discovery import Benchmark, ModelDetails, ModelInfo
from screamingface.errors import (
    AuthenticationError,
    EngineCapabilityError,
    EngineUnavailableError,
    PlanningError,
    ProviderConnectionError,
)

_MODELS_PATH = "/v1/models"
_MODEL_PARAMETERS_PATH = "/v1/model-parameters"
_BENCHMARKS_PATH = "/v1/benchmarks"
_OPERATORS_PATH = "/v1/operators"
_MAX_AGE = re.compile(r"max-age=(\d+)")


class Models:
    """Synchronous Model catalogue bound to one Client."""

    def __init__(self, get: Callable[[str], httpx.Response], engine_url: str) -> None:
        self._get = get
        self._engine_url = engine_url

    def list(self) -> Sequence[ModelInfo]:
        return self._load().models

    def get(self, model_id: str) -> ModelDetails:
        """Fetch profile-specific details for one canonical Model id."""

        selected = _model_id(model_id)
        return _decode_model_details(
            _sync_json(
                self._get,
                self._engine_url,
                _model_parameters_path(selected),
                "Model details",
            ),
            selected,
        )

    def _load(self) -> _ModelCatalogData:
        return _decode_model_catalog(
            _sync_json(self._get, self._engine_url, _MODELS_PATH, "Model catalogue")
        )


class Benchmarks:
    """Synchronous Benchmark catalogue bound to one Client."""

    def __init__(self, get: Callable[[str], httpx.Response], engine_url: str) -> None:
        self._get = get
        self._engine_url = engine_url

    def list(self) -> Sequence[Benchmark]:
        return _BenchmarkCatalog(tuple(_benchmark(entry) for entry in self._load().entries))

    def get(self, benchmark_id: str) -> Benchmark:
        return _benchmark(_entry_of(self._load(), benchmark_id))

    def _load(self) -> _BenchmarkCatalogData:
        return _decode_benchmarks(
            _sync_json(self._get, self._engine_url, _BENCHMARKS_PATH, "Benchmark catalogue")
        )


class AsyncModels:
    """Asynchronous Model catalogue bound to one AsyncClient."""

    def __init__(
        self,
        get: Callable[[str], Awaitable[httpx.Response]],
        engine_url: str,
    ) -> None:
        self._get = get
        self._engine_url = engine_url

    async def list(self) -> Sequence[ModelInfo]:
        return (await self._load()).models

    async def get(self, model_id: str) -> ModelDetails:
        """Fetch profile-specific details for one canonical Model id."""

        selected = _model_id(model_id)
        return _decode_model_details(
            await _async_json(
                self._get,
                self._engine_url,
                _model_parameters_path(selected),
                "Model details",
            ),
            selected,
        )

    async def _load(self) -> _ModelCatalogData:
        return _decode_model_catalog(
            await _async_json(self._get, self._engine_url, _MODELS_PATH, "Model catalogue")
        )


class AsyncBenchmarks:
    """Asynchronous Benchmark catalogue bound to one AsyncClient."""

    def __init__(
        self,
        get: Callable[[str], Awaitable[httpx.Response]],
        engine_url: str,
    ) -> None:
        self._get = get
        self._engine_url = engine_url

    async def list(self) -> Sequence[Benchmark]:
        return _BenchmarkCatalog(tuple(_benchmark(entry) for entry in (await self._load()).entries))

    async def get(self, benchmark_id: str) -> Benchmark:
        return _benchmark(_entry_of(await self._load(), benchmark_id))

    async def _load(self) -> _BenchmarkCatalogData:
        return _decode_benchmarks(
            await _async_json(
                self._get,
                self._engine_url,
                _BENCHMARKS_PATH,
                "Benchmark catalogue",
            )
        )


def _benchmark(entry: _BenchmarkEntry) -> Benchmark:
    return Benchmark(
        id=entry.id,
        title=entry.title,
        description=entry.description,
        revision=entry.revision,
        case_count=entry.case_count,
        origin=entry.origin,
        interaction=entry.interaction,
        difficulty=entry.difficulty,
        inverted_grade=entry.inverted_grade,
        attempts=entry.attempts,
        provenance=entry.provenance,
        saturation=entry.saturation,
    )


def _model_parameters_path(model_id: str) -> str:
    return f"{_MODEL_PARAMETERS_PATH}?model={quote(model_id, safe='')}"


def _model_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("model_id must be a string")
    selected = value.removeprefix("/").strip()
    if not selected:
        raise ValueError("model_id must be a non-empty string")
    return selected


def _entry_of(catalog: _BenchmarkCatalogData, benchmark_id: str) -> _BenchmarkEntry:
    selected = _benchmark_id(benchmark_id)
    for entry in catalog.entries:
        if entry.id == selected:
            return entry
    raise PlanningError(
        f"Benchmark {selected!r} is not installed on this Engine",
        code="unknown_benchmark",
        permanent=True,
    )


def _sync_json(
    get: Callable[[str], httpx.Response],
    engine_url: str,
    path: str,
    label: str,
) -> object:
    try:
        response = get(path)
    except httpx.HTTPError as exc:
        _unreachable(engine_url, label, exc)
    return _response_json(response, label)


async def _async_json(
    get: Callable[[str], Awaitable[httpx.Response]],
    engine_url: str,
    path: str,
    label: str,
) -> object:
    try:
        response = await get(path)
    except httpx.HTTPError as exc:
        _unreachable(engine_url, label, exc)
    return _response_json(response, label)


def _response_json(response: httpx.Response, label: str) -> object:
    if label == "Model details" and not response.is_success:
        _raise_model_details_error(response)
    if response.status_code in {401, 403}:
        raise AuthenticationError(
            f"SF Engine authentication is required for {label}",
            code="authentication_required",
            status=response.status_code,
            permanent=True,
        )
    if not response.is_success:
        raise PlanningError(
            f"Could not load the SF Engine {label}: HTTP {response.status_code}",
            code="engine_contract_error",
            status=response.status_code,
            permanent=response.status_code < 500,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise PlanningError(
            f"SF Engine {label} must be JSON",
            code="invalid_catalogue",
            permanent=True,
        ) from exc


# OME-878: refusal codes the Engine relays from the gateway's dynamic-admission
# decision. Each is pre-spend and names which knob to turn; only a catalog outage
# or a still-connecting profile is worth retrying.
_ADMISSION_REFUSAL_CODES = frozenset(
    {
        "model_not_on_openrouter",
        "provider_disabled",
        "provider_not_credentialed",
        "dynamic_admission_disabled",
        "dynamic_admission_unsupported",
        "openrouter_catalog_unavailable",
        "invalid_model_id",
        "unknown_provider",
        "model_not_admitted",
        "admission_capacity_reached",
        # Relayed profile states (review F6): the profile EXISTS but needs its
        # connection finished or redone — these carry no profile `name` field on
        # this wire, so the profile-shaped branch above cannot decode them.
        "auth_required",
        "profile_pending_auth",
    }
)

_RETRYABLE_ADMISSION_CODES = frozenset({"openrouter_catalog_unavailable", "profile_pending_auth"})


def _raise_model_details_error(response: httpx.Response) -> None:
    """Preserve AI Gateway's profile/model diagnostic relayed by the Engine."""

    try:
        root = response.json()
    except ValueError:
        return
    if not isinstance(root, Mapping):
        return
    if not isinstance(root.get("detail"), Mapping):
        # WHY plain return (review F8): a string-detail 404 here could as easily be
        # a reverse proxy or a route-less server as the Engine's own not-installed
        # answer — so the shared path keeps diagnosing it as a deployment problem
        # (`engine_contract_error`). Only the availability PROBE, which knows it
        # asked about a listing-missing model, rewrites that into today's
        # "not available on this Engine" (see `_evaluation/runner.py`).
        return
    detail = root["detail"]
    code = detail.get("code")
    provider = detail.get("provider")
    profile = detail.get("name")
    if (
        code in {"profile_not_found", "profile_pending_auth", "auth_required"}
        and isinstance(provider, str)
        and isinstance(profile, str)
    ):
        display = provider.replace("-", " ").title()
        messages = {
            "profile_not_found": f"{display} profile {profile!r} is not connected",
            "profile_pending_auth": f"{display} profile {profile!r} is still connecting",
            "auth_required": f"{display} profile {profile!r} must be reconnected",
        }
        actions = {
            "profile_not_found": "connect",
            "profile_pending_auth": "finish connecting",
            "auth_required": "reconnect",
        }
        raise ProviderConnectionError(
            messages[code],
            provider=provider,
            code=code,
            status=response.status_code,
            permanent=code != "profile_pending_auth",
            details=dict(detail),
            hint=f"Open `sf.connect()` and {actions[code]} {display}, then retry.",
        )
    if code == "model_not_found" and isinstance(detail.get("model"), str):
        model = detail["model"]
        raise PlanningError(
            f"Model {model!r} is not available from the selected provider profile",
            code="model_not_found",
            status=response.status_code,
            permanent=True,
            details=dict(detail),
        )
    if code in _ADMISSION_REFUSAL_CODES and isinstance(detail.get("message"), str):
        # The gateway already wrote the human sentence ("connect an OpenRouter
        # API key first", "check the id at openrouter.ai/models") — relay it
        # verbatim rather than paraphrasing it into something vaguer.
        raise PlanningError(
            detail["message"],
            code=str(code),
            status=response.status_code,
            permanent=code not in _RETRYABLE_ADMISSION_CODES,
            details=dict(detail),
        )


@dataclass(frozen=True, slots=True)
class _CachedOperators:
    catalog: _OperatorCatalog
    etag: str | None
    fresh_until: float


class OperatorCatalogResource:
    """Fetch and cache one Client's operator catalog: fresh within max-age, then If-None-Match.

    INVARIANT: no stale fallback (``must-revalidate``) — a transport error is always
    ``EngineUnavailableError`` even when an old copy is cached, and an unpinned name is
    never submitted.
    """

    def __init__(self, http: httpx.Client, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._http = http
        self._clock = clock
        self._cached: _CachedOperators | None = None

    def load(self) -> _OperatorCatalog:
        now = self._clock()
        cached = self._cached
        if cached is not None and now < cached.fresh_until:
            return cached.catalog
        try:
            response = self._http.get(
                _OPERATORS_PATH,
                headers=_conditional(cached),
                extensions={_REPLAY_SAFE: True},
            )
        except httpx.HTTPError as exc:
            _unreachable(_engine_url(self._http), "operator catalog", exc)
        self._cached = _next_cache(response, cached, now)
        return self._cached.catalog


class AsyncOperatorCatalogResource:
    """Asynchronous twin of ``OperatorCatalogResource`` over an ``httpx.AsyncClient``."""

    def __init__(
        self, http: httpx.AsyncClient, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._http = http
        self._clock = clock
        self._cached: _CachedOperators | None = None

    async def load(self) -> _OperatorCatalog:
        now = self._clock()
        cached = self._cached
        if cached is not None and now < cached.fresh_until:
            return cached.catalog
        try:
            response = await self._http.get(
                _OPERATORS_PATH,
                headers=_conditional(cached),
                extensions={_REPLAY_SAFE: True},
            )
        except httpx.HTTPError as exc:
            _unreachable(_engine_url(self._http), "operator catalog", exc)
        self._cached = _next_cache(response, cached, now)
        return self._cached.catalog


def _conditional(cached: _CachedOperators | None) -> dict[str, str]:
    return {} if cached is None or cached.etag is None else {"If-None-Match": cached.etag}


def _max_age(response: httpx.Response) -> int:
    match = _MAX_AGE.search(response.headers.get("Cache-Control", ""))
    return 0 if match is None else int(match.group(1))


def _next_cache(
    response: httpx.Response, cached: _CachedOperators | None, now: float
) -> _CachedOperators:
    fresh_until = now + _max_age(response)
    etag = response.headers.get("ETag")
    if response.status_code == 304:
        if cached is None:
            raise PlanningError(
                "SF Engine answered 304 for an operator catalog it never sent",
                code="engine_contract_error",
                status=304,
                permanent=True,
            )
        return _CachedOperators(cached.catalog, etag or cached.etag, fresh_until)
    if response.status_code == 404:
        raise EngineCapabilityError(
            "this SF Engine does not support reducers",
            status=404,
            permanent=True,
            details={"path": _OPERATORS_PATH},
            hint=(
                "Use an SF Engine that serves GET /v1/operators, or close the block with "
                "sf.Synthesize."
            ),
        )
    catalog = decode_operator_catalog(_response_json(response, "operator catalog"))
    return _CachedOperators(catalog, etag, fresh_until)


def _unreachable(engine_url: str, label: str, cause: Exception) -> NoReturn:
    raise EngineUnavailableError(
        f"Could not reach the SF Engine {label}",
        engine_url=engine_url,
    ) from cause


__all__ = [
    "AsyncBenchmarks",
    "AsyncModels",
    "AsyncOperatorCatalogResource",
    "Benchmarks",
    "Models",
    "OperatorCatalogResource",
]

"""Typed catalogue adapters at the SF Engine HTTP seam."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import NoReturn
from urllib.parse import quote

import httpx

from screamingface._benchmark_identity import benchmark_id as _benchmark_id
from screamingface._engine.catalog_contract import (
    _BenchmarkCatalogData,
    _BenchmarkEntry,
    _decode_benchmarks,
    _decode_model_catalog,
    _ModelCatalogData,
)
from screamingface._engine.model_parameters import _decode_model_details
from screamingface._ui.catalog import _BenchmarkCatalog
from screamingface.discovery import Benchmark, ModelDetails, ModelInfo
from screamingface.errors import (
    AuthenticationError,
    EngineUnavailableError,
    PlanningError,
    ProviderConnectionError,
)

_MODELS_PATH = "/v1/models"
_MODEL_PARAMETERS_PATH = "/v1/model-parameters"
_BENCHMARKS_PATH = "/v1/benchmarks"


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


def _unreachable(engine_url: str, label: str, cause: Exception) -> NoReturn:
    raise EngineUnavailableError(
        f"Could not reach the SF Engine {label}",
        engine_url=engine_url,
    ) from cause


__all__ = ["AsyncBenchmarks", "AsyncModels", "Benchmarks", "Models"]

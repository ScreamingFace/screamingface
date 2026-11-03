"""HTTP adapter for the Engine-owned Benchmark expression resource."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from screamingface._benchmark_identity import benchmark_id as _flat_benchmark_id
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._evaluation.benchmark import (
    _BenchmarkResource,
    _decode_benchmark_resource,
)
from screamingface.errors import EngineUnavailableError, PlanningError


class BenchmarkResources:
    """Fetch the one resource needed to compile every Candidate locally."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def load(
        self,
        benchmark: str,
        limit: int | None,
        cases: tuple[int, ...] | None = None,
    ) -> _BenchmarkResource:
        benchmark_id = _benchmark_id(benchmark)
        try:
            response = (
                self._http.get(
                    _path(benchmark_id),
                    params=_query(limit),
                    extensions={_REPLAY_SAFE: True},
                )
                if cases is None
                else self._http.post(
                    f"{_path(benchmark_id)}/selection",
                    json={"cases": list(cases)},
                    # WHY replay-safe despite the POST: the route only reads the catalog and
                    # builds a recipe; it starts no Run and spends nothing.
                    extensions={_REPLAY_SAFE: True},
                )
            )
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(
                "Could not reach the SF Engine Benchmark catalog",
                engine_url=_engine_url(self._http),
            ) from exc
        _success(response, selecting=cases is not None)
        return _decode_benchmark_resource(
            _json(response),
            requested_id=benchmark,
            requested_limit=limit,
            requested_cases=cases,
        )


class AsyncBenchmarkResources:
    """Asynchronous adapter for the same one-fetch resource boundary."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def load(
        self,
        benchmark: str,
        limit: int | None,
        cases: tuple[int, ...] | None = None,
    ) -> _BenchmarkResource:
        benchmark_id = _benchmark_id(benchmark)
        try:
            response = (
                await self._http.get(
                    _path(benchmark_id),
                    params=_query(limit),
                    extensions={_REPLAY_SAFE: True},
                )
                if cases is None
                else await self._http.post(
                    f"{_path(benchmark_id)}/selection",
                    json={"cases": list(cases)},
                    # WHY replay-safe despite the POST: the route only reads the catalog and
                    # builds a recipe; it starts no Run and spends nothing.
                    extensions={_REPLAY_SAFE: True},
                )
            )
        except httpx.HTTPError as exc:
            raise EngineUnavailableError(
                "Could not reach the SF Engine Benchmark catalog",
                engine_url=_engine_url(self._http),
            ) from exc
        _success(response, selecting=cases is not None)
        return _decode_benchmark_resource(
            _json(response),
            requested_id=benchmark,
            requested_limit=limit,
            requested_cases=cases,
        )


def _path(benchmark_id: str) -> str:
    """The catalog path of one Benchmark; `/selection` below it takes a Case-id list (OME-1739).

    WHY a POST body for the list: a 40-id list stays readable and out of access logs, and the
    selection route answers with a resource that echoes the ids it selected.
    """

    return f"/v1/benchmarks/{quote(benchmark_id, safe='')}"


def _query(limit: int | None) -> dict[str, int]:
    params: dict[str, int] = {}
    if limit is not None:
        params["limit"] = limit
    return params


def _benchmark_id(value: str) -> str:
    try:
        return _flat_benchmark_id(value)
    except (TypeError, ValueError) as exc:
        raise PlanningError(
            "Benchmark id must be one flat lowercase identifier",
            code="invalid_benchmark_selection",
            permanent=True,
        ) from exc


def _json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise PlanningError(
            "SF Engine Benchmark resource must be JSON",
            code="engine_contract_error",
            permanent=True,
        ) from exc


def _success(response: httpx.Response, *, selecting: bool = False) -> None:
    if response.is_success:
        return
    if selecting and response.status_code == 404 and not _unknown_benchmark(response):
        # WHY (review on #1653): an Engine older than OME-1739 has no `/selection` route, so its
        # router answers a plain 404. Reading that as "not installed" sends the researcher to
        # the Benchmark id when the fix is a newer Engine.
        raise PlanningError(
            "This SF Engine cannot run a fixed list of Case ids (it has no Case selection "
            "route, so it is older than OME-1739); upgrade the Engine, or run with limit=",
            code="engine_cannot_select_cases",
            status=404,
            permanent=True,
        )
    detail = _problem_detail(response)
    if response.status_code == 404:
        message = "The requested Benchmark is not installed on this Engine"
        code = "unknown_benchmark"
    elif response.status_code == 422:
        message = "The Benchmark case selection is invalid"
        code = "invalid_benchmark_selection"
    else:
        message = "Could not fetch the Benchmark expression"
        code = "benchmark_fetch_failed"
    if detail:
        message = f"{message}: {detail}"
    raise PlanningError(
        message,
        code=code,
        status=response.status_code,
        permanent=response.status_code < 500,
    )


def _unknown_benchmark(response: httpx.Response) -> bool:
    """Whether a 404 is the Engine's own "Unknown benchmark" problem, not a missing route."""

    try:
        payload: object = response.json()
    except ValueError:
        return False
    # WHY the title: the Engine's catalog routes answer an unknown id with an RFC 9457 problem
    # titled "Unknown benchmark"; a route the Engine lacks gets the router's bare 404 instead.
    return isinstance(payload, dict) and payload.get("title") == "Unknown benchmark"


def _problem_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    return detail if isinstance(detail, str) and detail.strip() else None


def _engine_url(http: httpx.Client | httpx.AsyncClient) -> str:
    return str(http.base_url).rstrip("/")


__all__: list[str] = []

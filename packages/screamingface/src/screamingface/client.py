"""Synchronous and asynchronous ScreamingFace clients."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, overload

from screamingface._client_connections import (
    _AuthListeners,
    _connect_async,
    _connect_sync,
    _engine_origin,
    _require_secure_connection_origin,
    _scoreboard_origin,
)
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine.identity import engine_headers

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    import httpx

    from screamingface._core.ports import AsyncRunTransport, SyncRunTransport
    from screamingface._engine.catalog import AsyncBenchmarks, AsyncModels, Benchmarks, Models
    from screamingface._engine.connections import AsyncConnections, Connections
    from screamingface._scoreboard.leaderboards import AsyncLeaderboards, Leaderboards
    from screamingface._ui.connections import ConnectionPanel
    from screamingface.connections import AsyncOAuthFlow, Connection, OAuthFlow
    from screamingface.events import Event
    from screamingface.recipe import Recipe
from screamingface._evaluation.model import _answer_seed_value
from screamingface.report import Report

DEFAULT_ENGINE_URL = "https://fusion.screamingface.ai"
DEFAULT_SCOREBOARD_URL = "https://leaderboard.screamingface.ai"


class Client:
    """A reusable synchronous Client configured for one SF Engine origin."""

    def __init__(
        self,
        *,
        engine_url: str = DEFAULT_ENGINE_URL,
        scoreboard_url: str = DEFAULT_SCOREBOARD_URL,
        http_transport: httpx.BaseTransport | None = None,
        scoreboard_transport: httpx.BaseTransport | None = None,
        run_transport: SyncRunTransport | None = None,
        save_results: bool = True,
    ) -> None:
        import httpx

        from screamingface._access.auth import (
            _AccessTokenStore,
            _client_caller_auth,
            _seed_access_tokens,
        )
        from screamingface._engine.benchmark import BenchmarkResources
        from screamingface._engine.catalog import Benchmarks, Models, OperatorCatalogResource
        from screamingface._engine.connections import Connections
        from screamingface._engine.transport import Url4CloudTransport
        from screamingface._scoreboard.leaderboards import Leaderboards

        self._engine_url = _engine_origin(engine_url)
        self._scoreboard_url = _scoreboard_origin(scoreboard_url)
        self._closed = False
        self._auth_listeners = _AuthListeners()
        self._access_tokens = _AccessTokenStore()
        _seed_access_tokens(
            self._access_tokens, os.environ, monotonic_now=time.monotonic(), wall_now=time.time()
        )
        self._engine_auth = _client_caller_auth(
            self._engine_url,
            token_store=self._access_tokens,
            discovery_error=_engine_access_discovery_error,
        )
        self._scoreboard_auth = _client_caller_auth(
            self._scoreboard_url,
            token_store=self._access_tokens,
        )
        self._http = httpx.Client(
            base_url=self._engine_url,
            headers=engine_headers(),
            timeout=30.0,
            auth=self._engine_auth,
            transport=http_transport,
        )
        self._scoreboard_http = httpx.Client(
            base_url=self._scoreboard_url,
            timeout=30.0,
            auth=self._scoreboard_auth,
            transport=scoreboard_transport,
        )
        self._transport: SyncRunTransport = (
            run_transport
            if run_transport is not None
            else Url4CloudTransport(self._engine_url, self._engine_auth, save_results=save_results)
        )
        self.models: Models = Models(self._http_get, self._engine_url)
        self.benchmarks: Benchmarks = Benchmarks(self._http_get, self._engine_url)
        self._benchmark_resources = BenchmarkResources(self._http)
        self._operator_catalog = OperatorCatalogResource(self._http)
        self.connections: Connections = Connections(self._http_request, self._engine_url)
        self.leaderboards: Leaderboards = Leaderboards(
            self._scoreboard_request,
            self._scoreboard_url,
        )

    @property
    def engine_url(self) -> str:
        return self._engine_url

    @property
    def scoreboard_url(self) -> str:
        return self._scoreboard_url

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def authenticated(self) -> bool:
        """Whether this process currently holds hosted caller credentials."""

        return self._engine_auth.authenticated

    @property
    def _auth(self) -> object:
        """Compatibility alias for older internal integrations."""

        return self._engine_auth

    @property
    def authenticating(self) -> bool:
        """Whether a hosted caller login is currently waiting for completion."""

        return self._engine_auth.authenticating

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import client_card_html

        return client_card_html(self)

    def login(self, *, timeout: float = 300.0) -> None:
        """Authenticate through the Engine's Cloudflare Access browser flow."""

        self._require_open()
        try:
            self._engine_auth.login(timeout=timeout)
        finally:
            self._auth_listeners.notify()

    def _cancel_login(self) -> None:
        self._require_open()
        self._engine_auth.cancel_login()
        self._auth_listeners.notify()

    def _subscribe_auth(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._require_open()
        return self._auth_listeners.subscribe(callback)

    def _subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]:
        # WHY: a notebook UI renders the Access authorization URL as a link; the built-in
        # presenter only writes it to stdout, which a widget callback on a worker thread
        # cannot surface (OME-930).
        self._require_open()
        return self._engine_auth.subscribe_authorization(presenter)

    def _access_required(self) -> bool:
        self._require_open()
        return self._engine_auth.access_required()

    def logout(self) -> None:
        """Forget caller credentials and start Cloudflare Access browser logout."""

        self._require_open()
        try:
            self._engine_auth.logout()
        finally:
            try:
                self._scoreboard_auth.logout()
            finally:
                self._access_tokens.clear()
                self._auth_listeners.notify()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._transport.close()
        finally:
            try:
                self._http.close()
            finally:
                try:
                    self._scoreboard_http.close()
                finally:
                    try:
                        self._scoreboard_auth.close()
                    finally:
                        try:
                            self._engine_auth.close()
                        finally:
                            self._access_tokens.clear()
                            self._closed = True

    @overload
    def evaluate(
        self,
        candidates: str,
        *,
        benchmark: None = None,
        limit: None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = True,
    ) -> Report: ...

    @overload
    def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe],
        *,
        benchmark: str,
        limit: int | None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = True,
    ) -> Report: ...

    @overload
    def evaluate(
        self,
        *,
        pinned_cache: str,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        answer_seed: int | None = None,
        record_reproduction: bool = True,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
    ) -> Report: ...

    @overload
    def evaluate(
        self,
        *,
        score_id: UUID | str,
        pinned_cache: str | None = None,
        url4: str | None = None,
        answer_seed: int | None = None,
        record_reproduction: bool = True,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
    ) -> Report: ...

    def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe] | str | None = None,
        *,
        benchmark: str | None = None,
        limit: int | None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool | None = None,
        pinned_cache: str | None = None,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        record_reproduction: bool = True,
    ) -> Report:
        """Evaluate Recipes, replay a complete URL4, or replay a published run from a pinned cache.

        `pinned_cache=` (or `score_id=`, for a private score you submitted) replays a published
        run at $0 from the answers it captured and judges it against the published score:
        `CandidateResult.reproduction`. An exact replay is recorded on the Scoreboard unless
        `record_reproduction=False`. A replay that cannot start raises `sf.ReproductionError`.

        `capture` is on by default: the Engine stores every model and web-tool result of each run
        in a pinned cache (`CandidateResult.pinned_cache`), so the score can be reproduced later.
        `capture=False` turns it off. An Engine that did not capture a run is reported with an
        `EvaluationWarning`.
        """

        from screamingface._evaluation.runner import evaluate_sync
        from screamingface._evaluation.url4 import evaluate_url4_sync

        self._require_open()
        if pinned_cache is not None or score_id is not None:
            return self._evaluate_replay(
                candidates=candidates,
                benchmark=benchmark,
                limit=limit,
                capture=capture,
                pinned_cache=pinned_cache,
                score_id=score_id,
                url4=url4,
                answer_seed=answer_seed,
                record_reproduction=record_reproduction,
                on_event=on_event,
                progress=progress,
            )
        candidates = _evaluation_candidates(candidates, url4, record_reproduction)
        capture = True if capture is None else capture
        # FEATURE (OME-1193): validate the declared sitting at the door — a bad seed must
        # fail before any token is minted or run scheduled.
        selected_seed = _answer_seed_value(answer_seed)
        if isinstance(candidates, str):
            _raw_url4_options(benchmark, limit)
            return evaluate_url4_sync(
                self._transport,
                candidates,
                on_event,
                progress,
                answer_seed=selected_seed,
                capture=capture,
                load_operators=self._operator_catalog.load,
            )
        if benchmark is None:
            raise TypeError("benchmark is required when evaluating Recipes")
        return evaluate_sync(
            self._benchmark_resources.load,
            self._transport,
            self.models._load,
            self.models.get,
            candidates,
            benchmark,
            limit,
            on_event,
            progress,
            answer_seed=selected_seed,
            capture=capture,
            load_operators=self._operator_catalog.load,
        )

    def _evaluate_replay(
        self,
        *,
        candidates: object,
        benchmark: str | None,
        limit: int | None,
        capture: bool | None,
        pinned_cache: str | None,
        score_id: UUID | str | None,
        url4: str | None,
        answer_seed: int | None,
        record_reproduction: bool,
        on_event: Callable[[Event], None] | None,
        progress: bool | None,
    ) -> Report:
        from screamingface._replay import replay_sync

        self._require_open()
        _replay_options(candidates, benchmark, limit, capture)
        return replay_sync(
            self,
            pinned_cache=pinned_cache,
            score_id=score_id,
            url4=url4,
            answer_seed=answer_seed,
            record_reproduction=record_reproduction,
            on_event=on_event,
            progress=progress,
        )

    @overload
    def connect(
        self,
        provider: None = None,
        *,
        api_key: None = None,
        method: None = None,
    ) -> ConnectionPanel: ...

    @overload
    def connect(
        self,
        provider: str,
        *,
        api_key: str,
        method: Literal["api_key"] | None = None,
    ) -> Connection: ...

    @overload
    def connect(
        self,
        provider: str,
        *,
        api_key: None = None,
        method: Literal["oauth"],
    ) -> OAuthFlow: ...

    def connect(
        self,
        provider: str | None = None,
        *,
        api_key: str | None = None,
        method: Literal["api_key", "oauth"] | None = None,
    ) -> Connection | ConnectionPanel | OAuthFlow:
        """Open the panel or connect one provider using API-key or OAuth auth."""

        self._require_open()
        if provider is None:
            if api_key is not None or method is not None:
                raise TypeError("provider is required when api_key or method is supplied")
            from screamingface._ui.connections import ConnectionPanel

            return ConnectionPanel(self)
        _require_secure_connection_origin(self._engine_url)
        return _connect_sync(self.connections, provider, api_key, method)

    def disconnect(self, provider: str) -> Connection:
        """Disconnect one provider; repeated calls remain harmless."""

        self._require_open()
        return self.connections.disconnect(provider)

    def __enter__(self) -> Client:
        self._require_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("ScreamingFace Client is closed")

    def _http_get(self, path: str) -> httpx.Response:
        self._require_open()
        return self._http.get(path, extensions={_REPLAY_SAFE: True})

    def _http_request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
    ) -> httpx.Response:
        self._require_open()
        return self._http.request(method, path, json=json, extensions={_REPLAY_SAFE: True})

    def _scoreboard_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        replay_safe: bool = False,
    ) -> httpx.Response:
        self._require_open()
        return self._scoreboard_http.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
            extensions={_REPLAY_SAFE: replay_safe},
        )


class AsyncClient:
    """An asynchronous Client with the same domain interface and result types."""

    def __init__(
        self,
        *,
        engine_url: str = DEFAULT_ENGINE_URL,
        scoreboard_url: str = DEFAULT_SCOREBOARD_URL,
        http_transport: httpx.AsyncBaseTransport | None = None,
        scoreboard_transport: httpx.AsyncBaseTransport | None = None,
        run_transport: AsyncRunTransport | None = None,
        save_results: bool = True,
    ) -> None:
        import httpx

        from screamingface._access.auth import (
            _AccessTokenStore,
            _client_caller_auth,
            _seed_access_tokens,
        )
        from screamingface._engine.benchmark import AsyncBenchmarkResources
        from screamingface._engine.catalog import (
            AsyncBenchmarks,
            AsyncModels,
            AsyncOperatorCatalogResource,
        )
        from screamingface._engine.connections import AsyncConnections
        from screamingface._engine.transport import AsyncUrl4CloudTransport
        from screamingface._scoreboard.leaderboards import AsyncLeaderboards

        self._engine_url = _engine_origin(engine_url)
        self._scoreboard_url = _scoreboard_origin(scoreboard_url)
        self._closed = False
        self._auth_listeners = _AuthListeners()
        self._access_tokens = _AccessTokenStore()
        _seed_access_tokens(
            self._access_tokens, os.environ, monotonic_now=time.monotonic(), wall_now=time.time()
        )
        self._engine_auth = _client_caller_auth(
            self._engine_url,
            token_store=self._access_tokens,
            discovery_error=_engine_access_discovery_error,
        )
        self._scoreboard_auth = _client_caller_auth(
            self._scoreboard_url,
            token_store=self._access_tokens,
        )
        self._http = httpx.AsyncClient(
            base_url=self._engine_url,
            headers=engine_headers(),
            timeout=30.0,
            auth=self._engine_auth,
            transport=http_transport,
        )
        self._scoreboard_http = httpx.AsyncClient(
            base_url=self._scoreboard_url,
            timeout=30.0,
            auth=self._scoreboard_auth,
            transport=scoreboard_transport,
        )
        self._transport: AsyncRunTransport = (
            run_transport
            if run_transport is not None
            else AsyncUrl4CloudTransport(
                self._engine_url, self._engine_auth, save_results=save_results
            )
        )
        self.models: AsyncModels = AsyncModels(self._http_get, self._engine_url)
        self.benchmarks: AsyncBenchmarks = AsyncBenchmarks(self._http_get, self._engine_url)
        self._benchmark_resources = AsyncBenchmarkResources(self._http)
        self._operator_catalog = AsyncOperatorCatalogResource(self._http)
        self.connections: AsyncConnections = AsyncConnections(self._http_request, self._engine_url)
        self.leaderboards: AsyncLeaderboards = AsyncLeaderboards(
            self._scoreboard_request,
            self._scoreboard_url,
        )

    @property
    def engine_url(self) -> str:
        return self._engine_url

    @property
    def scoreboard_url(self) -> str:
        return self._scoreboard_url

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def authenticated(self) -> bool:
        """Whether this process currently holds hosted caller credentials."""

        return self._engine_auth.authenticated

    @property
    def _auth(self) -> object:
        """Compatibility alias for older internal integrations."""

        return self._engine_auth

    @property
    def authenticating(self) -> bool:
        """Whether a hosted caller login is currently waiting for completion."""

        return self._engine_auth.authenticating

    def _repr_html_(self) -> str:
        from screamingface._ui.cards import client_card_html

        return client_card_html(self)

    async def login(self, *, timeout: float = 300.0) -> None:
        """Authenticate through the Engine's Cloudflare Access browser flow."""

        self._require_open()
        try:
            await self._engine_auth.login_async(timeout=timeout)
        finally:
            self._auth_listeners.notify()

    def _cancel_login(self) -> None:
        self._require_open()
        self._engine_auth.cancel_login()
        self._auth_listeners.notify()

    def _subscribe_auth(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._require_open()
        return self._auth_listeners.subscribe(callback)

    def _subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]:
        # WHY: a notebook UI renders the Access authorization URL as a link; the built-in
        # presenter only writes it to stdout, which a widget callback on a worker thread
        # cannot surface (OME-930).
        self._require_open()
        return self._engine_auth.subscribe_authorization(presenter)

    async def _access_required(self) -> bool:
        self._require_open()
        return await asyncio.to_thread(self._engine_auth.access_required)

    async def logout(self) -> None:
        """Forget caller credentials and start Cloudflare Access browser logout."""

        self._require_open()
        try:
            await self._engine_auth.logout_async()
        finally:
            try:
                await self._scoreboard_auth.logout_async()
            finally:
                self._access_tokens.clear()
                self._auth_listeners.notify()

    async def aclose(self) -> None:
        if self._closed:
            return
        try:
            await self._transport.close()
        finally:
            try:
                await self._http.aclose()
            finally:
                try:
                    await self._scoreboard_http.aclose()
                finally:
                    try:
                        await asyncio.to_thread(self._scoreboard_auth.close)
                    finally:
                        try:
                            await asyncio.to_thread(self._engine_auth.close)
                        finally:
                            self._access_tokens.clear()
                            self._closed = True

    @overload
    async def evaluate(
        self,
        candidates: str,
        *,
        benchmark: None = None,
        limit: None = None,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = True,
    ) -> Report: ...

    @overload
    async def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe],
        *,
        benchmark: str,
        limit: int | None = None,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = True,
    ) -> Report: ...

    @overload
    async def evaluate(
        self,
        *,
        pinned_cache: str,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        answer_seed: int | None = None,
        record_reproduction: bool = True,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
    ) -> Report: ...

    @overload
    async def evaluate(
        self,
        *,
        score_id: UUID | str,
        pinned_cache: str | None = None,
        url4: str | None = None,
        answer_seed: int | None = None,
        record_reproduction: bool = True,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
    ) -> Report: ...

    async def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe] | str | None = None,
        *,
        benchmark: str | None = None,
        limit: int | None = None,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool | None = None,
        pinned_cache: str | None = None,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        record_reproduction: bool = True,
    ) -> Report:
        """Asynchronously evaluate Recipes, replay a complete URL4, or replay a pinned cache.

        `capture` is on by default: the Engine stores every model and web-tool result of each run
        in a pinned cache (`CandidateResult.pinned_cache`), so the score can be reproduced later.
        `capture=False` turns it off. An Engine that did not capture a run is reported with an
        `EvaluationWarning`.
        """

        from screamingface._evaluation.runner import evaluate_async
        from screamingface._evaluation.url4 import evaluate_url4_async

        self._require_open()
        if pinned_cache is not None or score_id is not None:
            from screamingface._replay import replay_async

            _replay_options(candidates, benchmark, limit, capture)
            return await replay_async(
                self,
                pinned_cache=pinned_cache,
                score_id=score_id,
                url4=url4,
                answer_seed=answer_seed,
                record_reproduction=record_reproduction,
                on_event=on_event,
                progress=progress,
            )
        candidates = _evaluation_candidates(candidates, url4, record_reproduction)
        capture = True if capture is None else capture
        # FEATURE (OME-1193): see the sync twin — validate at the door.
        selected_seed = _answer_seed_value(answer_seed)
        if isinstance(candidates, str):
            _raw_url4_options(benchmark, limit)
            return await evaluate_url4_async(
                self._transport,
                candidates,
                on_event,
                progress,
                answer_seed=selected_seed,
                capture=capture,
                load_operators=self._operator_catalog.load,
            )
        if benchmark is None:
            raise TypeError("benchmark is required when evaluating Recipes")
        return await evaluate_async(
            self._benchmark_resources.load,
            self._transport,
            self.models._load,
            self.models.get,
            candidates,
            benchmark,
            limit,
            on_event,
            progress,
            answer_seed=selected_seed,
            capture=capture,
            load_operators=self._operator_catalog.load,
        )

    @overload
    async def connect(
        self,
        provider: str,
        *,
        api_key: str,
        method: Literal["api_key"] | None = None,
    ) -> Connection: ...

    @overload
    async def connect(
        self,
        provider: str,
        *,
        api_key: None = None,
        method: Literal["oauth"],
    ) -> AsyncOAuthFlow: ...

    async def connect(
        self,
        provider: str,
        *,
        api_key: str | None = None,
        method: Literal["api_key", "oauth"] | None = None,
    ) -> Connection | AsyncOAuthFlow:
        """Connect one provider using API-key or OAuth authentication."""

        self._require_open()
        _require_secure_connection_origin(self._engine_url)
        return await _connect_async(self.connections, provider, api_key, method)

    async def disconnect(self, provider: str) -> Connection:
        """Disconnect one provider through this AsyncClient."""

        self._require_open()
        return await self.connections.disconnect(provider)

    async def __aenter__(self) -> AsyncClient:
        self._require_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("ScreamingFace AsyncClient is closed")

    async def _http_get(self, path: str) -> httpx.Response:
        self._require_open()
        return await self._http.get(path, extensions={_REPLAY_SAFE: True})

    async def _http_request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
    ) -> httpx.Response:
        self._require_open()
        return await self._http.request(method, path, json=json, extensions={_REPLAY_SAFE: True})

    async def _scoreboard_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        replay_safe: bool = False,
    ) -> httpx.Response:
        self._require_open()
        return await self._scoreboard_http.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
            extensions={_REPLAY_SAFE: replay_safe},
        )


def _replay_options(
    candidates: object, benchmark: str | None, limit: int | None, capture: bool | None
) -> None:
    """A replay is one complete published run (spec §1): nothing else selects what runs."""

    if candidates is not None:
        raise TypeError("candidates must not be passed with pinned_cache= or score_id=")
    if benchmark is not None:
        raise TypeError("benchmark must not be passed with pinned_cache= or score_id=")
    if limit is not None:
        raise TypeError("limit must not be passed with pinned_cache= or score_id=")
    # S6: a replay reads answers and records none; only an explicit request to capture is wrong.
    if capture:
        raise TypeError("capture=True cannot be combined with a replay; a replay captures nothing")


def _evaluation_candidates(
    candidates: Recipe | Sequence[Recipe] | str | None, url4: str | None, record: bool
) -> Recipe | Sequence[Recipe] | str:
    if url4 is not None or record is not True:
        raise TypeError("url4= and record_reproduction= apply only with pinned_cache= or score_id=")
    if candidates is None:
        raise TypeError(
            "evaluate needs candidates, or pinned_cache= / score_id= to replay a published run"
        )
    return candidates


def _raw_url4_options(benchmark: str | None, limit: int | None) -> None:
    if benchmark is not None:
        raise TypeError("benchmark must not be passed when evaluating a complete URL4")
    if limit is not None:
        raise TypeError("limit must not be passed when evaluating a complete URL4")


def _engine_access_discovery_error(origin: str) -> BaseException:
    from screamingface.errors import EngineUnavailableError

    return EngineUnavailableError(
        "Could not reach the SF Engine to discover Cloudflare Access authentication",
        engine_url=origin,
    )


__all__ = ["AsyncClient", "Client", "DEFAULT_ENGINE_URL", "DEFAULT_SCOREBOARD_URL"]

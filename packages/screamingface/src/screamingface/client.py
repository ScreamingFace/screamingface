"""Synchronous and asynchronous ScreamingFace clients."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping, Sequence
from datetime import timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, cast, overload

from screamingface._analytics.tracking import tracked
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
    from contextlib import AbstractAsyncContextManager, AbstractContextManager
    from uuid import UUID

    import httpx

    from screamingface._core.ports import AsyncRunTransport, SyncRunTransport
    from screamingface._engine.catalog import AsyncBenchmarks, AsyncModels, Benchmarks, Models
    from screamingface._engine.connections import AsyncConnections, Connections
    from screamingface._engine.runs import RunRecord
    from screamingface._scoreboard.leaderboards import AsyncLeaderboards, Leaderboards
    from screamingface._ui.connections import ConnectionPanel
    from screamingface.classification import Classification
    from screamingface.connections import AsyncOAuthFlow, Connection, OAuthFlow
    from screamingface.credit import CreditStatus
    from screamingface.events import Event
    from screamingface.leaderboard import LeaderboardScore
    from screamingface.media import CaseMedia, FetchedMedia
    from screamingface.recipe import Recipe
    from screamingface.routing import RoutedAnswer
    from screamingface.runs import Run
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

        _require_run_transport(run_transport)
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
            analytics_engine_url=self._engine_url,
        )

    def credits(self, provider: str = "openrouter", *, refresh: bool = True) -> CreditStatus:
        """Read credits for the connection selected by the Engine for execution."""
        import httpx

        from screamingface.credit import _decode, _path, _unavailable
        from screamingface.errors import ScreamingFaceError

        self._require_open()
        _require_secure_connection_origin(self._engine_url)
        path = _path(provider, refresh=refresh)
        try:
            response = self._http_request("GET", path)
        except (httpx.HTTPError, ScreamingFaceError):
            return _unavailable(provider)
        return _decode(response, provider)

    def set_credit_management_key(self, provider: str, *, api_key: str) -> None:
        """Verify and securely store a management key for the current execution connection."""
        import httpx

        from screamingface.credit import _path, _secret, _setup_result
        from screamingface.errors import ScreamingFaceError

        self._require_open()
        _require_secure_connection_origin(self._engine_url)
        path, secret = _path(provider) + "/management-key", _secret(api_key)
        try:
            response = self._http_request("PUT", path, json={"api_key": secret})
        except (httpx.HTTPError, ScreamingFaceError):
            response = None
        _setup_result(response)

    def clear_credit_management_key(self, provider: str) -> None:
        """Remove the saved management key for this caller and provider."""
        import httpx

        from screamingface.credit import _path, _setup_result
        from screamingface.errors import ScreamingFaceError

        self._require_open()
        _require_secure_connection_origin(self._engine_url)
        path = _path(provider) + "/management-key"
        try:
            response = self._http_request("DELETE", path)
        except (httpx.HTTPError, ScreamingFaceError):
            response = None
        _setup_result(response)

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
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[False] = False,
    ) -> Report: ...

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
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[True],
        deadline: timedelta | None = None,
    ) -> Run: ...

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
        capture: bool = False,
        use_cache: bool = True,
        detach: bool = False,
        deadline: timedelta | None = None,
    ) -> Report | Run: ...

    @overload
    def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe],
        *,
        benchmark: str,
        limit: int | None = None,
        cases: Sequence[int] | None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[False] = False,
    ) -> Report: ...

    @overload
    def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe],
        *,
        benchmark: str,
        limit: int | None = None,
        cases: Sequence[int] | None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[True],
        deadline: timedelta | None = None,
    ) -> Run: ...

    @overload
    def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe],
        *,
        benchmark: str,
        limit: int | None = None,
        cases: Sequence[int] | None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = False,
        use_cache: bool = True,
        detach: bool = False,
        deadline: timedelta | None = None,
    ) -> Report | Run: ...

    @overload
    def evaluate(
        self,
        *,
        pinned_cache: str,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        answer_seed: int | None = None,
        record_reproduction: bool = True,
        limit: int | None = None,
        capture: Literal[False] | None = None,
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
        limit: int | None = None,
        capture: Literal[False] | None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
    ) -> Report: ...

    @tracked("evaluation")
    def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe] | str | None = None,
        *,
        benchmark: str | None = None,
        limit: int | None = None,
        cases: Sequence[int] | None = None,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool | None = None,
        pinned_cache: str | None = None,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        record_reproduction: bool = True,
        use_cache: bool = True,
        detach: bool = False,
        deadline: timedelta | None = None,
    ) -> Report | Run:
        """Evaluate Recipes, replay a complete URL4, or replay a published run from a pinned cache.

        `pinned_cache=` (or `score_id=`, for a private score you submitted) replays a published
        run at $0 from the answers it captured and judges it against the published score:
        `CandidateResult.reproduction`. An exact replay is recorded on the Scoreboard unless
        `record_reproduction=False`. A replay that cannot start raises `sf.ReproductionError`.

        `capture` is off by default. `capture=True` makes the Engine store every model and
        web-tool result of each run in a pinned cache (`CandidateResult.pinned_cache`), so the
        score can be reproduced later. An Engine that did not capture a run it was asked to
        capture is reported with an `EvaluationWarning`.

        `use_cache` is on by default: every model call may be answered from the request cache.
        `use_cache=False` opts this evaluation out (the calls are made fresh, and the report shows
        them as cache `bypass` / `opted_out`).

        `cases=[3, 17, 42]` runs only those Case ids (a Case's position in the Benchmark, 1 to N)
        instead of `limit=`'s first N, e.g. a development or held-out set. The Report names them in
        `selected_cases` and `selection_fingerprint`; such a run can't be submitted to the
        leaderboard. At most 1,000 ids.

        `detach=True` sends the evaluation to the Engine and returns its `sf.runs.Run` at once:
        the Engine runs it whether or not this notebook stays, until `deadline` (48 h by default,
        7 days at most). `run.wait()` gives the Report, from this machine or any other.
        """

        from screamingface._evaluation.runner import evaluate_sync
        from screamingface._evaluation.url4 import evaluate_url4_sync

        self._require_open()
        deadline_s = _deadline_seconds(detach, deadline)
        _detached_options(detach, on_event, progress)
        if pinned_cache is not None or score_id is not None:
            if detach:
                raise TypeError("a replay cannot be detached; it follows its run")
            return self._evaluate_replay(
                candidates=candidates,
                benchmark=benchmark,
                limit=limit,
                cases=cases,
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
        capture = bool(capture)
        # FEATURE (OME-1193): validate the declared sitting at the door — a bad seed must
        # fail before any token is minted or run scheduled.
        selected_seed = _answer_seed_value(answer_seed)
        _use_cache_value(use_cache)
        if isinstance(candidates, str):
            _raw_url4_options(benchmark, limit, cases)
            evaluated = evaluate_url4_sync(
                self._transport,
                candidates,
                on_event,
                progress,
                answer_seed=selected_seed,
                capture=capture,
                use_cache=use_cache,
                load_operators=self._operator_catalog.load,
                detach=detach,
                deadline_s=deadline_s,
            )
            return self._evaluated(evaluated)
        if benchmark is None:
            raise TypeError("benchmark is required when evaluating Recipes")
        evaluated = evaluate_sync(
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
            use_cache=use_cache,
            load_operators=self._operator_catalog.load,
            cases=cases,
            detach=detach,
            deadline_s=deadline_s,
        )
        return self._evaluated(evaluated)

    def _evaluated(self, evaluated: Report | str) -> Report | Run:
        """The Report, or, for a detached evaluation, its Run (E5 P2 spec D14)."""
        if not isinstance(evaluated, str):
            return evaluated
        from screamingface import runs
        from screamingface._engine import runs as wire

        return runs._run(
            _detached_run(self._transport, evaluated)
            or wire.get_sync(self._http_request, evaluated, summary=True),
            self,
        )

    def _evaluate_replay(
        self,
        *,
        candidates: object,
        benchmark: str | None,
        limit: int | None,
        capture: bool | None,
        cases: object = None,
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
        _replay_options(candidates, benchmark, capture, cases)
        return replay_sync(
            self,
            pinned_cache=pinned_cache,
            score_id=score_id,
            url4=url4,
            answer_seed=answer_seed,
            record_reproduction=record_reproduction,
            on_event=on_event,
            progress=progress,
            limit=limit,
        )

    def regrade(
        self,
        score_id: UUID | str,
        *,
        on_event: Callable[[Event], None] | None = None,
        progress: bool | None = None,
        expected_target_revision: str | None = None,
    ) -> LeaderboardScore:
        """Move a published score onto its Benchmark's current revision, at no model cost.

        Same answers, today's grading: every model reply, Candidate and judge, comes from the
        score's pinned cache, and only the Benchmark part (its grading) is the current revision's.
        It is for ScreamingFace team members after a Benchmark's revision moved because its
        grading changed (OME-1909); the Scoreboard accepts it only from an identity it lists as a
        re-grader. A Benchmark whose judge request changed (a new judge prompt or `max_tokens`)
        misses the cache on every judged Case, so it cannot be re-graded this way.

        Set ``expected_target_revision`` when moving scores under a declared transition.
        A different catalogue revision refuses before replay; a different result revision
        refuses before submission (``regrade_target_mismatch``, retryable). Omit it to use
        the current revision as before.

        Stages, in the order they run:

        1. The score is read from the public read only. A private score, even one you submitted, is
           the board's 404 (`LeaderboardError`, `code="unknown_score"`) before any run: the board
           never re-grades a score on a private board.
        2. A score that is itself a re-grade is refused (`PlanningError`,
           `code="regrade_the_source"`, `details["root_score_id"]` naming the score it re-graded):
           it has no pinned cache, so re-grade that root score instead. A score with no pinned
           cache, or a `partial` capture, is refused before anything else (`ReproductionError`,
           `code="not_reproducible"`).
        3. The current Benchmark is read from the Engine at the score's Case count.
        4. A score already on the current revision is refused (`PlanningError`,
           `code="already_current"`), and so is one whose revision the Benchmark does not list as
           re-gradable (`code="not_regradable"`). Each listed revision carries a Case Digest the
           Engine checks against the Benchmark's current Cases when it builds the catalogue, a
           tripwire for a later Case change; an old entry whose Cases differed is refused at step
           6, because its pinned cache misses. The url4 is rebuilt: the current Benchmark part,
           around the score's Candidate part unchanged (a published url4 with no Candidate part is
           `code="invalid_published_url4"`).
        5. The run replays from the pinned cache with the score's answer seed, never capturing.
           An Engine that does not acknowledge the copy has its run stopped (`ExecutionError`,
           `code="replay_unsupported"`).
        6. If any Case missed the copy, on a Candidate or a judge call, nothing is submitted
           (`ExecutionError`, `code="regrade_incomplete"`, `details["missed_cases"]`).
        7. The result is posted to the score's re-grade route. The new entry is credited to the
           score's submitter and authors and links back to the score; the score is unchanged. A
           second re-grade of one score at the same revision is
           `LeaderboardError(code="already_regraded")` with
           `existing_score_id` naming the first, so a batch can count it as done. The board's own
           refusals (`not_allowed`, `already_regraded`, `not_current_revision`) arrive only here,
           after the replay has run.

        Worked example: score `af95…` scored 0.5 on DRACO's revision `old-revision` with a fanout
        of two members and a final synthesis step, captured with answer seed 7 in copy `0b1f…`.
        DRACO is now at `new-revision`, which lists `old-revision` as re-gradable.
        `regrade("af95…")` runs the new DRACO url4 around the same Candidate text, all 3 Cases
        replay from `0b1f…` at seed 7, the new grading scores 1.0, and the board answers with a
        new entry `3c9a…` at `new-revision`, submitted by the original researcher. Returns that
        new entry.
        """

        from screamingface._regrade import regrade_sync

        self._require_open()
        return regrade_sync(
            self,
            score_id,
            on_event=on_event,
            progress=progress,
            expected_target_revision=expected_target_revision,
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
            from screamingface._analytics.prompt import offer
            from screamingface._ui.connections import ConnectionPanel

            offer()
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

    def fetch_media(self, media: CaseMedia) -> FetchedMedia:
        """Fetch one picture or file of a Case from this engine, checked against its placeholder.

        FEATURE (OME-1271): ``case.media`` lists a Case's pictures and files without fetching
        them; this opens one. A local engine drops parked pictures after a while (48 hours by
        default). e.g. ``client.fetch_media(case.media[0])`` shows the figure inline in
        Jupyter, and ``.save("figures/")`` writes it.

        Raises:
            MediaUnavailableError: the engine no longer holds it, or sent other bytes.
            EngineUnavailableError: the engine could not be reached.
        """

        from screamingface._engine.media import fetch_media_bytes
        from screamingface._engine.transport import _mint_sync
        from screamingface.media import FetchedMedia

        self._require_open()
        data: bytes = fetch_media_bytes(self._http, media, lambda: _mint_sync(self._http))
        return FetchedMedia(media=media, data=data)

    def classify(self, model: str, input: str) -> Classification:
        """Classify one text with a configured classifier model, through this engine.

        FEATURE (OME-1796): the engine asks the AI Gateway, which calls the classifier with your
        own Connection. e.g. ``client.classify("byom_<id>/classifier_v1", "Great service")``
        returns its labels and scores in the classifier's order. An input whose encoded request
        passes the engine's 8 KiB limit is refused before any call.

        Raises:
            PlanningError: the request is too long, a value holds a character UTF-8 cannot
                encode, or the engine refused it (for example an unknown classifier,
                ``classifier_not_found``).
            EngineCapabilityError: this engine does not serve ``/classify``.
            ExecutionError: the call did not finish. ``retryable`` is True only when nothing
                ran; once the classifier may have run, classifying again may bill it again.
            AuthenticationError: the engine refused the caller.
            EngineUnavailableError: the engine could not be reached.
        """

        from screamingface._engine.classification import classify

        self._require_open()
        return classify(self._engine_get, self._engine_url, model, input)

    def route_answer(self, profile: str, input: str) -> RoutedAnswer:
        """Answer one question with the model a routing profile on this engine selects.

        FEATURE (OME-1823): the engine classifies the question with the profile's classifier and
        asks the one model bound to the highest label. e.g.
        ``client.route_answer("expert_router_v1", "Sort a list in Python").answer``.

        Raises:
            PlanningError: the request is too long or holds a character UTF-8 cannot encode, or
                the engine refused it (for example ``routing_profile_not_found``).
            EngineCapabilityError: this engine does not serve ``/route-answer``.
            ExecutionError: the call did not finish. ``retryable`` is True only when nothing
                ran; otherwise asking again may bill the classifier and the selected model again.
            AuthenticationError: the engine refused the caller.
            EngineUnavailableError: the engine could not be reached.
        """

        from screamingface._engine.routed_answer import route_answer

        self._require_open()
        return route_answer(self._engine_get, self._engine_url, profile, input)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("ScreamingFace Client is closed")

    def _engine_get(
        self, path: str, *, headers: Mapping[str, str], timeout: httpx.Timeout
    ) -> AbstractContextManager[httpx.Response]:
        # WHY no replay-safe mark, unlike `_http_get`: the auth layer re-sends a marked request
        # after an Access re-login, and this seam carries paid calls that must never run twice.
        self._require_open()
        return self._http.stream("GET", path, headers=headers, timeout=timeout)

    def _engine_post_stream(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: httpx.Timeout,
    ) -> AbstractContextManager[httpx.Response]:
        # WHY replay-safe, unlike `_engine_get` (P15): on `POST /v1/chat/completions` an Access
        # challenge (302, 401 or 403) always comes before a run exists, because the Engine answers
        # a scheduled run with 200. So the auth layer may send this POST one more time after the
        # sign-in. A 408, 429 or 5xx is never sent again here: `self._http` has no retry layer.
        self._require_open()
        return self._http.stream(
            "POST",
            path,
            json=json,
            headers=headers,
            timeout=timeout,
            extensions={_REPLAY_SAFE: True},
        )

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

        _require_run_transport(run_transport)
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
            analytics_engine_url=self._engine_url,
        )

    async def credits(self, provider: str = "openrouter", *, refresh: bool = True) -> CreditStatus:
        """Read credits for the connection selected by the Engine for execution."""
        import httpx

        from screamingface.credit import _decode, _path, _unavailable
        from screamingface.errors import ScreamingFaceError

        self._require_open()
        _require_secure_connection_origin(self._engine_url)
        path = _path(provider, refresh=refresh)
        try:
            response = await self._http_request("GET", path)
        except (httpx.HTTPError, ScreamingFaceError):
            return _unavailable(provider)
        return _decode(response, provider)

    async def set_credit_management_key(self, provider: str, *, api_key: str) -> None:
        """Verify and securely store a management key for the current execution connection."""
        import httpx

        from screamingface.credit import _path, _secret, _setup_result
        from screamingface.errors import ScreamingFaceError

        self._require_open()
        _require_secure_connection_origin(self._engine_url)
        path, secret = _path(provider) + "/management-key", _secret(api_key)
        try:
            response = await self._http_request("PUT", path, json={"api_key": secret})
        except (httpx.HTTPError, ScreamingFaceError):
            response = None
        _setup_result(response)

    async def clear_credit_management_key(self, provider: str) -> None:
        """Remove the saved management key for this caller and provider."""
        import httpx

        from screamingface.credit import _path, _setup_result
        from screamingface.errors import ScreamingFaceError

        self._require_open()
        _require_secure_connection_origin(self._engine_url)
        path = _path(provider) + "/management-key"
        try:
            response = await self._http_request("DELETE", path)
        except (httpx.HTTPError, ScreamingFaceError):
            response = None
        _setup_result(response)

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
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[False] = False,
    ) -> Report: ...

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
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[True],
        deadline: timedelta | None = None,
    ) -> Run: ...

    @overload
    async def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe],
        *,
        benchmark: str,
        limit: int | None = None,
        cases: Sequence[int] | None = None,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[False] = False,
    ) -> Report: ...

    @overload
    async def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe],
        *,
        benchmark: str,
        limit: int | None = None,
        cases: Sequence[int] | None = None,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool = False,
        use_cache: bool = True,
        detach: Literal[True],
        deadline: timedelta | None = None,
    ) -> Run: ...

    @overload
    async def evaluate(
        self,
        *,
        pinned_cache: str,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        answer_seed: int | None = None,
        record_reproduction: bool = True,
        limit: int | None = None,
        capture: Literal[False] | None = None,
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
        limit: int | None = None,
        capture: Literal[False] | None = None,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
    ) -> Report: ...

    @tracked("evaluation")
    async def evaluate(
        self,
        candidates: Recipe | Sequence[Recipe] | str | None = None,
        *,
        benchmark: str | None = None,
        limit: int | None = None,
        cases: Sequence[int] | None = None,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
        answer_seed: int | None = None,
        capture: bool | None = None,
        pinned_cache: str | None = None,
        score_id: UUID | str | None = None,
        url4: str | None = None,
        record_reproduction: bool = True,
        use_cache: bool = True,
        detach: bool = False,
        deadline: timedelta | None = None,
    ) -> Report | Run:
        """Asynchronously evaluate Recipes, replay a complete URL4, or replay a pinned cache.

        `capture` is off by default. `capture=True` makes the Engine store every model and
        web-tool result of each run in a pinned cache (`CandidateResult.pinned_cache`), so the
        score can be reproduced later. An Engine that did not capture a run it was asked to
        capture is reported with an `EvaluationWarning`.

        `use_cache` is on by default: every model call may be answered from the request cache.
        `use_cache=False` opts this evaluation out (the calls are made fresh, and the report shows
        them as cache `bypass` / `opted_out`).

        `cases=[3, 17, 42]` runs only those Case ids (a Case's position in the Benchmark, 1 to N)
        instead of `limit=`'s first N, e.g. a development or held-out set. The Report names them in
        `selected_cases` and `selection_fingerprint`; such a run can't be submitted to the
        leaderboard. At most 1,000 ids.

        `detach=True` sends the evaluation to the Engine and returns its `sf.runs.Run` at once:
        the Engine runs it whether or not this notebook stays, until `deadline` (48 h by default,
        7 days at most). `run.wait()` gives the Report, from this machine or any other.
        """

        from screamingface._evaluation.runner import evaluate_async
        from screamingface._evaluation.url4 import evaluate_url4_async

        self._require_open()
        deadline_s = _deadline_seconds(detach, deadline)
        _detached_options(detach, on_event, progress)
        if pinned_cache is not None or score_id is not None:
            if detach:
                raise TypeError("a replay cannot be detached; it follows its run")
            return await self._evaluate_replay(
                candidates=candidates,
                benchmark=benchmark,
                limit=limit,
                cases=cases,
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
        capture = bool(capture)
        # FEATURE (OME-1193): see the sync twin — validate at the door.
        selected_seed = _answer_seed_value(answer_seed)
        _use_cache_value(use_cache)
        if isinstance(candidates, str):
            _raw_url4_options(benchmark, limit, cases)
            evaluated = await evaluate_url4_async(
                self._transport,
                candidates,
                on_event,
                progress,
                answer_seed=selected_seed,
                capture=capture,
                use_cache=use_cache,
                load_operators=self._operator_catalog.load,
                detach=detach,
                deadline_s=deadline_s,
            )
            return await self._evaluated(evaluated)
        if benchmark is None:
            raise TypeError("benchmark is required when evaluating Recipes")
        evaluated = await evaluate_async(
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
            use_cache=use_cache,
            load_operators=self._operator_catalog.load,
            cases=cases,
            detach=detach,
            deadline_s=deadline_s,
        )
        return await self._evaluated(evaluated)

    async def _evaluated(self, evaluated: Report | str) -> Report | Run:
        """The Report, or, for a detached evaluation, its Run, whose methods read and follow it
        on this Client's own async transport (E5 P2 spec D14): await `run.wait_async()`."""
        if not isinstance(evaluated, str):
            return evaluated
        from screamingface import runs
        from screamingface._engine import runs as wire

        record = _detached_run(self._transport, evaluated) or await wire.get_async(
            self._http_request, evaluated, summary=True
        )
        return runs._bound(record, runs._AsyncRuns(self))

    async def _evaluate_replay(
        self,
        *,
        candidates: object,
        benchmark: str | None,
        limit: int | None,
        capture: bool | None,
        cases: object = None,
        pinned_cache: str | None,
        score_id: UUID | str | None,
        url4: str | None,
        answer_seed: int | None,
        record_reproduction: bool,
        on_event: Callable[[Event], None | Awaitable[None]] | None,
        progress: bool | None,
    ) -> Report:
        from screamingface._replay import replay_async

        self._require_open()
        _replay_options(candidates, benchmark, capture, cases)
        return await replay_async(
            self,
            pinned_cache=pinned_cache,
            score_id=score_id,
            url4=url4,
            answer_seed=answer_seed,
            record_reproduction=record_reproduction,
            on_event=on_event,
            progress=progress,
            limit=limit,
        )

    async def regrade(
        self,
        score_id: UUID | str,
        *,
        on_event: Callable[[Event], None | Awaitable[None]] | None = None,
        progress: bool | None = None,
        expected_target_revision: str | None = None,
    ) -> LeaderboardScore:
        """Asynchronously move a published score onto its Benchmark's current revision.

        The same stages, checks and errors as `Client.regrade`.
        """

        from screamingface._regrade import regrade_async

        self._require_open()
        return await regrade_async(
            self,
            score_id,
            on_event=on_event,
            progress=progress,
            expected_target_revision=expected_target_revision,
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

    def _engine_post_stream(
        self,
        path: str,
        *,
        json: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: httpx.Timeout,
    ) -> AbstractAsyncContextManager[httpx.Response]:
        # WHY replay-safe: the same rule as `Client._engine_post_stream` (P15). An Access
        # challenge comes before a run exists, so one more send after the sign-in is safe. A 408,
        # 429 or 5xx is never sent again here: `self._http` has no retry layer.
        self._require_open()
        return self._http.stream(
            "POST",
            path,
            json=json,
            headers=headers,
            timeout=timeout,
            extensions={_REPLAY_SAFE: True},
        )

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


#: What `run_transport` must have beyond `close`, which the port's earlier shape had too.
_FOLLOW_PORT = ("register_run", "follow_run", "cancel_run")


def _require_run_transport(transport: object) -> None:
    """Refuse a `run_transport` without the follow-a-Run port when the Client is made. WHY at the
    door: one of the earlier shape (`run`, `cancel_active`) otherwise fails with a bare
    AttributeError, after the evaluation has already called the Engine."""
    if transport is None:
        return
    missing = [name for name in _FOLLOW_PORT if not callable(getattr(transport, name, None))]
    if missing:
        raise TypeError(
            "run_transport must follow a Run: register_run, follow_run, cancel_run and close "
            f"(SyncRunTransport or AsyncRunTransport); {type(transport).__name__} has no "
            f"{', '.join(missing)}"
        )


def _detached_run(transport: object, run_id: str) -> RunRecord | None:
    """The detached Run as its registration answered, from a transport that keeps it."""
    # WHY by name: a test's fake transport keeps none, and its Run is read from the Engine.
    detached_run = getattr(transport, "detached_run", None)
    return cast("RunRecord | None", detached_run(run_id)) if callable(detached_run) else None


def _deadline_seconds(detach: object, deadline: object) -> int | None:
    """``deadline`` in whole seconds, refused at the door (E5 P2 spec D11): only a detached Run
    has one, and it is a positive `timedelta`."""
    if not isinstance(detach, bool):
        raise TypeError("detach must be True or False")
    if deadline is None:
        return None
    if not isinstance(deadline, timedelta):
        raise TypeError("deadline must be a datetime.timedelta")
    if not detach:
        raise ValueError("deadline needs detach=True: an attached Run ends when you stop following")
    if deadline.total_seconds() < 1:
        raise ValueError("deadline must be at least 1 second")
    return int(deadline.total_seconds())


def _detached_options(detach: bool, on_event: object, progress: object) -> None:
    """A detached evaluation returns before anything runs, so nothing would reach `on_event` or
    the progress output: refused at the door rather than silently ignored."""
    if detach and (on_event is not None or progress):
        raise TypeError(
            "on_event and progress need an attached evaluation; follow a detached Run with "
            "run.wait()"
        )


def _use_cache_value(use_cache: object) -> None:
    """Refuse a non-bool `use_cache` at the door, before any token is minted (OME-1311)."""
    if not isinstance(use_cache, bool):
        raise TypeError("use_cache must be True or False")


def _replay_options(
    candidates: object, benchmark: str | None, capture: bool | None, cases: object = None
) -> None:
    """A replay is one complete published run (spec §1): nothing else selects what runs."""

    # WHY refused, not ignored (OME-1739): a replay runs the published Case set or its first N
    # (`limit=`); silently replaying other Cases than the list named would be a wrong answer.
    if cases is not None:
        raise TypeError("cases= is not supported when replaying; replay the run, or use limit=")
    if candidates is not None:
        raise TypeError("candidates must not be passed with pinned_cache= or score_id=")
    if benchmark is not None:
        raise TypeError("benchmark must not be passed with pinned_cache= or score_id=")
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


def _raw_url4_options(benchmark: str | None, limit: int | None, cases: object = None) -> None:
    if benchmark is not None:
        raise TypeError("benchmark must not be passed when evaluating a complete URL4")
    if limit is not None:
        raise TypeError("limit must not be passed when evaluating a complete URL4")
    if cases is not None:
        raise TypeError("cases must not be passed when evaluating a complete URL4")


def _engine_access_discovery_error(origin: str) -> BaseException:
    from screamingface.errors import EngineUnavailableError

    return EngineUnavailableError(
        "Could not reach the SF Engine to discover Cloudflare Access authentication",
        engine_url=origin,
    )


__all__ = ["AsyncClient", "Client", "DEFAULT_ENGINE_URL", "DEFAULT_SCOREBOARD_URL"]

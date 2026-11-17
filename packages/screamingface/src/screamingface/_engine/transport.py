"""The SF Engine transports: the evaluation is one Run, which the Engine drives (E5 P2 spec D1).

FEATURE: a detached Run (OME-1837). The Client registers the whole evaluation with every
Candidate's start, follows the Run on one stream, and keeps each Candidate's result; it starts no
Candidate itself. The Run half lives in `run_client.py`; this module holds the transports, which
own the HTTP client, the caller's sign-in and the local result store.
"""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from screamingface._access.auth import _default_caller_auth
from screamingface._access.base import _TransportAuth
from screamingface._core.ports import _AsyncRunSink, _RunOutcome, _RunSink
from screamingface._core.retry import RetryingAsyncTransport, RetryingTransport
from screamingface._core.wire import _REPLAY_SAFE
from screamingface._engine.identity import engine_headers
from screamingface._engine.result_download import (
    download_async,
    download_sync,
    fetch_result_async,
    fetch_result_sync,
)
from screamingface._engine.run_client import AsyncRunClient, FollowTimings, RunClient
from screamingface._engine.run_follow import RECONNECT_BASE_DELAY_S, RECONNECT_BUDGET_S
from screamingface._engine.trace import TraceContext
from screamingface._evaluation.model import Candidate, _Evaluation
from screamingface.errors import AuthenticationError, EngineUnavailableError, ExecutionError


class Url4CloudTransport:
    """Synchronous transport: register an evaluation as a Run, follow it, keep its results."""

    def __init__(
        self,
        engine_url: str,
        caller_auth: _TransportAuth | None = None,
        *,
        save_results: bool = False,
        reconnect_budget_s: float = RECONNECT_BUDGET_S,
        reconnect_base_delay_s: float = RECONNECT_BASE_DELAY_S,
    ) -> None:
        from screamingface._results.store import ResultStore

        self._result_store = ResultStore() if save_results else None
        if self._result_store is not None:
            from screamingface._results.recovery_notice import show_recoverable_results

            show_recoverable_results(self._result_store, engine_url)
        self._result_contexts = {}
        # FEATURE (OME-1785): the Run each Candidate belongs to; its local manifest is keyed by it.
        self._report_ids: dict[int, str] = {}
        self._engine_url = engine_url
        self._owns_auth = caller_auth is None
        self._caller_auth = caller_auth or _default_caller_auth(engine_url)
        # WHY a retrying transport (OME-1107): a transient edge failure between the caller and
        # a healthy origin used to end the whole evaluation. Only requests the call site marked
        # `_REPLAY_SAFE` are re-sent.
        self._http = httpx.Client(
            base_url=engine_url,
            headers=engine_headers(),
            timeout=30.0,
            auth=self._caller_auth,
            transport=RetryingTransport(httpx.HTTPTransport()),
        )
        # INVARIANT: built from the same source as the client above, so the two halves of
        # this transport can never verify against different roots.
        self._ssl = _websocket_ssl_context(engine_url)
        self._runs = RunClient(
            self._http,
            engine_url,
            self._caller_auth,
            self._ssl,
            FollowTimings(reconnect_budget_s, reconnect_base_delay_s),
        )

    def register_run(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> str:
        """Register the evaluation as a Run, with every Candidate's start (E5 P2 spec D1)."""
        from screamingface._engine.credit_notice import check_sync

        check_sync(self._http, candidates)
        run_id = self._runs.register(evaluation, candidates, detach=detach, deadline_s=deadline_s)
        self._report_ids.update({id(candidate): run_id for candidate in candidates})
        return run_id

    def follow_run(self, run_id: str, candidates: tuple[Candidate, ...], sink: _RunSink) -> None:
        self._runs.follow(run_id, candidates, sink, self._save_result)

    def cancel_run(self, run_id: str) -> None:
        self._runs.cancel(run_id)

    def adopt_run(self, run_id: str, candidates: tuple[Candidate, ...]) -> None:
        """Key ``candidates``' saved results by ``run_id``, a Run registered elsewhere."""
        self._report_ids.update({id(candidate): run_id for candidate in candidates})

    def save_result(self, candidate: Candidate, outcome: _RunOutcome) -> _RunOutcome:
        return self._save_result(candidate, outcome)

    def wait_run(self, run_id: str, *, detached: bool) -> None:
        """Follow the Run until it ends, showing nothing (`Run.wait`)."""
        self._runs.wait(run_id, detached=detached)

    def _save_result(self, candidate: Candidate, outcome: _RunOutcome) -> _RunOutcome:
        if self._result_store is None:
            return fetch_result_sync(self._http, outcome)
        saved = self._result_store.record(
            self._engine_url,
            candidate,
            outcome,
            _take_result_context(self._result_contexts, candidate),
        )
        return download_sync(self._http, saved, lambda: _mint_sync(self._http))

    def prepare_results(self, evaluation, candidates) -> Path | None:
        from screamingface._results.evaluation import prepare
        from screamingface._results.lifecycle import evaluation_path

        if self._result_store is not None:
            contexts = prepare(
                self._result_store,
                evaluation,
                candidates,
                report_id=self._report_ids.get(id(candidates[0])) if candidates else None,
            )
            self._result_contexts.update(
                {id(candidate): (candidate, contexts[id(candidate)]) for candidate in candidates}
            )
            if contexts:
                return evaluation_path(
                    self._result_store.directory, next(iter(contexts.values()))["id"]
                )
        return None

    def finish_results(self, candidates) -> None:
        for candidate in candidates:
            self._result_contexts.pop(id(candidate), None)
            self._report_ids.pop(id(candidate), None)

    def close(self) -> None:
        self._result_contexts.clear()
        try:
            self._http.close()
        finally:
            if self._owns_auth:
                self._caller_auth.close()


class AsyncUrl4CloudTransport:
    """The async twin of ``Url4CloudTransport``."""

    def __init__(
        self,
        engine_url: str,
        caller_auth: _TransportAuth | None = None,
        *,
        save_results: bool = False,
        reconnect_budget_s: float = RECONNECT_BUDGET_S,
        reconnect_base_delay_s: float = RECONNECT_BASE_DELAY_S,
    ) -> None:
        from screamingface._results.store import ResultStore

        self._result_store = ResultStore() if save_results else None
        if self._result_store is not None:
            from screamingface._results.recovery_notice import show_recoverable_results

            show_recoverable_results(self._result_store, engine_url)
        self._result_contexts = {}
        self._report_ids: dict[int, str] = {}
        self._engine_url = engine_url
        self._owns_auth = caller_auth is None
        self._caller_auth = caller_auth or _default_caller_auth(engine_url)
        self._http = httpx.AsyncClient(
            base_url=engine_url,
            headers=engine_headers(),
            timeout=30.0,
            auth=self._caller_auth,
            transport=RetryingAsyncTransport(httpx.AsyncHTTPTransport()),
        )
        self._ssl = _websocket_ssl_context(engine_url)
        self._runs = AsyncRunClient(
            self._http,
            engine_url,
            self._caller_auth,
            self._ssl,
            FollowTimings(reconnect_budget_s, reconnect_base_delay_s),
        )

    async def register_run(
        self,
        evaluation: _Evaluation | None,
        candidates: tuple[Candidate, ...],
        *,
        detach: bool = False,
        deadline_s: int | None = None,
    ) -> str:
        from screamingface._engine.credit_notice import check_async

        await check_async(self._http, candidates)
        run_id = await self._runs.register(
            evaluation, candidates, detach=detach, deadline_s=deadline_s
        )
        self._report_ids.update({id(candidate): run_id for candidate in candidates})
        return run_id

    async def follow_run(
        self, run_id: str, candidates: tuple[Candidate, ...], sink: _AsyncRunSink
    ) -> None:
        await self._runs.follow(run_id, candidates, sink, self._save_result)

    async def cancel_run(self, run_id: str) -> None:
        await self._runs.cancel(run_id)

    async def _save_result(self, candidate: Candidate, outcome: _RunOutcome) -> _RunOutcome:
        if self._result_store is None:
            return await fetch_result_async(self._http, outcome)
        saved = self._result_store.record(
            self._engine_url,
            candidate,
            outcome,
            _take_result_context(self._result_contexts, candidate),
        )
        return await download_async(self._http, saved, lambda: _mint_async(self._http))

    def prepare_results(self, evaluation, candidates) -> Path | None:
        from screamingface._results.evaluation import prepare
        from screamingface._results.lifecycle import evaluation_path

        if self._result_store is not None:
            contexts = prepare(
                self._result_store,
                evaluation,
                candidates,
                report_id=self._report_ids.get(id(candidates[0])) if candidates else None,
            )
            self._result_contexts.update(
                {id(candidate): (candidate, contexts[id(candidate)]) for candidate in candidates}
            )
            if contexts:
                return evaluation_path(
                    self._result_store.directory, next(iter(contexts.values()))["id"]
                )
        return None

    def finish_results(self, candidates) -> None:
        for candidate in candidates:
            self._result_contexts.pop(id(candidate), None)
            self._report_ids.pop(id(candidate), None)

    async def close(self) -> None:
        self._result_contexts.clear()
        try:
            await self._http.aclose()
        finally:
            if self._owns_auth:
                await asyncio.to_thread(self._caller_auth.close)


def _take_result_context(contexts, candidate):
    # WHY: retain the actual object until retirement; an integer identity alone
    # can be reused after a failed/abandoned evaluation releases its candidates.
    selected = contexts.pop(id(candidate), None)
    return selected[1] if selected is not None and selected[0] is candidate else None


def _mint_sync(http: httpx.Client, *, trace: TraceContext | None = None) -> str:
    # AIDEV-NOTE (OME-967): `trace` is keyword-with-default so the capability mint stays
    # callable without one (artifact redemption, and a prior contract test). The RUN path
    # always passes it — minting is the first outbound call, and a mint failure is one of
    # the three pre-first-frame classes this ticket exists to make joinable.
    try:
        response = http.post(
            "/token", headers=_trace_headers(trace), extensions={_REPLAY_SAFE: True}
        )
    except httpx.HTTPError as exc:
        raise EngineUnavailableError(
            "Could not reach the SF Engine capability endpoint",
            engine_url=_http_origin(http),
            trace_id=trace.trace_id if trace else None,
        ) from exc
    return _token(response)


async def _mint_async(http: httpx.AsyncClient, *, trace: TraceContext | None = None) -> str:
    try:
        response = await http.post(
            "/token", headers=_trace_headers(trace), extensions={_REPLAY_SAFE: True}
        )
    except httpx.HTTPError as exc:
        raise EngineUnavailableError(
            "Could not reach the SF Engine capability endpoint",
            engine_url=_http_origin(http),
            trace_id=trace.trace_id if trace else None,
        ) from exc
    return _token(response)


def _token(response: httpx.Response) -> str:
    _require_success(response, "mint an execution capability")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ExecutionError("SF Engine capability response must be JSON") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"token"}
        or not isinstance(payload["token"], str)
        or not payload["token"].strip()
    ):
        raise ExecutionError("SF Engine capability response is malformed")
    return payload["token"].strip()


def _require_success(
    response: httpx.Response, operation: str, *, trace_id: str | None = None
) -> None:
    if not response.is_success:
        _raise_response(response, operation, trace_id=trace_id)


# How much of an unstructured body may reach an exception message. Long enough to carry a
# short plain-text reason, far short of a rendered error page.
_BODY_SNIPPET_LIMIT = 200


def _body_summary(response: httpx.Response) -> str:
    """A bounded, single-line stand-in for a non-`problem+json` body (OME-1107).

    WHY: this used to be `response.text.strip()` verbatim. An edge proxy answers with a full
    HTML error page, so a transient Cloudflare 520 reached the user as ~7KB of markup with the
    one useful token — the status code — buried inside it. Anything the Engine itself says
    arrives as `problem+json` and is read by the caller; everything else is an intermediary
    speaking a format we do not parse, and its bulk is noise.
    """
    status = f"HTTP {response.status_code}"
    try:
        body = response.text
    except (UnicodeDecodeError, httpx.ResponseNotRead):
        body = ""
    collapsed = " ".join(body.split())
    # An HTML page carries no reason a human wants in a traceback — name the status and stop.
    if not collapsed or collapsed.lower().startswith(("<!doctype", "<html")):
        return status
    if len(collapsed) > _BODY_SNIPPET_LIMIT:
        collapsed = collapsed[:_BODY_SNIPPET_LIMIT].rstrip() + "…"
    return f"{status}: {collapsed}"


def _raise_response(
    response: httpx.Response, operation: str, *, trace_id: str | None = None
) -> None:
    # WHY the id reaches THIS function (OME-967): every response-derived failure funnels
    # here — mint, start, stop, artifact. A pre-first-frame failure is far more often an
    # Engine problem+json than an httpx transport error, so attaching the id only on the
    # transport branch would miss the common case.
    detail, code, details = _problem_parts(response)
    exception = AuthenticationError if response.status_code in {401, 403} else ExecutionError
    if exception is AuthenticationError:
        raise AuthenticationError(
            f"Could not {operation}: {detail}",
            code=code,
            status=response.status_code,
            permanent=True,
            details=details,
            trace_id=trace_id,
        )
    raise ExecutionError(
        f"Could not {operation}: {detail}",
        code=code,
        status=response.status_code,
        permanent=response.status_code < 500,
        details=details,
        trace_id=trace_id,
    )


def _problem_parts(response: httpx.Response) -> tuple[str, str | None, object]:
    """A failed response's (detail, code, details): the Engine's RFC 9457 fields, if any."""
    code: str | None = None
    problem: object = None
    detail = _body_summary(response)
    media_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
    if media_type != "application/problem+json":
        return detail, code, None
    try:
        problem = response.json()
    except ValueError:
        problem = None
    if isinstance(problem, dict):
        if isinstance(problem.get("detail"), str):
            detail = problem["detail"]
        if isinstance(problem.get("type"), str):
            code = problem["type"]
    return detail, code, problem


def _websocket_ssl_context(engine_url: str) -> ssl.SSLContext | None:
    """The trust store the WebSocket must use: the one the HTTP half already uses.

    WHY this cannot be left to `websockets`: given no context it builds one with
    `ssl.create_default_context()`, which trusts OpenSSL's own CA paths. `httpx` resolves
    `SSL_CERT_FILE`, then `SSL_CERT_DIR`, and otherwise falls back to the `certifi` bundle
    installed with this package. The two therefore agree only while those environment
    variables are set — and diverge in the DEFAULT case, where `httpx` trusts `certifi` and
    `websockets` trusts whatever OpenSSL was compiled to look at. A python.org macOS build
    whose ``Install Certificates.command`` was never run has nothing there at all.

    The split is invisible until it isn't: the Client mints its capability over HTTPS, which
    succeeds against `certifi`, and then fails to open a WebSocket to the SAME host with
    `SSLCertVerificationError`. A local Engine is reached over plain `ws://`, which never
    negotiates TLS, so this only ever appeared against a hosted Engine — and read as a
    property of being remote rather than a property of the trust store.

    Deferring to `httpx` rather than naming `certifi` here is deliberate: the invariant worth
    holding is that the two halves agree, including about the environment, not that either
    one trusts a particular bundle.

    Returns ``None`` for a plain-HTTP Engine, because `websockets` refuses a context on a
    ``ws://`` URI.
    """

    if urlsplit(engine_url).scheme != "https":
        return None
    return httpx.create_ssl_context()


def _trace_headers(trace: TraceContext | None) -> dict[str, str]:
    """The run's trace context as headers, or nothing when there is no trace to send."""
    return trace.headers() if trace is not None else {}


def _http_origin(http: httpx.Client | httpx.AsyncClient) -> str:
    return str(http.base_url).rstrip("/")


__all__ = ["AsyncUrl4CloudTransport", "Url4CloudTransport"]

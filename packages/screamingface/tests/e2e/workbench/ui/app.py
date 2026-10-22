"""The workbench UI's routes and guards (unit 4 plan, Task 5). Dev-only, loopback-only.

Guards, outermost first:

- **Host** (DNS rebinding): any request whose ``Host`` is not ``127.0.0.1:<port>`` or
  ``localhost:<port>`` gets 400 before routing.
- **Token** (request forgery): ``POST /runs`` and ``POST /runs/{id}/cancel`` need the
  per-launch token, as the ``X-Workbench-Token`` header or a ``token`` form field; otherwise
  403 and nothing is spawned. No cookie, so a browser holds no ambient credential: the token
  rides in the query string of pages opened with it, and only a token that matches is echoed.
- **Headers**: every response carries a CSP with ``default-src 'none'``, ``X-Frame-Options:
  DENY`` and ``Referrer-Policy: no-referrer`` (the last keeps the token out of Referer).

WHY ``img-src data:`` beyond the plan's CSP: an ``srcdoc`` frame inherits this policy, and
nbconvert inlines notebook images (plots) as ``data:`` URIs; data images cannot run code.

WHY cancel returns before the run has ended: ``RunManager.cancel`` waits for fixture
teardown (up to its interrupt grace, 30 s by default). The browser is redirected at once and
the run page streams the teardown output until the stream's ``end`` event.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import shlex
import sys
import threading
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from screamingface._runtime.config import default_data_dir as runtime_default_data_dir
from workbench.ui import live, pages, telemetry
from workbench.ui.bundles import BundleNotFound, BundleSummary, discover, load
from workbench.ui.runs import Run, RunBusy, RunManager, RunRejected, RunRequest, runtime_data_dir

CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src data:; connect-src 'self'; frame-src 'self'; form-action 'self'; base-uri 'none'"
)
TOKEN_HEADER = "x-workbench-token"
BODY_CAP_BYTES = 64 << 10  # a run request is a few fields
_RUN_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_TRUE = frozenset({"on", "true", "1", "yes"})
_SECURITY_HEADERS = (
    (b"content-security-policy", CSP.encode()),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-content-type-options", b"nosniff"),
)


def _positive(value: str | None) -> int:
    """A 1-based page number from the query; anything else is page 1."""
    ok = value is not None and value.isascii() and value.isdigit() and 0 < len(value) < 7
    return int(value) if ok and value else 1


class _HttpError(Exception):
    def __init__(
        self, status: int, reason: str, *, token: str | None = None, back: str | None = None
    ) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.token = token
        self.back = back  # the page to return to (default: the index)


class _Guard:
    """Pure ASGI middleware: Host allow-list, then security headers on every response.

    WHY not ``BaseHTTPMiddleware``: it buffers through a task group that interferes with the
    long-lived event stream; a raw ``send`` wrapper does not.
    """

    def __init__(self, app: ASGIApp, *, port: int) -> None:
        self._app = app
        self._hosts = {f"127.0.0.1:{port}".encode(), f"localhost:{port}".encode()}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def secured(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *_SECURITY_HEADERS]
            await send(message)

        hosts = [v for k, v in scope["headers"] if k == b"host"]
        if len(hosts) != 1 or hosts[0].lower() not in self._hosts:
            response = Response("Host not allowed: the workbench UI is loopback-only.", 400)
            await response(scope, receive, secured)
            return
        await self._app(scope, receive, secured)


def _same(given: str | None, token: str) -> bool:
    return given is not None and secrets.compare_digest(given.encode(), token.encode())


async def _read_capped(request: Request) -> bytes:
    declared = request.headers.get("content-length", "0")
    if declared.isdigit() and int(declared) > BODY_CAP_BYTES:
        raise _HttpError(413, "request body too large")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > BODY_CAP_BYTES:
            raise _HttpError(413, "request body too large")
    return bytes(body)


def _is_json(request: Request) -> bool:
    return request.headers.get("content-type", "").split(";")[0].strip() == "application/json"


def _json_fields(body: bytes) -> dict[str, Any]:
    try:
        data: object = json.loads(body)
    except ValueError as exc:
        raise _HttpError(400, "the request body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise _HttpError(400, "the request body must be a JSON object")
    return data  # pyright: ignore[reportUnknownVariableType]


def _form_fields(fields: dict[str, list[str]]) -> dict[str, Any]:
    confirm = fields.get("confirm_paid", [""])[-1].lower() in _TRUE
    target = fields.get("target", [None])[-1]
    return {"target": target, "notebooks": fields.get("notebooks", []), "confirm_paid": confirm}


def _run_request(data: dict[str, Any], known: Sequence[str]) -> RunRequest:
    target, notebooks, confirm = (data.get(k) for k in ("target", "notebooks", "confirm_paid"))
    if not isinstance(target, str):
        raise _HttpError(400, "choose a target")
    stems: list[object] = notebooks if isinstance(notebooks, list) else []  # pyright: ignore[reportUnknownVariableType]
    if notebooks is not None and not isinstance(notebooks, list):
        raise _HttpError(400, "notebooks must be a list of notebook names")
    if not all(isinstance(s, str) for s in stems):
        raise _HttpError(400, "notebooks must be a list of notebook names")
    if unknown := [s for s in stems if s not in known]:
        raise _HttpError(400, f"unknown notebook(s): {', '.join(map(str, unknown))}")
    if not isinstance(confirm, bool | None):
        raise _HttpError(400, "confirm_paid must be true or false")
    return RunRequest(target, tuple(map(str, stems)), confirm_paid=bool(confirm))


class _ClosingStream(StreamingResponse):
    """A stream whose async body is always closed when the response ends, however it ends.

    WHY: under ASGI spec >= 2.4 Starlette does not cancel the body on disconnect; the failed
    ``send`` raises out of its ``async for`` and leaves the generator suspended until garbage
    collection. Closing it here releases its file handles at once (Review Focus 4).
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            body = self.body_iterator
            if isinstance(body, AsyncGenerator):
                await body.aclose()


def _sse_line(line: str) -> str:
    # WHY: a CR or LF inside a data field would end it and let output forge SSE fields.
    return line.replace("\r", " ").replace("\n", " ")


class _Workbench:
    """Route handlers sharing one configuration (the app's single run manager and root)."""

    def __init__(
        self,
        *,
        root: Path,
        manager: RunManager,
        token: str,
        notebooks: Sequence[str],
        default_data_dir: Path,
        telemetry_interval: float,
    ) -> None:
        self.root = root
        self.telemetry_interval = telemetry_interval
        self.default_data_dir = default_data_dir
        self.manager = manager
        self.token = token
        self.notebooks = tuple(notebooks)
        self.run_ids: list[str] = []  # started by this process, oldest first

    # --- helpers --------------------------------------------------------------------------

    def page_token(self, request: Request) -> str | None:
        """The launch token if this page was opened with it, else None (never echo a guess)."""
        given = request.query_params.get("token")
        return self.token if _same(given, self.token) else None

    def active(self) -> Run | None:
        runs = (self.manager.get(i) for i in self.run_ids)
        return next((r for r in runs if r.returncode is None), None)

    def local_blocker(self) -> str | None:
        """Why ``local`` cannot start, from the manager's own gate (so the reasons agree)."""
        probe = RunRequest("local", (), confirm_paid=True)
        try:
            self.manager.command(probe, self.root / "runs" / "_probe")
        except RunRejected as exc:
            return str(exc)
        return None

    def live(self, run_id: str) -> Run | None:
        if not _RUN_ID.fullmatch(run_id):
            raise _HttpError(404, f"no run {run_id!r}")
        try:
            return self.manager.get(run_id)
        except KeyError:
            return None

    def disk_run_ids(self) -> list[str]:
        runs_dir = self.root / "runs"
        try:
            names = [p.name for p in runs_dir.iterdir() if p.is_dir() and not p.is_symlink()]
        except OSError:
            names = []
        ids = {n for n in names if _RUN_ID.fullmatch(n)} | set(self.run_ids)
        return sorted(ids, reverse=True)

    def stop_command(self, run: Run) -> str | None:
        """After a cancel that may have skipped ``down``, the command that stops the runtime.

        ``screamingface up`` detaches into its own session, so nothing in the run's process
        group stops it: only fixture teardown's ``down`` does. That may not have run when the
        group needed SIGKILL; on ``local`` the tester should check either way.
        """
        if run.returncode is None or not run.cancelled:
            return None
        if not (run.killed or run.request.target == "local"):
            return None
        data_dir = runtime_data_dir(run) or self.default_data_dir
        return f"screamingface down --data-dir {shlex.quote(str(data_dir))}"

    def bundles_of(self, run_id: str) -> list[BundleSummary]:
        return [b for b in discover(self.root) if b.key.startswith(f"runs/{run_id}/")]

    def authorize(self, request: Request, form_token: str | None) -> None:
        if not (
            _same(request.headers.get(TOKEN_HEADER), self.token) or _same(form_token, self.token)
        ):
            raise _HttpError(403, "missing or wrong launch token; open the startup URL")

    async def authorized_fields(self, request: Request) -> dict[str, Any]:
        body = await _read_capped(request)
        if _is_json(request):
            self.authorize(request, None)
            return _json_fields(body)
        fields = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        self.authorize(request, fields.get("token", [None])[-1])
        return _form_fields(fields)

    # --- routes ---------------------------------------------------------------------------

    def index(self, request: Request) -> HTMLResponse:
        token = self.page_token(request)
        state = pages.LaunchState(token, self.notebooks, self.local_blocker(), self.active())
        bundles = discover(self.root)
        html = pages.index_page(
            state, root=str(self.root), run_ids=self.disk_run_ids(), bundles=bundles
        )
        return HTMLResponse(html)

    def bundle(self, request: Request, key: str) -> HTMLResponse:
        try:
            detail = load(self.root, key)
        except BundleNotFound as exc:
            raise _HttpError(404, f"no bundle {key!r}") from exc
        view = pages.TelemetryView(
            spans_page=_positive(request.query_params.get("spans_page")),
            unfold=request.query_params.get("unfold", "").lower() in _TRUE,
        )
        try:
            loaded = telemetry.load(detail.directory)
        except Exception as exc:  # noqa: BLE001 - an untrusted bundle must not take the page down
            note = f"telemetry could not be read: {type(exc).__name__}"
            loaded = telemetry.Telemetry(notes=(note,))
        page = pages.bundle_page(detail, loaded, view, token=self.page_token(request))
        return HTMLResponse(page)

    async def start(self, request: Request) -> RedirectResponse:
        data = await self.authorized_fields(request)
        run_request = _run_request(data, self.notebooks)
        try:
            run = self.manager.start(run_request)
        except RunBusy as exc:
            raise _HttpError(409, str(exc), token=self.token) from exc
        except RunRejected as exc:
            raise _HttpError(400, str(exc), token=self.token) from exc
        self.run_ids.append(run.id)
        return RedirectResponse(f"/runs/{run.id}?token={quote(self.token, safe='')}", 303)

    def run_page(self, request: Request, run_id: str) -> HTMLResponse:
        token = self.page_token(request)
        run = self.live(run_id)
        bundles = self.bundles_of(run_id)
        if run is not None:
            stop = self.stop_command(run)
            return HTMLResponse(pages.run_page(run, bundles, token=token, stop_command=stop))
        if not (self.root / "runs" / run_id).is_dir():
            raise _HttpError(404, f"no run {run_id!r}")
        return HTMLResponse(pages.past_run_page(run_id, bundles, token=token))

    def events(self, request: Request, run_id: str, start: int) -> StreamingResponse:
        run = self.live(run_id)
        if run is None:
            raise _HttpError(404, f"no live run {run_id!r}")
        resume = request.headers.get("last-event-id", "")
        first = max(start, int(resume) if resume.isdigit() else 0, run.dropped)
        return StreamingResponse(
            self._stream(run, first),
            media_type="text/event-stream",
            headers={"cache-control": "no-store"},
        )

    def telemetry(self, run_id: str) -> StreamingResponse:
        """The live run's model calls and counters (unit 6 Task 6); see ``ui/live.py``."""
        run = self.live(run_id)
        if run is None:
            raise _HttpError(404, f"no live run {run_id!r}")
        frames = live.stream(
            live.LiveTelemetry(run.out_dir, run.request.target),
            lambda: run.returncode is not None,
            interval=self.telemetry_interval,
        )
        return _ClosingStream(
            frames, media_type="text/event-stream", headers={"cache-control": "no-store"}
        )

    def _stream(self, run: Run, first: int) -> Iterator[str]:
        yield "retry: 2000\n\n"
        index: int = first
        shown: dict[str, object] = {"running": None, "since": None}  # nothing to show yet
        for line in self.manager.follow(run.id, first):
            index += 1
            yield f"id: {index}\ndata: {_sse_line(line)}\n\n"
            # The CURRENT state (not as of this line): a resumed stream jumps straight to it.
            progress = {"running": run.running, "since": run.running_since}
            if progress != shown:
                shown = progress
                yield f"event: progress\ndata: {json.dumps(progress)}\n\n"
        end = {"returncode": run.returncode, "cancelled": run.cancelled}
        yield f"event: end\ndata: {json.dumps(end)}\n\n"

    async def cancel(self, request: Request, run_id: str) -> RedirectResponse:
        run = self.live(run_id)
        if run is None:
            raise _HttpError(404, f"no live run {run_id!r}")
        await self.authorized_fields(request)
        if run.returncode is not None:
            back = f"/runs/{run_id}?token={quote(self.token, safe='')}"
            reason = f"Run {run_id} already finished — nothing to cancel."
            raise _HttpError(409, reason, token=self.token, back=back)
        threading.Thread(target=self.manager.cancel, args=(run_id,), daemon=True).start()
        return RedirectResponse(f"/runs/{run_id}?token={quote(self.token, safe='')}", 303)

    def cancel_active(self) -> None:
        """On shutdown: a run lives in its own session, so Ctrl-C on the UI never reaches it."""
        for run_id in list(self.run_ids):
            if self.manager.get(run_id).returncode is None:
                try:
                    print(f"workbench UI: cancelling run {run_id} before exit…", file=sys.stderr)
                except OSError:
                    pass  # the terminal is gone (SIGHUP): cancel all the same
                self.manager.cancel(run_id)


def _error_response(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, _HttpError)
    page = pages.error_page(exc.status, exc.reason, token=exc.token, back=exc.back)
    return HTMLResponse(page, exc.status)


def create_app(
    *,
    root: Path,
    manager: RunManager,
    token: str,
    port: int,
    notebooks: Sequence[str],
    default_data_dir: Path | None = None,
    telemetry_interval: float = 0.5,
) -> FastAPI:
    """The workbench UI app. ``root`` holds bundles; runs write under ``root/runs/<id>``.

    ``default_data_dir`` is named in the stop command when a run's own runtime data dir is
    unknown (default: the runtime's, ``SCREAMINGFACE_DATA_DIR`` or ``~/.screamingface``).
    ``telemetry_interval`` is how often the live telemetry stream polls the run's files.
    """
    wb = _Workbench(
        root=root.resolve(),
        manager=manager,
        token=token,
        notebooks=notebooks,
        default_data_dir=default_data_dir or runtime_default_data_dir(),
        telemetry_interval=telemetry_interval,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await asyncio.to_thread(wb.cancel_active)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.run_ids = wb.run_ids
    app.add_exception_handler(_HttpError, _error_response)
    app.add_api_route("/", wb.index, methods=["GET"])
    app.add_api_route("/bundles/{key:path}", wb.bundle, methods=["GET"])
    app.add_api_route("/runs", wb.start, methods=["POST"])
    app.add_api_route("/runs/{run_id}", wb.run_page, methods=["GET"])
    app.add_api_route("/runs/{run_id}/cancel", wb.cancel, methods=["POST"])

    def events(request: Request, run_id: str, start: int = Query(0, ge=0, alias="from")):
        return wb.events(request, run_id, start)

    app.add_api_route("/runs/{run_id}/events", events, methods=["GET"])
    app.add_api_route("/runs/{run_id}/telemetry", wb.telemetry, methods=["GET"])
    app.add_middleware(_Guard, port=port)
    return app

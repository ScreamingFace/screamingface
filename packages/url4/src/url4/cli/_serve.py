"""Backend handlers and node/app assembly for ``url4 serve``.

This is the transport-adapter layer behind the CLI (:mod:`url4.cli`). It builds a
:class:`~url4.peer.server.Url4Node` from a :class:`ServeConfig` — registering one
intent-processor endpoint per configured ``[commands]`` route (a local
subprocess, doctrine N4; there is no other intent-processor kind — a user's LLM
backend is their own gateway script mounted as a command) — and wraps the node's
framework-free ``asgi()`` with the run-level concerns the node does not own:
bounded in-flight admission (503), a per-request timeout (504), and graceful
node shutdown.

Configuration — the ``ServeConfig`` model, the flag > env > url4.toml >
default resolution, the TOML decoders, and pre-bind validation — lives in
:mod:`url4.cli._config`; its public names are re-exported here, so this module
stays the one import surface for the serve path. What decides WHAT a node
serves and what RUNS it are different reasons to change.

# INVARIANT: this module imports no web framework and no HTTP client. Serving is
# the existing ``Url4Node.asgi()`` (raw ASGI) run under uvicorn (the
# ``url4[server]`` extra); Starlette is never involved. The core import graph
# stays framework-free.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path

from url4.cli._config import _HEALTH_PATH, ConfigError, ProviderSpec, ServeConfig, resolve
from url4.core.errors import ErrorCode, ResolutionError
from url4.io.layer import resolve_shelf
from url4.peer._asgi import lifespan as _lifespan
from url4.peer._asgi import send_error as _send_error
from url4.peer.server import Request, Url4Node

EndpointHandler = Callable[[Request], Awaitable[str]]
HoldingsHandler = Callable[[str | None], Awaitable[str]]
DataCallable = Callable[[], Awaitable[str]]

# --- backend handlers ------------------------------------------------------------


COMMAND_STDIN_SOURCES = ("context", "intent")
"""Which half of the :class:`~url4.peer.server.Request` a command route receives on stdin.

The legal set lives HERE because :func:`make_command_handler` is the only thing that can honour
it. A second consumer (the url4-cloud Runner's ``[commands]`` table) validates by passing the
operator's string through and translating the ``ValueError``, rather than keeping a copy that is
free to drift.
"""


def make_command_handler(
    argv: Sequence[str], timeout: float, *, stdin: str = "context"
) -> EndpointHandler:
    """An intent processor that runs a local subprocess (doctrine N4).

    The argv template mirrors the full :class:`~url4.peer.server.Request` surface a
    Python endpoint handler sees (1:1): ``{intent}``, ``{context}``,
    ``{param:<name>}`` (one decoded protocol param, "" when absent),
    and ``{params}`` (the whole mapping as JSON, for backends that want
    everything).

    ``stdin`` selects what is PIPED, independently of what is substituted — a route
    reading its payload from the pipe still gets ``{context}`` in argv. It defaults to
    ``"context"``, which is the only behaviour that existed before and what a bare
    ``cat`` route relies on.

    WHY the selector exists: a single argv token is capped by the kernel at
    ``MAX_ARG_STRLEN`` (32 pages = 131,072 bytes) regardless of ``ARG_MAX``, and exec
    fails outright with ``OSError [Errno 7]`` rather than truncating. A processor whose
    intent is engine-supplied — a cross-row reducer receives the JSON array of every row
    result — crosses that in ordinary use, and argv is then simply the wrong channel.
    A pipe has no such bound.

    # AIDEV-NOTE: security — the argv is OPERATOR config; only the piped stdin and the
    # token substitutions are caller-influenced. Selecting ``intent`` does not widen
    # that: intent is already caller-influenced and already reachable as ``{intent}``.
    # It NARROWS exposure — an argv token is visible in /proc/<pid>/cmdline to every
    # local reader, while a pipe is not, so a large payload belongs on stdin on those
    # grounds alone.
    # No shell: exec an argv LIST, never a command string.
    # INVARIANT: substitution is single-pass — tokens are recognized in the
    # operator's template only, so a "{param:x}" (or "{intent}") appearing in
    # caller-supplied intent, context, or param values stays literal instead
    # of cascading (blocks token-injection through caller input). stdin has never
    # been a substitution target, so the selector cannot affect that.

    # CONTRACT: a command route is not guaranteed to run at most once. A timeout is
    # reported as a transient error, and a `;retry=N` source retries it, so the same
    # command may run again after its side effect already landed. Command routes MUST
    # be idempotent.
    """
    if stdin not in COMMAND_STDIN_SOURCES:
        raise ValueError(f"stdin must be one of {list(COMMAND_STDIN_SOURCES)}, got {stdin!r}")
    template = tuple(argv)
    want_intent = stdin == "intent"

    async def handler(request: Request) -> str:
        command = _subst_all(template, request)
        piped = request.intent if want_intent else request.context
        return await _run_command(command, piped, timeout)

    return handler


_SUBST_TOKEN_RE = re.compile(r"\{(intent|context|params|param:([A-Za-z0-9_.\-]+))\}")


def _subst_all(template: Sequence[str], request: Request) -> list[str]:
    """Substitute the ``{...}`` tokens across every argv token of ``template``.

    The whole argv is done in one pass so ``{params}`` serializes at most once
    per request, rather than once per occurrence inside the ``re.sub`` callback.
    """
    params_json: str | None = None

    def replacement(match: re.Match[str]) -> str:
        nonlocal params_json
        kind = match.group(1)
        if kind == "params":
            if params_json is None:
                params_json = json.dumps(dict(sorted(request.params.items())))
            return params_json
        if kind.startswith("param:"):
            return request.params.get(match.group(2), "")
        return request.intent if kind == "intent" else request.context

    return [_SUBST_TOKEN_RE.sub(replacement, token) for token in template]


async def _run_command(command: list[str], stdin_text: str, timeout: float) -> str:
    """Run one argv to completion and return its stdout (stdout is the result).

    # CONTRACT: a timeout kills the process and raises a NON-permanent
    # :class:`~url4.core.errors.ResolutionError`, so a `;retry=N` source retries it.
    # The engine cannot tell "did not run" from "ran but the answer was lost", so
    # commands MUST be idempotent.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ResolutionError(f"command {command[0]!r} failed to start: {exc}") from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode()), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise ResolutionError(f"command {command[0]!r} timed out after {timeout}s") from None
    if proc.returncode != 0:
        raise ResolutionError(
            f"command {command[0]!r} exited {proc.returncode}: "
            f"{err.decode(errors='replace')[:500].strip()}"
        )
    # errors='replace': a command that emits non-UTF-8 bytes must not escape the
    # handler's ResolutionError contract as a raw UnicodeDecodeError (→ bare 500).
    return out.decode(errors="replace")


# --- read-side providers ----------------------------------------------------------


async def _provide(spec: ProviderSpec, timeout: float, collection: str | None = None) -> str:
    """Serve one read from its declared source (value, file, or command).

    File reads happen per request in a worker thread (never on the loop) so
    operators can edit the backing file without a restart — the same liveness
    a command provider gets by running per request. A missing/unreadable file
    is the source's failure, not the node's: ResolutionError, like a failing
    command.
    """
    if spec.value is not None:
        return spec.value
    if spec.file is not None:
        try:
            return await asyncio.to_thread(Path(spec.file).read_text, encoding="utf-8")
        except OSError as exc:
            raise ResolutionError(f"data file {spec.file!r} cannot be read: {exc}") from exc
    if spec.command is not None:
        argv = [token.replace("{collection}", collection or "") for token in spec.command]
        return await _run_command(argv, "", timeout)
    # Unreachable: _as_provider guarantees exactly one source is set.
    raise ResolutionError("provider declares no source")  # pragma: no cover


def make_data_provider(spec: ProviderSpec, timeout: float) -> DataCallable:
    """A ``Url4Node.data`` provider backed by a :class:`ProviderSpec`."""

    async def provider() -> str:
        return await _provide(spec, timeout)

    return provider


def make_shelf_handler(spec: ProviderSpec, timeout: float) -> HoldingsHandler:
    """A ``Url4Node.holdings`` handler for one declared ``@`` shelf.

    The handler receives the *requested* collection (the node falls back to the
    default shelf for undeclared collections), so a default-shelf ``command``
    provider can branch on it via the ``{collection}`` argv substitution.
    """

    async def handler(collection: str | None) -> str:
        return await _provide(spec, timeout, collection)

    return handler


def make_identity_handler(
    name: str, shelves: Mapping[str | None, ProviderSpec], timeout: float
) -> HoldingsHandler:
    """A ``Url4Node.identity`` handler dispatching over a principal's shelves.

    The node keeps ONE handler per identity (it has no per-collection registry
    for principals), so the exact-collection-then-default fallback lives here —
    deliberately mirroring ``Url4Node.fetch_holdings``'s self-holdings lookup
    so ``@`` and ``@name`` resolve collections identically.
    """

    async def handler(collection: str | None) -> str:
        spec = resolve_shelf(shelves, collection)
        if spec is None:
            raise ResolutionError(
                f"identity {name!r} serves no holdings for collection {collection!r}"
            )
        return await _provide(spec, timeout, collection)

    return handler


# --- node + ASGI assembly --------------------------------------------------------


def build_node(config: ServeConfig) -> Url4Node:
    """Assemble a :class:`Url4Node`: endpoints per command, plus the read registries."""
    node = Url4Node(
        "url4-serve",
        eval_path=config.eval_path,
        default_processor=config.resolved_default_route,
        concurrency=config.concurrency,
    )
    node.data(_HEALTH_PATH, "ok")
    for path, argv in config.commands.items():
        node.endpoint(path)(make_command_handler(argv, config.timeout))
    for path, spec in config.data.items():
        node.data(path, make_data_provider(spec, config.timeout), media_type=spec.media_type)
    for collection, spec in config.holdings.items():
        node.holdings(collection)(make_shelf_handler(spec, config.timeout))
    for name, shelves in config.identities.items():
        node.identity(name)(make_identity_handler(name, shelves, config.timeout))
    return node


AsgiApp = Callable[[Mapping, Callable, Callable], Awaitable[None]]


def build_asgi_app(node: Url4Node, config: ServeConfig) -> AsgiApp:
    """Wrap ``node.asgi()`` with admission control, timeout, and shutdown cleanup.

    The node owns dispatch and ``Url4Error`` -> HTTP mapping; this wrapper adds only
    what the node does not: 503 over max-inflight, 504 on per-request timeout, and
    closing the node on lifespan shutdown.
    """
    base = node.asgi()
    state = {"inflight": 0}

    async def app(scope: Mapping, receive: Callable, send: Callable) -> None:
        if scope["type"] == "lifespan":
            await _lifespan(receive, send, on_shutdown=node.aclose)
        elif scope["type"] == "http":
            await _serve_http(base, scope, receive, send, state, config)
        else:  # pragma: no cover - no websocket surface in v1
            await base(scope, receive, send)

    return app


async def _serve_http(base, scope, receive, send, state, config: ServeConfig) -> None:
    if state["inflight"] >= config.max_inflight:
        # INVARIANT: check-then-increment is atomic on the single-threaded loop (no
        # await between), so two requests can never both pass a full gate.
        await _send_error(
            send, 503, "overloaded", "server at capacity, retry shortly", retry_after=1
        )
        return
    state["inflight"] += 1
    guard = _StartGuard(send)
    try:
        async with asyncio.timeout(config.timeout):
            await base(scope, receive, guard.send)
    except TimeoutError:
        if not guard.started:  # nothing sent yet — the node computes the body before sending
            await _send_error(
                send, 504, ErrorCode.TIMEOUT, f"evaluation exceeded {config.timeout}s"
            )
    finally:
        state["inflight"] -= 1


class _StartGuard:
    """Tracks whether the response has started, so timeout can't double-send."""

    def __init__(self, send: Callable) -> None:
        self._send = send
        self.started = False

    async def send(self, message: Mapping) -> None:
        # INVARIANT: at most one ``http.response.start`` crosses this guard per
        # request — ``started`` is exactly what lets the 504 timeout path know
        # the response already began, so it never double-sends.
        if message["type"] == "http.response.start":
            self.started = True
        await self._send(message)


__all__ = [
    "COMMAND_STDIN_SOURCES",
    "ConfigError",
    "DataCallable",
    "EndpointHandler",
    "HoldingsHandler",
    "ProviderSpec",
    "ServeConfig",
    "build_asgi_app",
    "build_node",
    "make_command_handler",
    "make_data_provider",
    "make_identity_handler",
    "make_shelf_handler",
    "resolve",
]

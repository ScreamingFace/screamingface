"""Configuration, backend handlers, and node/app assembly for ``url4 serve``.

This is the transport-adapter layer behind the CLI (:mod:`url4.cli`). It builds a
:class:`~url4.peer.server.Url4Node` from a :class:`ServeConfig` — registering one
intent-processor endpoint per configured ``[commands]`` route (a local
subprocess, doctrine N4; there is no other intent-processor kind — a user's LLM
backend is their own gateway script mounted as a command) — and wraps the node's
framework-free ``asgi()`` with the run-level concerns the node does not own:
bounded in-flight admission (503), a per-request timeout (504), and graceful
node shutdown.

Beside the processor routes, the config wires the node's READ-side registries
(spec §5.4.2 relative data, §5.6 ``@``/``@name`` holdings): ``[data]`` maps a
path to a plain data read, ``[holdings]`` declares the node's own ``@``
shelves, and ``[identities.<name>]`` declares principals for ``@name``. All
three share one provider shape — an inline string, or a table with exactly one
of ``value`` / ``file`` / ``command`` — so a read backend follows the same
operator-owned model as a command route (a ``command`` provider IS doctrine N4
applied to reads).

# INVARIANT: this module imports no web framework and no HTTP client. Serving is
# the existing ``Url4Node.asgi()`` (raw ASGI) run under uvicorn (the
# ``url4[server]`` extra); Starlette is never involved. The core import graph
# stays framework-free.
"""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import tomllib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from url4.core.errors import ResolutionError

# WHY: the principal-name production belongs to the grammar, so config validation
# reads it from there — the same deliberate private-name import render.py and
# server.py make, for the same reason (re-declaring it would let the two drift).
# Importing it via url4.peer.server instead would lean on a re-export server never
# promised: it is absent from server's __all__, so a tidy-up there would break
# config validation with no signal.
from url4.core.grammar import _IDENTITY_NAME_RE
from url4.io.layer import resolve_shelf
from url4.peer._asgi import lifespan as _lifespan
from url4.peer._asgi import send_error as _send_error
from url4.peer.server import Request, Url4Node

_HEALTH_PATH = "/healthz"
# The TOML spelling of the unqualified shelf (`@` / `@name` with no collection
# path). TOML has no null key, so this reserved key normalizes to ``None`` at
# parse time — a collection literally named "default" cannot be declared, which
# mirrors how the node itself treats ``None`` as the fallback shelf.
_DEFAULT_COLLECTION = "default"

EndpointHandler = Callable[[Request], Awaitable[str]]
HoldingsHandler = Callable[[str | None], Awaitable[str]]
DataCallable = Callable[[], Awaitable[str]]


class ConfigError(ValueError):
    """A serve configuration is invalid — raised before bind (fail-fast)."""


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """One declared read backend: exactly one of ``value``/``file``/``command``.

    ``value`` serves inline text, ``file`` reads a file per request (live —
    edits need no restart, mirroring how commands run per request), ``command``
    runs an argv template (no shell, empty stdin; ``{collection}`` substitutes
    the requested holdings collection). ``media_type`` declares a data route's
    Content-Type so collections served there parse by type, not by sniffing
    (spec §5.3.7) — it is meaningless for holdings, which carry no type channel.
    """

    value: str | None = None
    file: str | None = None
    command: tuple[str, ...] | None = None
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class ServeConfig:
    """Everything ``url4 serve`` needs, resolved from flags > env > toml > default.

    ``commands`` is the ONLY backend registry: url4.toml ``[commands]`` maps a
    route path to an operator-owned argv template. ``default_route`` names the
    command a fan-out reduce dispatches to; unset, the FIRST declared command
    is used (see :attr:`resolved_default_route`).
    """

    host: str = "127.0.0.1"
    port: int = 4404
    default_route: str | None = None
    eval_path: str = "/v1"
    concurrency: int = 32
    max_inflight: int = 16
    timeout: float = 120.0
    commands: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Read-side registries (url4.toml only, like commands — never flags/env).
    # Holdings/identity collection keys are ``None`` for the default shelf
    # ("default" in TOML, normalized at parse time).
    data: Mapping[str, ProviderSpec] = field(default_factory=dict)
    holdings: Mapping[str | None, ProviderSpec] = field(default_factory=dict)
    identities: Mapping[str, Mapping[str | None, ProviderSpec]] = field(default_factory=dict)

    def validate(self) -> None:
        """Raise :class:`ConfigError` for any unusable setting, before bind."""
        _require(self.concurrency >= 1, f"concurrency must be >= 1, got {self.concurrency}")
        _require(self.max_inflight >= 1, f"max-inflight must be >= 1, got {self.max_inflight}")
        _require(self.timeout > 0, f"timeout must be > 0, got {self.timeout}")
        # INVARIANT: an empty host is never a loopback bind — it binds 0.0.0.0 AND ::
        # (every interface) while reading as "unset", and it would slip past the
        # non-loopback exposure warnings that are v1's only control in front of the
        # command routes (arbitrary local execution). `_pick` normalizes an empty
        # URL4_HOST away; this covers the explicit `--host ""` flag, which it cannot.
        _require(
            bool(self.host),
            "host cannot be empty — bind 127.0.0.1, or 0.0.0.0 for every interface",
        )
        # The eval path is a route like any other: it must be a path.
        _require_paths({self.eval_path: None}, "eval")
        # WHY: the connector is gone — the operator owns every backend, so a
        # node with zero commands has nothing to dispatch to. Fail fast.
        _require(
            bool(self.commands),
            "url4 serve requires at least one [commands] route in url4.toml — "
            "define your backends as commands (e.g. your own gateway script)",
        )
        _require_paths(self.commands, "command")
        _require_argv(self.commands)
        reserved = {self.eval_path, _HEALTH_PATH} & set(self.commands)
        _require(not reserved, f"command paths clash with reserved {sorted(reserved)}")
        # Data routes share the node's path namespace with commands and the
        # reserved routes — a clash would surface as an uncaught ValueError at
        # build time (`Url4Node._check_routable`); reject it pre-bind instead.
        _require_paths(self.data, "data")
        data_reserved = {self.eval_path, _HEALTH_PATH} & set(self.data)
        _require(not data_reserved, f"data paths clash with reserved {sorted(data_reserved)}")
        overlap = set(self.data) & set(self.commands)
        _require(not overlap, f"data paths clash with command routes {sorted(overlap)}")
        # INVARIANT: `{eval_path}/…` is the self-holdings qualifier namespace
        # (spec §5.6.3.1) — `GET /v1/science?q=(@)!'…'` scopes `@` to the
        # "science" shelf. A command or data route declared under it would
        # shadow every qualifier below that path (endpoints match first in
        # `_dispatch`), so reject it here rather than let one silently win.
        prefix = f"{self.eval_path}/"
        shadowed = sorted(p for p in (*self.commands, *self.data) if p.startswith(prefix))
        _require(
            not shadowed,
            f"routes {shadowed} live under the eval path {self.eval_path!r}, which is "
            f"reserved for self-holdings qualifiers (@ collections) — mount them elsewhere",
        )
        # INVARIANT: identity names must satisfy the node's own registration
        # rule (`Url4Node.identity`) — checking it here keeps the failure a
        # clean pre-bind ConfigError instead of a build-time ValueError.
        for name in self.identities:
            _require(
                bool(_IDENTITY_NAME_RE.fullmatch(name)),
                f"identity name {name!r} must match {_IDENTITY_NAME_RE.pattern!r}",
            )
        # The node registers /healthz as a data route; an eval path equal to it
        # would collide at build time (an uncaught ValueError) — reject it here so
        # the misconfiguration fails fast with a clean config error before bind.
        _require(
            self.eval_path != _HEALTH_PATH,
            f"eval path cannot be the reserved health path {_HEALTH_PATH!r}",
        )
        # INVARIANT: a fan-out reduce dispatches to the default route at
        # runtime, so an EXPLICIT one must be a declared command or the reduce
        # fails mid-evaluation.
        if self.default_route is not None:
            _require(
                self.default_route in self.commands,
                f"default route {self.default_route!r} is not a declared command "
                f"route: {sorted(self.commands)}",
            )

    @property
    def resolved_default_route(self) -> str:
        """The reduce route: the explicit ``default_route``, else the first command.

        # INVARIANT: only meaningful after :meth:`validate` — commands is
        # non-empty and an explicit default_route is declared.
        """
        if self.default_route is not None:
            return self.default_route
        return next(iter(self.commands))


def _require(ok: bool, message: str) -> None:  # noqa: FBT001 - tiny internal guard
    if not ok:
        raise ConfigError(message)


def _require_paths(paths: Mapping[str, object], label: str) -> None:
    for path in paths:
        _require(path.startswith("/"), f"{label} path {path!r} must start with '/'")


def _require_argv(commands: Mapping[str, tuple[str, ...]]) -> None:
    for path, argv in commands.items():
        _require(bool(argv), f"command {path!r} has an empty argv")


# --- config resolution -----------------------------------------------------------


def resolve(
    overrides: Mapping[str, object], env: Mapping[str, str], toml_path: Path | None
) -> ServeConfig:
    """Build a :class:`ServeConfig` — flag > env > url4.toml > default, per field.

    ``overrides`` holds CLI flag values (``None`` == unset). Commands come from
    url4.toml ``[commands]`` only — argv templates are operator config, not
    something to squeeze through a flag.
    """
    toml = _read_toml(toml_path)
    raw_route = _pick("default_route", overrides, env, toml)
    return ServeConfig(
        host=_pick_str("host", overrides, env, toml, "127.0.0.1"),
        port=_pick_int("port", overrides, env, toml, 4404),
        default_route=None if raw_route is None else str(raw_route),
        eval_path=_pick_str("eval_path", overrides, env, toml, "/v1"),
        concurrency=_pick_int("concurrency", overrides, env, toml, 32),
        max_inflight=_pick_int("max_inflight", overrides, env, toml, 16),
        timeout=_pick_float("timeout", overrides, env, toml, 120.0),
        commands=_toml_command_map(toml.get("commands")),
        data=_toml_data_map(toml.get("data")),
        holdings=_toml_shelf_map(toml.get("holdings"), "holdings"),
        identities=_toml_identity_map(toml.get("identities")),
    )


def _pick(
    name: str, overrides: Mapping[str, object], env: Mapping[str, str], toml: Mapping
) -> object:
    flag = overrides.get(name)
    if flag is not None:
        return flag
    # WHY: an empty env var is an UNSET var, not an empty value — `URL4_HOST=` in a
    # .env/compose file is an unresolved interpolation. Taking it literally let every
    # string field silently adopt "", and host="" binds 0.0.0.0 AND :: (every
    # interface) while reading as "default". Int fields already rejected "" loudly;
    # this makes strings consistent with them by falling through to toml > default.
    from_env = env.get(f"URL4_{name.upper()}")
    if from_env:
        return from_env
    return toml.get(name)


def _pick_str(name, overrides, env, toml, default: str) -> str:
    value = _pick(name, overrides, env, toml)
    return default if value is None else str(value)


def _pick_int(name, overrides, env, toml, default: int) -> int:
    value = _pick(name, overrides, env, toml)
    if value is None:
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer, got {value!r}") from None


def _pick_float(name, overrides, env, toml, default: float) -> float:
    value = _pick(name, overrides, env, toml)
    if value is None:
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a number, got {value!r}") from None


def _read_toml(path: Path | None) -> Mapping[str, object]:
    if path is None:
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read config {str(path)!r}: {exc}") from exc


def _toml_command_map(value: object) -> dict[str, tuple[str, ...]]:
    return {str(k): _as_argv(v) for k, v in value.items()} if isinstance(value, Mapping) else {}


def _as_argv(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(shlex.split(value))
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    raise ConfigError(f"command must be a string or list, got {value!r}")


def _toml_data_map(value: object) -> dict[str, ProviderSpec]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"[data] must be a table, got {value!r}")
    return {
        str(path): _as_provider(spec, f"data route {path!r}", allow_media_type=True)
        for path, spec in value.items()
    }


def _toml_shelf_map(value: object, label: str) -> dict[str | None, ProviderSpec]:
    """Parse a collection→provider table, normalizing "default" to ``None``."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"[{label}] must be a table, got {value!r}")
    shelves: dict[str | None, ProviderSpec] = {}
    for key, spec in value.items():
        collection = str(key)
        _require(bool(collection), f"[{label}] collection name cannot be empty")
        normalized = None if collection == _DEFAULT_COLLECTION else collection
        shelves[normalized] = _as_provider(spec, f"{label} collection {collection!r}")
    return shelves


def _toml_identity_map(value: object) -> dict[str, dict[str | None, ProviderSpec]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"[identities] must be a table, got {value!r}")
    return {
        str(name): _toml_shelf_map(shelves, f"identities.{name}") for name, shelves in value.items()
    }


def _as_provider(value: object, label: str, *, allow_media_type: bool = False) -> ProviderSpec:
    """Normalize one provider declaration — an inline string or a one-source table."""
    if isinstance(value, str):
        return ProviderSpec(value=value)
    if not isinstance(value, Mapping):
        raise ConfigError(f"{label} must be a string or a table, got {value!r}")
    known = {"value", "file", "command"} | ({"media_type"} if allow_media_type else set())
    unknown = set(map(str, value)) - known
    _require(not unknown, f"{label} has unknown keys {sorted(unknown)} (expected {sorted(known)})")
    sources = [key for key in ("value", "file", "command") if value.get(key) is not None]
    _require(
        len(sources) == 1,
        f"{label} must declare exactly one of value/file/command, got {sources or 'none'}",
    )
    media_type = value.get("media_type")
    spec = ProviderSpec(
        value=None if "value" not in sources else str(value["value"]),
        file=None if "file" not in sources else str(value["file"]),
        command=None if "command" not in sources else _as_argv(value["command"]),
        media_type=None if media_type is None else str(media_type),
    )
    if spec.command is not None:
        _require(bool(spec.command), f"{label} has an empty command argv")
    return spec


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
            await _send_error(send, 504, "timeout", f"evaluation exceeded {config.timeout}s")
    finally:
        state["inflight"] -= 1


class _StartGuard:
    """Tracks whether the response has started, so timeout can't double-send."""

    def __init__(self, send: Callable) -> None:
        self._send = send
        self.started = False

    async def send(self, message: Mapping) -> None:
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

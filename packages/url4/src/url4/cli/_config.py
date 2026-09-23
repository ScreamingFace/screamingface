"""Serve configuration: the models, their resolution, and their validation.

Split out of :mod:`url4.cli._serve`: the url4.toml contract is an operator-facing
product surface with its own rate of change, while the subprocess handlers and
the ASGI assembly change for other reasons. This module owns everything that
decides WHAT a node serves — ``ServeConfig``, the flag > env > url4.toml >
default resolution, the TOML decoders, and the pre-bind validation. The public
names are re-exported from :mod:`url4.cli._serve`, which stays the one import
surface for the serve path.

# INVARIANT: this module imports no web framework, no HTTP client, and no peer
# machinery — it is pure declaration and validation, safe to import for a
# dry-run config check.
"""

from __future__ import annotations

import shlex
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# WHY: the principal-name production belongs to the grammar, so config validation
# reads it from there — the same deliberate private-name import render.py and
# server.py make, for the same reason (re-declaring it would let the two drift).
# Importing it via url4.peer.server instead would lean on a re-export server never
# promised: it is absent from server's __all__, so a tidy-up there would break
# config validation with no signal.
from url4.core.grammar import _IDENTITY_NAME_RE

_HEALTH_PATH = "/healthz"
# The TOML spelling of the unqualified shelf (`@` / `@name` with no collection
# path). TOML has no null key, so this reserved key normalizes to ``None`` at
# parse time — a collection literally named "default" cannot be declared, which
# mirrors how the node itself treats ``None`` as the fallback shelf.
_DEFAULT_COLLECTION = "default"


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


__all__ = ["ConfigError", "ProviderSpec", "ServeConfig", "resolve"]

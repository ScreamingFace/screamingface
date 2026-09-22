"""The Engine's declared world — ``url4.toml``, read once at startup.

Both the control plane and Runner consume this module. Discovery must project onto the exact
configuration the Runner executes; a second partial TOML reader would let the two disagree.

Endpoints are DECLARED, never discovered. A route path is exactly
``"/" + gateway_id``: no renaming and no synthesized aliases. Gateway ids are unique by
construction (they are aigateway's own registry keys), so route uniqueness is inherited
rather than re-derived.

WHY declared: the aliasing this replaces derived a bare name via ``split("/", 1)[-1]``, which
turned ``openrouter/openai/gpt-5.5`` into ``/openai/gpt-5.5`` (reads as the OpenAI API, bills
OpenRouter) and ``openrouter/anthropic/claude-opus-4.8`` into ``/anthropic/claude-opus-4.8``.
Aliases were also collision-dependent, so adding a model elsewhere in the catalog could
silently REMOVE an alias an expression depended on.

The file format mirrors ``url4 serve``'s (``url4.cli._serve``), one way stricter: a model id here
must also be renderable as a URL4 expression path (see ``models.registry.ROUTE_ID_RE``).

The MODEL LIST itself lives in
:data:`screamingface_engine.world.models.builtins.BUILTIN_MODEL_WORLD`, seeded from every
aigateway provider plugin (OME-859). This module merges that world with the optional,
additive ``[[aigateway.models]]`` array, so one function still produces the single
world both halves consume.

``[data]``, ``[holdings]`` and ``[identities]`` are parsed here (F3, prd/02) and delegated to
url4's own resolvers, so provider semantics have exactly one owner. ``[commands]`` stays reserved:
its argv templates are exec mounts and the node tier has no sandbox for them, so declaring one is
a loud error — a config that looks like it works must not silently serve nothing. A
``command``-backed provider is refused in EVERY read-side section for the same reason (R12):
url4 runs a subprocess for it wherever it is declared, so ``[data]``, ``[holdings]`` and
``[identities]`` all reject it at load rather than expose the exec surface at the node tier.

# AIDEV-NOTE: delegation to url4's `_config` resolvers replaces the old duplication of
# `_serve.py`'s parsing (F3). The provider rules — value/file/command, the `default` shelf, the
# exact-then-default collection fallback — are url4's product contract, and a second parser here
# would let the engine and `url4 serve` disagree about the same file with no test able to see it.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from screamingface_engine import job_env
from screamingface_engine.world.models.builtins import BUILTIN_MODEL_WORLD
from screamingface_engine.world.models.registry import (
    ROUTE_ID_RE,
    ModelRegistry,
    decode_route_id,
    encode_route_id,
    is_route_legal,
)

# F3 (prd/02): the read-side section vocabularies are url4's, taken verbatim from its own serve
# config rather than re-declared. The `default`-shelf normalisation, the value/file/command
# provider rules, and the exact-then-default collection fallback are all owned there, so the
# engine cannot drift from what `url4 serve` would do with the same file. The private names are a
# deliberate cross-module reach, the same one url4's own `render.py`/`server.py` make, for the
# same reason: re-declaring them would let the two disagree.
from url4.cli._config import (
    ConfigError as Url4ConfigError,
)
from url4.cli._config import (
    ProviderSpec,
    _toml_data_map,
    _toml_identity_map,
    _toml_shelf_map,
)

DEFAULT_CONFIG_PATH = "/etc/url4/url4.toml"

"""Where the declared world lives unless :data:`job_env.RUNNER_CONFIG` overrides it. Image-level
wiring: the App never writes that variable — the file is baked into the image."""

DEFAULT_WEB_TOOL_MAX_ITERATIONS = 5

_AIGATEWAY_KEYS = frozenset(
    {
        "base_url",
        "default_route",
        "models",
        "allow_outbound",
        "timeout_s",
        "web_tool_max_iterations",
    }
)
_MODEL_KEYS = frozenset({"id", "web_search"})
# F3 (prd/02): `[commands]` is the ONE section still reserved. `[data]`, `[holdings]` and
# `[identities]` are now parsed (see `_parse_read_side`), so they are top-level keys, not reserved
# names — a declaration under one of them reaches url4's resolvers rather than a blanket error.
_RESERVED_TABLES = frozenset({"commands"})
_READ_SIDE_TABLES = frozenset({"data", "holdings", "identities"})
_TOP_LEVEL_KEYS = frozenset({"aigateway"} | _READ_SIDE_TABLES)


class WorldConfigError(ValueError):
    """The Runner's configuration is unusable — raised at startup, before any run."""


WEB_SEARCH_NATIVE_PROVIDERS = frozenset({"openrouter"})
"""Providers whose aigateway plugin carries a native web-search envelope.

A route served by one of these delegates retrieval to the provider; every other searching
route runs the Tavily tool loop here instead.

WHY only `openrouter`: `web_search` is declared by exactly one aigateway plugin
(`plugins/openrouter_provider/parameters.py`). The other plugins register bespoke
`custom_llm_provider` handlers — `codex` (OpenAI Codex OAuth), `gemini-cli` (Google Code
Assist), `antigravity`, and aigateway's own `anthropic` — rather than litellm's stock vendor
routes, so litellm's `web_search_options` is not reachable through them and a request
carrying an undeclared parameter is refused by the parameter contract.

AIDEV-NOTE: adding an entry here is NOT sufficient on its own. The provider's aigateway
plugin must first declare the parameter, build the envelope from one pure function shared by
the dispatch path and the cache-key projection, key the fields, and bump the cache adapter
revision (OME-777 invariant I1). This set is the LAST step of that work, not the first.
"""


_UNPREFIXED_PROVIDER = "anthropic"


def provider_of(model_id: str) -> str:
    """The provider that serves a route: the segment before the first `/`.

    WHY the segment and not a substring of the whole id: `openrouter/anthropic/claude-opus-4.8`
    is an OpenRouter route and must take OpenRouter's envelope. A substring test hands it to
    any future `anthropic` entry and silently sends it down the wrong provider's mechanism.

    INVARIANT: an id with no `/` is Anthropic's — aigateway's catalog leaves exactly that one
    provider unprefixed (`claude-haiku-4-5`), the `anthropic/` prefix appearing only in
    litellm_params.

    AIDEV-NOTE (OME-859): that INVARIANT is DOUBTFUL and the fallback looks unreachable. Every
    id `models/builtins.py` declares carries its provider prefix, because
    `models.registry.canonical_id` mirrors aigateway's `canonical_model_id`, which has NO
    per-provider exemption — the served id IS `anthropic/claude-haiku-4-5`, and believing
    otherwise is exactly what OME-795 was. The fallback is kept here only because
    `test_web_search_routing.py` pins it; removing it is a separate unit, not this one's
    business. If you touch this, settle the question rather than re-deriving the belief.
    """
    prefix, separator, _ = model_id.partition("/")
    return prefix if separator else _UNPREFIXED_PROVIDER


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """One declared route: the gateway id, plus whether it may search the web.

    A route is addressed as a table rather than a bare id so capabilities are declared WHERE
    the route is, not in a parallel list that can silently disagree with it.

    WHY only THAT it searches, never HOW: which mechanism a model can carry is a property of
    its provider, not a choice an operator should have to encode per route. Declaring the
    mechanism made the operator the keeper of that knowledge and let a route claim one its
    provider could not serve. The mechanism is therefore derived, and this file states intent.

    WHY the default is True: a deployment that supplies a Tavily key wants retrieval. The
    previous per-route opt-in meant a route stayed silently non-searching until somebody
    remembered to declare it. A route that must not search says so with `web_search = false`.
    """

    id: str
    web_search: bool = True

    @property
    def uses_native_web_search(self) -> bool:
        """The provider performs the search; the Runner only sets `web_search` on the body."""
        return self.web_search and provider_of(self.id) in WEB_SEARCH_NATIVE_PROVIDERS

    @property
    def uses_web_tools(self) -> bool:
        """The Runner performs the search itself, through the Tavily tool loop.

        INVARIANT: this and `uses_native_web_search` are mutually exclusive, and their
        disjunction is `web_search` — a searching route has exactly one mechanism.
        """
        return self.web_search and not self.uses_native_web_search


@dataclass(frozen=True, slots=True)
class AigatewaySection:
    """One declared aigateway world: which routes exist, and how to reach them."""

    base_url: str
    default_model: str
    models: tuple[ModelSpec, ...]
    allow_outbound: bool = True
    timeout_s: float = 60.0
    web_tool_max_iterations: int = DEFAULT_WEB_TOOL_MAX_ITERATIONS


@dataclass(frozen=True, slots=True)
class WorldConfig:
    """The whole declared world. ``aigateway is None`` is a legitimate tokenless world.

    ``data``/``holdings``/``identities`` are url4's own read-side registries, delegated verbatim
    (F3, prd/02). They are THIN wrappers: the engine keeps no provider semantics of its own, so a
    value/file/command decision is made in exactly one place (url4.cli._config) for both the node
    tier and a bare `url4 serve` node.
    """

    aigateway: AigatewaySection | None = None
    data: Mapping[str, ProviderSpec] = field(default_factory=dict)
    holdings: Mapping[str | None, ProviderSpec] = field(default_factory=dict)
    identities: Mapping[str, Mapping[str | None, ProviderSpec]] = field(default_factory=dict)


def routes_for(models: Sequence[ModelSpec]) -> dict[str, ModelSpec]:
    """Map each route path — ``"/" + id``, 1:1, no aliases — to the spec that declared it.

    The VALUE is the whole spec, not the bare id: the endpoint that serves a route needs the
    capability declared alongside it (`web_search`), and resolving it from the same lookup
    that resolves the id is what keeps a route and its capability from being fetched through
    two different paths that can disagree.
    """
    return {"/" + model.id: model for model in models}


def declared_model_ids(
    env: Mapping[str, str], *, registry: ModelRegistry = BUILTIN_MODEL_WORLD
) -> frozenset[str]:
    """Return the REAL gateway ids from the same fully validated world the Runner consumes.

    WHY decoded: this is what discovery compares against aigateway's own `GET /v1/models`
    response, whose `id` field is always the real (colon-bearing) id — `section.models[*].id`
    is the url4-ROUTE form (OME-873), and the two would never match for the 29 otherwise.
    """

    section = load_config(env, registry=registry).aigateway
    if section is None:
        return frozenset()
    return frozenset(decode_route_id(model.id) for model in section.models)


def load_config(
    env: Mapping[str, str],
    *,
    registry: ModelRegistry = BUILTIN_MODEL_WORLD,
    include_extra_models: bool = False,
) -> WorldConfig:
    """Read and validate the declared world from ``env``'s config path."""
    path = Path(env.get(job_env.RUNNER_CONFIG, DEFAULT_CONFIG_PATH))
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise WorldConfigError(f"cannot read world config {str(path)!r}: {exc}") from exc
    return parse_config(raw, env, registry=registry, include_extra_models=include_extra_models)


def parse_config(
    raw: Mapping[str, object],
    env: Mapping[str, str],
    *,
    registry: ModelRegistry = BUILTIN_MODEL_WORLD,
    include_extra_models: bool = False,
) -> WorldConfig:
    """Validate a parsed TOML mapping into a :class:`WorldConfig`. Fail-fast.

    INVARIANT: ``registry`` is the base world and the TOML array layers on top of it. Both the
    App and the Runner call through here, so their views of the world cannot diverge — the
    property that lets discovery promise exactly what execution accepts.

    ``include_extra_models`` (review F3): ``URL4_CLOUD_EXTRA_MODELS`` is a JOB-scoped
    key the App writes onto each scheduled run — only the Runner-boot path opts in.
    Default-off means the App's own parse (``declared_model_ids``) physically cannot
    absorb an ambient value: a leftover key can neither 503 discovery nor smuggle
    un-admitted ids into the declared projection.
    """
    _reject_unsupported_tables(raw)
    data, holdings, identities = _parse_read_side(raw)
    table = raw.get("aigateway")
    if table is None:
        return WorldConfig(data=data, holdings=holdings, identities=identities)
    if not isinstance(table, Mapping):
        raise WorldConfigError(f"[aigateway] must be a table, got {table!r}")
    return WorldConfig(
        aigateway=_parse_aigateway(table, env, registry, include_extra_models=include_extra_models),
        data=data,
        holdings=holdings,
        identities=identities,
    )


def _parse_read_side(
    raw: Mapping[str, object],
) -> tuple[
    dict[str, ProviderSpec],
    dict[str | None, ProviderSpec],
    dict[str, dict[str | None, ProviderSpec]],
]:
    """Parse `[data]`/`[holdings]`/`[identities]` through url4's own resolvers (F3).

    WHY delegate rather than re-implement: the provider kinds and the ``default``-shelf rule are
    url4's product contract; a second parser here would let the engine and `url4 serve` disagree
    about the same file with no test able to see it. url4 raises `ConfigError`, so it is translated
    to the engine's `WorldConfigError` at this boundary — callers catch one type.
    """
    try:
        data = _toml_data_map(raw.get("data"))
        holdings = _toml_shelf_map(raw.get("holdings"), "holdings")
        identities = _toml_identity_map(raw.get("identities"))
    except Url4ConfigError as exc:
        raise WorldConfigError(f"invalid world config: {exc}") from exc
    _reject_command_backed_read_side(data, holdings, identities)
    return data, holdings, identities


def _reject_command_backed_read_side(
    data: Mapping[str, ProviderSpec],
    holdings: Mapping[str | None, ProviderSpec],
    identities: Mapping[str, Mapping[str | None, ProviderSpec]],
) -> None:
    """Refuse a command-backed read-side provider — an exec mount the node tier cannot sandbox.

    WHY reject rather than skip: a skipped mount becomes a production 404 with no explanation,
    while this names each offending declaration so the operator fixes it.

    WHY every read-side section and not just ``[data]``: D2's table restricts only ``[data]``,
    but a ``command`` provider is an exec surface wherever it is declared. url4's ``_provide``
    runs ``asyncio.create_subprocess_exec`` for a command source regardless of the mount kind
    (``cli/_serve.py``), so a ``[holdings]``/``[identities]`` command is the same unsandboxed
    subprocess on the same network-reachable node tier that F3 rejects for ``[commands]``. R12
    (test-plan §2) names a command-backed provider explicitly; resolving the spec inconsistency
    in R12's direction is what keeps its mitigation true.
    """
    offenders = sorted(
        label
        for label, spec in _read_side_providers(data, holdings, identities)
        if spec.command is not None
    )
    if not offenders:
        return
    raise WorldConfigError(
        f"{offenders} use a 'command' provider — command-backed providers are exec mounts "
        "with no sandbox on the node tier, so they are rejected in v1; declare a 'value' or "
        "'file' provider instead"
    )


def _read_side_providers(
    data: Mapping[str, ProviderSpec],
    holdings: Mapping[str | None, ProviderSpec],
    identities: Mapping[str, Mapping[str | None, ProviderSpec]],
) -> Iterator[tuple[str, ProviderSpec]]:
    """Every declared read-side provider as ``(label, spec)``, label naming section and shelf.

    The label is what the rejection error reports, so an operator sees ``[holdings] 'secret'``
    rather than a bare provider kind they cannot locate in the file.
    """
    for path, spec in data.items():
        yield f"[data] {path!r}", spec
    for collection, spec in holdings.items():
        yield f"[holdings] {_shelf_name(collection)}", spec
    for name, shelves in identities.items():
        for collection, spec in shelves.items():
            yield f"[identities.{name}] {_shelf_name(collection)}", spec


def _shelf_name(collection: str | None) -> str:
    return "default" if collection is None else repr(collection)


def _reject_unsupported_tables(raw: Mapping[str, object]) -> None:
    declared = set(map(str, raw))
    reserved = sorted(declared & _RESERVED_TABLES)
    if reserved:
        raise WorldConfigError(
            f"{reserved} is not supported — read-side mounts are declared with [data], [holdings] "
            "and [identities]; [commands] registers argv templates as exec mounts, which is "
            "deferred deliberately (not forgotten) until a sandboxed tier can run them"
        )
    unknown = sorted(declared - _TOP_LEVEL_KEYS - _RESERVED_TABLES)
    if unknown:
        raise WorldConfigError(
            f"unknown top-level table(s) {unknown} (expected {sorted(_TOP_LEVEL_KEYS)})"
        )


def _parse_aigateway(
    table: Mapping[str, object],
    env: Mapping[str, str],
    registry: ModelRegistry,
    *,
    include_extra_models: bool = False,
) -> AigatewaySection:
    unknown = sorted(set(map(str, table)) - _AIGATEWAY_KEYS)
    if unknown:
        raise WorldConfigError(
            f"[aigateway] has unknown key(s) {unknown} (expected {sorted(_AIGATEWAY_KEYS)})"
        )
    models = _merge(registry, _declared_models(table.get("models")))
    section = AigatewaySection(
        base_url=_str(table, "base_url", "http://127.0.0.1:9105"),
        default_model=_normalize_id(_str(table, "default_route", "")),
        models=models,
        allow_outbound=_bool(table, "allow_outbound", default=True),
        timeout_s=_float(table, "timeout_s", 60.0),
        web_tool_max_iterations=_positive_int(
            table,
            "web_tool_max_iterations",
            DEFAULT_WEB_TOOL_MAX_ITERATIONS,
        ),
    )
    section = _apply_env(section, env)
    if include_extra_models:
        section = _apply_extra_models(section, env)
    _reject_unroutable_default(section.default_model)
    # WHY `section.models` and not the local `models` (review F2): the default may
    # legitimately arrive via the admitted overlay — validating against the
    # pre-overlay tuple would refuse a world that DOES declare it.
    _require_declared(section.default_model, section.models)
    return section


def _apply_extra_models(section: AigatewaySection, env: Mapping[str, str]) -> AigatewaySection:
    """Merge dynamically admitted ids (OME-880) into the world — ADDITIVELY only.

    The App writes ``URL4_CLOUD_EXTRA_MODELS`` onto a run when the gateway has
    dynamically admitted models this deployment; the run's world must route them
    or the pre-spend admission promise breaks mid-run. An id already declared
    keeps its declared spec (the overlay can never weaken a compiled route);
    unknown ids are appended with the same defaults a compiled OpenRouter route
    gets (``ModelSpec`` defaults, ``web_search=True``).

    WHY malformed fails LOUD: this env is App-written, never caller input, so an
    unreadable value is a bug — dropping it silently would resurface as a
    mid-run 404 with no trail back to the cause.
    """
    raw = env.get(job_env.EXTRA_MODELS)
    if raw is None or not raw.strip():
        return section
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise WorldConfigError(f"{job_env.EXTRA_MODELS} is not valid JSON: {raw!r}") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WorldConfigError(
            f"{job_env.EXTRA_MODELS} must be a JSON array of model ids, got {raw!r}"
        )
    for model_id in value:
        if ":" in model_id or not is_route_legal(model_id):
            raise WorldConfigError(
                f"{job_env.EXTRA_MODELS} entry {model_id!r} cannot be a url4 route"
            )
    declared_ids = {model.id for model in section.models}
    extras = tuple(ModelSpec(id=model_id) for model_id in value if model_id not in declared_ids)
    if not extras:
        return section
    return replace(section, models=section.models + extras)


def _apply_env(section: AigatewaySection, env: Mapping[str, str]) -> AigatewaySection:
    """Env beats the file, per field — a deployment overrides without rebuilding the image.

    The token is deliberately NOT here: it is a secret and never lands in a config file.
    """
    if env.get(job_env.AIGATEWAY_BASE_URL):
        section = replace(section, base_url=env[job_env.AIGATEWAY_BASE_URL])
    if env.get(job_env.AIGATEWAY_MODEL):
        section = replace(section, default_model=_normalize_id(env[job_env.AIGATEWAY_MODEL]))
    return section


def _reject_unroutable_default(default_model: str) -> None:
    """A `default_route` naming the REAL (colon-bearing) form of an id can never resolve.

    WHY a distinct error: `_require_declared` would report it as "not a declared model" beside
    a list of 88+ ids, which reads like a typo. The real cause is that the operator wrote the
    gateway's own id verbatim — the declared world only ever holds the `~`-encoded route form
    (OME-873), so this can never be a membership miss by coincidence.
    """
    if ":" in default_model:
        raise WorldConfigError(
            f"default_route {'/' + default_model!r} cannot be a route — it contains ':', which "
            f"no URL4 path segment may contain; use {'/' + encode_route_id(default_model)!r} "
            "(the same id with ':' encoded as '~') instead"
        )


def _require_declared(default_model: str, models: tuple[ModelSpec, ...]) -> None:
    ids = sorted(model.id for model in models)
    if default_model not in ids:
        # WHY truncate: the declared world is ~88 ids now that it comes from the compiled
        # registry, and a full dump buries the one id the operator got wrong.
        shown = ids[:10]
        suffix = f" (+{len(ids) - len(shown)} more)" if len(ids) > len(shown) else ""
        raise WorldConfigError(
            f"default_route {'/' + default_model!r} is not a declared model — "
            f"declared: {shown}{suffix}"
        )


def _declared_models(value: object) -> tuple[ModelSpec, ...]:
    """The `[[aigateway.models]]` array — OPTIONAL, because the registry is the base world.

    WHY it stayed after OME-859 moved the list into code: ollama discovers its models at run
    time and two provider seed lists are env-overridable
    (`AIGW_OPENROUTER_DEFAULT_MODELS`, `AIGW_HUGGINGFACE_DEFAULT_MODELS`), so a deployment must
    still be able to declare a route the compiled registry cannot know about.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise WorldConfigError(f"[aigateway] models must be a list, got {value!r}")
    models: list[ModelSpec] = []
    seen: set[str] = set()
    for entry in value:
        spec = _model_spec(entry)
        if spec.id in seen:
            raise WorldConfigError(f"[aigateway] declares duplicate model id {spec.id!r}")
        seen.add(spec.id)
        models.append(spec)
    return tuple(models)


def _merge(registry: ModelRegistry, declared: tuple[ModelSpec, ...]) -> tuple[ModelSpec, ...]:
    """The registry's routable AND aigateway-only ids, with the TOML array layered on top.

    INVARIANT: exactly one spec per ROUTE id. `routes_for` maps `"/" + id`, so a second spec
    for one route id would collapse silently and whichever lost would take its capability
    with it. The dict is keyed by the route id — `encode_route_id` of the real id — for every
    source, so a TOML override of an `aigateway_only` model (which can only ever name the
    encoded form; `ROUTE_ID_RE` bars a literal ':') lines up with the compiled entry it means
    to replace without any special-casing (OME-873).

    `ModelSpec.id` is therefore ALWAYS the url4-route form, for every entry, whether it came
    from the registry or from TOML. The real gateway id is recovered with `decode_route_id`
    exactly where a real request or a comparison against aigateway's own catalog needs it
    (`world/connector.py`, `catalog/executable.py`) — nowhere else needs to know the
    distinction.

    A TOML entry for a registry id REPLACES that spec, which is how `web_search = false` reaches
    a compiled route. A TOML entry for an unknown id is appended. Nothing removes an id: the
    declared world is exhaustive over aigateway's compiled seeds (OME-859 D1).
    """
    merged: dict[str, ModelSpec] = {
        model_id: ModelSpec(id=model_id) for model_id in sorted(registry.routable)
    }
    for model_id in sorted(registry.aigateway_only):
        route_id = encode_route_id(model_id)
        merged[route_id] = ModelSpec(id=route_id)
    for spec in declared:
        merged[spec.id] = spec
    if not merged:
        raise WorldConfigError(
            "[aigateway] must declare at least one model — neither the built-in world nor "
            "[[aigateway.models]] names one, and a world with no routes can serve nothing"
        )
    return tuple(merged.values())


def _model_spec(entry: object) -> ModelSpec:
    """One `[[aigateway.models]]` entry — a table, or a bare id string as shorthand.

    The string form is exactly ``{ id = "<it>" }``. It stays supported because "declare a
    plain route" should not require a table, and because both spellings take `web_search`'s
    default of true, so the two spellings cannot mean different things.
    """
    if isinstance(entry, Mapping):
        return _model_table(entry)
    if isinstance(entry, str):
        return ModelSpec(id=_model_id(entry))
    raise WorldConfigError(
        f"[aigateway] model entry must be a table or an id string, got {entry!r}"
    )


def _model_table(table: Mapping[str, object]) -> ModelSpec:
    unknown = sorted(set(map(str, table)) - _MODEL_KEYS)
    if unknown:
        raise WorldConfigError(
            f"[[aigateway.models]] has unknown key(s) {unknown} (expected {sorted(_MODEL_KEYS)})"
        )
    raw_id = table.get("id")
    if raw_id is None:
        raise WorldConfigError("[[aigateway.models]] entry is missing its `id`")
    value = table.get("web_search", True)
    if not isinstance(value, bool):
        raise WorldConfigError(f"[[aigateway.models]] web_search must be a boolean, got {value!r}")
    return ModelSpec(id=_model_id(str(raw_id)), web_search=value)


def _model_id(model: str) -> str:
    if not model:
        raise WorldConfigError("[aigateway] declares an empty model id")
    if model.startswith("/"):
        raise WorldConfigError(
            f"model id {model!r} must not start with '/' — the route path is derived as '/' + id"
        )
    if ROUTE_ID_RE.fullmatch(model) is None:
        raise WorldConfigError(
            f"model id {model!r} is not a valid URL4 expression path — each segment may contain "
            "only ASCII letters, digits, '-', '_', '.', or '~'"
        )
    return model


def _normalize_id(value: str) -> str:
    """Accept both ``/codex/gpt-5.5`` and ``codex/gpt-5.5`` — one leading slash only."""
    return value.removeprefix("/")


def _str(table: Mapping[str, object], key: str, default: str) -> str:
    value = table.get(key)
    return default if value is None else str(value)


def _bool(table: Mapping[str, object], key: str, *, default: bool) -> bool:
    value = table.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise WorldConfigError(f"[aigateway] {key} must be a boolean, got {value!r}")
    return value


def _float(table: Mapping[str, object], key: str, default: float) -> float:
    value = table.get(key)
    if value is None:
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise WorldConfigError(f"[aigateway] {key} must be a number, got {value!r}") from None


def _positive_int(table: Mapping[str, object], key: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WorldConfigError(f"[aigateway] {key} must be a positive integer, got {value!r}")
    return value


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AigatewaySection",
    "WorldConfig",
    "WorldConfigError",
    "declared_model_ids",
    "load_config",
    "parse_config",
    "routes_for",
]

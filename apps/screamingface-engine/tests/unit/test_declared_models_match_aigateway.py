"""The Runner's declared models must exist in aigateway's plugin registries.

PORTED FROM url4.json (OME-1183). Only `_RUNNER_CONFIG` and `_declared_default_route` touch the
config file — `_RUNNER_CONFIG` used to point at the real repo's
`apps/screamingface-engine/url4.json`, read with `tomllib.load`; it now points at this
directory's `url4.json`, read with `json.load`, and the value moved from `["aigateway"]` to
`["world"]`. In the real migration this constant would point at the renamed repo file
(`apps/screamingface-engine/url4.json`) instead of this draft copy. Nothing else in this file —
the `ast`-based plugin-registry extraction, the canonical-id mirror, the set-equality guards —
reads or depends on the config file format at all.

`_REPO_ROOT` is also adjusted for the draft's location: the original derived it as
`Path(__file__).resolve().parents[4]`, which found the repo root because the file lived inside
it (`apps/screamingface-engine/tests/unit/`). This draft copy lives in a scratchpad directory
outside the repo tree, so that arithmetic no longer lands on the repo root — it is hardcoded
below instead, purely so `_PLUGINS` can still find the real aigateway plugin sources this guard
reads. This has nothing to do with the TOML/JSON migration; it is a consequence of copying the
test out of its normal location to draft it.

Declaring endpoints buys deterministic routing; the cost is a second place to edit when a model
is added or removed. This guard makes that cost visible at CI time instead of at run time,
where a stale id becomes a `/v1/chat/completions` failure inside a user's expression.

The plugin lists are read with `ast` rather than imported: aigateway is a separate uv project
(pydantic, litellm) and is NOT installed in the screamingface-engine test environment. Source-level
extraction keeps the guard dependency-free and honest about what it checks — the literal slug
lists, which is exactly what drifts.

Providers whose registries are built at runtime (ollama discovers a local host, huggingface
fetches router slugs) are undeclarable by construction and are not covered here.

OpenRouter and HuggingFace sit between the two: their slugs ARE compiled into the plugin, as
each `_default_model_slugs()` returns, but a deployment can replace them wholesale via
`AIGW_OPENROUTER_DEFAULT_MODELS` / `AIGW_HUGGINGFACE_DEFAULT_MODELS`. They are covered against
those seeds — that catches the typo this guard exists for — with the standing caveat that a
deployment which overrides the env var has moved the target and is on its own.

OME-859 changed two things here.

1. The declared side is now `models/builtins.py::BUILTIN_MODEL_WORLD`, not `url4.json` — the
   list moved into code so it could be type-checked and validated at construction.
2. The assertion is SET EQUALITY, not containment. Containment is why this guard reported
   nothing while the gateway grew from 25 declared ids to 117 served ones: three seed PRs landed
   on 2026-08-17 alone (OME-816/817/818 via #581/#583, then OME-856), every one of them green
   here. Equality fails in both directions — a typo as declared-but-not-served, a missed seed PR
   as served-but-not-declared.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from screamingface_engine.models.builtins import BUILTIN_MODEL_WORLD

# Hardcoded, not `Path(__file__).resolve().parents[4]`: this draft lives in a scratchpad
# directory, not in `apps/screamingface-engine/tests/unit/`, so that arithmetic would no
# longer land on the repo root. See the module docstring.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLUGINS = _REPO_ROOT / "apps/aigateway/src/aigateway/plugins"
_RUNNER_CONFIG = _REPO_ROOT / "apps/screamingface-engine/url4.json"

# (source file, the assigned name holding the slug list, the plugin's `custom_llm_provider`).
#
# INVARIANT: the third field is the PROVIDER NAME, never a pre-computed prefix string. The
# gateway derives every public id through one universal rule (`canonical_model_id`), mirrored
# below in `_canonical` — so this table states only what the rule needs as input.
#
# AIDEV-NOTE: this used to carry a hand-written prefix per provider, with anthropic's set to ""
# on the belief that `/v1/models` advertised bare `claude-haiku-4-5`. `canonical_model_id` has
# no such exemption — it prefixes unless the slug already starts with `<provider>/` — so the
# gateway served `anthropic/claude-haiku-4-5` while url4.json declared the bare form, all five
# Anthropic routes silently dropped out of the projected catalog, and the declared default_route
# failed with `model must be provider-prefixed`. Twenty-six tests passed throughout (OME-795).
# Do not reintroduce a per-provider prefix column: four independent guesses drift, one rule
# cannot.
_SLUG_SOURCES = (
    ("anthropic_provider/settings.py", "names", "anthropic"),
    ("codex_provider/models.py", "_MODEL_SLUGS", "codex"),
    ("gemini_provider/models.py", "_MODEL_SLUGS", "gemini-cli"),
    ("antigravity_provider/settings.py", "names", "antigravity"),
)

# (source file, the function whose `return [...]` holds the slugs, the `custom_llm_provider`).
# WHY a separate table: these slugs are returned by a default-factory function rather than
# bound to a module-level name, so the assignment scan below cannot see them. OpenRouter's seeds
# are already spelled as full gateway ids (`openrouter/<author>/…`), which is precisely the
# already-prefixed case `_canonical` leaves alone.
_RETURNED_SLUG_SOURCES = (
    ("openrouter_provider/settings.py", "_default_model_slugs", "openrouter"),
    # OME-859: HuggingFace was absent from this table because it had no compiled list when the
    # guard was written; its models were built at run time from fetched router slugs. PR #583
    # gave it 24 compiled seeds, so 24 served ids were invisible to this guard entirely.
    ("huggingface_provider/settings.py", "_default_model_slugs", "huggingface"),
)


def _canonical(provider: str, slug: str) -> str:
    """The public id aigateway advertises for ``slug``, by aigateway's own rule.

    INVARIANT: mirrors `aigateway.core.model_capabilities.canonical_model_id` — keep the slug
    when it already begins with ``<provider>/``, otherwise prefix it. aigateway is a separate uv
    project and is NOT installed here, so this is a mirror rather than an import; it is one line
    of one rule, which is the smallest surface that can go stale.
    """
    prefix = f"{provider}/"
    return slug if slug.startswith(prefix) else f"{prefix}{slug}"


def _string_list_assigned_to(source: Path, name: str) -> tuple[str, ...]:
    """Every string literal in the first ``name = [...]`` assignment in ``source``."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            continue
        items = [
            e.value
            for e in node.value.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if items and len(items) == len(node.value.elts):
            return tuple(items)
    raise AssertionError(f"no `{name} = [...]` string list found in {source} — the guard is stale")


def _string_list_returned_by(source: Path, name: str) -> tuple[str, ...]:
    """Every string literal in the first ``return [...]`` inside ``def name`` in ``source``."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != name:
            continue
        for statement in ast.walk(node):
            if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.List):
                continue
            items = [
                e.value
                for e in statement.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if items and len(items) == len(statement.value.elts):
                return tuple(items)
    raise AssertionError(f"no `def {name}` returning a string list in {source} — guard is stale")


def _aigateway_model_ids() -> set[str]:
    ids: set[str] = set()
    for relative, name, provider in _SLUG_SOURCES:
        source = _PLUGINS / relative
        assert source.is_file(), f"{source} moved — update _SLUG_SOURCES"
        ids.update(_canonical(provider, slug) for slug in _string_list_assigned_to(source, name))
    for relative, name, provider in _RETURNED_SLUG_SOURCES:
        source = _PLUGINS / relative
        assert source.is_file(), f"{source} moved — update _RETURNED_SLUG_SOURCES"
        ids.update(_canonical(provider, slug) for slug in _string_list_returned_by(source, name))
    return ids


def _declared_default_route() -> str:
    """The `default_route` url4.json names, without its leading slash."""
    with _RUNNER_CONFIG.open("rb") as handle:
        return str(json.load(handle)["world"]["default_route"]).lstrip("/")


def _declared_models() -> tuple[str, ...]:
    """Every id the Engine declares — routable and aigateway-only alike (OME-859).

    Reads `BUILTIN_MODEL_WORLD` rather than `url4.json`: the list lives in code now. The JSON
    array is still parsed for `default_route` below, and is still accepted as an ADDITIVE
    overlay, but a deployment's own additions are its business and not this guard's.
    """
    return tuple(sorted(BUILTIN_MODEL_WORLD.all_ids))


def test_the_guard_actually_finds_the_plugin_registries() -> None:
    # Without this, an upstream rename would empty the reference set and the equality assertion
    # below would pass vacuously — the guard would go green precisely when it should fail.
    ids = _aigateway_model_ids()

    assert len(ids) >= 100
    # Anthropic is prefixed like every other provider — `canonical_model_id` has no exemption.
    assert "anthropic/claude-haiku-4-5" in ids
    assert "codex/gpt-5.5" in ids
    # The returned-list extractor is the one that would silently contribute nothing.
    assert "openrouter/openai/gpt-5.5" in ids
    # INVARIANT: every provider contributes. A rename in ONE plugin must not go unnoticed just
    # because the others still make the total look healthy — which is how OME-859 found that
    # HuggingFace had never been in `_RETURNED_SLUG_SOURCES` at all.
    for provider in (
        "anthropic",
        "antigravity",
        "codex",
        "gemini-cli",
        "huggingface",
        "openrouter",
    ):
        assert any(i.startswith(f"{provider}/") for i in ids), (
            f"{provider} extraction found nothing — its plugin list moved or was renamed"
        )


def test_the_canonical_rule_prefixes_once_and_only_once() -> None:
    # INVARIANT: the mirrored rule is idempotent — an already-qualified slug (OpenRouter's
    # seeds) must survive untouched, or every OpenRouter id would gain a second prefix.
    assert _canonical("anthropic", "claude-haiku-4-5") == "anthropic/claude-haiku-4-5"
    assert _canonical("openrouter", "openrouter/openai/gpt-5.5") == "openrouter/openai/gpt-5.5"
    assert _canonical("codex", _canonical("codex", "gpt-5.5")) == "codex/gpt-5.5"


def test_the_declared_default_route_is_a_declared_model() -> None:
    """INVARIANT: the fan-out reduce dispatches here, so it must name a route that resolves.

    A default_route that no `world.models` entry declares is unreachable: it fails at
    the gateway inside a user's expression rather than at boot (OME-795).
    """
    assert _declared_default_route() in set(_declared_models())


def test_every_declared_model_exists_in_aigateway() -> None:
    declared = set(_declared_models())

    missing = sorted(declared - _aigateway_model_ids())

    assert missing == [], (
        f"the Engine declares model(s) aigateway does not serve: {missing}. "
        "Either the plugin list changed, or the id is misspelled — a declared route that "
        "resolves to nothing fails inside a user's expression, not at boot."
    )


def test_every_model_aigateway_serves_is_declared() -> None:
    """INVARIANT: the direction this guard was missing until OME-859.

    Containment in the other direction alone is why 85 served models became unaddressable while
    CI stayed green. An undeclared model cannot be named by any url4 expression and is dropped
    from the `GET /v1/models` projection, so it is invisible rather than broken — which is
    exactly why a human never noticed.
    """
    served = _aigateway_model_ids()

    undeclared = sorted(served - set(_declared_models()))

    assert undeclared == [], (
        f"aigateway serves model(s) the Engine does not declare: {undeclared}. Add "
        "each slug to the matching screamingface_engine/models/seeds/ module — "
        "authored as the SLUG, without the provider prefix, which "
        "ProviderSeed.ids() applies."
    )


def test_the_unroutable_ids_are_exactly_the_colon_bearing_ones() -> None:
    """INVARIANT: the partition is a pure function of the id, and no id is renamed to dodge it.

    A route path is exactly "/" + the gateway id — no aliases (OME-859 D3). If somebody
    "fixed" a colon id by escaping it, it would move from `aigateway_only` into `routable` and
    this is the assertion that would catch it.
    """
    served = _aigateway_model_ids()

    assert BUILTIN_MODEL_WORLD.aigateway_only == {i for i in served if ":" in i}
    assert BUILTIN_MODEL_WORLD.routable == {i for i in served if ":" not in i}


def test_the_unroutable_set_is_pinned() -> None:
    """The OME-819 work-list, as reviewable text. Growing it must be a conscious edit.

    A `:` cannot appear in a URL4 path segment (url4 spec §8), so every HuggingFace router id
    (each pins a `:<provider>` backend) and five OpenRouter `:batch`/`:free` variants are
    unroutable by grammar, not by policy.
    """
    unroutable = BUILTIN_MODEL_WORLD.aigateway_only

    assert len(unroutable) == 29
    assert sum(1 for i in unroutable if i.startswith("huggingface/")) == 24
    assert sum(1 for i in unroutable if i.startswith("openrouter/")) == 5


@pytest.mark.parametrize("model", _declared_models())
def test_declared_model_ids_are_route_shaped(model: str) -> None:
    assert model, "empty model id"
    assert not model.startswith("/"), f"{model!r} must not start with '/' — routes derive it"
    assert model == model.strip(), f"{model!r} has surrounding whitespace"


# The 32 route ids `url4.json` declared by hand before OME-859 moved the list into code. Every one
# must still be routable: a route id that changed or vanished breaks live expressions, and two of
# them are score-affecting benchmark judge pins.
#
# AIDEV-NOTE: this is a MIGRATION guard, not a permanent contract. Once OME-859 has shipped and no
# branch still carries the old url4.json, it is safe to delete — the equality assertions above are
# what hold the world correct from then on.
_PRE_OME859_DECLARED = frozenset(
    {
        "anthropic/claude-opus-4-8",
        "anthropic/claude-opus-4-7",
        "anthropic/claude-sonnet-4-6",
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-haiku-4-5",
        "codex/gpt-5.5",
        "codex/gpt-5.4",
        "codex/gpt-5.4-mini",
        "codex/gpt-5.3-codex",
        "codex/gpt-5.2",
        "gemini-cli/gemini-3.1-flash-lite",
        "gemini-cli/gemini-2.5-pro",
        "gemini-cli/gemini-2.5-flash",
        "gemini-cli/gemini-2.5-flash-lite",
        "antigravity/gemini-3-flash",
        "openrouter/openai/gpt-5.5",
        "openrouter/openai/gpt-5.4",
        "openrouter/anthropic/claude-opus-4.8",
        "openrouter/anthropic/claude-fable-5",
        "openrouter/anthropic/claude-haiku-4.5",
        "openrouter/google/gemini-3.1-pro-preview",
        "openrouter/google/gemini-3-flash-preview",
        "openrouter/moonshotai/kimi-k2.6",
        "openrouter/moonshotai/kimi-k3",
        "openrouter/deepseek/deepseek-v4-pro",
        "openrouter/deepseek/deepseek-v4-flash",
        "openrouter/qwen/qwen3.6-plus",
        "openrouter/qwen/qwen3.8-2.4t-a95b",
        "openrouter/qwen/qwen3-coder",
        "openrouter/z-ai/glm-5.2",
        "openrouter/mistralai/ministral-3b-2512",
        "openrouter/microsoft/phi-4",
    }
)


def test_no_previously_declared_route_disappeared() -> None:
    missing = sorted(_PRE_OME859_DECLARED - BUILTIN_MODEL_WORLD.routable)

    assert missing == [], (
        f"these routes existed before OME-859 and must not vanish: {missing}. A route id that "
        "changes or disappears breaks live url4 expressions."
    )


def test_the_pinned_benchmark_judges_survived_the_migration() -> None:
    """INVARIANT: a different judge materially changes scores, so these two ids are contracts.

    DRACO's judge is pinned by arXiv:2602.11685 §4.2; HealthBench's by
    `benchmarks/healthbench/definition.py::JUDGE_MODEL`.
    """
    assert "openrouter/google/gemini-3.1-pro-preview" in BUILTIN_MODEL_WORLD.routable
    assert "openrouter/openai/gpt-5.4" in BUILTIN_MODEL_WORLD.routable

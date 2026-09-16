"""One declared flag, a derived mechanism.

PORTED FROM url4.json (OME-1183). `_parse_models` used to build a TOML `models = [...]` text
snippet and hand it to `tomllib.loads`; it now takes the `world.models` value directly as a
Python list, per `_with()`/`_world()` in `test_runner_config_ported.py`. `_RUNNER_CONFIG` used
to point at the real repo's `apps/screamingface-engine/url4.json`; it now points at this
directory's `url4.json` (the migration's stand-in for the renamed repo file).

FEATURE: web search on a model route.
STORY: as an operator, I declare THAT a route may search, and the Engine decides HOW —
so I never have to know which provider carries a native search envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.models.registry import EMPTY_MODEL_WORLD
from screamingface_engine.world_config import (
    WEB_SEARCH_NATIVE_PROVIDERS,
    ModelSpec,
    WorldConfigError,
    load_config,
    parse_config,
    provider_of,
)

_RUNNER_CONFIG = Path(__file__).resolve().parents[2] / "url4.json"


def _parse_models(models: list) -> tuple[ModelSpec, ...]:
    """Parse a `models` list, pointing `default_route` at its first entry so it stays declared."""
    first = models[0]
    default_id = first if isinstance(first, str) else first["id"]
    doc = {"world": {"default_route": f"/{default_id}", "models": models}}
    # OME-859: EMPTY_MODEL_WORLD so this helper still returns exactly the routes its argument
    # declares. The production default adds the 88 compiled ids.
    section = parse_config(doc, {}, registry=EMPTY_MODEL_WORLD).aigateway
    assert section is not None
    return section.models


# --- provider resolution ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("openrouter/openai/gpt-5.5", "openrouter"),
        # WHY this case exists: the id CONTAINS "anthropic", but the route is OpenRouter's and
        # must take OpenRouter's envelope. A substring test would misroute it.
        ("openrouter/anthropic/claude-opus-4.8", "openrouter"),
        ("codex/gpt-5.5", "codex"),
        ("gemini-cli/gemini-2.5-pro", "gemini-cli"),
        ("antigravity/gemini-3-flash", "antigravity"),
        # Anthropic ids are unprefixed in aigateway's catalog; the convention is the fallback.
        ("claude-haiku-4-5", "anthropic"),
    ],
)
def test_provider_of_reads_the_leading_segment(model_id: str, expected: str) -> None:
    assert provider_of(model_id) == expected


def test_only_openrouter_is_declared_native() -> None:
    """AIDEV-NOTE: this set grows ONLY when an aigateway plugin gains a web-search envelope."""
    assert WEB_SEARCH_NATIVE_PROVIDERS == frozenset({"openrouter"})


# --- mechanism selection ---------------------------------------------------------------


def test_openrouter_route_delegates_natively() -> None:
    spec = ModelSpec(id="openrouter/openai/gpt-5.5")
    assert spec.uses_native_web_search is True
    assert spec.uses_web_tools is False


@pytest.mark.parametrize(
    "model_id",
    [
        "claude-haiku-4-5",
        "codex/gpt-5.5",
        "gemini-cli/gemini-2.5-pro",
        "antigravity/gemini-3-flash",
        "huggingface/meta-llama/Llama-3-8B",
        "ollama/llama3",
    ],
)
def test_provider_without_a_native_envelope_takes_the_tavily_loop(model_id: str) -> None:
    spec = ModelSpec(id=model_id)
    assert spec.uses_web_tools is True
    assert spec.uses_native_web_search is False


@pytest.mark.parametrize("model_id", ["openrouter/openai/gpt-5.5", "codex/gpt-5.5"])
def test_disabled_route_uses_no_mechanism(model_id: str) -> None:
    spec = ModelSpec(id=model_id, web_search=False)
    assert spec.uses_native_web_search is False
    assert spec.uses_web_tools is False


@pytest.mark.parametrize("web_search", [True, False])
@pytest.mark.parametrize(
    "model_id", ["openrouter/openai/gpt-5.5", "codex/gpt-5.5", "claude-haiku-4-5"]
)
def test_mechanisms_partition_the_flag(model_id: str, web_search: bool) -> None:
    """INVARIANT: exactly one mechanism when the route searches, and none when it does not."""
    spec = ModelSpec(id=model_id, web_search=web_search)
    assert not (spec.uses_native_web_search and spec.uses_web_tools)
    assert (spec.uses_native_web_search or spec.uses_web_tools) is web_search


# --- declaration -----------------------------------------------------------------------


def test_web_search_defaults_to_true() -> None:
    assert _parse_models(["codex/gpt-5.5"])[0] == ModelSpec(id="codex/gpt-5.5")
    assert _parse_models(["codex/gpt-5.5"])[0].web_search is True


def test_a_route_may_opt_out() -> None:
    (spec,) = _parse_models([{"id": "codex/gpt-5.5", "web_search": False}])
    assert spec.web_search is False


def test_web_search_must_be_a_boolean() -> None:
    with pytest.raises(WorldConfigError, match="web_search must be a boolean"):
        _parse_models([{"id": "a", "web_search": "yes"}])


# --- reachability of the shipped config -------------------------------------------------


def test_both_search_mechanisms_are_reachable_from_the_shipped_config() -> None:
    # No route NAMES a mechanism any more — `world_config.ModelSpec` derives it from the id's
    # provider — so a declared-but-unserved route can no longer strand the Tavily loop the way
    # a stale `web_tools = true` id once could. What this guard now protects is that the shipped
    # config still exercises BOTH mechanisms: an all-openrouter (or all-Tavily) catalog would
    # silently orphan the other loop, and nothing else would say so.
    section = load_config({job_env.RUNNER_CONFIG: str(_RUNNER_CONFIG)}).aigateway
    assert section is not None

    assert any(model.uses_web_tools for model in section.models), (
        "no declared route resolves to the Tavily loop — it is now unreachable"
    )
    assert any(model.uses_native_web_search for model in section.models), (
        "no declared route resolves to native web search — it is now unreachable"
    )

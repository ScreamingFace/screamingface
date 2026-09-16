"""Every model the DRACO lineup answers with must have a declared route.

FEATURE: a client can run any of DRACO's published configurations against this deployment.
STORY: as a benchmark author, `budget_trio` is one of the paper's nine fusions, so its three
panel members must be addressable — not a `ResolutionError` two minutes into a paid run.

Routing is EXACT-MATCH with no wildcard form, so an undeclared model is not a degraded run: the
expression fails to resolve. Before this guard existed, four of the eight lineup models were
undeclared and nothing said so — the gap was invisible because the documented example expression
only ever used the three that happened to be declared.

INVARIANT: the lineup below is a HAND-COPY of
`screamingface-benchmarks/benchmarks_config/draco.yaml`, and it duplicates that file ON PURPOSE.
The two repos are not built together and this one cannot import the other, so a shared source is
not available; the point of the copy is to FAIL when the lineup changes, which is exactly when a
human needs to re-check both sides. A test that derived the list from url4.json would assert
nothing.

PORTED FROM url4.json (OME-1183): the file it reads is JSON now; every assertion is
unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from screamingface_engine import job_env
from screamingface_engine.world_config import ModelSpec, load_config

_RUNNER_CONFIG = Path(__file__).resolve().parents[2] / "url4.json"

_GATEWAY_PREFIX = "openrouter/"
"""DRACO runs every model through OpenRouter (`draco.yaml`: "calls go through OpenRouter,
default for closed models"), so a route id is that prefix plus the paper's upstream slug."""

# The 7 solos plus every distinct fusion panel member / synthesizer (draco.yaml §eval).
# `qwen3.6-plus` is the one model that is NOT a solo — it appears only in `best_open_source`.
DRACO_LINEUP = (
    "anthropic/claude-fable-5",
    "anthropic/claude-opus-4.8",
    "openai/gpt-5.5",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3-flash-preview",
    "moonshotai/kimi-k2.6",
    "deepseek/deepseek-v4-pro",
    "qwen/qwen3.6-plus",
)

DRACO_JUDGE = "google/gemini-3.1-pro-preview"
"""arXiv:2602.11685 §4.2 pins it. Also a solo candidate — see the dual-role test below."""


def _routes() -> dict[str, ModelSpec]:
    """Every declared model route, keyed by its gateway id, as the parsed spec."""
    section = load_config({job_env.RUNNER_CONFIG: str(_RUNNER_CONFIG)}).aigateway
    assert section is not None
    return {model.id: model for model in section.models}


@pytest.mark.parametrize("slug", DRACO_LINEUP)
def test_every_lineup_model_has_a_declared_route(slug: str) -> None:
    declared = _routes()
    assert _GATEWAY_PREFIX + slug in declared, (
        f"DRACO's lineup names {slug!r} but url4.json declares no route for it. Routing is "
        "exact-match, so every configuration using this model fails to resolve. Declare it here "
        "AND seed it in aigateway's `_default_model_slugs()` — "
        "`test_declared_models_match_aigateway.py` enforces the pair."
    )


def test_the_dual_role_judge_route_can_retrieve_as_a_candidate() -> None:
    """The route declares capability; the Benchmark Judge call pins retrieval off in URL4.

    AIDEV-NOTE: before OME-797 this route named `web_tools = true` explicitly and took the
    Tavily loop. The mechanism is now derived from the provider — this id is `openrouter/…`,
    which resolves to `uses_native_web_search` instead — so the assertion follows the
    mechanism that actually serves the route today rather than pinning the retired one.
    """

    spec = _routes()[_GATEWAY_PREFIX + DRACO_JUDGE]
    assert spec.uses_native_web_search is True


def test_the_lineup_has_no_duplicate_entries() -> None:
    """A duplicate would make the parametrized guard above silently weaker than it reads."""
    assert len(set(DRACO_LINEUP)) == len(DRACO_LINEUP)

"""The shipped model world — shape and totals.

Parity with aigateway is asserted by ``test_declared_models_match_aigateway.py``, which reads the
plugin source. This file pins what the shipped world must look like regardless of that.
"""

from __future__ import annotations

from screamingface_engine.models.builtins import BUILTIN_MODEL_WORLD


def test_the_shipped_world_declares_every_compiled_provider() -> None:
    providers = {model_id.partition("/")[0] for model_id in BUILTIN_MODEL_WORLD.all_ids}

    assert providers == {
        "anthropic",
        "antigravity",
        "codex",
        "gemini-cli",
        "huggingface",
        "openrouter",
    }


def test_the_shipped_world_totals_match_the_audited_gap() -> None:
    # INVARIANT: 117 compiled ids, 29 of them colon-bearing (24 HuggingFace + 5 OpenRouter
    # `:batch`/`:free`). Audited 2026-08-17 against the plugin seeds at f4684a83; the equality
    # guard is what keeps this true, this test is what makes a change visible.
    #
    # AIDEV-NOTE: these totals move whenever aigateway lands a seed PR — three did on 2026-08-17
    # alone (OME-816/817/818 via #581/#583, then OME-856). Do NOT relax this test to stop it
    # failing; the equality guard names the exact ids to add to a seeds/ module.
    assert len(BUILTIN_MODEL_WORLD) == 117
    assert len(BUILTIN_MODEL_WORLD.routable) == 88
    assert len(BUILTIN_MODEL_WORLD.aigateway_only) == 29


def test_the_default_route_is_routable() -> None:
    # INVARIANT: url4.json's default_route must resolve. OME-795 shipped a default_route that no
    # declared model matched; it failed inside a user's expression, not at boot.
    assert "anthropic/claude-haiku-4-5" in BUILTIN_MODEL_WORLD.routable


def test_the_pinned_benchmark_judges_are_routable() -> None:
    # INVARIANT: a different judge materially changes benchmark scores (DRACO arXiv:2602.11685
    # §4.2 pins its judge; healthbench/definition.py pins JUDGE_MODEL). Both must stay routes.
    assert "openrouter/google/gemini-3.1-pro-preview" in BUILTIN_MODEL_WORLD.routable
    assert "openrouter/openai/gpt-5.4" in BUILTIN_MODEL_WORLD.routable


def test_every_huggingface_id_is_aigateway_only() -> None:
    # WHY: every HF router id pins a `:<provider>` backend, so all 24 are colon-blocked. The
    # url4.json footer used to claim HF was "undeclarable by construction" because it built its
    # list at runtime — PR #583 gave it 24 compiled seeds, so the colon is the only reason now.
    hf = {i for i in BUILTIN_MODEL_WORLD.all_ids if i.startswith("huggingface/")}

    assert hf and hf <= BUILTIN_MODEL_WORLD.aigateway_only

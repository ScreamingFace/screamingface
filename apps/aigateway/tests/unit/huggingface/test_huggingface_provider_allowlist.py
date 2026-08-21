"""OME-791 (B1, B3) — only a KNOWN pinned Hugging Face provider may be cached.

FEATURE: one globally shared exact-request cache (OME-305), keyed identically for every caller.

STORY: as a benchmark operator I send ``…:preferred`` from two accounts with different provider
preference orders and neither is served the other's answer — the request dispatches normally,
uncached, instead of replaying a backend it would never have selected.

THE HAZARD, stated once. The ``:<suffix>`` position accepts two different KINDS of token:

    a PROVIDER   — ``:novita``, ``:groq``      → one fixed backend answers. Describable.
    a POLICY     — ``:fastest``, ``:cheapest``, ``:preferred``  → a selection RULE.

A policy names no backend. ``:preferred`` is the sharp case: it resolves against the REQUESTING
ACCOUNT's preference order, so it is identity-dependent — and the global key is architecturally
identity-free, so the hazard cannot be keyed around, only declined.

WHY THESE TESTS EXIST AT ALL (B3). The pre-existing suite stayed fully green when policy suffixes
were changed to the correct bypass behaviour: it tested the PARSER's raise sites, never the
semantic question "is this backend fixed for the next call?". Syntax-shaped tests cannot see a
hazard that is entirely about meaning. Every test here is written against the hazard instead.

AIDEV-NOTE: ``test_two_backends_for_one_repo_do_not_collide`` in the keys module is NOT evidence
of correctness for policies. Two policies producing two DIFFERENT keys is not the desired
outcome — the desired outcome is that neither receives a key at all.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.plugins.huggingface_provider.global_cache import project_global_cache_request
from aigateway.plugins.huggingface_provider.settings import (
    KNOWN_ROUTER_BACKENDS,
    pinned_router_target,
)

_REPO = "deepseek-ai/DeepSeek-R1"

# Routing policies documented at https://huggingface.co/docs/inference-providers/index.
# ``auto`` is the inference clients' spelling of the same "pick one for me" idea.
_ROUTING_POLICIES = ("fastest", "cheapest", "preferred", "auto")

# Two REAL partner slugs, deliberately ones absent from this repository's seed list, to pin that
# the catalog publishes but does not admit.
_REAL_PROVIDERS = ("groq", "baseten")


def _body(model: str, **extra: Any) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}], **extra}


def _bypasses(model: str) -> bool:
    produced = project_global_cache_request(_body(model))
    return isinstance(produced, CacheBypass) and produced.reason == PROJECTION_BYPASS_REASON


# --- the hazard, named for what it is ---------------------------------------------------------


@pytest.mark.parametrize("policy", _ROUTING_POLICIES)
def test_an_id_whose_backend_is_chosen_per_request_bypasses(policy: str) -> None:
    """The semantic test the old suite lacked.

    Not "does the parser raise" — it does not, and it must not. The question is whether the id
    names a backend that is FIXED for the next call. A policy does not, so no row filled under it
    describes the request that would replay it.
    """
    assert _bypasses(f"huggingface/{_REPO}:{policy}")


def test_the_account_dependent_policy_is_the_sharpest_case() -> None:
    # ``:preferred`` follows the REQUESTING ACCOUNT's provider preference order, so one account's
    # answer would be replayed to another whose identical request selects a different provider.
    # Called out separately because it is the one hazard that is a cross-ACCOUNT correctness bug
    # rather than a within-account attribution bug.
    assert _bypasses(f"huggingface/{_REPO}:preferred")


def test_an_unsuffixed_id_bypasses() -> None:
    # Equivalent to ``:fastest`` per the router docs — the default policy, spelled by omission.
    assert _bypasses(f"huggingface/{_REPO}")


@pytest.mark.parametrize(
    "suffix", ["notarealprovider", "wildly-made-up", "NOVITA", "novita2", "hf_inference"]
)
def test_an_unknown_suffix_bypasses(suffix: str) -> None:
    # FAIL CLOSED. Includes near-misses (wrong case, wrong separator, trailing digit) because
    # those are what a typo or a future rename actually looks like.
    assert _bypasses(f"huggingface/{_REPO}:{suffix}")


# --- the positive half: known providers still work --------------------------------------------


@pytest.mark.parametrize("provider", _REAL_PROVIDERS)
def test_a_known_provider_suffix_still_projects(provider: str) -> None:
    # Without this, "bypass everything" would satisfy every test above.
    produced = project_global_cache_request(_body(f"huggingface/{_REPO}:{provider}"))

    assert not isinstance(produced, CacheBypass)
    assert produced["resolved_model"] == f"{_REPO}:{provider}"


def test_two_known_providers_for_one_repo_stay_separated() -> None:
    # The suffix is output-affecting, so it must remain in the key material.
    first = project_global_cache_request(_body(f"huggingface/{_REPO}:{_REAL_PROVIDERS[0]}"))
    second = project_global_cache_request(_body(f"huggingface/{_REPO}:{_REAL_PROVIDERS[1]}"))

    assert not isinstance(first, CacheBypass) and not isinstance(second, CacheBypass)
    assert first["resolved_model"] != second["resolved_model"]


def test_exactly_the_allowlisted_suffixes_are_cacheable() -> None:
    """The completeness statement: cacheability is a FUNCTION of the allowlist, nothing else.

    Sweeping the whole allowlist plus the whole policy set in one assertion is what makes a
    future edit to either side visible here rather than only in a distant route test.
    """
    cacheable = {
        provider
        for provider in KNOWN_ROUTER_BACKENDS
        if not _bypasses(f"huggingface/{_REPO}:{provider}")
    }

    assert cacheable == set(KNOWN_ROUTER_BACKENDS)
    assert all(_bypasses(f"huggingface/{_REPO}:{policy}") for policy in _ROUTING_POLICIES)


# --- the allowlist itself ----------------------------------------------------------------------


def test_no_routing_policy_is_in_the_allowlist() -> None:
    # A standing guard against the exact regression B1 fixed: a policy admitted to the provider
    # allowlist would be cached as though it named a fixed backend.
    assert not (set(_ROUTING_POLICIES) & KNOWN_ROUTER_BACKENDS)


def test_the_allowlist_carries_the_full_partner_table_not_just_the_seeded_providers() -> None:
    """Sourced from the partner table, NOT from ``default_models``.

    The seed list names 8 providers; the partner table names 18. Deriving the allowlist from the
    seeds would silently refuse to cache a perfectly valid request for a real partner the
    operator happens not to have seeded — turning a catalog into an admission list.
    """
    from aigateway.plugins.huggingface_provider.settings import _default_model_slugs

    seeded = {slug.split(":")[1] for slug in _default_model_slugs() if ":" in slug}

    assert len(KNOWN_ROUTER_BACKENDS) == 18
    assert seeded < KNOWN_ROUTER_BACKENDS, "every seeded provider must be allowlisted"
    assert {"groq", "baseten"} <= KNOWN_ROUTER_BACKENDS, "unseeded real partners must cache too"


# --- dispatch stays permissive (B1.4) -----------------------------------------------------------


@pytest.mark.parametrize("suffix", [*_ROUTING_POLICIES, "notarealprovider"])
def test_a_policy_or_unknown_suffix_is_still_a_VALID_id_for_dispatch(suffix: str) -> None:
    """This change narrows CACHEABILITY, never validity.

    INVARIANT: ``_validate_model_slug`` stays permissive. If the allowlist had been wired into
    slug validation instead, a valid Hugging Face request would start being REFUSED by the
    gateway — turning a cache optimisation into an outage.
    """
    from aigateway.plugins.huggingface_provider.settings import _validate_model_slug

    slug = f"huggingface/{_REPO}:{suffix}"

    assert _validate_model_slug(slug) == slug  # does not raise
    assert pinned_router_target(slug) is None  # but is not cacheable


def test_a_malformed_id_is_still_refused() -> None:
    # The allowlist must not have loosened the malformed-id refusal it sits behind.
    from aigateway.plugins.huggingface_provider.settings import _validate_model_slug

    with pytest.raises(ValueError, match="unsafe/malformed"):
        _validate_model_slug("huggingface/nscale/meta-llama/Llama-3.1-8B-Instruct")

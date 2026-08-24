"""OME-791 — HF parameter promotion and global-cache KEY differences.

FEATURE: one globally shared exact-request cache (OME-305). The projection made HF
*describable*; promoting its parameter rules from ``bypass`` to ``keyed`` is what makes an
identical re-run actually cheaper.

STORY: as a benchmark operator I re-run a suite against a backend-pinned HF model and the
identical calls key identically, while any materially different request keys differently.

What this module pins, and why each matters:
- every one of the TWELVE newly-keyed request paths, because a keyed path with no
  key-difference proof is how two materially different requests come to share one answer;
- a derived-set meta-test, so a future keyed path cannot land without its own proof.

Split from ``test_huggingface_route_global_cache.py`` (OME-791 review): that file exceeded the
450-line limit, and keying is a different responsibility from the route's miss/hit behaviour.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from aigateway.core.profile_index import ProfileIndexStore
from aigateway.core.profile_models import Profile, ProfileState, profile_id_for
from aigateway.core.request_cache.global_controls import GlobalCacheControls
from aigateway.core.request_cache.global_plan import build_global_cache_plan
from aigateway.plugins.huggingface_provider.parameters import (
    huggingface_chat_parameter_rules,
)
from aigateway.plugins.huggingface_provider.plugin import PLUGIN

_CHAT_PATH = "/v1/chat/completions"
_PATCH_TARGET = (
    "aigateway.plugins.huggingface_provider.plugin.HuggingFaceProviderPlugin.chat_completion"
)
_MODEL = "huggingface/deepseek-ai/DeepSeek-R1:novita"
_HF_KEY = "hf_route_global_cache_key_1234567890"

# The complete set of HF request paths that OME-791 promotes to ``keyed``.
#
# INVARIANT: TWELVE, not the ten ``direct_rule`` calls a reader counts in ``parameters.py``.
# ``function_calling_rules`` emits ``tools`` AND ``tool_choice`` as two separate rules
# (``standard_parameters.py:232-252``, with ``tool_choice=True`` defaulted at ``:204``), so a
# literal set written from the source file alone is wrong by two. The meta-test below derives
# the real set from the live rule table and asserts equality against this literal, so the two
# can never drift.
_EXPECTED_KEYED_PATHS = frozenset(
    {
        "temperature",
        "max_tokens",
        "stop",
        "response_format",
        "seed",
        "n",
        "frequency_penalty",
        "presence_penalty",
        "logprobs",
        "top_logprobs",
        "tools",
        "tool_choice",
    }
)

# One concrete pair of DIFFERENT values per keyed path. A path missing from this table has no
# key-difference proof, which the meta-test refuses.
_KEY_DIFFERENCE_CASES: dict[str, tuple[Any, Any]] = {
    "temperature": (0.0, 1.0),
    "max_tokens": (16, 32),
    "stop": (["END"], ["STOP"]),
    "response_format": ({"type": "text"}, {"type": "json_object"}),
    "seed": (1, 2),
    "n": (1, 2),
    "frequency_penalty": (0.0, 0.5),
    "presence_penalty": (0.0, 0.5),
    # INVARIANT: ``top_logprobs`` requires ``logprobs is True``, so the pair varies the
    # dependent field while holding the enabling one — otherwise the 400 combination rule,
    # not the key, would be what distinguishes the two requests.
    "logprobs": (True, False),
    "top_logprobs": (1, 2),
    "tools": (
        [{"type": "function", "function": {"name": "alpha", "parameters": {}}}],
        [{"type": "function", "function": {"name": "beta", "parameters": {}}}],
    ),
    "tool_choice": ("auto", "none"),
}


def _published_cache_behaviour(document: dict[str, Any]) -> dict[str, str]:
    """``{request_path: cache_behavior}`` as a CALLER reads it off the contract document.

    Shape (verified against the live route): each entry under ``parameters`` — and each tool
    entry under ``tools`` — carries a ``gateway`` block holding ``cache_behavior``. Reading both
    sections matters: ``tools`` and ``tool_choice`` are two of the twelve promoted paths and do
    not appear beside the scalar parameters.
    """
    published: dict[str, str] = {}
    for section in ("parameters", "tools"):
        entries = document.get(section)
        if not isinstance(entries, dict):
            continue
        for name, entry in entries.items():
            gateway = entry.get("gateway") if isinstance(entry, dict) else None
            if isinstance(gateway, dict) and "cache_behavior" in gateway:
                published[str(name)] = str(gateway["cache_behavior"])
    return published


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": _MODEL,
        "messages": [{"role": "user", "content": "how many primes below one hundred?"}],
    }
    body.update(overrides)
    return body


def _key_hash(body: dict[str, Any]) -> str:
    """The global cache key for ``body``, through the REAL plan.

    WHY the whole plan rather than the projection alone: a key-difference test that called the
    projection directly would prove nothing about promotion, because the projection does not
    see parameters at all. Only the plan applies the rule table, so only the plan can show that
    a promoted path actually reached the key.
    """
    decision = build_global_cache_plan(
        body=body,
        plugin=PLUGIN,
        controls=GlobalCacheControls(participate=True),
        cache_enabled=True,
    )
    assert not hasattr(decision, "reason"), f"expected a key, got a bypass: {decision}"
    return cast(Any, decision).key_hash


# --- promotion, proven per path -----------------------------------------------


def test_the_promoted_set_is_exactly_the_twelve_paths_this_unit_claims() -> None:
    keyed = {
        rule.request_path
        for rule in huggingface_chat_parameter_rules(model=_MODEL, auth_type=None)
        if rule.cache_behavior == "keyed"
    }

    assert keyed == set(_EXPECTED_KEYED_PATHS)


def test_every_keyed_path_has_an_explicit_key_difference_proof() -> None:
    """The meta-test that makes this file self-enforcing.

    INVARIANT: a keyed path with no key-difference proof is exactly how two materially
    different requests come to share one stored answer. Deriving the set from the LIVE rules
    means a future promotion cannot land silently — it fails here until someone adds its pair.
    Mirrors ``test_every_openrouter_keyed_path_has_an_explicit_key_difference_proof``.
    """
    keyed = {
        rule.request_path
        for rule in huggingface_chat_parameter_rules(model=_MODEL, auth_type=None)
        if rule.cache_behavior == "keyed"
    }

    assert keyed == set(_KEY_DIFFERENCE_CASES), (
        "every keyed HF path needs a concrete differing-value pair in _KEY_DIFFERENCE_CASES"
    )


@pytest.mark.parametrize("path", sorted(_KEY_DIFFERENCE_CASES))
def test_a_keyed_path_changes_the_key_when_its_value_changes(path: str) -> None:
    low, high = _KEY_DIFFERENCE_CASES[path]
    extra = {"logprobs": True} if path == "top_logprobs" else {}

    assert _key_hash(_body(**{path: low}, **extra)) != _key_hash(_body(**{path: high}, **extra))


@pytest.mark.parametrize("path", sorted(_KEY_DIFFERENCE_CASES))
def test_a_keyed_path_keys_identically_for_an_identical_value(path: str) -> None:
    low, _ = _KEY_DIFFERENCE_CASES[path]
    extra = {"logprobs": True} if path == "top_logprobs" else {}

    assert _key_hash(_body(**{path: low}, **extra)) == _key_hash(_body(**{path: low}, **extra))


def test_two_backends_for_one_repo_do_not_collide() -> None:
    # The projection retains ``:<backend>`` in ``resolved_model``; this is the end-to-end
    # consequence, at the level a caller can observe.
    novita = _key_hash(_body(model="huggingface/deepseek-ai/DeepSeek-R1:novita"))
    together = _key_hash(_body(model="huggingface/deepseek-ai/DeepSeek-R1:together"))

    assert novita != together


def test_two_repos_do_not_collide() -> None:
    first = _key_hash(_body(model="huggingface/deepseek-ai/DeepSeek-R1:novita"))
    second = _key_hash(_body(model="huggingface/Qwen/Qwen3-235B-A22B:novita"))

    assert first != second


def test_every_registered_model_contributes_the_full_keyed_set() -> None:
    """HF's own regression floor, derived rather than hardcoded.

    AIDEV-NOTE: this replaces the tempting alternative of raising
    ``_OBSERVED_NON_BYPASS_INSTANCES`` in the SHARED conformance test. That number depends on
    catalog and environment state, and the file is append-only-protected; a floor derived from
    THIS plugin is both stronger for HF and free of blast radius.
    """
    entries = list(PLUGIN.register_models())
    assert entries, "no HF models registered"

    for entry in entries:
        keyed = {
            rule.request_path
            for rule in huggingface_chat_parameter_rules(model=entry.model_name, auth_type=None)
            if rule.cache_behavior == "keyed"
        }
        assert keyed == set(_EXPECTED_KEYED_PATHS), entry.model_name


async def _no_discovery(*_args: Any, **_kwargs: Any) -> None:
    return None


@pytest.mark.asyncio
async def test_the_published_parameter_contract_reports_the_promoted_behaviour(
    authenticated_client, credential_blobs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The caller-visible half of promotion, which nothing else asserts.

    WHY this test exists: the published contract digests each rule's ``cache_behavior`` and
    ``projection_revision`` (``core/model_parameter_contract.py:78``), so this unit moves every
    HF model's ``contract_id`` and flips twelve rows of its detail document. No existing test
    pins a digest or the old revision, which means the entire caller-visible surface could flip
    with nothing objecting. One assertion is enough to make the change deliberate.
    """
    # No live discovery evidence: the unit suite forbids catalog egress
    # (``tests/conftest.py:145-165``), and live backend evidence is orthogonal to what this
    # test asserts — the GATEWAY's own declared cache disposition, which comes from the rule
    # table rather than from any snapshot.
    monkeypatch.setattr(
        type(PLUGIN), "discover_chat_parameter_snapshot", _no_discovery, raising=True
    )

    account_id = authenticated_client.get("/v1/auth/me").json()["id"]
    index = ProfileIndexStore(credential_store=credential_blobs.store)
    await index.upsert(
        Profile(
            id=profile_id_for(account_id, "huggingface", "default"),
            account_id=account_id,
            provider="huggingface",
            name="default",
            state=ProfileState.AUTHENTICATED,
            auth_type="api_key",
        )
    )

    resp = authenticated_client.get("/v1/model-parameters", params={"model": _MODEL})
    assert resp.status_code == 200, resp.text

    published = _published_cache_behaviour(resp.json())
    keyed = {path for path, behaviour in published.items() if behaviour == "keyed"}

    assert keyed == set(_EXPECTED_KEYED_PATHS), (
        f"the published contract does not report the promoted set: {sorted(keyed)}"
    )
    # And nothing ELSE quietly became cacheable: the published set is exactly the promotion.
    assert not [path for path, b in published.items() if b not in {"keyed", "bypass"}], published

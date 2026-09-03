"""OME-884 — the SHARED ambient-runtime certification behind direct OpenAI caching.

FEATURE: one global exact-request cache (OME-305). A stored row is replayable by anyone
with no model entry and no credential, so before this provider may fill or serve one the
gateway certifies that nothing in process-global state can change what OpenAI would
answer for an identical request.

STORY: as an operator I can set a LiteLLM global and know the gateway stops caching
direct OpenAI rather than quietly serving me answers produced under different settings.

INVARIANT under test: the certification is TOTAL and fails CLOSED. A poisoned value, a
read that raises, and a runtime the gate could not inspect all end at the same verdict.

Scope of THIS file: the verdict the cache reader and the dispatch reader SHARE, seen from
the cache side (``participates_in_global_cache``), plus the inventory that keeps the
guarded-global list honest. Siblings:
  ``test_openai_dispatch.py``        — the same shared verdict seen from the 503 side.
  ``test_openai_runtime_modifier.py`` — the one deliberate ASYMMETRY, both readers at once.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterator, Mapping
from typing import Any

import litellm
import pytest
from litellm.secret_managers.main import get_secret_bool

from aigateway.plugins.openai_provider.plugin import PLUGIN
from aigateway.plugins.openai_provider.runtime_guard import (
    _EXPERIMENTAL_HANDLER_ENV,
    _LITELLM_GLOBAL_CALLBACK_FIELDS,
    _LITELLM_GLOBAL_TRUTHY_FIELDS,
    _MODIFY_PARAMS_FIELD,
    litellm_env_flag_is_true,
)

# The neutralizer is shared with the projection, keyed-parameter and modifier suites; see
# ``ambient_state`` for WHY the inventory there is hand-written rather than derived.
# Bound to the original private names so every relocated test body below reads unchanged.
from .ambient_state import AMBIENT_SAFE_ENV
from .ambient_state import AMBIENT_SAFE_STATE as _AMBIENT_SAFE_STATE
from .ambient_state import safe_runtime as _safe_runtime

# A model the deployment seeds, and one that is route-valid but deliberately NOT in
# ``default_models``. Participation must answer identically for both: the catalog
# publishes, it does not admit.
_SEEDED = "openai/gpt-5.6-sol"
_UNLISTED = "openai/gpt-4o-2024-11-20"


# --- participation: the deployment-local gate, kept OUT of the key -------------
#
# WHY participation is tested apart from the projection: they are the two halves of ONE
# decision — may this provider take part, and what would its key be — but only this half
# may read the environment. The projection's own purity is pinned next door in
# ``test_openai_global_cache_projection.py``.
_UNSAFE_RUNTIME_STATES: list[tuple[str, Any]] = [
    ("openai_config", lambda mp: mp.setattr(litellm.OpenAIConfig, "temperature", 1)),
    ("custom_headers", lambda mp: mp.setenv("OPENAI_CUSTOM_HEADERS", '{"X-Leak":"ambient"}')),
    (
        "experimental_handler",
        lambda mp: mp.setenv("EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER", "true"),
    ),
    ("secret_manager", lambda mp: mp.setattr(litellm, "secret_manager_client", object())),
    ("headers", lambda mp: mp.setattr(litellm, "headers", {"X-Leak": "ambient"})),
    ("fallbacks", lambda mp: mp.setattr(litellm, "model_fallbacks", ["openai/gpt-4o-mini"])),
    ("proxy_auth", lambda mp: mp.setattr(litellm, "proxy_auth", object())),
    ("drop_params", lambda mp: mp.setattr(litellm, "drop_params", True)),
    ("callbacks", lambda mp: mp.setattr(litellm, "callbacks", [object()])),
    ("pre_call_rules", lambda mp: mp.setattr(litellm, "pre_call_rules", [object()])),
]


def test_a_safe_runtime_participates(monkeypatch: pytest.MonkeyPatch) -> None:
    # Anti-vacuity for every refusal below: without it a hook that returned False
    # unconditionally would pass the whole parametrized sweep.
    _safe_runtime(monkeypatch)

    assert PLUGIN.participates_in_global_cache(_SEEDED) is True
    assert PLUGIN.participates_in_global_cache(_UNLISTED) is True


@pytest.mark.parametrize(
    "name,poison", _UNSAFE_RUNTIME_STATES, ids=[name for name, _ in _UNSAFE_RUNTIME_STATES]
)
def test_unsafe_ambient_state_refuses_participation(
    monkeypatch: pytest.MonkeyPatch, name: str, poison: Any
) -> None:
    """INVARIANT: the cache is a SECOND route to this provider's answers.

    A stored row needs no model entry and no credential to be replayed, and the cache
    stage runs ahead of both — so the dispatch-side 503 cannot protect it. Every state
    that makes DISPATCH unsafe must therefore also stop the READ, or a poisoned runtime
    would keep serving rows the dispatch guard refuses to refill.
    """
    _safe_runtime(monkeypatch)
    poison(monkeypatch)

    assert PLUGIN.participates_in_global_cache(_SEEDED) is False, name


def test_an_ambient_alias_stands_down_only_for_the_model_it_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliberate asymmetry: an alias is a per-MODEL hazard, not a provider-wide one.

    An entry in ``litellm.model_alias_map`` silently redirects one id to another, so a
    row stored for the requested id would be replayed while a miss dispatched something
    else. That is a wrong-hit class for THAT model — and no reason at all to abandon
    every other model's cache, which is what a provider-wide refusal would do.
    """
    _safe_runtime(monkeypatch)
    monkeypatch.setattr(litellm, "model_alias_map", {_SEEDED: "openai/gpt-4o-mini"})

    assert PLUGIN.participates_in_global_cache(_SEEDED) is False
    assert PLUGIN.participates_in_global_cache(_UNLISTED) is True
    assert PLUGIN.participates_in_global_cache("openai/gpt-4o") is True


def test_participation_is_total_for_a_non_string_or_hostile_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The gate runs before the request's shape is adjudicated, so it must survive a
    # model that is not a string — and a ``model_alias_map`` that is not a mapping.
    _safe_runtime(monkeypatch)
    for value in (None, 7, ["openai/gpt-4o"], {"a": 1}):
        assert PLUGIN.participates_in_global_cache(value) is True

    monkeypatch.setattr(litellm, "model_alias_map", "not-a-mapping")
    assert PLUGIN.participates_in_global_cache(_SEEDED) is True


@pytest.mark.parametrize(
    "value",
    [None, "true", "TRUE", "True", "  true  ", "false", "FALSE", "yes", "1", "0", "", "on"],
)
def test_the_flag_helper_matches_installed_litellm_semantics(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    """Parity with the ACTUAL branch LiteLLM takes, measured rather than assumed.

    ``get_secret_bool`` -> ``str_to_bool`` recognizes only ``"true"``/``"false"`` after
    ``.strip().lower()`` and answers ``None`` for everything else, INCLUDING unset. The
    secret-manager branch is a different code path entirely, which is why a configured
    secret-manager client is its own refusal above rather than something this helper
    tries to model.
    """
    monkeypatch.setattr(litellm, "secret_manager_client", None)
    if value is None:
        monkeypatch.delenv(_EXPERIMENTAL_HANDLER_ENV, raising=False)
    else:
        monkeypatch.setenv(_EXPERIMENTAL_HANDLER_ENV, value)

    assert litellm_env_flag_is_true(value) is (get_secret_bool(_EXPERIMENTAL_HANDLER_ENV) is True)


# --- OME-884 review: a RAISING ambient read is itself an unsafe runtime ---------
#
# WHY this is a distinct class from the poisons above: those set a value the guard then
# READS successfully. Here the read itself explodes. The guard's docstring promised
# "fail CLOSED and never raise", but every read was only defensive about a MISSING
# attribute (``getattr(..., None)``) — not about one that answers by raising. A hostile
# or merely broken LiteLLM global therefore escaped as an ordinary exception.


class _ExplodingAliasMap(Mapping[str, str]):
    """A ``model_alias_map`` whose membership test raises instead of answering."""

    def __contains__(self, key: object) -> bool:
        raise RuntimeError("hostile alias map")

    def __getitem__(self, key: str) -> str:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class _ExplodingTruthiness:
    """An ambient global that cannot even be asked whether it is set."""

    def __bool__(self) -> bool:
        raise RuntimeError("hostile truthiness")


def _raising_get_config() -> dict[str, Any]:
    raise RuntimeError("ambient config read exploded")


_RAISING_AMBIENT_READS: list[tuple[str, Any]] = [
    (
        "get_config",
        lambda mp: mp.setattr(
            litellm.OpenAIConfig, "get_config", staticmethod(_raising_get_config)
        ),
    ),
    ("alias_lookup", lambda mp: mp.setattr(litellm, "model_alias_map", _ExplodingAliasMap())),
    ("truthiness", lambda mp: mp.setattr(litellm, "headers", _ExplodingTruthiness())),
    ("callback_truthiness", lambda mp: mp.setattr(litellm, "callbacks", _ExplodingTruthiness())),
]


@pytest.mark.parametrize(
    "name,poison", _RAISING_AMBIENT_READS, ids=[name for name, _ in _RAISING_AMBIENT_READS]
)
def test_a_raising_ambient_read_refuses_participation(
    monkeypatch: pytest.MonkeyPatch, name: str, poison: Any
) -> None:
    """INVARIANT: unreadable is treated exactly like unsafe.

    The gate cannot certify a runtime it was unable to inspect, so the only sound answer
    is to stand down. Letting the exception escape instead was doubly wrong: it broke the
    hook's own documented totality, and it moved the decision to
    ``build_global_cache_plan``'s catch-all — which reports the outcome as this
    provider's projection bypass whether or not that is what actually happened.
    """
    _safe_runtime(monkeypatch)
    poison(monkeypatch)

    assert PLUGIN.participates_in_global_cache(_SEEDED) is False, name


def test_the_safe_runtime_helper_covers_every_field_the_guard_reads() -> None:
    """Ties the suites' INDEPENDENT inventory back to the production tuples.

    WHY both halves exist: the helper is written by hand so that a field the guard forgets
    is still neutralized here (otherwise guard and setup omit the same field and pass
    together, which is exactly how ``modify_params`` stayed invisible). This assertion is
    the other direction — a field ADDED to the guard must be added there too, or every
    suite sharing the neutralizer silently starts testing ambient session state again.
    """
    guarded = set(_LITELLM_GLOBAL_TRUTHY_FIELDS) | set(_LITELLM_GLOBAL_CALLBACK_FIELDS)
    missing = guarded - set(_AMBIENT_SAFE_STATE)
    assert not missing, f"_AMBIENT_SAFE_STATE does not neutralize {sorted(missing)}"


def test_every_guarded_global_still_exists_on_installed_litellm() -> None:
    """A rename or removal upstream must be a LOUD dependency-review event.

    INVARIANT: every name the guard inspects is a real ``litellm`` module attribute at the
    pinned version (1.97.0). The guard reads them with ``getattr(litellm, field, None)``,
    which is the right shape for fail-closed defaults but the wrong shape for detecting
    that a name has MOVED: a renamed global silently reads ``None``, the check passes, and
    a genuine ambient hazard stops being guarded with nothing failing.

    AIDEV-NOTE: this asserts EXISTENCE only. It deliberately does not assert the current
    default value, because "what is safe" is the guard's decision to make, not this test's
    — and pinning defaults here would break on an upstream change that is not a hazard.
    """
    assert importlib.metadata.version("litellm") == "1.97.0", (
        "the guarded-global inventory is pinned against LiteLLM 1.97.0 — re-verify the "
        "tuple against the new release before moving this pin"
    )
    for field in (
        *_LITELLM_GLOBAL_TRUTHY_FIELDS,
        *_LITELLM_GLOBAL_CALLBACK_FIELDS,
        # Not a member of either tuple by design — it is read on its own because its
        # verdict is cache-only — but it is read by ``getattr`` all the same, so a
        # rename must be just as loud here as for the shared members.
        _MODIFY_PARAMS_FIELD,
    ):
        assert hasattr(litellm, field), (
            f"litellm has no module attribute {field!r}: the guard's "
            f"getattr(litellm, {field!r}, None) can never fire, so this hazard is unguarded"
        )


# --- OME-884 review cycle 2: the inventory must be able to DISAGREE ------------
#
# WHY a second list when one already exists: the coverage assertion above proves only
# ``production guarded fields ⊆ neutralized fields``. That direction cannot see a
# production OMISSION. Delete ``post_call_rules`` from the guard's tuple and the setup
# still neutralizes it, the existence sweep no longer looks at it, and every test in this
# package stays green while a genuine ambient hazard silently stops being guarded.
#
# So these expectations are written out BY HAND from the spec (docs/spec §5), NOT derived
# from ``_LITELLM_GLOBAL_TRUTHY_FIELDS`` / ``_LITELLM_GLOBAL_CALLBACK_FIELDS``. The two
# sides must be CAPABLE of disagreeing, or the comparison proves nothing. Adding a guarded
# global is therefore a two-file edit on purpose: production plus this list.
_EXPECTED_TRUTHY_FIELDS: tuple[str, ...] = (
    "model_fallbacks",
    "headers",
    "pre_call_rules",
    "post_call_rules",
    "drop_params",
)
_EXPECTED_CALLBACK_FIELDS: tuple[str, ...] = (
    "callbacks",
    "input_callback",
    "success_callback",
    "failure_callback",
    "_async_input_callback",
    "_async_success_callback",
    "_async_failure_callback",
)
_EXPECTED_GUARDED_FIELDS = (*_EXPECTED_TRUTHY_FIELDS, *_EXPECTED_CALLBACK_FIELDS)


def test_the_shared_truthy_inventory_matches_the_expectation_exactly() -> None:
    """Exact agreement, so a production REMOVAL fails as loudly as an addition.

    AIDEV-NOTE: compared ``sorted`` rather than as tuples — order carries no behaviour
    (the guard uses ``any(...)`` over the members), so pinning it would turn a harmless
    re-ordering into a red gate while adding no protection. Sorting still catches an
    added member, a removed member and a duplicated one.
    """
    assert sorted(_LITELLM_GLOBAL_TRUTHY_FIELDS) == sorted(_EXPECTED_TRUTHY_FIELDS)


def test_the_shared_callback_inventory_matches_the_expectation_exactly() -> None:
    assert sorted(_LITELLM_GLOBAL_CALLBACK_FIELDS) == sorted(_EXPECTED_CALLBACK_FIELDS)


def test_the_request_modifier_stays_outside_the_shared_inventory() -> None:
    """The asymmetry is a DECISION, so promoting the flag must break a test.

    Membership in either shared tuple means "refuse the cache AND the dispatch". LiteLLM
    rewrites only a request that already carries a ceiling, so folding
    ``modify_params`` in would refuse requests it can never touch — an outage this
    gateway invented. ``test_openai_runtime_modifier.py`` owns the behaviour; this pins
    the shape.
    """
    assert _MODIFY_PARAMS_FIELD not in _EXPECTED_GUARDED_FIELDS
    assert _MODIFY_PARAMS_FIELD not in _LITELLM_GLOBAL_TRUTHY_FIELDS
    assert _MODIFY_PARAMS_FIELD not in _LITELLM_GLOBAL_CALLBACK_FIELDS


def test_every_expected_global_exists_on_installed_litellm() -> None:
    """The existence sweep, driven by the EXPECTED list rather than the production one.

    WHY it is worth having twice: the sibling sweep above iterates the production tuples,
    so a field dropped from production also drops out of its own existence check. Driving
    the same assertion from the independent list keeps the upstream-rename alarm wired to
    every field this gateway is SUPPOSED to guard.
    """
    assert importlib.metadata.version("litellm") == "1.97.0", (
        "the guarded-global inventory is pinned against LiteLLM 1.97.0 — re-verify the "
        "expectations against the new release before moving this pin"
    )
    for field in (*_EXPECTED_GUARDED_FIELDS, _MODIFY_PARAMS_FIELD):
        assert hasattr(litellm, field), f"litellm has no module attribute {field!r}"


def test_the_neutralizer_covers_every_expected_field() -> None:
    """The shared setup must silence everything the spec says is a hazard.

    Same argument as the production-driven coverage test, from the other list: a field
    missing here is ambient session state leaking into every suite that shares the helper.
    """
    missing = set(_EXPECTED_GUARDED_FIELDS) - set(_AMBIENT_SAFE_STATE)
    assert not missing, f"the shared neutralizer does not silence {sorted(missing)}"
    assert _MODIFY_PARAMS_FIELD in _AMBIENT_SAFE_STATE
    assert _EXPERIMENTAL_HANDLER_ENV in AMBIENT_SAFE_ENV


@pytest.mark.parametrize("field", _EXPECTED_GUARDED_FIELDS)
def test_every_expected_global_actually_disables_participation(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """The omission detector with teeth: poison each field and demand a refusal.

    WHY this exists alongside ``_UNSAFE_RUNTIME_STATES``: that table carries realistic,
    hand-written poisons and is the readable proof of the behaviour, but it covers a
    SUBSET of the guarded fields. This one is exhaustive by construction — remove a field
    from the production tuple and the guard stops reading it, so poisoning it no longer
    refuses and this test goes red. A one-element list is the right generic poison: it is
    truthy for the truthy members, and for the callback members it is a callback list
    holding something other than the exempt ``"cache"``.
    """
    _safe_runtime(monkeypatch)
    monkeypatch.setattr(litellm, field, [object()])

    assert PLUGIN.participates_in_global_cache(_SEEDED) is False, field

"""OME-791 — the HuggingFace global-cache projection, as a pure function of the body.

FEATURE: one globally shared exact-request cache (OME-305). Before this unit every
``huggingface/*`` request bypassed at the projection step, because the provider inherited
``CacheBypass`` from ``ProviderPluginBase`` — so an identical benchmark re-run paid full
price every time.

STORY: as a benchmark operator I re-run a suite against a backend-pinned HF model and the
identical calls come back from the first run's rows, with no second dispatch.

What these tests pin, and why each matters:
- the CLOSED three-member return shape, because ``_projected`` bypasses on set inequality —
  an extra member fails exactly as hard as a missing one, and both look like "not implemented";
- ``resolved_model`` keeping the ``:<backend>`` suffix, which is what makes two backends for
  one repo key differently with no separate mechanism;
- the bypass classes, each returning the one clamped reason a projection may return;
- purity, determinism, totality and fresh containers, which the registry sweeps check
  generically but which are cheaper to diagnose here.
"""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.cache_ports import PROJECTION_BYPASS_REASON, CacheBypass
from aigateway.core.request_cache.global_controls import GlobalCacheControls
from aigateway.core.request_cache.global_plan import build_global_cache_plan
from aigateway.plugins.huggingface_provider.global_cache import (
    GLOBAL_CACHE_ADAPTER_REVISION,
    project_global_cache_request,
)
from aigateway.plugins.huggingface_provider.plugin import PLUGIN, HuggingFaceProviderPlugin
from aigateway.plugins.huggingface_provider.settings import (
    OFFICIAL_ROUTER_API_BASE,
    HuggingFacePluginSettings,
)

_PINNED = "huggingface/deepseek-ai/DeepSeek-R1:novita"
_PROJECTION_MEMBERS = {"resolved_model", "provider_adapter_revision", "prepared"}


def _body(model: object = _PINNED, **extra: Any) -> dict[str, Any]:
    return {"model": model, "messages": [{"role": "user", "content": "hi"}], **extra}


def test_a_backend_pinned_request_projects_with_exactly_the_three_members() -> None:
    produced = project_global_cache_request(_body())

    assert not isinstance(produced, CacheBypass)
    # INVARIANT: core compares the member set for EQUALITY
    # (``global_eligibility._projected``), so a helpful extra key silently un-caches the
    # whole provider with a reason indistinguishable from "no projection at all".
    assert set(produced) == _PROJECTION_MEMBERS


def test_the_resolved_model_is_the_upstream_id_and_keeps_the_backend_suffix() -> None:
    produced = project_global_cache_request(_body())

    assert not isinstance(produced, CacheBypass)
    # WHY the prefix is stripped here but NOT for anthropic: litellm strips
    # ``huggingface/`` and passes the remainder to the wire verbatim — pinned by the
    # installed-transform assertion in test_huggingface_dispatch.py.
    assert produced["resolved_model"] == "deepseek-ai/DeepSeek-R1:novita"


def test_two_backends_for_one_repo_are_two_different_upstream_ids() -> None:
    # INVARIANT: the ``:<backend>`` suffix selects which inference provider answers, so it
    # is output-affecting. It keys as a structural consequence of ``resolved_model``.
    novita = project_global_cache_request(_body("huggingface/deepseek-ai/DeepSeek-R1:novita"))
    together = project_global_cache_request(_body("huggingface/deepseek-ai/DeepSeek-R1:together"))

    assert not isinstance(novita, CacheBypass)
    assert not isinstance(together, CacheBypass)
    assert novita["resolved_model"] != together["resolved_model"]


def test_the_prepared_view_is_exactly_the_pinned_official_router() -> None:
    produced = project_global_cache_request(_body())

    assert not isinstance(produced, CacheBypass)
    # The ONE output-affecting thing this boundary adds: which endpoint answers.
    # ``api_key`` and ``extra_headers`` are transport — the former is stripped and excluded
    # from the key by core, the latter is a DISPATCH_CONTROL_FIELD a caller cannot set.
    assert produced["prepared"] == {"api_base": OFFICIAL_ROUTER_API_BASE}


def test_the_projection_hands_back_fresh_containers_every_call() -> None:
    first = project_global_cache_request(_body())
    second = project_global_cache_request(_body())

    assert not isinstance(first, CacheBypass)
    assert not isinstance(second, CacheBypass)
    # INVARIANT: core hashes ``prepared`` by reference and does NOT copy it, so a shared
    # module-level table would let one reader alter every later request's key material.
    assert first["prepared"] is not second["prepared"]


def test_the_projection_is_deterministic() -> None:
    assert project_global_cache_request(_body()) == project_global_cache_request(_body())


def test_the_projection_never_mutates_the_body_it_was_given() -> None:
    body = _body(temperature=0.5)
    before = {"model": body["model"], "messages": [dict(body["messages"][0])], "temperature": 0.5}

    project_global_cache_request(body)

    assert body == before


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(None, id="missing"),
        pytest.param(7, id="not-a-string"),
        pytest.param(["a"], id="a-list"),
        pytest.param("", id="empty"),
        pytest.param("deepseek-ai/DeepSeek-R1:novita", id="no-gateway-prefix"),
        pytest.param("openrouter/deepseek/deepseek-r1", id="another-providers-prefix"),
        pytest.param("huggingface/", id="bare-prefix"),
        pytest.param("huggingface/lonely-token:novita", id="no-org-slash-model"),
        pytest.param("huggingface/novita/deepseek-ai/DeepSeek-R1", id="provider-as-path-segment"),
        pytest.param("huggingface/deepseek-ai/DeepSeek-R1:", id="empty-suffix"),
        pytest.param("huggingface/deepseek-ai/DeepSeek-R1:a:b", id="two-suffixes"),
    ],
)
def test_a_model_id_this_provider_cannot_describe_bypasses(model: object) -> None:
    produced = project_global_cache_request(_body(model))

    assert isinstance(produced, CacheBypass)
    # INVARIANT: one clamped reason. The vocabulary is a caller-visible wire contract, so a
    # projection may never mint a more precise value.
    assert produced.reason == PROJECTION_BYPASS_REASON


def test_an_unsuffixed_id_bypasses_even_though_it_dispatches_fine() -> None:
    # AIDEV-NOTE: this is the one bypass that does NOT mirror a dispatch refusal — unlike
    # openrouter's ``:online``, an unsuffixed HF id is perfectly dispatchable. It is refused
    # because ``pinned_router_target`` records that without ``:<provider>`` the router selects
    # a backend PER REQUEST, so no single upstream describes the next call. Replaying one
    # backend's answer for a request that would have gone elsewhere corrupts model
    # attribution, which for a benchmark product is a wrong answer rather than a stale one.
    produced = project_global_cache_request(_body("huggingface/deepseek-ai/DeepSeek-R1"))

    assert isinstance(produced, CacheBypass)
    assert produced.reason == PROJECTION_BYPASS_REASON


def test_every_registered_default_model_projects() -> None:
    # INVARIANT: the conformance sweep requires that once ANY rule is keyed, the projection
    # is non-bypass for EVERY declared model. A projection that recognised only a subset
    # would fail the moment the rules were promoted.
    for entry in PLUGIN.register_models():
        produced = project_global_cache_request(_body(entry.model_name))
        assert not isinstance(produced, CacheBypass), entry.model_name


def test_the_projection_is_total() -> None:
    # A projection may never fail a request, only decline to key it. Core wraps the call in
    # ``except Exception``, so a raise would show up as a silent permanent bypass.
    for body in ({}, {"model": _PINNED}, {"messages": None}, {"model": {}, "messages": 1}):
        assert project_global_cache_request(dict(body)) is not None


def test_the_projection_reads_no_operator_configuration() -> None:
    # The registry sweep proves this generically with a poisoned settings object; this local
    # copy exists because the sweeps only ever run HF with DEFAULT settings, so a regression
    # here would otherwise surface far from its cause.
    class _Poisoned:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"the projection read settings.{name}")

    plugin = HuggingFaceProviderPlugin(HuggingFacePluginSettings())
    plugin.settings = _Poisoned()  # type: ignore[assignment]

    produced = plugin.global_cache_projection(_body())

    assert not isinstance(produced, CacheBypass)
    assert produced["prepared"] == {"api_base": OFFICIAL_ROUTER_API_BASE}


def test_the_adapter_revision_is_reported_and_is_this_providers_own() -> None:
    produced = project_global_cache_request(_body())

    assert not isinstance(produced, CacheBypass)
    assert produced["provider_adapter_revision"] == GLOBAL_CACHE_ADAPTER_REVISION
    assert GLOBAL_CACHE_ADAPTER_REVISION.startswith("huggingface-global-cache-")


def test_the_plugin_hook_delegates_to_the_pure_module() -> None:
    assert PLUGIN.global_cache_projection(_body()) == project_global_cache_request(_body())


# ---------------------------------------------------------------------------
# Participation — the impure half of the same feature (D3, D6, D11).
#
# WHY it is tested beside the projection rather than in its own module: the two are one
# decision. The projection states "the official router answered this"; participation is
# what makes that statement true, by declining whenever it would not be. Splitting them
# would let a reader change one without seeing the other.
# ---------------------------------------------------------------------------


def _plugin(**settings: Any) -> HuggingFaceProviderPlugin:
    """A FRESH plugin instance, so one test's settings cannot leak into another.

    WHY not ``PLUGIN.settings_cls``: that attribute is typed as the base ``PluginSettings``, so
    pyright rejects both the constructor argument and any HF-specific keyword. Naming the
    concrete class keeps the settings kwargs type-checked, which is the point of passing them.
    """
    return HuggingFaceProviderPlugin(HuggingFacePluginSettings(**settings))


def test_a_default_deployment_participates() -> None:
    assert _plugin().participates_in_global_cache() is True


def test_a_trailing_slash_on_the_official_base_still_participates() -> None:
    # WHY normalised and not literal: litellm's ``_build_chat_completion_url`` does
    # ``model_url.rstrip("/")`` before appending ``/chat/completions``, so the two spellings
    # produce byte-identical upstream calls. A literal ``!=`` would disable caching for a
    # deployment that is provably sending the same request.
    assert _plugin(router_api_base=OFFICIAL_ROUTER_API_BASE + "/").participates_in_global_cache()


def test_a_deployment_pointed_somewhere_else_does_not_participate() -> None:
    # INVARIANT: this is the whole reason the projection may emit a CONSTANT base while the
    # settings field remains overridable. Two deployments with different bases must never
    # share rows, and the projection cannot see the difference — so participation must.
    assert (
        _plugin(router_api_base="https://proxy.internal/v1").participates_in_global_cache() is False
    )


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        pytest.param("model_fallbacks", ["openai/gpt-4o"], id="model-fallbacks"),
        pytest.param("model_alias_map", {"x": "y"}, id="model-alias-map"),
        pytest.param("headers", {"x-tenant": "acme"}, id="headers"),
        pytest.param("proxy_auth", object(), id="proxy-auth"),
        pytest.param("pre_call_rules", [lambda _: True], id="pre-call-rules"),
        pytest.param("post_call_rules", [lambda _: True], id="post-call-rules"),
        pytest.param("drop_params", True, id="drop-params"),
        pytest.param("additional_drop_params", ["seed"], id="additional-drop-params"),
        pytest.param("success_callback", ["langfuse"], id="a-real-callback"),
    ],
)
def test_unsafe_ambient_litellm_state_declines_participation(
    attribute: str, value: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AIDEV-NOTE: ``model_fallbacks`` is the load-bearing one and the reason this guard
    # exists at all. litellm reads it at ``main.py:602``, INSIDE ``async def acompletion``
    # (lines 388-698) — the exact entry point HF's inherited ``chat_completion`` calls — and
    # dispatches a DIFFERENT model. The fill path stores any answer carrying a
    # ``finish_reason`` without comparing its model to the key's, and rows never expire. So
    # one process-global setting writes another model's answer under an HF key, permanently.
    # That is a wrong answer, not a stale one.
    import litellm

    monkeypatch.setattr(litellm, attribute, value, raising=False)

    assert _plugin().participates_in_global_cache() is False


def test_a_clean_process_participates(monkeypatch: pytest.MonkeyPatch) -> None:
    # The mirror of the test above: if the guard could not be satisfied, HF would cache
    # nowhere and every other test here would pass vacuously.
    import litellm

    # ``"cache"`` in a callback list is explicitly permitted — it is litellm's own cache
    # bookkeeping, not a third-party observer, and both existing exemplars allow it.
    monkeypatch.setattr(litellm, "success_callback", ["cache"], raising=False)

    assert _plugin().participates_in_global_cache() is True


def test_a_raising_guard_costs_a_bypass_and_never_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # INVARIANT: the cache may never become an availability dependency.
    #
    # AIDEV-NOTE: asserted at the PLAN level on purpose, not on the hook's return value. The
    # core already owns this guarantee — ``global_plan.py:72-77`` wraps the participation call
    # in ``except Exception`` precisely so provider hooks do not each need their own catch — so
    # a ``try`` inside the hook would be a second guard protecting nothing, the same pattern
    # this plugin rejected for ``HuggingFaceChatConfig``. What actually matters to a caller is
    # that the REQUEST still succeeds with a bypass, which only this end-to-end assertion pins.
    plugin = _plugin()

    class _Exploding:
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("settings unavailable")

    monkeypatch.setattr(plugin, "settings", _Exploding())

    decision = build_global_cache_plan(
        body=_body(),
        plugin=plugin,
        controls=GlobalCacheControls(participate=True),
        cache_enabled=True,
    )

    assert isinstance(decision, CacheBypass)
    assert decision.reason == PROJECTION_BYPASS_REASON


def test_a_decline_names_its_reason_in_logs_without_leaking_the_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # WHY this matters (D11): every decline path publishes the SAME wire reason,
    # ``provider_projection``. Without a log line an operator whose HF caching silently
    # stopped has no way to learn which check declined. The token names the condition; the
    # configured URL is NEVER logged, because it can carry an internal hostname.
    from aigateway.plugins.huggingface_provider import plugin as plugin_module

    plugin_module.reset_decline_log()
    secret_base = "https://internal-proxy.corp.example/v1"

    with caplog.at_level("WARNING"):
        assert _plugin(router_api_base=secret_base).participates_in_global_cache() is False

    messages = [record.getMessage() for record in caplog.records]
    assert any("router_api_base" in message for message in messages)
    assert all(secret_base not in message for message in messages)


def test_the_decline_log_is_emitted_once_per_condition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aigateway.plugins.huggingface_provider import plugin as plugin_module

    plugin_module.reset_decline_log()
    plugin = _plugin(router_api_base="https://proxy.internal/v1")

    with caplog.at_level("WARNING"):
        for _ in range(5):
            plugin.participates_in_global_cache()

    declines = [r for r in caplog.records if "global cache" in r.getMessage()]
    # A per-request warning on a hot path is its own operational problem.
    assert len(declines) == 1


def test_the_cache_reference_mapper_answers_none_rather_than_being_absent() -> None:
    # AIDEV-NOTE: NOT decoration. ``plugins/taxonomy/session.py:374`` reaches this hook
    # through ``getattr`` inside a ``try`` and there is no base-class default, so a provider
    # that omits it logs "cache-reference mapper failed provider=huggingface" on EVERY hit —
    # an operator-visible failure that never happened. HF owns no usage-accounting strategy,
    # so ``None`` is the truthful answer.
    assert PLUGIN.cache_reference_from_cached_response({"usage": {"total_tokens": 5}}) is None

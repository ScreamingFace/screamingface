"""OME-629 (OME-479 §5.1/§5.3/§6.1): per-model OpenRouter evidence, closed-world.

FEATURE: model-specific provider evidence. Until now /v1/model-parameters reported
the SAME provider evidence for every OpenRouter model, because the plugin's whole
observation set was its reviewed labelled-local endpoint inventory. OpenRouter
publishes a per-model ``supported_parameters`` array; this reads it and overlays it.

STORY: as an API consumer I can tell an OpenRouter model that supports ``seed``
from one that does not, instead of reading the same inventory for both.

INVARIANT (closed-world in a PRESENT row, owner decision 2026-07-27): OpenRouter
documents ``supported_parameters`` as "array of supported API parameters for this
model" and lets the catalog be filtered by it, which only works if the array is
complete enough for NEGATIVE filtering. So inside a present row an omission is a
real ``unsupported`` verdict — but only for names the catalog's OWN vocabulary
(the union across every row of the fetched document) proves it tracks. A name no
row mentions is silence, not denial.

INVARIANT (evidence axis only): none of this changes gateway.status, the
/v1/models summary, or dispatch. A rule stays the only thing that enables a
parameter, so a warm cache can never authorize what a cold cache rejects.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aigateway.core.chat_parameters import (
    ProviderDiscoverySnapshot,
    ProviderParameterObservation,
)
from aigateway.core.model_capabilities import model_row
from aigateway.core.model_parameter_contract import build_model_parameter_document
from aigateway.core.parameter_discovery import DiscoveryHttpClient, RawResponse
from aigateway.core.plugin_base import ModelEntry
from aigateway.plugins.openrouter_provider.discovery import (
    MODEL_SOURCE,
    MODELS_URL,
    OPENAPI_URL,
    SNAPSHOT_SOURCE_REVISION,
    parse_model_catalog_observations,
)
from aigateway.plugins.openrouter_provider.plugin import OpenRouterProviderPlugin

_FLASH = "google/gemini-2.0-flash-001"
_FABLE = "anthropic/claude-fable-5"

# Two rows with DELIBERATELY different arrays, mirroring the verified live shape.
# Union vocabulary = the ten names below; `frequency_penalty` / `n` / `logprobs`
# appear in NEITHER row, so the catalog is silent about them.
_CATALOG: dict[str, Any] = {
    "data": [
        {
            "id": _FLASH,
            "supported_parameters": [
                "max_tokens",
                "temperature",
                "top_p",
                "top_k",
                "seed",
                "stop",
                "tools",
                "tool_choice",
                "response_format",
                "repetition_penalty",
            ],
        },
        {
            "id": _FABLE,
            "supported_parameters": [
                "max_tokens",
                "temperature",
                "top_p",
                "stop",
                "tools",
                "tool_choice",
            ],
        },
    ]
}
_OPENAPI: dict[str, object] = {
    "components": {"schemas": {"ChatRequest": {"properties": {"temperature": {}}}}}
}


class _CatalogClient(DiscoveryHttpClient):
    """Serves the fixture catalog; records every dialed URL."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.calls.append(url)
        body = _CATALOG if url == MODELS_URL else _OPENAPI
        return RawResponse(status=200, content_type="application/json", body=json.dumps(body))


def _verdicts(upstream: str) -> dict[str, ProviderParameterObservation]:
    return {
        o.request_path: o
        for o in parse_model_catalog_observations(_CATALOG, upstream_model_id=upstream)
    }


# --- closed-world catalog reading --------------------------------------------


def test_a_listed_parameter_is_positive_per_model_evidence() -> None:
    seed = _verdicts(_FLASH)["seed"]
    assert seed.support == "supported"
    assert seed.source == MODEL_SOURCE


def test_a_vocabulary_parameter_this_row_omits_is_reported_unsupported() -> None:
    # `seed` is in the catalog's own vocabulary (the flash row lists it) and the
    # fable row omits it — that omission is the source's negative verdict, which
    # is exactly what the catalog's supported_parameters FILTER relies on.
    seed = _verdicts(_FABLE)["seed"]
    assert seed.support == "unsupported"
    assert seed.source == MODEL_SOURCE


def test_a_name_no_row_mentions_produces_no_observation_either_way() -> None:
    # OpenRouter simply does not track `frequency_penalty` in this document.
    # Inventing `unsupported` here would fabricate a negative and wrongly erase the
    # provider's reviewed labelled-local evidence for a field it does forward.
    for upstream in (_FLASH, _FABLE):
        assert "frequency_penalty" not in _verdicts(upstream)
        assert "n" not in _verdicts(upstream)


def test_two_rows_produce_genuinely_different_evidence() -> None:
    flash = {p: o.support for p, o in _verdicts(_FLASH).items()}
    fable = {p: o.support for p, o in _verdicts(_FABLE).items()}
    # same vocabulary (one document, one universe) — different verdicts.
    assert set(flash) == set(fable)
    assert flash != fable


def test_the_wrapped_native_path_carries_both_verdicts() -> None:
    # top_k is OpenRouter-native; AIGateway addresses it through the wrapper, so
    # BOTH the positive and the negative verdict must land on the rule's path or
    # the overlay would silently miss it.
    assert _verdicts(_FLASH)["provider_params.top_k"].support == "supported"
    assert _verdicts(_FABLE)["provider_params.top_k"].support == "unsupported"
    assert "top_k" not in _verdicts(_FLASH)
    assert "top_k" not in _verdicts(_FABLE)


def test_gateway_owned_names_never_become_evidence() -> None:
    # `model`/`messages`/`stream` are gateway-owned, never model parameters. Under
    # closed-world they would otherwise surface as `unsupported` rows for every
    # model that omits them — noise the contract must never carry.
    catalog = {
        "data": [
            {"id": _FLASH, "supported_parameters": ["temperature", "stream"]},
            {"id": _FABLE, "supported_parameters": ["temperature", "model", "messages"]},
        ]
    }
    for upstream in (_FLASH, _FABLE):
        paths = {
            o.request_path
            for o in parse_model_catalog_observations(catalog, upstream_model_id=upstream)
        }
        assert paths == {"temperature"}


def test_an_absent_row_or_malformed_array_stays_silent() -> None:
    # honest absence — labelled-local evidence serves. Never a wall of fabricated
    # `unsupported` verdicts just because the document could not be read.
    assert parse_model_catalog_observations(_CATALOG, upstream_model_id="nope/absent") == ()
    assert (
        parse_model_catalog_observations(
            {"data": [{"id": _FLASH, "supported_parameters": "nope"}]}, upstream_model_id=_FLASH
        )
        == ()
    )


def test_an_unreadable_document_stays_silent() -> None:
    # INVARIANT: a payload shape the parser cannot read is NOT a source that said
    # "no". Same closed-world danger as above, one level up: a document that is not
    # an object, or whose `data` is not an array, must yield nothing rather than
    # letting an upstream shape change silently rewrite every model's evidence.
    assert parse_model_catalog_observations(["not", "an", "object"], upstream_model_id=_FLASH) == ()
    assert parse_model_catalog_observations({"data": {}}, upstream_model_id=_FLASH) == ()


def test_an_unreadable_neighbour_row_contributes_no_vocabulary() -> None:
    # The vocabulary is scanned across EVERY row, so one junk entry must not abort
    # the read — nor add phantom names that would become negatives for its peers.
    observed = parse_model_catalog_observations(
        {"data": ["junk", {"id": _FLASH, "supported_parameters": ["temperature", "seed"]}]},
        upstream_model_id=_FLASH,
    )
    assert {(o.request_path, o.support) for o in observed} == {
        ("temperature", "supported"),
        ("seed", "supported"),
    }


# --- the declared source -----------------------------------------------------


def test_the_plugin_declares_its_catalog_source_before_any_fetch() -> None:
    ref = OpenRouterProviderPlugin().chat_discovery_source(model=f"openrouter/{_FLASH}")
    assert ref is not None
    assert (ref.source, ref.revision) == (MODEL_SOURCE, SNAPSHOT_SOURCE_REVISION)


def test_a_non_dispatchable_model_declares_no_source() -> None:
    # nothing to discover for an id this provider cannot dispatch — and declaring
    # a source for it would commit the plugin to a snapshot it will never produce.
    plugin = OpenRouterProviderPlugin()
    assert plugin.chat_discovery_source(model="bare-model") is None
    assert plugin.chat_discovery_source(model="openrouter/not-a-valid-id") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model", [f"openrouter/{_FLASH}", "bare-model", "openrouter/not-a-valid-id"]
)
async def test_declaring_a_source_and_reporting_no_attempt_is_unreachable(model: str) -> None:
    # INVARIANT: the runtime treats "declared a source, then returned None" as an
    # inconsistency it degrades on. Both hooks must therefore agree on the SAME
    # predicate — proven here over the ids that decide it, in both directions.
    plugin = OpenRouterProviderPlugin()
    client = _CatalogClient()
    declared = plugin.chat_discovery_source(model=model)
    snapshot = await plugin.discover_chat_parameter_snapshot(model=model, client=client)
    assert (declared is None) == (snapshot is None)
    if declared is None:
        assert client.calls == []  # no source declared → no connection opened


@pytest.mark.asyncio
async def test_the_declared_revision_is_the_one_the_snapshot_carries() -> None:
    # a revision that disagreed with the snapshot's would let the cache key one
    # reading while storing another.
    plugin = OpenRouterProviderPlugin()
    model = f"openrouter/{_FLASH}"
    ref = plugin.chat_discovery_source(model=model)
    snapshot = await plugin.discover_chat_parameter_snapshot(model=model, client=_CatalogClient())
    assert ref is not None and snapshot is not None
    assert snapshot.source_revision == ref.revision


@pytest.mark.asyncio
async def test_the_live_snapshot_reads_the_row_closed_world() -> None:
    # end of the dynamic path: fetch → parse → per-model verdicts, both signs.
    plugin = OpenRouterProviderPlugin()
    client = _CatalogClient()
    snapshot = await plugin.discover_chat_parameter_snapshot(
        model=f"openrouter/{_FABLE}", client=client
    )
    assert snapshot is not None
    verdicts = {o.request_path: o.support for o in snapshot.model_observations}
    assert verdicts["temperature"] == "supported"
    assert verdicts["seed"] == "unsupported"
    # OME-647: the snapshot is a source PAIR now. Still an EXACT list — the point
    # of the assertion is that discovery dials the FIXED public documents and
    # nothing else, which a two-element list pins just as tightly as a one-element
    # list did.
    assert client.calls == [MODELS_URL, OPENAPI_URL]


# --- composition into the detailed contract ----------------------------------


def _document(upstream: str, *, observed: str | None = None, stale: bool = False) -> Any:
    """Compose the contract exactly as the route does, for one catalog row.

    ``observed=None`` models a degraded read: the runtime yielded no snapshot.
    """
    plugin = OpenRouterProviderPlugin()
    model = f"openrouter/{upstream}"
    snapshot = (
        None
        if observed is None
        else ProviderDiscoverySnapshot(
            source_revision=SNAPSHOT_SOURCE_REVISION,
            model_observations=parse_model_catalog_observations(
                _CATALOG, upstream_model_id=observed
            ),
        )
    )
    return build_model_parameter_document(
        canonical_id=model,
        gateway_provider="openrouter",
        auth_mode="api_key",
        scope="account_connection",
        context_identity="acct:test|prof:1",
        rules=plugin.chat_parameter_rules(model=model, auth_type="api_key"),
        observations=plugin.overlay_discovered_observations(
            plugin.chat_parameter_observations(model=model, auth_type="api_key"),
            snapshot,
            stale=stale,
        ),
        tools=plugin.chat_parameter_tools(model=model, auth_type="api_key"),
        transport=plugin.chat_transport_capabilities(model=model, auth_type="api_key"),
        freshness={"stale": stale, "degraded": False},
    )


def test_two_models_differ_in_evidence_but_not_in_gateway_status() -> None:
    flash = _document(_FLASH, observed=_FLASH)["parameters"]
    fable = _document(_FABLE, observed=_FABLE)["parameters"]
    # THE point of the unit: provider evidence is now model-specific …
    assert flash["seed"]["provider"] != fable["seed"]["provider"]
    # … while the gateway's own decision is identical, because it comes from the
    # rule set, which discovery never touches.
    shared = set(flash) & set(fable)
    assert {p: flash[p]["gateway"] for p in shared} == {p: fable[p]["gateway"] for p in shared}


def test_a_ruled_path_the_row_omits_stays_enabled_with_unsupported_evidence() -> None:
    # The accepted, DOCUMENTED gap: evidence moves, authorization does not. The
    # contract reports honestly that this model does not support seed while the
    # gateway still forwards it (OpenRouter ignores it upstream). Closing that is a
    # separate architecture decision, deliberately not made here.
    seed = _document(_FABLE, observed=_FABLE)["parameters"]["seed"]
    assert seed["provider"]["support"] == "unsupported"
    assert seed["provider"]["source"] == MODEL_SOURCE
    assert seed["gateway"]["status"] == "enabled"


def test_a_dynamic_only_path_appears_as_a_visible_disabled_row() -> None:
    entry = _document(_FLASH, observed=_FLASH)["parameters"]["repetition_penalty"]
    assert entry["provider"]["support"] == "supported"
    assert entry["gateway"]["status"] == "disabled"
    assert entry["gateway"]["reason"] == "projection_not_implemented"


def test_a_path_the_catalog_is_silent_about_keeps_its_labelled_local_evidence() -> None:
    entry = _document(_FLASH, observed=_FLASH)["parameters"]["frequency_penalty"]
    assert entry["provider"]["source"] == "openrouter:static"
    assert entry["gateway"]["status"] == "enabled"


def test_stale_evidence_is_flagged_on_the_dynamic_rows_only() -> None:
    params = _document(_FABLE, observed=_FABLE, stale=True)["parameters"]
    assert params["seed"]["provider"]["stale"] is True
    assert params["frequency_penalty"]["provider"]["stale"] is False


def test_degraded_discovery_falls_back_to_labelled_local_evidence() -> None:
    # past the stale window the runtime yields NO snapshot; the contract must be
    # the honest labelled-local one, never a fabricated per-model claim.
    params = _document(_FABLE)["parameters"]
    assert params["seed"]["provider"]["source"] == "openrouter:static"
    assert MODEL_SOURCE not in {e["provider"]["source"] for e in params.values()}


def test_the_models_summary_is_identical_for_both_models() -> None:
    # /v1/models is the RULE projection. Discovery must not reach it — otherwise
    # the summary would start disagreeing with dispatch.
    plugin = OpenRouterProviderPlugin()
    rows = [
        model_row(plugin, ModelEntry(model_name=f"openrouter/{u}", litellm_params={}))
        for u in (_FLASH, _FABLE)
    ]
    assert rows[0]["supported_parameters"] == rows[1]["supported_parameters"]
    assert rows[0]["supported_tools"] == rows[1]["supported_tools"]

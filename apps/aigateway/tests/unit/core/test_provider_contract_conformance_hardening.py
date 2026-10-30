"""Mutation tests for the provider-agnostic conformance oracle."""

from __future__ import annotations

from typing import Any

import pytest

from aigateway.core.auth_types import AuthMode
from aigateway.core.chat_parameters import (
    ProviderDiscoverySnapshot,
    ProviderParameterObservation,
    ProviderToolObservation,
)
from aigateway.core.model_parameter_contract import build_model_parameter_document
from tests.unit.core.test_provider_contract_conformance import (
    _document,
    _iter_models,
)


def _served_document(
    plugin: Any,
    canonical: str,
    auth_mode: AuthMode,
    *,
    snapshot: ProviderDiscoverySnapshot | None,
) -> dict[str, Any]:
    observations = plugin.overlay_discovered_observations(
        plugin.chat_parameter_observations(model=canonical, auth_type=auth_mode),
        snapshot,
        stale=False,
    )
    tools = plugin.overlay_discovered_tools(
        plugin.chat_parameter_tools(model=canonical, auth_type=auth_mode), snapshot
    )
    return build_model_parameter_document(
        canonical_id=canonical,
        gateway_provider=plugin.custom_llm_provider,
        auth_mode=auth_mode,
        scope="account_connection",
        context_identity="acct:conformance|prof:1",
        rules=plugin.chat_parameter_rules(model=canonical, auth_type=auth_mode),
        observations=observations,
        tools=tools,
        transport=plugin.chat_transport_capabilities(model=canonical, auth_type=auth_mode),
        freshness={"stale": False, "degraded": False},
        source_revision=snapshot.source_revision if snapshot else None,
    )


def _assert_every_enabled_rule_has_its_own_schema() -> None:
    for plugin, _entry, canonical in _iter_models():
        for mode in plugin.available_auth_modes():
            rules = {
                rule.request_path: rule
                for rule in plugin.chat_parameter_rules(model=canonical, auth_type=mode)
                if mode in rule.applicable_auth_modes
            }
            parameters = _served_document(plugin, canonical, mode, snapshot=None)["parameters"]
            for path, rule in rules.items():
                where = (canonical, mode, path)
                assert rule.parameter_schema is not None, where
                assert parameters[path]["schema"] is not None, where


def test_every_enabled_rule_has_its_own_schema() -> None:
    _assert_every_enabled_rule_has_its_own_schema()


def test_schema_bearing_observation_cannot_mask_a_schema_less_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin, _entry, canonical = next(_iter_models())
    mode = plugin.available_auth_modes()[0]
    original_rules = plugin.chat_parameter_rules(model=canonical, auth_type=mode)
    selected = next(rule for rule in original_rules if mode in rule.applicable_auth_modes)
    schema_less = selected.model_copy(update={"parameter_schema": None})
    observations = plugin.chat_parameter_observations(model=canonical, auth_type=mode)
    schema_bearing = tuple(
        observation.model_copy(update={"parameter_schema": selected.parameter_schema})
        if observation.request_path == selected.request_path
        else observation
        for observation in observations
    )
    monkeypatch.setattr(
        plugin,
        "chat_parameter_rules",
        lambda **_kwargs: tuple(
            schema_less if rule.request_path == selected.request_path else rule
            for rule in original_rules
        ),
    )
    monkeypatch.setattr(plugin, "chat_parameter_observations", lambda **_kwargs: schema_bearing)

    with pytest.raises(AssertionError):
        _assert_every_enabled_rule_has_its_own_schema()


def test_document_composer_preserves_reviewed_evidence_without_snapshot() -> None:
    plugin, _entry, canonical = next(_iter_models())
    mode = plugin.available_auth_modes()[0]

    assert _served_document(plugin, canonical, mode, snapshot=None) == _document(
        plugin, canonical, mode
    )


def test_document_composer_uses_real_discovery_overlay_hooks() -> None:
    plugin, _entry, canonical = next(
        row
        for row in _iter_models()
        if row[0].chat_parameter_tools(model=row[2], auth_type=row[0].available_auth_modes()[0])
    )
    mode = plugin.available_auth_modes()[0]
    rule = next(
        rule
        for rule in plugin.chat_parameter_rules(model=canonical, auth_type=mode)
        if mode in rule.applicable_auth_modes
    )
    tool = plugin.chat_parameter_tools(model=canonical, auth_type=mode)[0]
    snapshot = ProviderDiscoverySnapshot(
        source_revision="synthetic-v1",
        endpoint_observations=(
            ProviderParameterObservation(
                request_path=rule.request_path,
                support="supported",
                source="synthetic_overlay",
                schema=rule.parameter_schema,
            ),
        ),
        tool_observations=(
            ProviderToolObservation(tool_type=tool.tool_type, support="unsupported"),
        ),
    )

    document = _served_document(plugin, canonical, mode, snapshot=snapshot)

    assert document["parameters"][rule.request_path]["provider"]["source"] == "synthetic_overlay"
    assert document["tools"][tool.tool_type]["provider_support"] == "unsupported"

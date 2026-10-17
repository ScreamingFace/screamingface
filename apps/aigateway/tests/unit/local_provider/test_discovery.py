from __future__ import annotations

import json
import logging

import pytest

from aigateway.core.parameter_discovery import DiscoveryError, RawResponse
from aigateway.plugins.local_provider.plugin import LocalProviderPlugin
from aigateway.plugins.local_provider.settings import LocalPluginSettings


class _Client:
    def __init__(self, response: RawResponse) -> None:
        self.response = response
        self.calls: list[str] = []

    async def get(self, url: str, *, timeout_s: float, max_bytes: int) -> RawResponse:
        self.calls.append(url)
        return self.response


def _response(payload: object, *, status: int = 200) -> RawResponse:
    return RawResponse(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.asyncio
async def test_disabled_provider_declares_no_source_and_performs_no_egress() -> None:
    plugin = LocalProviderPlugin(LocalPluginSettings(enabled=False))
    client = _Client(_response({"object": "list", "data": [{"id": "fixture:model"}]}))

    assert plugin.register_models() == []
    assert plugin.model_discovery_source() is None
    assert await plugin.discover_live_models(client=client) is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_enabled_provider_publishes_raw_colon_bearing_model_ids() -> None:
    plugin = LocalProviderPlugin(LocalPluginSettings(enabled=True))
    client = _Client(
        _response(
            {
                "object": "list",
                "data": [{"id": "fixture:model"}, {"id": "org/model"}],
            }
        )
    )

    entries = await plugin.discover_live_models(client=client)

    assert entries is not None
    assert [entry.model_name for entry in entries] == [
        "local/fixture:model",
        "local/org/model",
    ]
    assert client.calls == ["http://127.0.0.1:1234/v1/models"]


@pytest.mark.asyncio
async def test_valid_empty_catalog_is_authoritative() -> None:
    plugin = LocalProviderPlugin(LocalPluginSettings(enabled=True))

    entries = await plugin.discover_live_models(
        client=_Client(_response({"object": "list", "data": []}))
    )

    assert entries == ()


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (_response({"object": "list", "data": []}, status=503), "bad_status"),
        (_response({"object": "wrong", "data": []}), "malformed_json"),
        (_response({"object": "list", "data": "not-a-list"}), "malformed_json"),
        (_response({"object": "list", "data": [{"id": 7}]}), "malformed_json"),
    ],
)
@pytest.mark.asyncio
async def test_untrusted_catalog_failures_are_sanitized(
    response: RawResponse,
    reason: str,
) -> None:
    plugin = LocalProviderPlugin(LocalPluginSettings(enabled=True))

    with pytest.raises(DiscoveryError) as exc:
        await plugin.discover_live_models(client=_Client(response))

    assert exc.value.reason == reason
    assert response.body not in str(exc.value)


@pytest.mark.asyncio
async def test_unrouteable_and_duplicate_ids_do_not_hide_healthy_models(caplog) -> None:
    plugin = LocalProviderPlugin(LocalPluginSettings(enabled=True))
    client = _Client(
        _response(
            {
                "object": "list",
                "data": [
                    {"id": "fixture:model"},
                    {"id": "custom@model"},
                    {"id": "custom model"},
                    {"id": "fixture:model"},
                ],
            }
        )
    )

    with caplog.at_level(logging.WARNING):
        entries = await plugin.discover_live_models(client=client)

    assert entries is not None
    assert [entry.model_name for entry in entries] == ["local/fixture:model"]
    records = [record for record in caplog.records if record.message == "local models skipped"]
    assert len(records) == 1
    assert records[0].skipped_model_count == 3
    assert "custom" not in caplog.text

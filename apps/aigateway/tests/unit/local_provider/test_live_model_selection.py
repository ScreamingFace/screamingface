from __future__ import annotations

import httpx
import pytest

from aigateway.plugins.local_provider.settings import LocalPluginSettings
from tests.live.test_local_provider_live import _selected_model


def test_live_model_selection_requires_an_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIGW_LIVE_LOCAL_MODEL", raising=False)

    with pytest.raises(pytest.fail.Exception, match="AIGW_LIVE_LOCAL_MODEL"):
        _selected_model(LocalPluginSettings(enabled=True))


def test_live_model_selection_uses_only_the_named_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIGW_LIVE_LOCAL_MODEL", "chat-model")
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: httpx.Response(
            200,
            request=httpx.Request("GET", "http://127.0.0.1:1234/v1/models"),
            json={
                "object": "list",
                "data": [{"id": "embedding-model"}, {"id": "chat-model"}],
            },
        ),
    )

    assert _selected_model(LocalPluginSettings(enabled=True)) == "chat-model"

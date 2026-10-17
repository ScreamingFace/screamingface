from __future__ import annotations

import logging

from screamingface_engine.config import Settings
from screamingface_engine.local import _local_model_prefixes


def test_local_overlay_is_enabled_only_for_numeric_loopback_aigateway() -> None:
    assert _local_model_prefixes(Settings(aigateway_base_url="http://127.0.0.1:9105")) == (
        "local",
        "ollama",
    )
    assert _local_model_prefixes(Settings(aigateway_base_url="http://[::1]:9105")) == (
        "local",
        "ollama",
    )


def test_remote_or_hostname_aigateway_keeps_the_closed_world() -> None:
    assert _local_model_prefixes(Settings(aigateway_base_url="http://localhost:9105")) == ()
    assert _local_model_prefixes(Settings(aigateway_base_url="https://gateway.example")) == ()
    assert _local_model_prefixes(Settings(aigateway_base_url=None)) == ()


def test_nonnumeric_gateway_logs_that_the_local_overlay_is_disabled(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert _local_model_prefixes(Settings(aigateway_base_url="http://localhost:9105")) == ()

    assert "local model overlay disabled: gateway is not numeric loopback" in caplog.messages
    assert "localhost" not in caplog.text

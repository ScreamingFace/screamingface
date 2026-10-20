"""Both transports share one destination independent of the engine."""

import sys
import types

import pytest

from screamingface._analytics import colab, endpoint, wiring


@pytest.fixture(autouse=True)
def clean_endpoint(monkeypatch):
    monkeypatch.delenv("SCREAMINGFACE_ANALYTICS_ENDPOINT", raising=False)
    endpoint.analytics_origin.cache_clear()
    yield
    endpoint.analytics_origin.cache_clear()


@pytest.mark.parametrize("environment", [None, "dev", "staging"])
def test_both_transports_use_selected_origin(environment, monkeypatch):
    host = f"https://analytics.{environment + '.' if environment else ''}screamingface.ai"
    if environment:
        monkeypatch.setenv("SCREAMINGFACE_ANALYTICS_ENDPOINT", host + "/")
    destinations = []
    monkeypatch.setattr(wiring, "_coordinator", None)
    monkeypatch.setattr(wiring, "origin", lambda: "python")
    monkeypatch.setattr(wiring, "BackgroundSink", lambda url, allowed: destinations.append(url))
    wiring.coordinator()
    assert destinations == [host + "/v1/events"]
    scripts = []
    output = types.SimpleNamespace(eval_js=lambda script, **kwargs: scripts.append(script))
    monkeypatch.setitem(sys.modules, "google.colab", types.SimpleNamespace(output=output))
    colab.exchange("state")
    assert f'const origin = "{host}";' in scripts[0]
    assert "origin + '/bridge/consent" in scripts[0]
    monkeypatch.setenv("SCREAMINGFACE_ANALYTICS_ENDPOINT", "https://other.example")
    colab.exchange("state")
    assert f'const origin = "{host}";' in scripts[1]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://analytics.example",
        "https://user:password@example.com",
        "https://example.com/v1/events",
        "https://example.com?x=1",
        "https://example.com#fragment",
        "https://",
        "https://example.com:bad",
        "https://exam ple.com",
    ],
)
def test_invalid_configuration_never_falls_back(value, monkeypatch):
    monkeypatch.setenv("SCREAMINGFACE_ANALYTICS_ENDPOINT", value)
    with pytest.raises(ValueError):
        endpoint.analytics_origin()

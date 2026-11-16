"""Credit refreshes preserve unrelated edits and the connection's display mode."""

from types import SimpleNamespace
from xml.etree import ElementTree

import httpx
import pytest
from test_connection_panel import SECRET, Engine, _button, _client, _panel, _password
from test_credits import payload

import screamingface as sf
from screamingface.credit import _decode


@pytest.fixture
def clock(monkeypatch):
    from screamingface._ui import credit_controller

    now = [1000.0]
    monkeypatch.setattr(credit_controller.time, "monotonic", lambda: now[0])
    return now


@pytest.mark.parametrize("automatic", [False, True])
def test_credit_refresh_preserves_unsaved_provider_key(clock, automatic):
    engine = Engine()
    body = payload()

    with _credit_client(engine, body) as client:
        panel = sf.ConnectionPanel(client)
        try:
            root = panel.widget()
            assert panel._view is not None
            password = _enter_provider_key(root)
            body["account"]["amount_usd"] = "87.65"
            clock[0] += 300
            if automatic:
                panel._auto_refresh_credits()
            else:
                _button(root, "Refresh credits").click()
            assert _password(root) is password
            assert password.value == SECRET
            assert _values(panel._view._credits.children[0].value)[0] == "$87.65"
            # The preserved controls must still submit to the same provider.
            _button(root, "Save").click()
            assert engine.connected
            assert password.value == ""
            assert panel.connections[0].status == "connected"
        finally:
            panel.close()


@pytest.mark.parametrize("hosted", [False, True])
@pytest.mark.parametrize("failure", ["http", "malformed"])
def test_lookup_failure_preserves_panel_credit_labels(hosted, failure):
    body = payload()
    if hosted:
        body["account"] = dict(body["hosted"])
        body["hosted"] = dict(body["key"])
        body["management_key_configured"] = False
        body["connection_token"] = None
    response = httpx.Response(200, json=body)
    client = SimpleNamespace(
        engine_url="https://engine.example" if hosted else "http://localhost:9100",
        authenticated=True,
        authenticating=False,
        connections=SimpleNamespace(list=lambda: ()),
        credits=lambda provider, **kwargs: _decode(response, provider),
    )
    panel = _panel(client)
    labels = ["Hosted allowance"] if hosted else ["Account balance", "Key allowance"]
    try:
        panel.widget()
        assert panel._view is not None
        assert _labels(panel._repr_html_()) == labels
        assert _labels(panel._view._credits.children[0].value) == labels
        response = (
            httpx.Response(503, json={"detail": "unavailable"})
            if failure == "http"
            else httpx.Response(200, json={"invalid": "body"})
        )
        panel.refresh_credits()
        assert _labels(panel._repr_html_()) == labels
        assert _labels(panel._view._credits.children[0].value) == labels
        assert _values(panel._view._credits.children[0].value) == ["Unavailable"] * len(labels)
    finally:
        panel.close()


def _labels(html):
    return _texts(html, "sf-credits__label")


def _values(html):
    return _texts(html, "sf-credits__value")


def _texts(html, css_class):
    root = ElementTree.fromstring(f"<root>{html}</root>")
    return [node.text for node in root.iter("div") if node.get("class") == css_class]


def _credit_client(engine, body):
    def handle(request):
        if request.url.path == "/v1/credits/openrouter":
            return httpx.Response(200, json=body)
        return engine(request)

    return _client(handle)


def _enter_provider_key(root):
    _button(root, "Connect").click()
    _button(root, "API key").click()
    password = _password(root)
    password.value = SECRET
    return password

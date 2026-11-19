"""The panel follows the current connection and bounds background reads."""

import httpx
from test_credits import payload

import screamingface as sf


def panel_for():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/v1/connections":
            return httpx.Response(200, json={"object": "list", "data": []})
        return httpx.Response(200, json=payload())

    client = sf.Client(
        engine_url="http://localhost:9100", http_transport=httpx.MockTransport(handle)
    )
    return client, sf.ConnectionPanel(client), calls


def test_automatic_refresh_uses_cache_and_limits_frequency(monkeypatch):
    from screamingface._ui import credit_controller

    now = [1000.0]
    monkeypatch.setattr(credit_controller.time, "monotonic", lambda: now[0])
    client, panel, calls = panel_for()
    try:
        count = len(calls)
        panel._auto_refresh_credits()
        assert len(calls) == count
        now[0] += 300
        panel._auto_refresh_credits()
        assert len(calls) == count + 1
        assert calls[-1].url.params["refresh"] == "false"
        panel.refresh_credits()
        assert calls[-1].url.params["refresh"] == "true"
        panel.close()
        now[0] += 300
        panel._auto_refresh_credits()
        assert len(calls) == count + 2
    finally:
        panel.close()
        client.close()


def test_refresh_never_overlaps_and_discards_changed_connection(monkeypatch):
    client, panel, calls = panel_for()
    original = client.credits

    def read(provider, *, refresh=True):
        count = len(calls)
        panel.refresh_credits()
        assert len(calls) == count
        panel._invalidate_credits()
        return original(provider, refresh=refresh)

    monkeypatch.setattr(client, "credits", read)
    try:
        panel.refresh_credits()
        assert panel._state.credit_status is None
    finally:
        panel.close()
        client.close()


def test_bridge_acknowledges_refresh_and_close_disables_it():
    from screamingface._ui.credit_refresh import create_refresh_bridge

    calls = []
    bridge = create_refresh_bridge(lambda: calls.append("read"))
    replies = []
    bridge.send = lambda message: replies.append(message)
    bridge._handle_custom_msg({"type": "refresh"}, [])
    bridge._handle_custom_msg({"type": "untrusted"}, [])
    assert calls == ["read"] and replies == [{"type": "refreshed"}]
    bridge.active = False
    bridge._handle_custom_msg({"type": "refresh"}, [])
    assert calls == ["read"]
    bridge.close()


def test_panel_close_stops_bridge_and_reusing_widget_does_not_add_timers():
    client, panel, _ = panel_for()
    try:
        widget = panel.widget()
        assert panel.widget() is widget
        assert panel._view is not None
        bridge = panel._view._credit_bridge
        widget.close()
        assert bridge.active is False
    finally:
        panel.close()
        client.close()


def test_hosted_card_has_one_budget_and_byok_explains_spending_cap():
    from screamingface._ui.credit_view import credit_html
    from screamingface.credit import _decode

    body = payload()
    html = credit_html(_decode(httpx.Response(200, json=body), "openrouter"))
    assert "spending cap" in html and "not additional credit" in html
    body["account"] = dict(body["hosted"])
    body["hosted"] = dict(body["key"])
    body["management_key_configured"] = False
    html = credit_html(_decode(httpx.Response(200, json=body), "openrouter"))
    assert html.count("$12.34") == 1
    assert "Hosted allowance" in html and "Account balance" not in html


def test_refresh_preserves_unsent_input_but_connection_change_clears_it():
    client, panel, _ = panel_for()
    try:
        panel.widget()
        assert panel._view is not None
        password = panel._view._credits.children[1].children[1]
        password.value = "unsent-private"
        panel.refresh_credits()
        assert panel._view._credits.children[1].children[1] is password
        assert password.value == "unsent-private"
        panel._invalidate_credits()
        panel._view.render()
        assert password.value == ""
    finally:
        panel.close()
        client.close()


def test_unavailable_reading_still_has_manual_refresh():
    from screamingface.credit import _unavailable

    client, panel, _ = panel_for()
    try:
        panel._state.credit_status = _unavailable("openrouter")
        panel.widget()
        assert panel._view is not None
        buttons = panel._view._credits.children[1].children
        assert [button.description for button in buttons] == ["Refresh credits"]
    finally:
        panel.close()
        client.close()

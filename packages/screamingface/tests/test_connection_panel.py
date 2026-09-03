from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from typing import Any, cast

import httpx
import ipywidgets as widgets
import pytest

import screamingface as sf

SECRET = "sk-or-v1-widget-secret"


class Engine:
    def __init__(self) -> None:
        self.connected = False
        self.reject = False
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        self.calls.append(request)
        row = {
            "object": "connection",
            "provider": "openrouter",
            "display_name": "OpenRouter",
            "auth_methods": ["api_key"],
            "status": "connected" if self.connected else "not_connected",
            "auth_method": "api_key" if self.connected else None,
            "account_label": None,
        }
        if request.method == "GET":
            return httpx.Response(200, json={"object": "list", "data": [row]})
        if request.method == "PUT":
            if self.reject:
                return httpx.Response(
                    401,
                    json={
                        "type": "about:blank",
                        "title": "Unauthorized",
                        "status": 401,
                        "detail": "private " + SECRET,
                    },
                )
            assert json.loads(request.content) == {"api_key": SECRET}
            self.connected = True
            return httpx.Response(
                200,
                json={**row, "status": "connected", "auth_method": "api_key"},
            )
        self.connected = False
        return httpx.Response(200, json={**row, "status": "not_connected", "auth_method": None})


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> sf.Client:
    return sf.Client(
        engine_url="http://127.0.0.1:9108",
        http_transport=httpx.MockTransport(handler),
    )


def _walk(widget: widgets.Widget) -> tuple[widgets.Widget, ...]:
    children = getattr(widget, "children", ())
    return (widget, *(item for child in children for item in _walk(child)))


def _buttons(widget: widgets.Widget) -> list[widgets.Button]:
    return [item for item in _walk(widget) if isinstance(item, widgets.Button)]


def _button(widget: widgets.Widget, description: str) -> widgets.Button:
    return next(item for item in _buttons(widget) if item.description == description)


def _password(widget: widgets.Widget) -> widgets.Password:
    return next(item for item in _walk(widget) if isinstance(item, widgets.Password))


def _text(widget: widgets.Widget) -> str:
    return "\n".join(
        value
        for item in _walk(widget)
        for attribute in ("value", "description", "tooltip")
        if isinstance((value := getattr(item, attribute, None)), str)
    )


def _panel(client: object) -> sf.ConnectionPanel:
    """Construct a panel from the deliberately minimal test doubles below."""

    return sf.ConnectionPanel(cast(Any, client))


def _hosted_panel(*connections: sf.Connection) -> sf.ConnectionPanel:
    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return connections

    class HostedClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = True
        authenticating = False
        connections = Connections()

    return _panel(HostedClient())


async def _wait_for_button(widget: widgets.Widget, description: str) -> None:
    for _ in range(100):
        if [button.description for button in _buttons(widget)] == [description]:
            return
        await asyncio.sleep(0.01)


class _CountingConnections:
    """Records whether providers were reloaded, so an interrupt path can prove it was not."""

    def __init__(self) -> None:
        self.calls = 0

    def list(self) -> tuple[sf.Connection, ...]:
        self.calls += 1
        return ()


class _EmptyConnections:
    def list(self) -> tuple[sf.Connection, ...]:
        return ()


class _SharedAuthClient:
    engine_url = "https://fusion.dev.screamingface.ai"
    authenticated = False
    authenticating = False
    connections = _EmptyConnections()

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.listeners: list[Callable[[], None]] = []

    def _subscribe_auth(self, listener: Callable[[], None]) -> Callable[[], None]:
        self.listeners.append(listener)

        def unsubscribe() -> None:
            self.listeners.remove(listener)

        return unsubscribe

    def _notify(self) -> None:
        for listener in tuple(self.listeners):
            listener()

    def login(self, *, timeout: float = 300.0) -> None:
        del timeout
        self.authenticating = True
        self._notify()
        self.started.set()
        self.authenticating = False
        self.authenticated = True
        self._notify()

    def _cancel_login(self) -> None:
        self.authenticating = False
        self.release.set()
        self._notify()

    def logout(self) -> None:
        self.authenticated = False
        self._notify()


def test_panel_keeps_the_full_collapsed_api_key_ui_and_only_one_openrouter_row() -> None:
    engine = Engine()
    client = _client(engine)
    panel = client.connect()
    root = panel.widget()

    assert [item.provider for item in panel.connections] == ["openrouter"]
    assert "Connections" in _text(root)
    assert "OpenRouter" in _text(root)
    assert "Hosted Engine" not in _text(root)
    assert "http://127.0.0.1:9108" in _text(root)
    assert [button.description for button in _buttons(root)] == ["Connect"]

    _button(root, "Connect").click()
    assert [button.description for button in _buttons(root)] == ["API key", "Cancel"]
    _button(root, "API key").click()
    password = _password(root)
    password.value = SECRET
    _button(root, "Save").click()

    assert password.value == ""
    assert [button.description for button in _buttons(root)] == ["Disconnect"]
    assert panel.connections[0].status == "connected"
    assert SECRET not in _text(root)
    assert SECRET not in panel._repr_html_()

    _button(root, "Disconnect").click()
    assert panel.connections[0].status == "not_connected"
    assert [button.description for button in _buttons(root)] == ["Connect"]
    root.close()
    client.close()


def test_panel_displays_safe_inline_errors_and_always_clears_the_password() -> None:
    engine = Engine()
    engine.reject = True
    client = _client(engine)
    root = client.connect().widget()

    _button(root, "Connect").click()
    _button(root, "API key").click()
    password = _password(root)
    password.value = SECRET
    _button(root, "Save").click()

    assert password.value == ""
    assert "Provider connection was rejected" in _text(root)
    assert SECRET not in _text(root)
    root.close()
    client.close()


def test_panel_displays_a_closed_client_error_instead_of_looking_saved() -> None:
    engine = Engine()
    client = _client(engine)
    root = client.connect().widget()
    _button(root, "Connect").click()
    _button(root, "API key").click()
    password = _password(root)
    password.value = SECRET
    client.close()

    _button(root, "Save").click()

    assert password.value == ""
    assert "Client is closed" in _text(root)
    assert engine.connected is False
    root.close()


def test_local_panel_renders_engine_unavailability_inline() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private socket detail", request=request)

    client = _client(unreachable)
    panel = client.connect()
    root = panel.widget()

    assert panel.connections == ()
    assert "Could not reach the SF Engine provider connections" in _text(root)
    assert "Start the local Engine" in _text(root)
    assert "private socket detail" not in _text(root)
    assert repr(panel) == "ConnectionPanel(engine='http://127.0.0.1:9108', )"
    root.close()
    client.close()


def test_panel_ipython_display_builds_the_interactive_widget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import IPython.display

    engine = Engine()
    client = _client(engine)
    panel = client.connect()
    displayed: list[widgets.Widget] = []
    monkeypatch.setattr(IPython.display, "display", displayed.append)

    panel._ipython_display_()

    assert len(displayed) == 1
    assert "OpenRouter" in _text(displayed[0])
    displayed[0].close()
    client.close()


def test_panel_retains_dormant_oauth_pending_and_cancel_controls() -> None:
    connection = sf.Connection(
        provider="future",
        display_name="Future Provider",
        auth_methods=("oauth", "api_key"),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )

    class Connections:
        def __init__(self) -> None:
            self.current = connection

        def list(self) -> tuple[sf.Connection, ...]:
            return (self.current,)

    class FutureClient:
        engine_url = "http://127.0.0.1:9108"
        connections = Connections()

    panel = _panel(FutureClient())
    root = panel.widget()

    _button(root, "Connect").click()
    assert [button.description for button in _buttons(root)] == ["OAuth", "API key", "Cancel"]

    _button(root, "Cancel").click()
    assert [button.description for button in _buttons(root)] == ["Connect"]
    _button(root, "Connect").click()

    pending = sf.Connection(
        provider="future",
        display_name="Future Provider",
        auth_methods=("oauth", "api_key"),
        status="pending",
        auth_method="oauth",
        account_label=None,
    )
    FutureClient.connections.current = pending
    panel.refresh()
    assert [button.description for button in _buttons(root)] == ["Cancel"]
    root.close()


@pytest.mark.asyncio
async def test_panel_starts_oauth_and_polls_without_blocking_the_notebook() -> None:  # noqa: PLR0915
    authorized = False
    started_oauth = False
    deleted = False
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal deleted, polls, started_oauth
        status = "connected" if authorized else "pending" if started_oauth else "not_connected"
        row = {
            "object": "connection",
            "provider": "anthropic",
            "display_name": "Anthropic",
            "auth_methods": ["api_key", "oauth"],
            "status": status,
            "auth_method": "oauth" if authorized else None,
            "account_label": "alice@example.com" if authorized else None,
        }
        if request.method == "POST":
            started_oauth = True
            return httpx.Response(
                201,
                json={
                    "object": "oauth_authorization",
                    "provider": "anthropic",
                    "authorize_url": "https://provider.example/authorize?state=private",
                    "expires_in": 600,
                },
            )
        if request.method == "DELETE":
            deleted = True
            return httpx.Response(
                200,
                json={
                    **row,
                    "status": "not_connected",
                    "auth_method": None,
                    "account_label": None,
                },
            )
        if started_oauth:
            polls += 1
        listed = {
            **row,
            "status": "not_connected" if deleted else row["status"],
            "auth_method": None if deleted else row["auth_method"],
            "account_label": None if deleted else row["account_label"],
        }
        return httpx.Response(200, json={"object": "list", "data": [listed]})

    client = _client(handler)
    panel = client.connect()
    root = panel.widget()
    _button(root, "Connect").click()

    # Jupyter can dispatch a later widget click on a different loop from the one that
    # rendered it. The OAuth poller must use the loop active for the click.
    stale_loop = asyncio.new_event_loop()
    panel._loop = stale_loop

    started = time.monotonic()
    _button(root, "OAuth").click()
    elapsed = time.monotonic() - started

    assert elapsed < 0.1
    assert "https://provider.example/authorize?state=private" in _text(root)
    assert [button.description for button in _buttons(root)] == ["Cancel"]

    for _ in range(100):
        if polls:
            break
        await asyncio.sleep(0.01)
    assert polls == 1
    authorized = True
    await _wait_for_button(root, "Disconnect")

    assert panel.connections[0].status == "connected"
    assert "alice@example.com" in _text(root)
    root.close()
    panel.close()
    client.close()
    stale_loop.close()


def test_panel_oauth_without_a_running_loop_remains_cancelable() -> None:
    connection = sf.Connection(
        provider="anthropic",
        display_name="Anthropic",
        auth_methods=("api_key", "oauth"),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )

    class Flow:
        authorize_url = "https://provider.example/authorize"
        expired = False

        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> sf.Connection:
            self.cancelled = True
            return connection

    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return (connection,)

    class Client:
        engine_url = "http://127.0.0.1:9108"
        connections = Connections()

        def __init__(self) -> None:
            self.flow = Flow()

        def connect(self, provider: str, *, method: str) -> Flow:
            assert (provider, method) == ("anthropic", "oauth")
            return self.flow

    client = Client()
    panel = _panel(client)
    root = panel.widget()
    _button(root, "Connect").click()
    _button(root, "OAuth").click()

    assert "https://provider.example/authorize" in _text(root)
    assert panel._tasks == {}

    _button(root, "Cancel").click()

    assert client.flow.cancelled is True
    assert [button.description for button in _buttons(root)] == ["Connect"]
    root.close()
    panel.close()


@pytest.mark.asyncio
async def test_panel_reports_an_expired_oauth_flow_and_cleans_up_its_task() -> None:
    connection = sf.Connection(
        provider="anthropic",
        display_name="Anthropic",
        auth_methods=("oauth",),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )

    class Flow:
        authorize_url = "https://provider.example/authorize"
        expired = True

    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return (connection,)

        def get(self, provider: str) -> sf.Connection:
            raise AssertionError(f"expired flow unexpectedly polled {provider}")

    class Client:
        engine_url = "http://127.0.0.1:9108"
        connections = Connections()

        def connect(self, provider: str, *, method: str) -> Flow:
            assert (provider, method) == ("anthropic", "oauth")
            return Flow()

    panel = _panel(Client())
    root = panel.widget()
    _button(root, "Connect").click()
    _button(root, "OAuth").click()

    for _ in range(100):
        if "expired" in _text(root):
            break
        await asyncio.sleep(0.01)

    assert panel._state.notice == "OAuth authorization for 'anthropic' expired"
    assert "OAuth authorization for" in _text(root)
    assert "expired" in _text(root)
    assert panel._tasks == {}
    assert [button.description for button in _buttons(root)] == ["Connect"]
    root.close()


def test_hosted_panel_prompts_for_engine_login_before_loading_providers() -> None:
    connection = sf.Connection(
        provider="openrouter",
        display_name="OpenRouter",
        auth_methods=("api_key",),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )

    class HostedConnections:
        calls = 0

        def list(self) -> tuple[sf.Connection, ...]:
            self.calls += 1
            return (connection,)

    class HostedClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        connections = HostedConnections()

        def __init__(self) -> None:
            self.authenticated = False
            self.authenticating = False
            self.logins = 0
            self.logouts = 0

        def login(self, *, timeout: float = 300.0) -> None:
            assert timeout == 300
            self.logins += 1
            self.authenticated = True

        def logout(self) -> None:
            self.logouts += 1
            self.authenticated = False

    client = HostedClient()
    panel = _panel(client)
    root = panel.widget()

    assert panel.connections == ()
    assert client.connections.calls == 0
    assert "ScreamingFace Hosted Engine" in _text(root)
    assert "😱" in _text(root)
    assert "login required" in _text(root)
    assert "OpenRouter" not in panel._repr_html_()
    assert [button.description for button in _buttons(root)] == ["Log in"]
    assert "access=login_required" in repr(panel)

    _button(root, "Log in").click()

    assert client.logins == 1
    assert client.connections.calls == 1
    assert panel.connections == (connection,)
    assert "authenticated" in _text(root)
    assert [button.description for button in _buttons(root)] == ["Log out"]

    _button(root, "Log out").click()

    assert client.logouts == 1
    assert panel.connections == ()
    assert client.connections.calls == 1
    assert [button.description for button in _buttons(root)] == ["Log in"]
    root.close()


def test_hosted_panel_shows_login_errors_without_loading_providers() -> None:
    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            raise AssertionError("providers must not load after a failed login")

    class RejectingClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False
        connections = Connections()

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            raise sf.AuthenticationError("Cloudflare Access login failed")

        def logout(self) -> None:
            self.authenticated = False

    panel = _panel(RejectingClient())
    root = panel.widget()

    _button(root, "Log in").click()

    assert "Cloudflare Access login failed" in _text(root)
    assert "login required" in _text(root)
    assert [button.description for button in _buttons(root)] == ["Log in"]
    root.close()


def test_hosted_panel_login_is_synchronous_and_bounded() -> None:
    """Login completes inside the click handler, within a bounded wait.

    WHY this replaced "login is non-blocking and waiting can be cancelled": a hosted
    notebook delivers a widget update only from a cell body or a click handler. Measured in
    Colab, a completion posted from a worker thread or an event-loop callback after the cell
    ends is silently dropped — so a threaded login could never put its authorization link on
    screen, nor show its own result. Login therefore runs on the clicking thread.

    The cost, stated rather than hidden: the Cancel button rendered while waiting cannot be
    clicked, because its handler queues behind this one, for up to _LOGIN_WAIT_SECONDS. That
    is accepted deliberately — Cloudflare Access can involve an emailed OTP, and cutting a
    first-time user off mid-login is worse than a briefly unavailable Cancel.
    """

    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return ()

    class WaitingClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False
        connections = Connections()

        def __init__(self) -> None:
            self.timeouts: list[float] = []
            self.cancellations = 0
            self.logouts = 0

        def login(self, *, timeout: float = 300.0) -> None:
            self.timeouts.append(timeout)
            self.authenticating = False
            raise sf.AuthenticationError(
                "Cloudflare Access login was cancelled",
                code="access_login_cancelled",
                permanent=False,
            )

        def _cancel_login(self) -> None:
            self.cancellations += 1
            self.authenticating = False

        def logout(self) -> None:
            self.logouts += 1
            self.authenticated = False

    client = WaitingClient()
    panel = _panel(client)
    root = panel.widget()

    _button(root, "Log in").click()

    assert client.timeouts == [300.0]
    # INVARIANT: a cancelled login is the user's own action, not an error to report at them.
    assert "cancelled" not in _text(root)
    assert client.logouts == 0
    # The wait is over by the time the click returns, so the row is back to its resting state.
    assert [button.description for button in _buttons(root)] == ["Log in"]
    root.close()


@pytest.mark.asyncio
async def test_hosted_panel_returns_to_login_after_cloudflare_denial() -> None:
    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            raise AssertionError("providers must not load after a denied login")

    class DeniedClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False
        connections = Connections()

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            self.authenticating = True
            self.authenticating = False
            raise sf.AuthenticationError(
                "Cloudflare Access rejected the browser login transfer",
                code="access_transfer_rejected",
                status=403,
            )

        def logout(self) -> None:
            self.authenticated = False

    panel = _panel(DeniedClient())
    root = panel.widget()
    _button(root, "Log in").click()

    for _ in range(100):
        if "rejected" in _text(root):
            break
        await asyncio.sleep(0.01)

    assert "rejected" in _text(root)
    assert [button.description for button in _buttons(root)] == ["Log in"]
    root.close()


@pytest.mark.asyncio
async def test_hosted_panel_shows_authenticated_when_provider_loading_fails() -> None:
    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            raise sf.ScreamingFaceError("The provider is not available on this SF Engine")

    class AuthenticatedClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False
        connections = Connections()

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            self.authenticated = True

        def _cancel_login(self) -> None:
            self.authenticating = False

        def logout(self) -> None:
            self.authenticated = False

    client = AuthenticatedClient()
    panel = _panel(client)
    root = panel.widget()
    _button(root, "Log in").click()

    for _ in range(100):
        if "provider is not available" in _text(root):
            break
        await asyncio.sleep(0.01)

    assert client.authenticated is True
    assert "authenticated" in _text(root)
    assert [button.description for button in _buttons(root)] == ["Log out"]
    root.close()


def test_authenticated_panel_renders_even_when_initial_provider_loading_fails() -> None:
    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            raise sf.ScreamingFaceError("Provider discovery is unavailable")

    class AuthenticatedClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = True
        authenticating = False
        connections = Connections()

        def logout(self) -> None:
            self.authenticated = False

    panel = _panel(AuthenticatedClient())
    root = panel.widget()

    assert "Provider discovery is unavailable" in _text(root)
    assert "authenticated" in _text(root)
    assert [button.description for button in _buttons(root)] == ["Log out"]
    root.close()


def test_all_open_panels_follow_shared_login_and_logout_state() -> None:
    # Login now completes within the click, so a second panel opened afterwards starts from
    # the shared authenticated state, and the broadcast keeps both in step on logout.
    client = _SharedAuthClient()
    first = _panel(client)
    first_root = first.widget()

    _button(first_root, "Log in").click()

    assert [button.description for button in _buttons(first_root)] == ["Log out"]
    second = _panel(client)
    second_root = second.widget()
    assert [button.description for button in _buttons(second_root)] == ["Log out"]

    _button(first_root, "Log out").click()

    assert [button.description for button in _buttons(first_root)] == ["Log in"]
    assert [button.description for button in _buttons(second_root)] == ["Log in"]
    first_root.close()
    second_root.close()
    first.close()
    second.close()
    assert client.listeners == []


@pytest.mark.asyncio
async def test_unprotected_remote_engine_skips_the_access_login_row() -> None:
    connection = sf.Connection(
        provider="openrouter",
        display_name="OpenRouter",
        auth_methods=("api_key",),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )

    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return (connection,)

    class RemoteClient:
        engine_url = "https://remote-engine.example"
        authenticated = False
        authenticating = False
        connections = Connections()

        def _access_required(self) -> bool:
            return False

    panel = _panel(RemoteClient())
    root = panel.widget()
    for _ in range(100):
        if "OpenRouter" in _text(root):
            break
        await asyncio.sleep(0.01)

    assert "Hosted Engine" not in _text(root)
    assert "OpenRouter" in _text(root)
    assert [button.description for button in _buttons(root)] == []
    root.close()


@pytest.mark.asyncio
async def test_unexpected_login_failure_does_not_leave_panel_waiting() -> None:
    class Client:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False
        connections = _EmptyConnections()

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            raise RuntimeError("Client closed during login")

    panel = _panel(Client())
    root = panel.widget()
    _button(root, "Log in").click()
    await _wait_for_button(root, "Log in")

    assert "Client closed during login" in _text(root)
    root.close()


def test_non_screamingface_hosted_engine_shows_a_neutral_label_without_the_mark() -> None:
    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return ()

    class RemoteHostedClient:
        engine_url = "https://engine.acme.example"
        connections = Connections()

        def __init__(self) -> None:
            self.authenticated = False
            self.authenticating = False

    panel = _panel(RemoteHostedClient())
    root = panel.widget()

    text = _text(root)
    assert "Hosted Engine" in text
    assert "ScreamingFace Hosted Engine" not in text
    assert "😱" not in text
    assert "login required" in text
    root.close()


def test_authenticated_hosted_provider_rows_show_caller_availability_without_controls() -> None:
    connected = sf.Connection(
        provider="openrouter",
        display_name="OpenRouter",
        auth_methods=("api_key",),
        status="connected",
        auth_method="api_key",
        account_label="private-account@example.com",
    )
    caller_disconnected = sf.Connection(
        provider="anthropic",
        display_name="Anthropic",
        auth_methods=("api_key", "oauth"),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )
    panel = _hosted_panel(connected, caller_disconnected)
    root = panel.widget()

    text = _text(root)
    html = panel._repr_html_()
    representation = repr(panel)
    assert [button.description for button in _buttons(root)] == ["Log out"]
    assert text.count("Available via ScreamingFace") == 1
    assert html.count("Available via ScreamingFace") == 1
    assert text.count("Connected") == 1
    assert "Unavailable" in text
    assert "Unavailable" in html
    assert "private-account@example.com" not in text
    assert "private-account@example.com" not in html
    assert "openrouter=connected" in representation
    assert "anthropic=unavailable" in representation
    assert "not_connected" not in representation
    root.close()


@pytest.mark.parametrize("status", ["not_connected", "pending", "needs_reauth", "error"])
def test_hosted_non_connected_wire_states_project_to_unavailable(status: str) -> None:
    connection = sf.Connection(
        provider="future",
        display_name="Future Provider",
        auth_methods=("oauth",),
        status=cast(Any, status),
        auth_method=None,
        account_label=None,
    )
    panel = _hosted_panel(connection)
    root = panel.widget()

    expected_cell = (
        "<div class='sf-connections__status unavailable'><i class='sq'></i>Unavailable</div>"
    )
    widget_text = _text(root)
    html = panel._repr_html_()
    assert widget_text.count(expected_cell) == 1
    assert html.count(expected_cell) == 1
    assert "Available via ScreamingFace" not in widget_text
    assert "Available via ScreamingFace" not in html
    assert "future=unavailable" in repr(panel)
    assert [button.description for button in _buttons(root)] == ["Log out"]
    root.close()


@pytest.mark.parametrize("engine_url", ["http://localhost:9108", "http://[::1]:9108"])
def test_loopback_provider_rows_keep_byok_controls(engine_url: str) -> None:
    connection = sf.Connection(
        provider="openrouter",
        display_name="OpenRouter",
        auth_methods=("api_key",),
        status="not_connected",
        auth_method=None,
        account_label=None,
    )

    class Connections:
        def list(self) -> tuple[sf.Connection, ...]:
            return (connection,)

    class LocalClient:
        authenticated = False
        authenticating = False
        connections = Connections()

        def __init__(self) -> None:
            self.engine_url = engine_url

    panel = _panel(LocalClient())
    root = panel.widget()

    assert [button.description for button in _buttons(root)] == ["Connect"]
    root.close()


def _render_on_a_disposable_loop(panel: sf.ConnectionPanel) -> widgets.Widget:
    """Render on a loop that is then closed, reproducing the Colab lifecycle.

    WHY: Colab may close or replace the asyncio loop that was live when the widget
    rendered. The panel must not depend on that loop still existing when a background
    completion arrives. A plain ``asyncio.run`` cannot be nested inside an async test,
    so these cases stay synchronous.
    """

    async def render() -> widgets.Widget:
        return panel.widget()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(render())
    finally:
        loop.close()


def _settle(root: widgets.Widget, *, until: Callable[[str], bool]) -> str:
    for _ in range(200):
        text = _text(root)
        if until(text):
            return text
        time.sleep(0.01)
    return _text(root)


class _GatedAccessClient:
    """Holds Access discovery open until the test releases it."""

    engine_url = "https://fusion.dev.screamingface.ai"
    authenticated = False
    authenticating = False

    def __init__(self, *, required: bool = True, error: Exception | None = None) -> None:
        self.connections = _EmptyConnections()
        self.started = threading.Event()
        self.release = threading.Event()
        self._required = required
        self._error = error

    def _access_required(self) -> bool:
        self.started.set()
        assert self.release.wait(1)
        if self._error is not None:
            raise self._error
        return self._required


def test_module_level_connect_reaches_a_terminal_state_after_the_loop_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # WHY: the issue's acceptance requires the documented module-level entrypoint to be
    # covered, not only the internal ConnectionPanel helper.
    client = _GatedAccessClient(required=True)
    monkeypatch.setattr("screamingface._default_client.default_client", lambda: cast(Any, client))

    async def render() -> widgets.Widget:
        return sf.connect().widget()

    loop = asyncio.new_event_loop()
    try:
        root = loop.run_until_complete(render())
    finally:
        loop.close()

    assert client.started.wait(1)
    client.release.set()
    text = _settle(root, until=lambda value: "checking" not in value)

    assert "checking" not in text
    assert [button.description for button in _buttons(root)] == ["Log in"]
    root.close()


def test_static_html_does_not_claim_checking_when_no_probe_is_running() -> None:
    # INVARIANT: "checking" means a probe is in flight. _repr_html_ never starts one,
    # so it must render the resolved state instead of a status nothing will clear.
    client = _GatedAccessClient(required=True)
    panel = _panel(client)

    html = panel._repr_html_()

    assert "checking" not in html
    assert "login required" in html
    assert not client.started.is_set()


def test_access_discovery_resolves_when_the_widget_renders_without_a_loop() -> None:
    # WHY: a plain script or an older kernel renders with no running loop at all, so the
    # probe runs synchronously; that branch must still reach a terminal state.
    client = _GatedAccessClient(required=True)
    client.release.set()
    panel = _panel(client)

    root = panel.widget()

    assert client.started.is_set()
    text = _text(root)
    assert "checking" not in text
    assert "login required" in text
    assert [button.description for button in _buttons(root)] == ["Log in"]
    root.close()


def test_an_async_access_probe_is_never_read_as_a_result() -> None:
    # INVARIANT: an ``async def _access_required`` must never be invoked as if it were
    # synchronous. A coroutine object is truthy, so its return value would report "access
    # required" for every Engine while the coroutine itself was silently never awaited.
    #
    # WHY the assertion is a warning check: an un-awaited coroutine never executes its
    # body, so no counter inside the probe can observe the call. The leaked coroutine is
    # the only observable, and it surfaces as a RuntimeWarning when it is collected.
    import gc
    import warnings

    class AsyncProbeClient:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False

        def __init__(self) -> None:
            self.connections = _EmptyConnections()

        async def _access_required(self) -> bool:
            return False

    client = AsyncProbeClient()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        panel = _panel(client)
        root = panel.widget()
        gc.collect()

    never_awaited = [
        entry
        for entry in caught
        if issubclass(entry.category, RuntimeWarning) and "never awaited" in str(entry.message)
    ]
    assert never_awaited == []

    text = _text(root)
    assert "checking" not in text
    assert "login required" in text
    assert [button.description for button in _buttons(root)] == ["Log in"]
    root.close()


_ACCESS_URL = "https://engine.example/cdn-cgi/access/login?key=abc123&next=%2F"


class _AuthorizingClient:
    """Hosted client whose login announces an authorization URL, then blocks."""

    engine_url = "https://fusion.dev.screamingface.ai"
    authenticated = False
    authenticating = False

    def __init__(self, *, url: str = _ACCESS_URL, fail: Exception | None = None) -> None:
        self.connections = _EmptyConnections()
        self.presenters: list[Callable[[str], None]] = []
        self.release = threading.Event()
        self.announced = threading.Event()
        self._url = url
        self._fail = fail

    def _subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]:
        self.presenters.append(presenter)

        def unsubscribe() -> None:
            if presenter in self.presenters:
                self.presenters.remove(presenter)

        return unsubscribe

    def login(self, *, timeout: float = 300.0) -> None:
        del timeout
        self.authenticating = True
        for presenter in tuple(self.presenters):
            presenter(self._url)
        self.announced.set()
        assert self.release.wait(1)
        self.authenticating = False
        if self._fail is not None:
            raise self._fail
        self.authenticated = True

    def _cancel_login(self) -> None:
        self.authenticating = False
        self.release.set()


def _render_click_login(panel: sf.ConnectionPanel) -> tuple[Any, widgets.Widget]:
    """Render and click Log in on one loop, returning that loop so it can be pumped.

    WHY: the presenter fires on the login worker thread and is delivered through the
    panel's dispatcher, so the loop it posts to has to keep running for the callback to
    land. A plain sleep would never drain it.
    """

    async def render_and_click() -> widgets.Widget:
        root = panel.widget()
        _button(root, "Log in").click()
        return root

    loop = asyncio.new_event_loop()
    return loop, loop.run_until_complete(render_and_click())


def _settle_on_loop(loop: Any, root: widgets.Widget, *, until: Callable[[str], bool]) -> str:
    for _ in range(200):
        text = _text(root)
        if until(text):
            return text
        loop.run_until_complete(asyncio.sleep(0.01))
    return _text(root)


def test_the_authorization_link_is_escaped() -> None:
    seen: list[str] = []

    class Client:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False

        def __init__(self) -> None:
            self.connections = _EmptyConnections()
            self.presenters: list[Callable[[str], None]] = []

        def _access_required(self) -> bool:
            return True

        def _subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]:
            self.presenters.append(presenter)
            return lambda: self.presenters.remove(presenter)

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            for presenter in tuple(self.presenters):
                presenter('https://e.example/login?a=1&b="x"')
            seen.append(_text(root))
            self.authenticated = True

        def _cancel_login(self) -> None:
            self.authenticating = False

    panel = _panel(Client())
    root = panel.widget()
    _button(root, "Log in").click()

    assert seen != []
    assert "&amp;" in seen[0]
    assert "&quot;" in seen[0] or "&#x27;" in seen[0]
    root.close()


def test_the_authorization_subscription_is_released_when_the_panel_closes() -> None:
    client = _AuthorizingClient()
    panel = _panel(client)
    root = panel.widget()

    assert client.presenters != []
    panel.close()

    assert client.presenters == []
    root.close()


def test_an_authorization_announced_after_close_is_ignored() -> None:
    # A login can still be in flight when the panel closes; the late announcement must not
    # resurrect state on a dead panel.
    client = _AuthorizingClient()
    panel = _panel(client)
    root = panel.widget()
    presenter = client.presenters[0]

    panel.close()
    presenter(_ACCESS_URL)

    assert panel._state.access_authorization_url is None
    root.close()


def test_access_discovery_resolves_before_the_widget_is_displayed() -> None:
    # WHY: a hosted notebook delivers a widget update only from a cell body or a click
    # handler — never from a loop callback or a worker thread after the cell ends. So the
    # probe must resolve while `widget()` is still running, and no "checking" state may
    # survive into the displayed panel. Measured in Colab; see the PR.
    probe_threads: list[str] = []

    class Client:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False

        def __init__(self) -> None:
            self.connections = _EmptyConnections()

        def _access_required(self) -> bool:
            probe_threads.append(threading.current_thread().name)
            return True

    async def render() -> widgets.Widget:
        # A running loop must NOT push the probe onto a worker thread any more.
        return _panel(Client()).widget()

    loop = asyncio.new_event_loop()
    try:
        root = loop.run_until_complete(render())
    finally:
        loop.close()

    assert probe_threads == ["MainThread"]
    text = _text(root)
    assert "checking" not in text
    assert "login required" in text
    root.close()


def test_the_authorization_link_appears_from_within_the_login_click() -> None:
    # INVARIANT: the link must be rendered before login starts waiting, and on the clicking
    # thread — a mid-handler render reaches a hosted notebook, a later one does not.
    seen_during_login: list[str] = []
    url = "https://engine.example/cdn-cgi/access/login?key=mid-handler"

    class Client:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticating = False

        def __init__(self) -> None:
            self.connections = _EmptyConnections()
            self.authenticated = False
            self.presenters: list[Callable[[str], None]] = []

        def _access_required(self) -> bool:
            return True

        def _subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]:
            self.presenters.append(presenter)
            return lambda: self.presenters.remove(presenter)

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            for presenter in tuple(self.presenters):
                presenter(url)
            # Whatever the panel has rendered by now is what a hosted notebook will show
            # while the user completes the browser flow.
            seen_during_login.append(_text(root))
            self.authenticated = True

        def _cancel_login(self) -> None:
            self.authenticating = False

    client = Client()
    panel = _panel(client)
    root = panel.widget()
    _button(root, "Log in").click()

    assert seen_during_login != []
    assert "Authorize" in seen_during_login[0]
    assert "cdn-cgi/access/login?key=mid-handler" in seen_during_login[0]
    # And once login returns, the panel has already moved on — no deferred repaint needed.
    final = _text(root)
    assert "Authorize" not in final
    assert [button.description for button in _buttons(root)] == ["Log out"]
    root.close()


def test_interrupting_the_login_wait_leaves_the_row_usable() -> None:
    # WHY: the stop button is the user's only escape from the wait, since Cancel provably
    # cannot be clicked while the handler blocks. KeyboardInterrupt is therefore an expected
    # exit path, and it must not leave the row showing Cancel with no channel left to repaint.
    class Client:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False

        def __init__(self) -> None:
            self.connections = _CountingConnections()

        def _access_required(self) -> bool:
            return True

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            # The token can land just before the user hits stop.
            self.authenticated = True
            raise KeyboardInterrupt

        def _cancel_login(self) -> None:
            self.authenticating = False

    client = Client()
    panel = _panel(client)
    root = panel.widget()

    with pytest.raises(KeyboardInterrupt):
        _button(root, "Log in").click()

    # INVARIANT: no network call during the unwind — reloading providers would delay the
    # very interrupt the user reached for.
    assert client.connections.calls == 0
    assert panel._state.access_pending is False
    assert panel._state.access_authorization_url is None
    # The token did land, so the row tells the truth about that — what it must not do is
    # sit on Cancel with no channel left to repaint it.
    assert [button.description for button in _buttons(root)] == ["Log out"]
    assert "Cancel" not in _text(root)
    root.close()


def test_the_panel_subscribes_through_a_real_client() -> None:
    # WHY a real Client and not a double: every other panel test stubs
    # _subscribe_authorization, so nothing exercised the actual seam to the auth object. If
    # that wiring broke, the panel would silently never receive an authorization URL — the
    # exact failure this work exists to fix — and no test would notice.
    client = _client(Engine())
    panel = _panel(client)

    root = panel.widget()

    assert panel._unsubscribe_authorization is not None
    panel.close()
    assert panel._unsubscribe_authorization is None
    root.close()


@pytest.mark.asyncio
async def test_async_client_exposes_the_same_authorization_subscription() -> None:
    # INVARIANT: parity with Client. AsyncClient declares the same private surface the panel
    # relies on; an unexercised async path is what produced the coroutine-read-as-bool bug.
    client = sf.AsyncClient(
        engine_url="http://127.0.0.1:9108",
        http_transport=httpx.MockTransport(Engine()),
    )
    seen: list[str] = []

    unsubscribe = client._subscribe_authorization(seen.append)

    assert callable(unsubscribe)
    unsubscribe()
    # Idempotent, like the auth-state subscription it mirrors.
    unsubscribe()
    await client.aclose()


def test_no_cancel_is_offered_while_the_login_blocks() -> None:
    # WHY: the login handler blocks, so a queued Cancel click cannot run until the wait is
    # already over. A button that looks live and does nothing is worse than no button — the
    # notebook stop button is the escape, and it leaves a clean row.
    during: list[list[str]] = []

    class Client:
        engine_url = "https://fusion.dev.screamingface.ai"
        authenticated = False
        authenticating = False

        def __init__(self) -> None:
            self.connections = _EmptyConnections()
            self.presenters: list[Callable[[str], None]] = []

        def _access_required(self) -> bool:
            return True

        def _subscribe_authorization(self, presenter: Callable[[str], None]) -> Callable[[], None]:
            self.presenters.append(presenter)
            return lambda: self.presenters.remove(presenter)

        def login(self, *, timeout: float = 300.0) -> None:
            del timeout
            for presenter in tuple(self.presenters):
                presenter("https://engine.example/cdn-cgi/access/login?key=k")
            during.append([button.description for button in _buttons(root)])
            self.authenticated = True

        def _cancel_login(self) -> None:
            self.authenticating = False

    panel = _panel(Client())
    root = panel.widget()
    _button(root, "Log in").click()

    # Only the Authorize link is offered while the wait is in progress.
    assert during == [[]]
    root.close()

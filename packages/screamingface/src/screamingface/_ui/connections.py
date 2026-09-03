"""Engine connection-panel controller, independent of notebook rendering details."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast, overload

from screamingface._ui.connection_state import (
    _ConnectionPanelState,
    _sync_access_probe,
    _user_message,
)
from screamingface._ui.connection_view import (
    _NotebookConnectionView,
    _provider_presentation,
    static_panel_html,
)
from screamingface._ui.engine_origin import _is_hosted_engine
from screamingface.errors import ScreamingFaceError

if TYPE_CHECKING:
    from ipywidgets import Widget

    from screamingface.connections import Connection, OAuthFlow


# Deliberately the same 300s the Client documents as its login default — one notion of how
# long a login may take, rather than a panel-specific number that drifts from it.
# WHY it is this long: the wait blocks the click handler, so a queued Cancel cannot run until
# it returns — but Cloudflare Access can involve an emailed OTP, and cutting a first-time
# user off mid-login is worse than a Cancel button that is briefly unavailable.
_LOGIN_WAIT_SECONDS = 300.0


class _ConnectionCatalog(Protocol):
    def list(self) -> tuple[Connection, ...]: ...

    def get(self, provider: str) -> Connection: ...


class _Client(Protocol):
    @property
    def engine_url(self) -> str: ...

    @property
    def connections(self) -> _ConnectionCatalog: ...

    @property
    def authenticated(self) -> bool: ...

    @property
    def authenticating(self) -> bool: ...

    def login(self, *, timeout: float = 300.0) -> None: ...

    def _cancel_login(self) -> None: ...

    def _subscribe_auth(self, callback: Callable[[], None]) -> Callable[[], None]: ...

    def _access_required(self) -> bool: ...

    def logout(self) -> None: ...

    @overload
    def connect(
        self,
        provider: str,
        *,
        api_key: str,
        method: Literal["api_key"] | None = None,
    ) -> Connection: ...

    @overload
    def connect(
        self,
        provider: str,
        *,
        api_key: None = None,
        method: Literal["oauth"],
    ) -> OAuthFlow: ...

    def disconnect(self, provider: str) -> Connection: ...


class ConnectionPanel:
    """A fresh Engine-scoped connection view with optional notebook controls."""

    def __init__(self, client: _Client) -> None:
        self.engine: str = client.engine_url
        self._client = client
        hosted = _is_hosted_engine(client.engine_url)
        self._state = _ConnectionPanelState(
            hosted=hosted,
            engine_url=client.engine_url,
            # Temporary tester-release policy: only a loopback Engine exposes BYOK controls.
            # Keep this separate from `hosted`, which may later be cleared when a remote Engine
            # reports that it does not require Cloudflare Access.
            provider_mutations_enabled=not hosted,
            access_check_pending=(
                hosted and not client.authenticated and _sync_access_probe(client) is not None
            ),
        )
        if not hosted or client.authenticated:
            try:
                self._state.connections = client.connections.list()
            except (ScreamingFaceError, ValueError) as exc:
                self._state.notice = _user_message(exc)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._unsubscribe_auth: Callable[[], None] | None = None
        self._unsubscribe_authorization: Callable[[], None] | None = None
        self._view: _NotebookConnectionView | None = None
        self._closed = False

    @property
    def connections(self) -> tuple[Connection, ...]:
        return self._state.connections

    @property
    def authenticated(self) -> bool:
        return self._client.authenticated

    @property
    def authenticating(self) -> bool:
        return self._client.authenticating

    def refresh(self) -> tuple[Connection, ...]:
        self._state.connections = (
            self._client.connections.list()
            if not self._state.hosted or self._client.authenticated
            else ()
        )
        self._render_rows()
        return self._state.connections

    def widget(self) -> Widget:
        # WHY kept: _start_oauth needs a loop to create its polling task on. Nothing else
        # defers work any more — Access discovery is synchronous and login runs in the click.
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        subscribe = getattr(self._client, "_subscribe_auth", None)
        if callable(subscribe) and self._unsubscribe_auth is None:
            typed_subscribe = cast(
                Callable[[Callable[[], None]], Callable[[], None]],
                subscribe,
            )
            self._unsubscribe_auth = typed_subscribe(self._auth_state_changed)
        self._subscribe_authorization()
        # WHY: the access check starts BEFORE the view is built. _render_rows() no-ops while
        # `_view` is None, so the first render already reflects the probe instead of
        # flickering login_required -> checking -> login_required.
        self._start_access_check()
        self._view = _NotebookConnectionView(self, self._state)
        return self._view.root

    def _repr_html_(self) -> str:
        return static_panel_html(
            self.engine,
            self._state,
            authenticated=self._client.authenticated if self._state.hosted else False,
            authenticating=self._client.authenticating if self._state.hosted else False,
        )

    def _ipython_display_(self) -> None:
        from IPython.display import display

        display(self.widget())

    def __repr__(self) -> str:
        provider_mutations_enabled = self._state.provider_mutations_enabled
        statuses = ", ".join(
            f"{item.provider}="
            + _provider_presentation(
                item,
                provider_mutations_enabled=provider_mutations_enabled,
            ).status_class
            for item in self._state.connections
        )
        access = (
            f", access={'authenticated' if self._client.authenticated else 'login_required'}"
            if self._state.hosted
            else ""
        )
        return f"ConnectionPanel(engine={self.engine!r}{access}, {statuses})"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._unsubscribe_auth is not None:
            self._unsubscribe_auth()
            self._unsubscribe_auth = None
        if self._unsubscribe_authorization is not None:
            self._unsubscribe_authorization()
            self._unsubscribe_authorization = None
        for task in tuple(self._tasks.values()):
            task.cancel()
        self._tasks.clear()

    def _render_rows(self) -> None:
        if self._view is not None:
            self._view.render()

    def _show_methods(self, provider: str) -> None:
        self._state.modes[provider] = "methods"
        self._render_rows()

    def _show_api_key(self, provider: str) -> None:
        self._state.modes[provider] = "api_key"
        self._render_rows()

    def _cancel_mode(self, provider: str) -> None:
        self._state.modes.pop(provider, None)
        self._render_rows()

    def _attempt(self, action: Callable[[], Any]) -> None:
        self._set_notice(None)
        try:
            action()
        except (ScreamingFaceError, RuntimeError, ValueError) as exc:
            self._set_notice(_user_message(exc))

    def _set_notice(self, message: str | None) -> None:
        self._state.notice = message
        if self._view is not None:
            self._view.render_notice()

    def _submit_api_key(self, provider: str, api_key: str) -> None:
        self._client.connect(provider, api_key=api_key)
        self._state.modes.pop(provider, None)
        self.refresh()

    def _start_oauth(self, provider: str) -> None:
        flow = self._client.connect(provider, method="oauth")
        if not hasattr(flow, "authorize_url"):
            raise ValueError("the Engine did not start an OAuth authorization")
        self._state.modes.pop(provider, None)
        self._state.flows[provider] = flow
        self._render_rows()
        # WHY: Jupyter may render a widget and later dispatch its button callback on a
        # different event loop. Always prefer the loop active for this click; scheduling
        # the poller on the loop cached by ``widget()`` can leave it dormant forever.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
        if loop is None or loop.is_closed():
            return
        self._loop = loop
        self._tasks[provider] = loop.create_task(self._poll_oauth(provider, flow))

    async def _poll_oauth(self, provider: str, flow: object) -> None:
        try:
            while self._state.flows.get(provider) is flow:
                if bool(getattr(flow, "expired", False)):
                    raise ValueError(f"OAuth authorization for {provider!r} expired")
                connection = await asyncio.to_thread(self._client.connections.get, provider)
                if connection.status != "pending":
                    self._state.flows.pop(provider, None)
                    self._state.connections = await asyncio.to_thread(self._client.connections.list)
                    self._render_rows()
                    return
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except (ScreamingFaceError, RuntimeError, ValueError) as exc:
            self._state.flows.pop(provider, None)
            self._set_notice(_user_message(exc))
            self._render_rows()
        finally:
            current = asyncio.current_task()
            if self._tasks.get(provider) is current:
                self._tasks.pop(provider, None)

    def _login_access(self) -> None:
        self._client.login()

    def _access_waiting(self) -> bool:
        return self._state.access_pending or self._client.authenticating

    def _subscribe_authorization(self) -> None:
        subscribe = getattr(self._client, "_subscribe_authorization", None)
        if not callable(subscribe) or self._unsubscribe_authorization is not None:
            return
        typed_subscribe = cast(
            Callable[[Callable[[str], None]], Callable[[], None]],
            subscribe,
        )
        self._unsubscribe_authorization = typed_subscribe(self._authorization_announced)

    def _authorization_announced(self, authorization_url: str) -> None:
        # WHY: applied INLINE, never through the dispatcher. Login now runs on the clicking
        # thread, and a hosted notebook delivers a widget update only from a cell body or a
        # click handler — a loop callback or worker thread after the cell ends is silently
        # dropped. Rendering here, mid-handler, is what puts the link on screen (OME-930).
        if self._closed:
            return
        self._apply_authorization_url(authorization_url)

    def _apply_authorization_url(self, authorization_url: str | None) -> None:
        if self._closed:
            return
        self._state.access_authorization_url = authorization_url
        self._render_rows()

    def _start_login_access(self) -> None:
        self._set_notice(None)
        if self._access_waiting():
            self._render_rows()
            return
        # WHY: deliberately synchronous, on the clicking thread. A hosted notebook delivers
        # a widget update only from a cell body or a click handler; the login worker thread
        # this replaced announced its authorization URL into a channel Colab drops, so the
        # link never appeared. Rendering mid-handler is the only thing that reaches the
        # browser, which also means the panel needs no deferred repaint to finish.
        # AIDEV-NOTE: the trade-off is that Cancel cannot be clicked while this blocks — its
        # handler queues behind this one, for up to _LOGIN_WAIT_SECONDS.
        self._state.access_pending = True
        self._render_rows()
        self._set_notice(None)
        try:
            self._client.login(timeout=_LOGIN_WAIT_SECONDS)
        except (ScreamingFaceError, RuntimeError, ValueError) as exc:
            # WHY: a cancelled login is the user's own action, not a failure to report at
            # them. Preserved from the completion handler this replaced.
            if getattr(exc, "code", None) != "access_login_cancelled":
                self._set_notice(_user_message(exc))
        finally:
            self._state.access_pending = False
            self._state.access_authorization_url = None
            # INVARIANT: the row is always re-rendered, including on KeyboardInterrupt. The
            # stop button is the user's only escape from the wait — Cancel cannot be clicked
            # while the handler blocks — so an interrupt is an expected exit path, and it
            # must not leave the row showing Cancel with no channel left to repaint it.
            self._render_rows()
        # WHY outside the finally: refresh() makes a network call, and on KeyboardInterrupt
        # that would run during the unwind and delay the very interrupt the user reached for.
        # Reloading providers is only meaningful when login actually returned.
        if self._client.authenticated:
            self._attempt(self.refresh)

    def _start_access_check(self) -> None:
        if not self._state.access_check_pending or self._state.access_check_started:
            return
        check = _sync_access_probe(self._client)
        if check is None:
            self._state.access_check_pending = False
            self._render_rows()
            return
        self._state.access_check_started = True
        # WHY: resolved synchronously, never on a worker thread. A hosted notebook cannot
        # repaint from a background completion, so a threaded probe leaves the row reading
        # "checking" forever even though the state is correct. Probing here means the view
        # is built already showing the answer, and no "checking" state ever reaches a user.
        # Measured at ~0.2s against the hosted Engine.
        self._run_access_check_sync(check)

    def _run_access_check_sync(self, check: Callable[[], bool]) -> None:
        try:
            required = check()
        except Exception as exc:
            self._complete_access_check(True, exc)
        else:
            self._complete_access_check(required, None)

    def _complete_access_check(self, required: bool, error: Exception | None) -> None:
        if self._closed:
            return
        self._state.access_check_pending = False
        if error is not None:
            self._set_notice(_user_message(error))
        elif not required:
            self._state.hosted = False
            try:
                self._state.connections = self._client.connections.list()
            except (ScreamingFaceError, ValueError) as exc:
                self._state.connections = ()
                self._set_notice(_user_message(exc))
        self._render_rows()

    def _auth_state_changed(self) -> None:
        if self._closed:
            return
        # WHY inline, not deferred: a hosted notebook delivers a widget update only from a
        # cell body or a click handler. Login is synchronous now, so this always arrives on
        # the thread that can render — and posting it to an event loop would repeat exactly
        # the bug this work removed (OME-930).
        self._apply_auth_state()

    def _apply_auth_state(self) -> None:
        if self._closed:
            return
        self._state.access_pending = self._client.authenticating
        if not self._client.authenticating:
            self._state.access_authorization_url = None
        if self._client.authenticated:
            try:
                self._state.connections = self._client.connections.list()
            except (ScreamingFaceError, ValueError) as exc:
                self._state.connections = ()
                self._set_notice(_user_message(exc))
        else:
            self._state.connections = ()
        self._render_rows()

    def _logout_access(self) -> None:
        self._client.logout()
        self._state.access_pending = False
        self._state.connections = ()
        self._render_rows()

        self._state.access_pending = False
        self._state.connections = ()
        self._render_rows()

    def _disconnect(self, provider: str) -> None:
        self._client.disconnect(provider)
        self._state.modes.pop(provider, None)
        self._drop_flow(provider)
        self.refresh()

    def _cancel_flow(self, provider: str) -> None:
        flow = self._state.flows.pop(provider, None)
        cancel = getattr(flow, "cancel", None)
        if callable(cancel):
            cancel()
        self._drop_flow(provider)
        self._state.modes.pop(provider, None)
        self.refresh()

    def _drop_flow(self, provider: str) -> None:
        self._state.flows.pop(provider, None)
        task = self._tasks.pop(provider, None)
        if task is not None:
            task.cancel()


__all__ = ["ConnectionPanel"]

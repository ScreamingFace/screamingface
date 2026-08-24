"""Static HTML and ipywidgets adapters for the connection-panel controller."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any, Protocol, assert_never

from screamingface._ui.connection_state import _ConnectionPanelState
from screamingface._ui.engine_origin import _is_screamingface_engine
from screamingface._ui.provider_icons import provider_icon_html
from screamingface._ui.style import STYLE

if TYPE_CHECKING:
    from screamingface.connections import Connection


class _PanelController(Protocol):
    engine: str

    @property
    def authenticated(self) -> bool: ...

    @property
    def authenticating(self) -> bool: ...

    def close(self) -> None: ...

    def _attempt(self, action: Any) -> None: ...

    def _cancel_flow(self, provider: str) -> None: ...

    def _cancel_mode(self, provider: str) -> None: ...

    def _disconnect(self, provider: str) -> None: ...

    def _logout_access(self) -> None: ...

    def _show_api_key(self, provider: str) -> None: ...

    def _show_methods(self, provider: str) -> None: ...

    def _start_login_access(self) -> None: ...

    def _start_oauth(self, provider: str) -> None: ...

    def _set_notice(self, message: str | None) -> None: ...

    def _submit_api_key(self, provider: str, api_key: str) -> None: ...


_STYLE = (
    STYLE
    + """<style>
.sf-connections{border:0;border-radius:0}
.sf-connection-widget.widget-vbox{border:0!important;box-shadow:none!important}
.sf-connections__head{display:flex;flex-direction:column;padding:4px 14px 14px}
.sf-connections__title{font-size:28px;font-weight:700;line-height:1.15;letter-spacing:-.01em}
.sf-connections__sub{font-size:14px;color:var(--sf-ink-2);margin-top:4px}
.sf-connections__engine{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:12px;color:var(--sf-ink-3);white-space:nowrap;margin-top:12px}
/* the rows live in a sealed box (panel + hairline), the way the system's tables read —
   the header band is one neutral step up so the column labels sit on their own ground */
.sf-conn-tbl{border:1px solid var(--sf-line-2)!important;margin:0 12px 4px!important}
.sf-conn-head{display:flex;align-items:center;gap:12px;padding:9px 14px;
  background:var(--sf-surface);border-bottom:1px solid var(--sf-line-2)}
.sf-conn-head .sf-connections__meta{font:600 11px/1.4 "IBM Plex Mono",ui-monospace,monospace;
  text-transform:uppercase;letter-spacing:.08em;color:var(--sf-ink-2)}
.sf-connections__row{min-height:56px!important;display:flex!important;
  flex-flow:row nowrap!important;align-items:center!important;gap:12px!important;
  padding:8px 14px!important;border:0!important;
  border-bottom:1px solid var(--sf-line)!important}
.sf-connections__row:last-child{border-bottom:0!important}
.sf-connections__meta{display:grid;
  grid-template-columns:minmax(150px,1.5fr) 140px minmax(110px,1.1fr);
  align-items:center;gap:12px;width:100%;min-width:0}
.sf-conn-prov{display:flex;align-items:center;gap:10px;min-width:0}
.sf-tile-icon{flex:0 0 auto;width:24px;height:24px;display:flex;align-items:center;
  justify-content:center;background:var(--sf-surface-2);border:1px solid var(--sf-line-2);
  color:var(--sf-ink-2);font:600 11px/1 "IBM Plex Mono",ui-monospace,monospace}
/* real vendored provider logos (assets/provider_icons/) sit bare — no swatch box,
   they're brand marks already, not a placeholder needing a frame to read as one */
.sf-tile-icon--logo{width:auto;height:auto;background:none;border:0}
.sf-tile-icon--logo svg{display:block;width:1.35em;height:1.35em}
.sf-tile-icon--logo .sf-icon-dark{display:none}
@media(prefers-color-scheme:dark){.sf-tile-icon--logo .sf-icon-light{display:none}
  .sf-tile-icon--logo .sf-icon-dark{display:block}}
.jp-mod-theme-dark .sf-tile-icon--logo .sf-icon-light,
[data-jp-theme-light="false"] .sf-tile-icon--logo .sf-icon-light,
.vscode-dark .sf-tile-icon--logo .sf-icon-light,
.vscode-high-contrast .sf-tile-icon--logo .sf-icon-light{display:none}
.jp-mod-theme-dark .sf-tile-icon--logo .sf-icon-dark,
[data-jp-theme-light="false"] .sf-tile-icon--logo .sf-icon-dark,
.vscode-dark .sf-tile-icon--logo .sf-icon-dark,
.vscode-high-contrast .sf-tile-icon--logo .sf-icon-dark{display:block}
.jp-mod-theme-light .sf-tile-icon--logo .sf-icon-light,
[data-jp-theme-light="true"] .sf-tile-icon--logo .sf-icon-light,
.vscode-light .sf-tile-icon--logo .sf-icon-light{display:block}
.jp-mod-theme-light .sf-tile-icon--logo .sf-icon-dark,
[data-jp-theme-light="true"] .sf-tile-icon--logo .sf-icon-dark,
.vscode-light .sf-tile-icon--logo .sf-icon-dark{display:none}
.sf-connections__provider{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;min-width:0}
.sf-connections__status{display:inline-flex;align-items:center;gap:8px;font-size:14px;
  white-space:nowrap;color:var(--sf-ink)}
.sf-connections__status .sq{flex:0 0 auto;width:11px;height:11px;background:var(--sf-ink-3)}
.sf-connections__status.connected .sq,.sf-connections__status.authenticated .sq{
  background:var(--sf-success-solid)}
.sf-connections__status.login_required .sq,.sf-connections__status.waiting .sq,
.sf-connections__status.needs_reauth .sq,.sf-connections__status.error .sq{
  background:var(--sf-blind)}
/* an inactive row recedes (the whole label dims) while a live one stays full ink — state
   reads from weight+square, never from hue alone, so a colour-blind reader still gets it */
.sf-connections__status.not_connected,.sf-connections__status.unavailable,
.sf-connections__status.login_required{
  color:var(--sf-ink-3)}
.sf-connections__source{font-size:14px;color:var(--sf-ink-3);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.sf-connections__controls{flex:0 0 auto;margin-left:auto;display:flex;align-items:center;
  justify-content:flex-end;gap:4px;height:32px;min-width:104px}
.sf-connections__notice{padding:8px 12px;border-bottom:1px solid var(--sf-line);
  border-left:2px solid var(--sf-blind);color:var(--sf-blind);
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12px;white-space:pre-wrap}
.sf-connection-widget .widget-button,.sf-connection-widget .widget-text input{
  border-radius:0!important;box-shadow:none!important;background-image:none!important}
.sf-connection-widget .widget-button{height:32px!important;width:auto!important;
  padding:0 12px!important;border:1px solid var(--sf-line-2)!important;
  background:transparent!important;color:var(--sf-ink-2)!important;
  font:600 13px/1 "IBM Plex Mono",ui-monospace,monospace!important;white-space:nowrap}
.sf-connection-widget .widget-button:hover{background:var(--sf-surface)!important;
  color:var(--sf-ink)!important;border-color:var(--sf-ink-2)!important}
/* .sf-button--primary is the ONE call-to-action per row (Connect, Save, Log in) — the
   product register's accent (blue), never ink: ink-fill is reserved for the base/ghost
   button, and gold never enters this surface (there is no "win" moment in connections) */
.sf-connection-widget .sf-button--primary{background:var(--sf-accent)!important;
  border-color:var(--sf-accent)!important;color:var(--sf-accent-contrast)!important}
.sf-connection-widget .sf-button--primary:hover{background:var(--sf-accent-hover)!important;
  border-color:var(--sf-accent-hover)!important}
.sf-connection-widget .widget-text{width:180px!important;height:32px!important}
.sf-connection-widget .widget-text input{height:32px!important;padding:0 8px!important;
  border:1px solid var(--sf-line-2)!important;background:var(--sf-bg)!important;
  color:var(--sf-ink)!important;font:13px/1 "IBM Plex Mono",ui-monospace,monospace!important}
.sf-connections__authorize{display:inline-flex;align-items:center;height:32px;padding:0 12px;
  border:1px solid var(--sf-accent);background:var(--sf-accent);text-decoration:none!important;
  color:var(--sf-accent-contrast)!important;font:600 13px/1 "IBM Plex Mono",ui-monospace,monospace}
.sf-connections__authorize:hover{background:var(--sf-accent-hover);border-color:var(--sf-accent-hover)}
.sf-connection-widget .widget-hbox{align-items:center}
@media(max-width:680px){.sf-connections__engine{display:none}
  .sf-connections__source,.sf-conn-head>span:nth-child(3){display:none}
  .sf-connections__meta,.sf-conn-head{grid-template-columns:minmax(120px,1fr) 88px}
  .sf-connections__row{padding:6px 8px!important;gap:8px!important}
  .sf-connection-widget .widget-text{width:140px!important}}
</style>"""
)


def static_panel_html(
    engine: str,
    state: _ConnectionPanelState,
    *,
    authenticated: bool,
    authenticating: bool,
) -> str:
    access = (
        _static_access_row(state, authenticated=authenticated, authenticating=authenticating)
        if state.hosted
        else ""
    )
    rows = "".join(
        _static_row(item, provider_mutations_enabled=state.provider_mutations_enabled)
        for item in state.connections
    )
    table = (
        f"<div class='sf-conn-tbl'>{_column_head_html()}{access}{rows}</div>"
        if (access or rows)
        else ""
    )
    return (
        f"{_STYLE}<div class='sf-ui sf-connections' "
        "aria-label='ScreamingFace connections'>"
        f"{_header_html(engine)}{table}</div>"
    )


class _NotebookConnectionView:
    """ipywidgets adapter; all mutations are delegated to the controller."""

    def __init__(self, controller: _PanelController, state: _ConnectionPanelState) -> None:
        try:
            import ipywidgets as widgets
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Install screamingface[notebook] to use the interactive connection panel."
            ) from exc

        self._widgets = widgets
        self._controller = controller
        self._state = state
        self._notice = widgets.HTML()
        self._rows = widgets.VBox()

        view = self

        class PanelWidget(widgets.VBox):
            def close(self) -> None:
                view._controller.close()
                super().close()

        header = widgets.HTML(value=f"{_STYLE}{_header_html(controller.engine)}")
        self.root = PanelWidget(children=(header, self._notice, self._rows))
        for css_class in ("sf-ui", "sf-connection-widget", "sf-connections"):
            self.root.add_class(css_class)
        self.render()

    def render(self) -> None:
        self.render_notice()
        access = (self._interactive_access_row(),) if self._state.hosted else ()
        providers = tuple(self._interactive_row(item) for item in self._state.connections)
        if access or providers:
            self._rows.children = (self._column_head(), *access, *providers)
            self._rows.add_class("sf-conn-tbl")
        else:
            # no rows yet — drop the frame rather than render an empty bordered box
            self._rows.children = ()
            self._rows.remove_class("sf-conn-tbl")

    def render_notice(self) -> None:
        self._notice.value = _notice_html(self._state.notice)

    def _column_head(self) -> Any:
        return self._widgets.HTML(value=_column_head_html())

    def _interactive_access_row(self):
        widgets = self._widgets
        status = self._state.access_status(
            authenticated=self._controller.authenticated,
            authenticating=self._controller.authenticating,
        )
        meta = widgets.HTML(value=_access_meta_html(status, self._state.engine_url))
        meta.layout.flex = "1 1 auto"
        meta.layout.min_width = "0"
        if status == "checking":
            button = self._button("Checking…", "Checking whether this Engine requires Access")
            button.disabled = True
        elif status == "waiting":
            # AIDEV-NOTE: no Cancel here, deliberately. Login blocks the click handler, so a
            # queued Cancel click cannot run until the wait is already over — a control that
            # looks live and does nothing is worse than none. The notebook stop button is the
            # escape, and it leaves a clean row. Re-adding it means restoring the controller's
            # _cancel_access_login too, and making the wait pump the kernel so a click can
            # actually be delivered mid-login.
            authorization_url = self._state.access_authorization_url
            controls = [self._authorization_link(authorization_url)] if authorization_url else []
            return self._row(meta, controls)
        elif status == "authenticated":
            button = self._button("Log out", "Log out of this Client and Cloudflare Access")
            button.on_click(lambda _: self._controller._attempt(self._controller._logout_access))
        else:
            button = self._button(
                "Log in",
                "Log in to this Engine through Cloudflare Access",
                primary=True,
            )
            button.on_click(lambda _: self._controller._start_login_access())
        return self._row(meta, [button])

    def _authorization_link(self, authorization_url: str) -> Any:
        """The Access authorization URL as a single link.

        WHY a link at all: nothing running in the kernel can open a tab on the user's
        machine — a hosted notebook executes in a datacenter, so `webbrowser.open` would
        open a browser there. An anchor rendered in the user's own browser is the only
        channel that reaches them (OME-930).

        WHY the URL is not also shown as text: it is hundreds of characters of Cloudflare
        token, and it collided with the provider and status columns. It existed as a
        fallback against a blocked popup, and clicking the anchor is confirmed working
        inside Colab's sandboxed output iframe, so the link alone is the affordance.
        """

        href = escape(authorization_url, quote=True)
        return self._widgets.HTML(
            value=(
                "<a class='sf-connections__authorize' "
                f"href='{href}' target='_blank' rel='noopener noreferrer' "
                "title='Complete Cloudflare Access login in a new tab'>Authorize</a>"
            )
        )

    def _interactive_row(self, connection: Connection):
        widgets = self._widgets
        meta = widgets.HTML(
            value=_meta_html(
                connection,
                provider_mutations_enabled=self._state.provider_mutations_enabled,
            )
        )
        meta.layout.flex = "1 1 auto"
        meta.layout.min_width = "0"
        return self._row(meta, self._controls_for(connection))

    def _row(self, meta: Any, controls_: list[Any]):
        widgets = self._widgets
        controls = widgets.HBox(children=tuple(controls_))
        controls.add_class("sf-connections__controls")
        controls.layout.flex = "0 0 auto"
        row = widgets.HBox(children=(meta, controls))
        row.add_class("sf-connections__row")
        row.layout.align_items = "center"
        row.layout.flex_flow = "row nowrap"
        return row

    def _controls_for(self, connection: Connection) -> list[Any]:
        if not self._state.provider_mutations_enabled:
            controls = []
        elif connection.provider in self._state.flows:
            controls = self._oauth_controls(connection)
        elif connection.status == "pending":
            controls = self._pending_controls(connection)
        elif connection.status == "connected":
            controls = self._connected_controls(connection)
        elif self._state.modes.get(connection.provider) == "methods":
            controls = self._method_controls(connection)
        elif self._state.modes.get(connection.provider) == "api_key":
            controls = self._api_key_controls(connection)
        else:
            controls = self._collapsed_controls(connection)
        return controls

    def _collapsed_controls(self, connection: Connection) -> list[Any]:
        button = self._button("Connect", "Choose how to connect this provider", primary=True)
        button.on_click(lambda _: self._controller._show_methods(connection.provider))
        return [button]

    def _method_controls(self, connection: Connection) -> list[Any]:
        controls: list[Any] = []
        if "oauth" in connection.auth_methods:
            oauth = self._button("OAuth", "Start provider OAuth authorization")
            oauth.on_click(
                lambda _: self._controller._attempt(
                    lambda: self._controller._start_oauth(connection.provider)
                )
            )
            controls.append(oauth)
        if "api_key" in connection.auth_methods:
            api_key = self._button("API key", "Enter an API key for this provider")
            api_key.on_click(lambda _: self._controller._show_api_key(connection.provider))
            controls.append(api_key)
        cancel = self._button("Cancel", "Close connection options")
        cancel.on_click(lambda _: self._controller._cancel_mode(connection.provider))
        controls.append(cancel)
        return controls

    def _api_key_controls(self, connection: Connection) -> list[Any]:
        password = self._widgets.Password(placeholder="API key")
        password.layout.width = "180px"
        save = self._button("Save", "Store this API key in the configured Engine", primary=True)

        def submit(_: Any) -> None:
            key = password.value
            try:
                self._controller._attempt(
                    lambda: self._controller._submit_api_key(connection.provider, key)
                )
            finally:
                password.value = ""

        save.on_click(submit)
        cancel = self._button("Cancel", "Close the API key editor")
        cancel.on_click(lambda _: self._controller._cancel_mode(connection.provider))
        return [password, save, cancel]

    def _connected_controls(self, connection: Connection) -> list[Any]:
        button = self._button("Disconnect", "Remove this provider connection")
        button.on_click(
            lambda _: self._controller._attempt(
                lambda: self._controller._disconnect(connection.provider)
            )
        )
        return [button]

    def _pending_controls(self, connection: Connection) -> list[Any]:
        button = self._button("Cancel", "Cancel the pending OAuth authorization")
        button.on_click(
            lambda _: self._controller._attempt(
                lambda: self._controller._disconnect(connection.provider)
            )
        )
        return [button]

    def _oauth_controls(self, connection: Connection) -> list[Any]:
        flow = self._state.flows[connection.provider]
        authorize_url = escape(str(getattr(flow, "authorize_url", "")), quote=True)
        link = self._widgets.HTML(
            value=(
                "<a class='sf-connections__authorize' "
                f"href='{authorize_url}' target='_blank' rel='noopener noreferrer'>Authorize</a>"
            )
        )
        cancel = self._button("Cancel", "Cancel this OAuth authorization attempt")
        cancel.on_click(
            lambda _: self._controller._attempt(
                lambda: self._controller._cancel_flow(connection.provider)
            )
        )
        return [link, cancel]

    def _button(self, description: str, tooltip: str, *, primary: bool = False):
        button = self._widgets.Button(description=description, tooltip=tooltip)
        button.add_class("sf-button")
        if primary:
            button.add_class("sf-button--primary")
        return button


def _header_html(engine: str) -> str:
    return (
        "<div class='sf-connections__head'>"
        "<div class='sf-connections__title'>Connections</div>"
        "<div class='sf-connections__sub'>Live provider status</div>"
        f"<div class='sf-connections__engine'>Engine · {escape(engine)}</div></div>"
    )


def _icon_html(provider: str | None, display_name: str) -> str:
    if provider is not None:
        real = provider_icon_html(provider)
        if real is not None:
            return real
    letter = escape(display_name[:1].upper()) if display_name else "?"
    return f"<span class='sf-tile-icon' aria-hidden='true'>{letter}</span>"


def _source_html(text: str | None) -> str:
    return f"<span class='sf-connections__source'>{escape(text) if text else '—'}</span>"


@dataclass(frozen=True, slots=True)
class _ProviderPresentation:
    status_class: str
    status_label: str
    source: str | None


def _provider_presentation(
    connection: Connection,
    *,
    provider_mutations_enabled: bool,
) -> _ProviderPresentation:
    if provider_mutations_enabled:
        return _ProviderPresentation(
            status_class=connection.status,
            status_label=_status_label(connection.status),
            source=connection.account_label,
        )

    # INVARIANT: hosted callers see only availability they can act on. Profile lifecycle states
    # belong to the operator, so they must not leak into the caller-facing label or styling.
    match connection.status:
        case "connected":
            return _ProviderPresentation(
                status_class="connected",
                status_label="Connected",
                source="Available via ScreamingFace",
            )
        case "not_connected" | "pending" | "needs_reauth" | "error":
            return _ProviderPresentation(
                status_class="unavailable",
                status_label="Unavailable",
                source=None,
            )
    assert_never(connection.status)


def _meta_html(connection: Connection, *, provider_mutations_enabled: bool) -> str:
    presentation = _provider_presentation(
        connection,
        provider_mutations_enabled=provider_mutations_enabled,
    )
    return (
        "<div class='sf-connections__meta'>"
        "<span class='sf-conn-prov'>"
        f"{_icon_html(connection.provider, connection.display_name)}"
        f"<span class='sf-connections__provider'>{escape(connection.display_name)}</span>"
        "</span>"
        f"{_status_html(presentation.status_class, label=presentation.status_label)}"
        f"{_source_html(presentation.source)}</div>"
    )


def _static_row(connection: Connection, *, provider_mutations_enabled: bool) -> str:
    return (
        "<div class='sf-connections__row'>"
        f"{_meta_html(connection, provider_mutations_enabled=provider_mutations_enabled)}</div>"
    )


def _screaming_mark_html() -> str:
    # WHY: the 😱 mark identifies ScreamingFace's own hosted Engine; rendered as the system
    # emoji exactly as shipped (SFDS — never recoloured, boxed, or redrawn). aria-hidden because
    # the adjacent provider label already names the row.
    return "<span class='sf-tile-icon' aria-hidden='true'>😱</span>"


def _access_meta_html(status: str, engine_url: str) -> str:
    # WHY: only ScreamingFace's own hosted Engine gets the brand name + 😱 mark; any other
    # remote Engine is a neutral "Hosted Engine" with the monogram fallback (no brand logo).
    if _is_screamingface_engine(engine_url):
        label = "ScreamingFace Hosted Engine"
        icon = _screaming_mark_html()
    else:
        label = "Hosted Engine"
        icon = _icon_html(None, label)
    return (
        "<div class='sf-connections__meta'>"
        "<span class='sf-conn-prov'>"
        f"{icon}"
        f"<span class='sf-connections__provider'>{label}</span>"
        "</span>"
        f"{_status_html(status)}"
        f"{_source_html(None)}</div>"
    )


def _status_label(status: str) -> str:
    """Capitalise decisive states; transitional and diagnostic states stay quiet."""

    words = status.replace("_", " ")
    return words.capitalize() if status in {"connected", "authenticated", "unavailable"} else words


def _status_html(status: str, *, label: str | None = None) -> str:
    return (
        f"<div class='sf-connections__status {status}'><i class='sq'></i>"
        f"{escape(_status_label(status) if label is None else label)}</div>"
    )


def _column_head_html() -> str:
    return (
        "<div class='sf-conn-head'><div class='sf-connections__meta'>"
        "<span>provider</span><span>status</span><span>source</span></div>"
        "<span class='sf-connections__controls'></span></div>"
    )


def _static_access_row(
    state: _ConnectionPanelState,
    *,
    authenticated: bool,
    authenticating: bool,
) -> str:
    status = state.access_status(
        authenticated=authenticated,
        authenticating=authenticating,
    )
    return f"<div class='sf-connections__row'>{_access_meta_html(status, state.engine_url)}</div>"


def _notice_html(message: str | None) -> str:
    if message is None:
        return ""
    return f"<div class='sf-connections__notice' role='alert'>{escape(message)}</div>"


__all__: list[str] = []

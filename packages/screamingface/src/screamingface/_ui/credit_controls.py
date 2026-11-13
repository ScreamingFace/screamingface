"""Notebook credit controls; preserve unsent input until the connection changes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from screamingface._ui.connection_state import _ConnectionPanelState
from screamingface._ui.credit_view import credit_html

if TYPE_CHECKING:
    from screamingface._ui.connection_view import _PanelController
    from screamingface.credit import CreditStatus


class _NotebookCreditView:
    def __init__(
        self,
        controller: _PanelController,
        state: _ConnectionPanelState,
        widgets: Any,
        button: Callable[..., Any],
    ) -> None:
        self._controller = controller
        self._state = state
        self._widgets = widgets
        self._button = button
        self.root = widgets.VBox()
        self._credit_control_key: tuple[Any, ...] | None = None

    def _clear_credit_controls(self) -> None:
        for child in self.root.children:
            for control in getattr(child, "children", ()):
                if isinstance(control, self._widgets.Password):
                    control.value = ""
                control.close()
            child.close()
        self.root.children = ()
        self._credit_control_key = None

    def _render_credits(self) -> None:
        status = self._state.credit_status
        if status is None:
            self._clear_credit_controls()
            return
        widgets = self._widgets
        control_key = (
            status.connection_token,
            status.management_key_configured,
            self._state.provider_mutations_enabled,
        )
        if self._credit_control_key == control_key and self.root.children:
            self.root.children[0].value = credit_html(status)
            return
        self._clear_credit_controls()
        self._credit_control_key = control_key
        if not self._state.credit_supported and not any(
            item.provider == "openrouter" and item.status == "connected"
            for item in self._state.connections
        ):
            self.root.children = (widgets.HTML(value=credit_html(status)),)
            return
        row = self._controls(status)
        self.root.children = (widgets.HTML(value=credit_html(status)), row)

    def _controls(self, status: CreditStatus) -> Any:
        widgets = self._widgets
        refresh = self._button("Refresh credits", "Read the current provider balance")
        refresh.on_click(lambda _: self._controller._attempt(self._controller.refresh_credits))
        controls: list[Any] = [refresh]
        if (
            status.connection_token is not None
            and self._state.provider_mutations_enabled
            and status.account.reason != "hosted_unavailable"
        ):
            controls.extend(self._management_controls(status))
        row = widgets.HBox(children=tuple(controls))
        row.add_class("sf-credits__controls")
        row.layout.flex_flow = "row wrap"
        return row

    def _management_controls(self, status: CreditStatus) -> list[Any]:
        widgets = self._widgets
        controls: list[Any] = []
        password = widgets.Password(placeholder="Management key (optional)")
        save = self._button("Verify and save", "Verify the account association before saving")

        def submit(_: Any) -> None:
            secret = password.value
            password.value = ""
            self._controller._attempt(lambda: self._controller.set_credit_management_key(secret))

        save.on_click(submit)
        controls.extend([password, save])
        if status.management_key_configured:
            remove = self._button("Remove key", "Remove the saved management key")
            remove.on_click(
                lambda _: self._controller._attempt(self._controller.clear_credit_management_key)
            )
            controls.append(remove)
        fields = tuple(controls)
        for field in fields:
            field.layout.display = "none"
        settings = self._button("Account settings", "Show optional account balance settings")

        def toggle(_: Any) -> None:
            opened = fields[0].layout.display == "none"
            for field in fields:
                field.layout.display = "" if opened else "none"
            settings.description = "Close settings" if opened else "Account settings"
            if not opened:
                password.value = ""

        settings.on_click(toggle)
        controls.append(settings)
        return controls

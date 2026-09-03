"""UI-independent state for the Engine connection panel."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from screamingface.connections import Connection

type PanelMode = Literal["methods", "api_key"]


@dataclass
class _ConnectionPanelState:
    """Mutable presentation state owned by one connection-panel controller."""

    hosted: bool
    engine_url: str
    provider_mutations_enabled: bool
    connections: tuple[Connection, ...] = ()
    notice: str | None = None
    access_pending: bool = False
    access_check_pending: bool = False
    access_check_started: bool = False
    # The pending Cloudflare Access authorization URL, rendered as a link while a
    # login is in flight. Mirrors `flows` for provider OAuth.
    access_authorization_url: str | None = None
    modes: dict[str, PanelMode] = field(default_factory=dict)
    flows: dict[str, object] = field(default_factory=dict)

    def access_status(self, *, authenticated: bool, authenticating: bool) -> str:
        # INVARIANT: "checking" means a probe is in flight. A pending-but-unstarted
        # check has nothing driving it (the static _repr_html_ path never starts one),
        # so it must report the resolved state rather than a status nothing will clear.
        if self.access_check_pending and self.access_check_started:
            status = "checking"
        elif self.access_pending or authenticating:
            status = "waiting"
        elif authenticated:
            status = "authenticated"
        else:
            status = "login_required"
        return status


def _user_message(error: Exception) -> str:
    message = getattr(error, "user_message", None)
    return message if isinstance(message, str) else str(error)


def _sync_access_probe(client: object) -> Callable[[], bool] | None:
    """The client's synchronous Access probe, or None when it has none usable here.

    WHY: ``AsyncClient._access_required`` is ``async def``. Calling it returns a coroutine
    — which is truthy — so a bare ``callable()`` check reports "access required" for every
    Engine and leaves the coroutine un-awaited. ConnectionPanel is a synchronous surface,
    so an async probe is treated as absent rather than mis-read.
    INVARIANT: only a probe that returns a real bool synchronously is ever invoked.
    """

    probe = getattr(client, "_access_required", None)
    if not callable(probe) or inspect.iscoroutinefunction(probe):
        return None
    return cast(Callable[[], bool], probe)


__all__: list[str] = []

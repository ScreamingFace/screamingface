"""Credit reads owned by one connection panel, including refresh lifecycle."""

from __future__ import annotations

import inspect
import time
from typing import Any

from screamingface._ui.connection_state import _ConnectionPanelState
from screamingface.credit import CreditStatus
from screamingface.errors import ScreamingFaceError


class _CreditController:
    _client: Any
    _state: _ConnectionPanelState
    _closed: bool
    _view: Any

    def _init_credits(self) -> None:
        self._credit_busy = False
        self._credit_generation = 0
        self._credit_last_attempt = float("-inf")

    def _invalidate_credits(self) -> None:
        self._credit_generation += 1
        self._credit_last_attempt = float("-inf")
        self._state.credit_status = None

    def _auto_refresh_credits(self) -> None:
        if time.monotonic() - self._credit_last_attempt >= 300:
            self._read_credits(refresh=False)

    def refresh_credits(self) -> None:
        """Refresh the current execution connection's credits without overlapping reads."""
        self._read_credits(refresh=True)

    def _read_credits(self, *, refresh: bool) -> None:
        read = getattr(self._client, "credits", None)
        if (
            self._closed
            or self._credit_busy
            or not callable(read)
            or inspect.iscoroutinefunction(read)
        ):
            return
        if self._state.hosted and not self._client.authenticated:
            self._state.credit_status = None
            return
        self._credit_busy = True
        generation = self._credit_generation
        self._credit_last_attempt = time.monotonic()
        try:
            result = read("openrouter", refresh=refresh)
            # INVARIANT: a connection/auth change during a read cannot restore the old balance.
            if not self._closed and generation == self._credit_generation:
                self._state.credit_status = result if isinstance(result, CreditStatus) else None
                if isinstance(result, CreditStatus) and result.connection_token is not None:
                    self._state.credit_supported = True
        except (ScreamingFaceError, ValueError):
            self._state.credit_status = None
        finally:
            self._credit_busy = False
        if self._view is not None and not self._closed:
            self._view.render()
            # WHY: manual refresh restarts the browser timer as well as the kernel cooldown.
            self._view._credit_bridge.send({"type": "refreshed"})

    def set_credit_management_key(self, api_key: str) -> None:
        """Verify a management key without displaying or retaining the submitted secret."""
        configure = getattr(self._client, "set_credit_management_key", None)
        if self._closed or not callable(configure):
            return
        configure("openrouter", api_key=api_key)
        self._invalidate_credits()
        self.refresh_credits()

    def clear_credit_management_key(self) -> None:
        remove = getattr(self._client, "clear_credit_management_key", None)
        if self._closed or not callable(remove):
            return
        remove("openrouter")
        self._invalidate_credits()
        self.refresh_credits()

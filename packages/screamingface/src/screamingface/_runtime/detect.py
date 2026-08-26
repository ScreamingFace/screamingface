"""Discovery of a running `screamingface up` stack for default-client routing.

Think of it as `screamingface status`'s cheapest question — "is a stack I could point
the SDK at actually alive?" — asked once, lazily, when the default Client is built:

1. Read the supervisor's state record (`runtime.json` in the data dir). Absent or
   unreadable → no local stack, zero network cost.
2. Validate it with the exact schema check the `status` command uses
   (`_state_services`): current schema version + the full service map.
3. Probe the engine's `/healthz` once with a short timeout. A crashed runtime's
   leftover state file must never route `sf.connect()` at a dead port.

Returns the services map only when all three stages pass; every failure mode returns
``None`` so the caller falls back to the hosted default exactly as before.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import urlopen

from screamingface._runtime.config import STATE_FILENAME, default_data_dir

if TYPE_CHECKING:
    from pathlib import Path

# WHY 0.3s: matches the runtime CLI's own health probes — long enough for a live local
# loopback service, short enough that a stale record cannot stall notebook startup.
_PROBE_TIMEOUT_SECONDS = 0.3


def _local_state_path() -> Path:
    return default_data_dir() / STATE_FILENAME


def _engine_alive(url: str) -> bool:
    try:
        with urlopen(f"{url}/healthz", timeout=_PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310
            return response.status == 200
    except (OSError, URLError, ValueError):
        return False


def running_local_services() -> dict[str, str] | None:
    """Return the running local stack's service URLs, or None when there is none.

    Never raises: discovery is a best-effort routing hint, and any defect in local
    state must degrade to the hosted default, not break `sf.connect()`.
    """

    try:
        state = json.loads(_local_state_path().read_text())
    except (OSError, json.JSONDecodeError):
        return None
    from screamingface._runtime.cli import _state_services

    services = _state_services(state if isinstance(state, dict) else None)
    if not services or not _engine_alive(services["engine"]):
        return None
    return services


__all__: list[str] = []

"""Which sink this deployment runs, by name.

The registry exists so the composition root wires an adapter it names rather than one it imports:
`create_app` asks for `settings.ticket_sink` and never mentions `QueueSink`. Adding `LinearSink`
is then one file plus one line here, and no edit to `main.py` at all.

`build_sink` raises at boot on an unknown name, in the same spirit as `main.py`'s two startup
guards: a misconfigured sink that fell back to a default would be a service quietly filing
nothing, or filing into the wrong place, with a healthy `/readyz` the whole time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from ..config import ENV_PREFIX
from .ports import TicketSink
from .queue_sink import QueueSink

SINKS: Mapping[str, Callable[[], TicketSink]] = MappingProxyType({"queue": QueueSink})
"""Name → factory. `queue` is the whole of v1 (spec §6); `linear` joins it once `OME-976` and the
credential-ownership question are both settled."""


def build_sink(name: str) -> TicketSink:
    """The sink `name` selects, or a `ValueError` naming the ones that exist."""
    factory = SINKS.get(name.strip().lower())
    if factory is None:
        raise ValueError(
            f"{ENV_PREFIX}TICKET_SINK={name!r} names no ticket sink, so this service would "
            f"accept reports and file none of them. Valid names: {', '.join(sorted(SINKS))}."
        )
    return factory()


__all__ = ["SINKS", "build_sink"]

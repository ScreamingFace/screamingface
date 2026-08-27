"""Which sink this deployment runs, by name.

The registry exists so the composition root wires an adapter it names rather than one it imports:
`create_app` asks for `settings.ticket_sink` and never mentions `QueueSink` or `LinearSink`.
Adding an adapter is one file plus one line in :data:`SINKS`, and no edit to `main.py` beyond the
one call it already makes.

A factory takes `Settings` rather than nothing, because an adapter that talks to a third party
needs credentials and this is the one module allowed to know which fields those are. It is also
the only place `.get_secret_value()` is spelled for the Linear key — the adapter is handed a
plain string it never has to unwrap, and there is exactly one line to audit for "where does the
credential come from".

**Two refusals happen at BOOT here, not at the first report**, in the same spirit as `main.py`'s
startup guards: an unknown sink name, and a `linear` selection with no credential. Both fail in
the direction that looks like success — a service that accepts reports, answers `202`, files none
of them, and reports itself ready the whole time.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from ..config import ENV_PREFIX, Settings
from .linear_sink import LinearSink
from .ports import TicketSink
from .queue_sink import QueueSink

QUEUE = "queue"
LINEAR = "linear"


def _queue_sink(settings: Settings) -> TicketSink:
    """v1's adapter, and the default. Reads nothing: the `reports` table IS the queue (spec §9),
    which is what keeps a tracker credential out of this service's environment entirely."""
    return QueueSink()


def _linear_sink(settings: Settings) -> TicketSink:
    """The direct adapter — or a boot failure naming exactly what an operator has to supply.

    CLAUDE.md rule 9 governs this selection (see `linear_sink.py`'s docstring); this function is
    what makes the selection cost a credential rather than being free. Both values are checked
    because either one missing produces the same outcome: every report answered `202`, no ticket
    anywhere, `/readyz` green. A pod that refuses to start is a page; a pod that files nothing is
    discovered weeks later by somebody asking where their bug report went.
    """
    api_key = settings.linear_api_key.get_secret_value().strip()
    team_id = settings.linear_team_id.strip()
    missing = [
        name
        for name, value in (
            (f"{ENV_PREFIX}LINEAR_API_KEY", api_key),
            (f"{ENV_PREFIX}LINEAR_TEAM_ID", team_id),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            f"{ENV_PREFIX}TICKET_SINK={LINEAR} files tickets into Linear directly, which needs "
            f"{' and '.join(missing)} — not set. Without them this service would accept every "
            f"report, answer 202, file none of them, and report itself ready the whole time. "
            f"Supply them from a Secret, or leave {ENV_PREFIX}TICKET_SINK={QUEUE}."
        )
    return LinearSink(
        api_key=api_key,
        team_id=team_id,
        api_url=settings.linear_api_url,
        timeout_s=settings.linear_timeout_s,
    )


SINKS: Mapping[str, Callable[[Settings], TicketSink]] = MappingProxyType(
    {QUEUE: _queue_sink, LINEAR: _linear_sink}
)
"""Name → factory. `queue` is v1's default and spec §9's decision; `linear` exists for the
deployment whose operator has both amended rule 9 (`OME-976`) and answered where the credential
lives and who rotates it. Nothing here selects either one — `Settings.ticket_sink` does."""


@runtime_checkable
class ClosingSink(Protocol):
    async def aclose(self) -> None:
        """Release whatever this adapter opened — for `LinearSink`, an HTTP connection pool."""
        ...


def sink_name(settings: Settings) -> str:
    """The configured name, normalized once so no two readers normalize it differently.

    Case-insensitive and trimmed: the value arrives from a ConfigMap, where a trailing space
    survives YAML quoting and nobody sees it. Refusing to boot over one would be pedantry, not
    safety.
    """
    return settings.ticket_sink.strip().lower()


def build_sink(settings: Settings) -> TicketSink:
    """The sink `settings.ticket_sink` selects, or a `ValueError` naming the ones that exist."""
    factory = SINKS.get(sink_name(settings))
    if factory is None:
        raise ValueError(
            f"{ENV_PREFIX}TICKET_SINK={settings.ticket_sink!r} names no ticket sink, so this "
            f"service would accept reports and file none of them. Valid names: "
            f"{', '.join(sorted(SINKS))}."
        )
    return factory(settings)


async def close_sink(sink: TicketSink) -> None:
    """Close a sink that has something to close, at shutdown.

    Structural, never an `isinstance` against an adapter class: the composition root calls this
    and must go on not knowing which adapters exist. A sink with no `aclose` — `QueueSink`, and
    every stub a test puts on the seam — is left alone rather than being an error.
    """
    if isinstance(sink, ClosingSink):
        await sink.aclose()


__all__ = ["LINEAR", "QUEUE", "SINKS", "ClosingSink", "build_sink", "close_sink", "sink_name"]

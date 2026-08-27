"""`QueueSink`, the registry that names it, and the composition root that asks for it by name."""

from __future__ import annotations

import pytest

from report_intake.config import Settings
from report_intake.delivery.ports import Queued, TicketContent, TicketSink
from report_intake.delivery.queue_sink import QueueSink
from report_intake.delivery.registry import SINKS, build_sink
from report_intake.main import create_app


def _content() -> TicketContent:
    return TicketContent(ref="r_8f21c0", title="[r_8f21c0] ExecutionError: x", body="## Report")


@pytest.mark.asyncio
async def test_the_queue_sink_answers_queued_with_no_ticket_id() -> None:
    """Spec §6: v1 marks the record ready and lets an agent file it via MCP during triage. No
    ticket id comes back, which spec §2.2's success shape already models."""
    assert await QueueSink().deliver(_content()) == Queued()


def test_the_queue_sink_satisfies_the_port() -> None:
    """The registry hands `create_app` a `TicketSink`, and this is what makes that claim true of
    the concrete class rather than only of the annotation."""
    assert isinstance(QueueSink(), TicketSink)


def test_the_registry_resolves_the_configured_default() -> None:
    """The anti-drift check for the one number `config.py` cannot import: `ticket_sink` defaults
    to a plain string, and this asserts that string still names a sink."""
    assert isinstance(build_sink(Settings().ticket_sink), QueueSink)


def test_the_sink_name_is_matched_case_insensitively_and_untrimmed() -> None:
    """It arrives from a ConfigMap, where a trailing space survives YAML quoting and nobody sees
    it. Refusing to boot over one would be pedantry, not safety."""
    assert isinstance(build_sink("  Queue "), QueueSink)


def test_an_unknown_sink_name_is_refused_naming_the_ones_that_exist() -> None:
    """A misconfigured sink that fell back to a default would be a service quietly filing nothing,
    with a healthy `/readyz` the whole time."""
    with pytest.raises(ValueError, match="names no ticket sink") as raised:
        build_sink("linear")

    assert "queue" in str(raised.value)


def test_the_service_refuses_to_start_with_a_sink_nobody_implements(
    hermetic_environment: None, database_url: str
) -> None:
    """Boot, not the first report. The two startup guards in `main.py` exist for the same reason:
    a configuration mistake that looks like a working pod is the expensive kind."""
    with pytest.raises(ValueError, match="names no ticket sink"):
        create_app(Settings(database_url=database_url, ticket_sink="linear"))


def test_create_app_wires_the_named_sink_rather_than_importing_one(
    hermetic_environment: None, database_url: str
) -> None:
    """Hexagonal wiring, CLAUDE.md's architecture rule: the composition root asks the registry for
    `settings.ticket_sink` and does not know `QueueSink` exists. Adding `LinearSink` is one file
    plus one registry line, with no edit here."""
    app = create_app(Settings(database_url=database_url))

    assert isinstance(app.state.ticket_sink, QueueSink)


def test_every_registered_name_builds_a_sink() -> None:
    """The registry is a mapping of names to factories, and a name whose factory does not satisfy
    the port is a boot failure on the day someone selects it rather than today."""
    for name in SINKS:
        assert isinstance(build_sink(name), TicketSink)

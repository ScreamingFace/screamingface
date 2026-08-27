"""`QueueSink`, the registry that names it, and the composition root that asks for it by name."""

from __future__ import annotations

import pytest

from report_intake.config import Settings
from report_intake.delivery.linear_sink import LinearSink
from report_intake.delivery.ports import Queued, TicketContent, TicketSink
from report_intake.delivery.queue_sink import QueueSink
from report_intake.delivery.registry import LINEAR, QUEUE, SINKS, build_sink, close_sink
from report_intake.main import create_app

_LINEAR_CREDENTIALS = {"linear_api_key": "lin_api_notreal", "linear_team_id": "team-uuid"}
"""What an operator has to supply before the `linear` sink will start. Not a real key: these
tests never reach a workspace, and the adapter's own suite drives it over a stubbed transport."""


def _content() -> TicketContent:
    return TicketContent(ref="r_8f21c0", title="[r_8f21c0] ExecutionError: x", body="## Report")


def _settings(**values: object) -> Settings:
    return Settings.model_validate(values)


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
    assert isinstance(build_sink(Settings()), QueueSink)


def test_the_sink_name_is_matched_case_insensitively_and_untrimmed() -> None:
    """It arrives from a ConfigMap, where a trailing space survives YAML quoting and nobody sees
    it. Refusing to boot over one would be pedantry, not safety."""
    assert isinstance(build_sink(_settings(ticket_sink="  Queue ")), QueueSink)


def test_an_unknown_sink_name_is_refused_naming_the_ones_that_exist() -> None:
    """A misconfigured sink that fell back to a default would be a service quietly filing nothing,
    with a healthy `/readyz` the whole time."""
    with pytest.raises(ValueError, match="names no ticket sink") as raised:
        build_sink(_settings(ticket_sink="jira"))

    assert "queue" in str(raised.value)
    assert "linear" in str(raised.value)


def test_the_service_refuses_to_start_with_a_sink_nobody_implements(
    hermetic_environment: None, database_url: str
) -> None:
    """Boot, not the first report. The startup guards in `main.py` exist for the same reason:
    a configuration mistake that looks like a working pod is the expensive kind."""
    with pytest.raises(ValueError, match="names no ticket sink"):
        create_app(_settings(database_url=database_url, ticket_sink="jira"))


def test_create_app_wires_the_named_sink_rather_than_importing_one(
    hermetic_environment: None, database_url: str
) -> None:
    """Hexagonal wiring, CLAUDE.md's architecture rule: the composition root asks the registry for
    `settings.ticket_sink` and does not know `QueueSink` exists. Adding an adapter is one file
    plus one registry line, with no edit here."""
    app = create_app(_settings(database_url=database_url))

    assert isinstance(app.state.ticket_sink, QueueSink)


@pytest.mark.parametrize("name", sorted(SINKS))
def test_every_registered_name_builds_a_sink(name: str) -> None:
    """The registry is a mapping of names to factories, and a name whose factory does not satisfy
    the port is a boot failure on the day someone selects it rather than today.

    Each name is built from settings that CONFIGURE it, because a sink talking to a third party
    legitimately refuses to be built without a credential — that refusal has its own cases below.
    """
    settings = _settings(ticket_sink=name, **(_LINEAR_CREDENTIALS if name == LINEAR else {}))

    assert isinstance(build_sink(settings), TicketSink)


# --- selecting `linear` ------------------------------------------------------------------------
#
# CLAUDE.md rule 9 governs the SELECTION, and `OME-976` has not amended it — so the cases below
# are about what happens when an operator makes that selection, not about this repo making it.
# The default is unchanged and every deployment still runs `queue`.


def test_the_linear_sink_is_not_what_this_service_files_through_by_default() -> None:
    """The whole shape of spec §9's decision, asserted rather than asserted about: shipping the
    adapter changes nothing for a deployment that does not name it."""
    assert Settings().ticket_sink == QUEUE
    assert not isinstance(build_sink(Settings()), LinearSink)


def test_selecting_linear_with_credentials_builds_the_linear_sink() -> None:
    assert isinstance(build_sink(_settings(ticket_sink=LINEAR, **_LINEAR_CREDENTIALS)), LinearSink)


def test_selecting_linear_without_an_api_key_refuses_to_start_and_names_it() -> None:
    """A service that accepts reports and files none of them behind a healthy `/readyz` is the
    failure this refusal exists to prevent. The message is the fix, so it names the variable."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_LINEAR_API_KEY") as raised:
        build_sink(_settings(ticket_sink=LINEAR, linear_team_id="team-uuid"))

    assert "REPORT_INTAKE_LINEAR_TEAM_ID" not in str(raised.value)


def test_selecting_linear_without_a_team_id_refuses_to_start_and_names_it() -> None:
    """Both halves are required for the same reason: an issue create with no team is refused by
    Linear on every report, which is a queue quietly growing rather than a pod that fails."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_LINEAR_TEAM_ID"):
        build_sink(_settings(ticket_sink=LINEAR, linear_api_key="lin_api_notreal"))


def test_selecting_linear_with_neither_names_both() -> None:
    with pytest.raises(ValueError) as raised:
        build_sink(_settings(ticket_sink=LINEAR))

    assert "REPORT_INTAKE_LINEAR_API_KEY" in str(raised.value)
    assert "REPORT_INTAKE_LINEAR_TEAM_ID" in str(raised.value)


def test_a_credential_of_pure_whitespace_is_no_credential() -> None:
    """A ConfigMap or a Secret rendered from an empty template yields `" "`, not `""`, and a
    truthiness check alone would boot a pod that authenticates with a space."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_LINEAR_API_KEY"):
        build_sink(_settings(ticket_sink=LINEAR, linear_api_key="  ", linear_team_id="team-uuid"))


def test_the_refusal_to_start_never_echoes_the_key_it_did_receive() -> None:
    """The one credential-shaped value in this service's environment besides the Turnstile secret
    and the database URL. A boot failure is a log line in a cluster, and this one must not carry
    a long-lived token to the private tracker into it."""
    with pytest.raises(ValueError) as raised:
        build_sink(_settings(ticket_sink=LINEAR, linear_api_key="lin_api_notreal"))

    assert "lin_api_notreal" not in str(raised.value)


def test_the_service_refuses_to_start_on_a_linear_selection_with_no_credential(
    hermetic_environment: None, database_url: str
) -> None:
    """At BOOT, in `create_app`, and not at the first report — which is the whole point: the
    reporter would already have been told `202`."""
    with pytest.raises(ValueError, match="REPORT_INTAKE_LINEAR_API_KEY"):
        create_app(_settings(database_url=database_url, ticket_sink=LINEAR))


def test_the_service_starts_with_a_configured_linear_sink_on_the_seam(
    hermetic_environment: None, database_url: str
) -> None:
    """The other direction. An operator who has answered rule 9 and supplied a credential gets
    the adapter wired onto exactly the seam `QueueSink` sits on — no second delivery path."""
    app = create_app(
        _settings(database_url=database_url, ticket_sink=LINEAR, **_LINEAR_CREDENTIALS)
    )

    assert isinstance(app.state.ticket_sink, LinearSink)


@pytest.mark.asyncio
async def test_closing_a_sink_that_has_nothing_to_close_is_not_an_error() -> None:
    """`close_sink` is structural so the composition root can stay ignorant of which adapters
    exist. `QueueSink` has no pool, and every stub a test puts on the seam has none either."""
    await close_sink(QueueSink())

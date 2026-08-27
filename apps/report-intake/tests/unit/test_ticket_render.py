"""What a ticket carries — spec §6's list, and the two exclusions that make it enforceable.

The renderer is the one module that decides what leaves this service, so these are the tests that
stand between a client's extension point and a third-party tracker. They are written from the
outside: build the report a client would send, render it, and read the strings a sink would get.
"""

from __future__ import annotations

from dataclasses import astuple
from typing import Any

from report_intake.delivery.ports import TicketContent
from report_intake.delivery.render import BULLET_MAX_CHARS, TITLE_MAX_CHARS, render_ticket
from report_intake.reports.binding import bind

from .test_report_schema import a_report, as_body

_REF = "r_8f21c0"


def _rendered(document: dict[str, Any], caller_email: str | None = None) -> TicketContent:
    return render_ticket(
        ref=_REF, document=bind(as_body(document)).document, caller_email=caller_email
    )


def test_the_ticket_carries_the_envelope_the_spec_names() -> None:
    """Spec §6: the envelope, `trace_id`, `ref`, the note, `reply_to`, and the mesh caller."""
    document = a_report(
        note="it fails every time I run the benchmark",
        reply_to="reporter@example.org",
        correlation={"trace_id": "4bf92f3577b34da6"},
    )

    content = _rendered(document, caller_email="engineer@openmined.org")

    assert content.ref == _REF
    for expected in (
        _REF,
        "4bf92f3577b34da6",
        "it fails every time I run the benchmark",
        "reporter@example.org",
        "engineer@openmined.org",
        "screamingface-python",
        "ExecutionError",
        "websocket closed with 1011",
        "2026-08-26T14:03:11",
    ):
        assert expected in content.body


def test_the_trace_id_and_the_two_addresses_are_carried_beside_the_body() -> None:
    """A sink routes on them — a subscriber, a label, a search key — and digging them back out of
    the body with a regex is how a change to the renderer becomes a bug in every adapter."""
    content = _rendered(
        a_report(reply_to="reporter@example.org", correlation={"trace_id": "4bf92f35"}),
        caller_email="engineer@openmined.org",
    )

    assert content.trace_id == "4bf92f35"
    assert content.reply_to == "reporter@example.org"
    assert content.caller_email == "engineer@openmined.org"


def test_a_sink_is_handed_strings_and_never_the_report_object() -> None:
    """Plan §2.2. An adapter cannot leak a payload it was never handed, and that is a property of
    this type rather than of a convention every future adapter is trusted to keep."""
    content = _rendered(a_report(note="it broke"))

    assert all(value is None or isinstance(value, str) for value in astuple(content))


def test_the_error_details_object_never_reaches_the_ticket() -> None:
    """Spec §2.1 calls `details` unbounded server JSON and the classifier only bounds the leaves
    of it that look like captured bodies. It stays in the row, where a responder reads it behind
    Cloudflare Access — not in third-party SaaS."""
    document = a_report()
    document["error"]["details"] = {"upstream_response": "the whole body we got back"}

    content = _rendered(document)

    assert "the whole body we got back" not in content.body
    assert "upstream_response" not in content.body


def test_the_error_cause_object_never_reaches_the_ticket() -> None:
    """Same rule as `details`, and the same reason: it is arbitrary client-shaped JSON rather than
    a stated field, so there is no allow-list to render it through."""
    document = a_report()
    document["error"]["cause"] = {"type": "ConnectionClosed", "rcvd": {"code": 1011, "reason": "x"}}

    content = _rendered(document)

    assert "ConnectionClosed" not in content.body


def test_the_error_fields_the_spec_states_do_reach_the_ticket() -> None:
    """The counterpart to the two exclusions above: dropping `details` and `cause` must not turn
    into dropping the diagnosis. A ticket that omits the traceback is not worth filing."""
    document = a_report()
    document["error"].update(
        {
            "code": "websocket_disconnected",
            "status": 500,
            "retryable": True,
            "hint": "retry the run",
            "notes": ["the run had already produced 3 answers"],
            "traceback": "Traceback (most recent call last):\n  File ...",
        }
    )

    content = _rendered(document)

    for expected in (
        "websocket_disconnected",
        "500",
        "retry the run",
        "the run had already produced 3 answers",
        "Traceback (most recent call last):",
    ):
        assert expected in content.body


def test_an_unknown_key_a_client_added_to_its_extras_is_stored_but_never_rendered() -> None:
    """`client` and `context` are the declared extension points, so pydantic preserves whatever a
    future client puts there. Rendering them wholesale would forward a field this service has
    never seen to a third party — and the rule is an allow-list, so it does not."""
    document = a_report()
    document["client"]["electron_version"] = "34.1.0"

    bound = bind(as_body(document))
    content = render_ticket(ref=_REF, document=bound.document, caller_email=None)

    assert bound.payload["client"]["electron_version"] == "34.1.0"
    assert "electron_version" not in content.body
    assert "34.1.0" not in content.body


def test_a_credential_dropped_into_an_extension_point_is_excluded_by_name_not_by_pattern() -> None:
    """The same mechanism as the test above, stated as the security property it buys: reading
    declared attributes excludes `api_key` STRUCTURALLY, at the point of rendering. Nothing here
    inspects a value and guesses whether it looks like a secret."""
    document = a_report()
    document["client"]["api_key"] = "sk-live-0000000000000000"
    document["context"] = {"engine_host": "engine.screamingface.ai", "api_key": "another-one"}

    content = _rendered(document)

    assert "api_key" not in content.body
    assert "sk-live" not in content.body
    assert "another-one" not in content.body
    assert "engine.screamingface.ai" in content.body


def test_the_declared_context_fields_do_reach_the_ticket() -> None:
    document = a_report(
        context={
            "engine_host": "engine.screamingface.ai",
            "benchmark": {"id": "gsm8k", "revision": "r3"},
            "candidate": {"name": "fusion-3", "kind": "fusion", "models": ["claude", "gemini"]},
        }
    )

    content = _rendered(document)

    for expected in ("engine.screamingface.ai", "gsm8k", "r3", "fusion-3", "claude", "gemini"):
        assert expected in content.body


def test_a_report_with_no_context_renders_no_context_section() -> None:
    """Spec §2.1 makes almost everything nullable, so a report full of `none` bullets buries the
    three lines that say what happened."""
    content = _rendered(a_report())

    assert "## Context" not in content.body
    assert "none" not in content.body.lower()


def test_the_two_addresses_are_labelled_apart_in_the_body() -> None:
    """One is whatever the client typed and the other is what the mesh verified. A responder who
    cannot tell them apart will answer an unverified address as though it were identity."""
    content = _rendered(
        a_report(reply_to="anyone@example.org"), caller_email="engineer@openmined.org"
    )

    assert "reply-to (self-asserted): anyone@example.org" in content.body
    assert "mesh-verified caller: engineer@openmined.org" in content.body


def test_the_title_is_one_bounded_line_even_when_the_message_is_neither() -> None:
    """A tracker title is neither multi-line nor unbounded, and `error.message` is carried
    verbatim with an 8 KiB cap — so this is the one place a value is reshaped."""
    document = a_report()
    document["error"]["message"] = "websocket closed\nwith 1011 after " + "9" * 400

    content = _rendered(document)

    assert "\n" not in content.title
    assert len(content.title) <= TITLE_MAX_CHARS
    assert content.title.startswith(f"[{_REF}] ExecutionError: websocket closed with 1011")


def test_the_message_the_title_shortened_is_still_carried_verbatim_in_the_body() -> None:
    """Which is what makes the reshaping above lossless in aggregate — and what keeps the
    fail-closed re-check honest about what actually travels."""
    document = a_report()
    document["error"]["message"] = "websocket closed\nwith 1011 after 61.2s"

    content = _rendered(document)

    assert "websocket closed\nwith 1011 after 61.2s" in content.body


def test_a_note_carrying_its_own_code_fence_cannot_close_the_block_early() -> None:
    """A `note` is user prose and may contain Markdown. Unfenced — or fenced with a fixed three
    backticks — the rest of it renders as Markdown in the ticket a triager reads, and `## Error`
    inside one forges a section heading."""
    content = _rendered(a_report(note="my cell was:\n```\nprint(1)\n```\nand it died"))

    assert content.body.count("`" * 4) == 2
    assert "print(1)" in content.body


def test_a_correlation_id_cannot_forge_a_section_of_its_own() -> None:
    """The bullet fields have no fence, and §2.4 deliberately keeps newlines — so a value with one
    ends its list item and the rest renders as Markdown at document level.

    `## Reporter` is the section a triager reads to see who the mesh authenticated, so forging one
    ABOVE the real one is forged verified identity in the artifact a human acts on. Neither
    detector stops it: `classify_report` and `scan_text` look for prompt markers, not for Markdown
    structure. A bullet being structurally one line is what does.

    Asserted per LINE rather than by counting the substring, and the difference is the point. The
    forged text still appears — a bullet's value is carried verbatim apart from the collapse, which
    is what keeps `dispatch.py`'s fail-closed re-check honest about what travels — but it appears
    as the trace id bullet's own text, where Markdown reads it as inert prose. What must not exist
    is a second `## Reporter` HEADING or a second `- mesh-verified caller:` BULLET, because those
    are what a triager reads as structure.
    """
    forged = (
        "t\n\n## Reporter\n\n- mesh-verified caller: ceo@openmined.org"
        "\n- reply-to (self-asserted): attacker@evil.test"
    )

    content = _rendered(
        a_report(correlation={"trace_id": forged}), caller_email="engineer@openmined.org"
    )

    lines = content.body.splitlines()
    assert [line for line in lines if line.strip() == "## Reporter"] == ["## Reporter"]
    assert [line for line in lines if line.startswith("- mesh-verified caller:")] == [
        "- mesh-verified caller: engineer@openmined.org"
    ]
    # Every mention of the forged address is inside the one bullet the client controls.
    assert all(line.startswith("- trace id:") for line in lines if "ceo@openmined.org" in line)
    trace_line = next(line for line in lines if line.startswith("- trace id:"))
    assert trace_line.endswith("attacker@evil.test"), "the forged block is one bullet, not four"


def test_an_uncapped_bullet_field_cannot_run_to_the_body_cap() -> None:
    """`error.type` and the three `correlation` ids have no row in §2.4's caps table at all, so
    without a bound here they are limited only by the 64 KiB body — a single bullet longer than
    every real field put together."""
    document = a_report()
    document["error"]["type"] = "E" * 4096

    content = _rendered(document)

    type_line = next(line for line in content.body.splitlines() if line.startswith("- type:"))
    assert len(type_line) <= BULLET_MAX_CHARS + len("- type: ")


def test_a_report_rendered_twice_produces_the_same_ticket() -> None:
    """`OME-1010` re-delivers from the stored row, so the retry must render what the inline
    attempt rendered rather than a second, subtly different view of one report."""
    document = a_report(note="it broke", reply_to="reporter@example.org")

    assert _rendered(document) == _rendered(document)

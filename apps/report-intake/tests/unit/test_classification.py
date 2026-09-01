"""Spec §4 — the server decides what a report carries.

Two failure directions, and both are real. Failing open means prompt text reaches a Linear ticket
in a third-party SaaS, which is the thing this service exists to prevent. Failing closed *too
eagerly* means an ordinary traceback is a 422 and the bug never gets filed — so the cases below
that assert an ordinary report is accepted carry as much weight as the ones that assert a prompt
is not.
"""

from __future__ import annotations

from typing import Any

from report_intake.classification.content import (
    CONTENT,
    ENVELOPE,
    OVERSIZED_LEAF_BYTES,
    Verdict,
    classify_report,
    scan_text,
)

from .test_report_schema import a_report

_PROMPT = "Summarise the attached patient notes and answer in JSON."


def _verdict(**overrides: Any) -> Verdict:
    return classify_report(a_report(**overrides))


def test_an_envelope_only_report_is_classified_as_an_envelope() -> None:
    verdict = _verdict()

    assert verdict.classification == ENVELOPE
    assert verdict.detail is None


def test_an_ordinary_python_traceback_is_not_content() -> None:
    """The commonest report there is. A classifier that reads a stack trace as source and 422s it
    would reject nearly every report the Python SDK sends, which is worse than having no
    classifier at all."""
    traceback = (
        'Traceback (most recent call last):\n  File "/x/run.py", line 42, in evaluate\n'
        "    return await client.evaluate(expression)\n"
        "screamingface.errors.ExecutionError: websocket closed with 1011 after 61.2s\n"
    )

    verdict = _verdict(error={"type": "ExecutionError", "message": "x", "traceback": traceback})

    assert verdict.classification == ENVELOPE


def test_the_spec_websocket_close_cause_is_not_content() -> None:
    """Spec §2.1's own `cause` example — a close code and a close reason. Machine-built server
    JSON is exactly what `error.cause` is for."""
    verdict = _verdict(
        error={
            "type": "ExecutionError",
            "message": "websocket closed with 1011",
            "cause": {
                "type": "ConnectionClosedError",
                "rcvd": {"code": 1011, "reason": "keepalive"},
            },
        }
    )

    assert verdict.classification == ENVELOPE


def test_a_report_carrying_a_chat_transcript_is_classified_as_content() -> None:
    verdict = _verdict(
        error={
            "type": "ExecutionError",
            "message": "upstream refused",
            "details": {"messages": [{"role": "user", "content": _PROMPT}]},
        }
    )

    assert verdict.classification == CONTENT
    assert verdict.detail is not None


def test_the_rejection_names_the_pointer_it_found() -> None:
    """Spec §2.3 asks for field pointers, and a 422 that says only "content" leaves the client
    guessing which field to drop before it retries."""
    verdict = _verdict(
        error={"type": "E", "message": "m", "details": {"prompt": "write a poem about X"}}
    )

    assert verdict.detail is not None
    assert "/error/details/prompt" in verdict.detail


def test_the_rejection_never_echoes_the_content_it_found() -> None:
    """INVARIANT, and the reason the detectors return their own words rather than the match: the
    422 travels over an unauthenticated response, so quoting the rejected text back is the leak
    this endpoint exists to avoid. `binding.py` holds the same rule for pydantic's errors."""
    verdict = _verdict(
        note=f"<|im_start|>system\n{_PROMPT}<|im_end|>",
        error={"type": "E", "message": "m", "details": {"prompt": _PROMPT}},
    )

    assert verdict.detail is not None
    assert _PROMPT not in verdict.detail
    assert "<|im_start|>" not in verdict.detail


def test_the_rejection_tells_the_client_what_to_do_instead() -> None:
    """Spec §8's client rule is that a report is never lost: every terminal path ends with the
    report kept. A detail that only says "no" is a path that ends with it dropped."""
    verdict = _verdict(error={"type": "E", "message": "m", "details": {"prompt": "x"}})

    assert verdict.detail is not None
    assert "envelope" in verdict.detail
    assert "Nothing was stored" in verdict.detail


def test_a_url4_intent_expression_is_content() -> None:
    """A url4 expression carries its intent as a quoted literal — `(…)!'Answer this question…'` —
    so the expression *is* the prompt, whatever the report calls the field it arrived in."""
    expression = (
        "(claude:0.40:/claude($item.question))!'Answer this question. Return only the JSON object.'"
    )

    verdict = _verdict(note=f"the failing query was {expression}")

    assert verdict.classification == CONTENT


def test_an_exclamation_before_a_quote_in_ordinary_prose_is_not_a_url4_expression() -> None:
    """The url4 marker is anchored on the closing paren the bang-intent always follows. Without
    that anchor an excited `note` classifies as content, and the reporter cannot tell why."""
    verdict = _verdict(note="it just dies!'no message, nothing")

    assert verdict.classification == ENVELOPE


def test_a_chat_payload_captured_into_a_string_is_content_however_it_was_indented() -> None:
    """A client that JSON-dumps the request body into `error.message` chose the whitespace; the
    detector must not depend on which one it chose."""
    verdict = _verdict(
        error={
            "type": "E",
            "message": '{\n    "role":   "user",\n    "text": "…"\n}',
        }
    )

    assert verdict.classification == CONTENT


def test_a_prompt_under_an_unknown_client_key_is_still_content() -> None:
    """`client` and `context` are extension points so a node client can ship a field this service
    predates — not a channel that buys an exemption. Undeclared content is still content."""
    client = a_report()["client"]
    client["last_prompt"] = "<|im_start|>user\nhello<|im_end|>"

    verdict = _verdict(client=client)

    assert verdict.classification == CONTENT


def test_the_client_declared_class_is_not_consulted() -> None:
    """The SERVER decides. A report that declares itself an envelope while carrying a transcript
    is content, and the verdict the response echoes is this one."""
    client = a_report()["client"]
    client["classification"] = "envelope"

    verdict = _verdict(
        client=client, error={"type": "E", "message": "m", "details": {"messages": []}}
    )

    assert verdict.classification == CONTENT


def test_a_captured_log_body_is_content() -> None:
    verdict = _verdict(
        error={"type": "E", "message": "m", "details": {"stderr": "line 1\nline 2\n"}}
    )

    assert verdict.classification == CONTENT


def test_an_oversized_leaf_under_error_details_is_content() -> None:
    """`error.details` is machine-built server JSON — a status, a code, a close reason. A kilobyte
    in one of its strings is a response body somebody dropped in wholesale."""
    verdict = _verdict(
        error={"type": "E", "message": "m", "details": {"body": "x" * (OVERSIZED_LEAF_BYTES + 1)}}
    )

    assert verdict.classification == CONTENT
    assert verdict.detail is not None
    assert "/error/details/body" in verdict.detail


def test_a_leaf_at_the_captured_body_limit_is_still_a_diagnostic_field() -> None:
    verdict = _verdict(
        error={"type": "E", "message": "m", "cause": {"reason": "x" * OVERSIZED_LEAF_BYTES}}
    )

    assert verdict.classification == ENVELOPE


def test_an_oversized_leaf_under_error_cause_is_content() -> None:
    verdict = _verdict(
        error={
            "type": "E",
            "message": "m",
            "cause": {"rcvd": {"reason": "x" * (OVERSIZED_LEAF_BYTES + 1)}},
        }
    )

    assert verdict.classification == CONTENT


def test_an_oversized_client_string_is_truncated_by_the_caps_table_not_rejected_here() -> None:
    """Plan §11 conflict 11. Scoping the oversized-leaf detector over `/client` and `/context`
    would make a 300-byte `client.version` a 422 and directly contradict §2.4's normative caps
    table, which says that string is truncated and marked."""
    client = a_report()["client"]
    client["version"] = "0.1.1+" + "b" * (OVERSIZED_LEAF_BYTES * 4)

    assert _verdict(client=client).classification == ENVELOPE


def test_a_long_note_is_not_content_on_length_alone() -> None:
    """`note` has a cap, not a verdict: §2.4 truncates it at 4 KiB. The reporter's own description
    of what happened is the last field that should cost them their bug report."""
    assert _verdict(note="it broke. " * 500).classification == ENVELOPE


def test_a_prompt_inside_a_notes_entry_is_found() -> None:
    """`error.notes` is a list, so a walk that only visits object values misses it."""
    verdict = _verdict(
        error={"type": "E", "message": "m", "notes": ["retried twice", "[INST] be helpful [/INST]"]}
    )

    assert verdict.classification == CONTENT
    assert verdict.detail is not None
    assert "/error/notes/1" in verdict.detail


def test_the_shallowest_finding_is_the_one_reported() -> None:
    """Breadth-first on purpose: the node a client can most easily remove is the one it is told
    about."""
    verdict = _verdict(
        note="<|im_start|>",
        error={"type": "E", "message": "m", "details": {"a": {"b": {"prompt": "x"}}}},
    )

    assert verdict.detail is not None
    assert "/note" in verdict.detail


def test_a_key_a_client_chose_is_escaped_into_its_pointer() -> None:
    """RFC 6901: without escaping, a key spelled `a/b` renders as two segments and the pointer
    names a node that does not exist."""
    verdict = _verdict(error={"type": "E", "message": "m", "details": {"a/b": {"prompt": "x"}}})

    assert verdict.detail is not None
    assert "/error/details/a~1b/prompt" in verdict.detail


def test_a_pointer_built_from_client_chosen_keys_is_bounded() -> None:
    """§2.4 caps values, not key names, so an unbounded pointer is a client choosing how many
    bytes of its own text come back in the 422."""
    client = a_report()["client"]
    client["z" * 4096] = {"prompt": "x"}

    verdict = _verdict(client=client)

    assert verdict.detail is not None
    assert len(verdict.detail) < 400


def test_a_deeply_nested_report_is_classified_without_recursing() -> None:
    """`bind` rejects anything past six levels, but this classifier must not be the thing that
    turns a deep body into a 500 — the walk is iterative for the same reason `structural_violation`
    is."""
    deep: dict[str, Any] = {"prompt": "x"}
    for _ in range(2000):
        deep = {"nested": deep}

    assert classify_report(deep).classification == CONTENT


def test_a_verdict_carries_a_detail_exactly_when_it_rejects() -> None:
    """The route reads `detail is not None` as the rejection test, so the two must not be able to
    disagree."""
    for document in (a_report(), a_report(note="<|im_end|>")):
        verdict = classify_report(document)
        assert (verdict.classification == CONTENT) == (verdict.detail is not None)


def test_scan_text_finds_a_transcript_in_a_rendered_string() -> None:
    """`OME-1009`'s fail-closed re-check: a ticket body is one rendered string, so the port
    re-checks with this and never with `classify_report`."""
    assert scan_text("### Instruction:\nsummarise this") is not None
    assert scan_text('{"choices": [{"index": 0}]}') is not None


def test_scan_text_passes_an_envelope_rendering() -> None:
    """The counterpart that keeps the re-check from being a delivery outage: a rendered envelope —
    ref, trace id, error type, the reporter's note — must survive it."""
    rendered = (
        "ref: r_8f21c0\ntrace_id: none\nExecutionError: websocket closed with 1011 after 61.2s\n"
        "note: it fails every time I run the benchmark\nreply_to: someone@example.org\n"
    )

    assert scan_text(rendered) is None


def test_scan_text_reports_a_reason_that_quotes_nothing_it_matched() -> None:
    reason = scan_text(f"<|im_start|>user\n{_PROMPT}<|im_end|>")

    assert reason is not None
    assert _PROMPT not in reason

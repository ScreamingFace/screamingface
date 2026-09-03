"""Spec §2.1's shape, and the binding step that produces it.

Two rules carry most of these cases: unknown keys are forbidden at the top level and preserved
inside `client` and `context`, and the `schema` major is a 400 rather than a 422 because a client
cannot fix a major mismatch by correcting a field.
"""

from __future__ import annotations

from typing import Any

import pytest

from report_intake.core.problem import ProblemException
from report_intake.reports.binding import bind
from report_intake.reports.caps import CLIENT_CONTEXT_STRING_BYTES, MAX_DEPTH, NOTE_BYTES
from report_intake.reports.schema import SUPPORTED_SCHEMA


def a_report(**overrides: Any) -> dict[str, Any]:
    """The smallest report spec §2.1 accepts, plus whatever the case under test needs."""
    document: dict[str, Any] = {
        "schema": SUPPORTED_SCHEMA,
        "occurred_at": "2026-08-26T14:03:11.204Z",
        "client": {
            "name": "screamingface-python",
            "version": "0.1.1.post5",
            "host": "notebook",
            "platform": "darwin",
            "runtime": {"name": "cpython", "version": "3.13.1"},
        },
        "error": {"type": "ExecutionError", "message": "websocket closed with 1011"},
    }
    document.update(overrides)
    return document


def as_body(document: Any) -> bytes:
    import json

    return json.dumps(document).encode("utf-8")


def _refusal(document: Any) -> ProblemException:
    with pytest.raises(ProblemException) as raised:
        bind(as_body(document))
    return raised.value


def test_a_minimal_report_binds() -> None:
    bound = bind(as_body(a_report()))

    assert bound.document.client.runtime.name == "cpython"
    assert bound.document.error.message == "websocket closed with 1011"
    assert bound.truncations == ()


def test_correlation_defaults_to_all_nulls_rather_than_being_required() -> None:
    """A report without a trace id is weaker, not invalid — `OME-967` is a degradation, not a
    blocker on filing a bug."""
    bound = bind(as_body(a_report()))

    assert (bound.document.correlation.trace_id, bound.document.correlation.run_id) == (None, None)


def test_an_unknown_key_at_the_top_level_is_refused() -> None:
    """The top level is a small stable set, so an unknown key there is a typo worth a 422."""
    problem = _refusal(a_report(surprise="hello"))

    assert problem.problem.status == 422
    assert "/surprise" in (problem.problem.detail or "")


def test_an_unknown_key_inside_client_survives_verbatim() -> None:
    """Clients in four languages will not ship in lockstep: a `node` client adding
    `electron_version` must not be rejected by a service that predates it."""
    document = a_report()
    document["client"]["electron_version"] = "34.1.0"

    bound = bind(as_body(document))

    assert bound.payload["client"]["electron_version"] == "34.1.0"


def test_an_unknown_key_inside_context_survives_verbatim() -> None:
    bound = bind(as_body(a_report(context={"cluster": "eu-west-1"})))

    assert bound.payload["context"]["cluster"] == "eu-west-1"


def test_an_unrecognised_host_value_is_stored_rather_than_rejected() -> None:
    """The vocabularies are documented, not enforced: a client shipping before the service learns
    its name must still be able to report a bug."""
    document = a_report()
    document["client"]["host"] = "kubernetes-operator"

    assert bind(as_body(document)).document.client.host == "kubernetes-operator"


def test_a_report_from_a_future_schema_major_is_refused_as_a_bad_request() -> None:
    """400, not 422: no correction to a field makes this build accept it, so a 422 would invite a
    retry loop over a body that can never be accepted."""
    problem = _refusal(a_report(schema="screamingface.error-report/v2"))

    assert problem.problem.status == 400
    assert "v2" in (problem.problem.detail or "")


def test_a_schema_from_another_family_is_a_schema_violation_not_a_version_problem() -> None:
    """A malformed report, not a future one — so it lands where every other field violation
    lands."""
    assert _refusal(a_report(schema="something.else/v1")).problem.status == 422


def test_a_missing_schema_is_a_schema_violation() -> None:
    document = a_report()
    del document["schema"]

    assert _refusal(document).problem.status == 422


def test_a_body_that_is_not_json_is_a_bad_request() -> None:
    with pytest.raises(ProblemException) as raised:
        bind(b"{not json")

    assert raised.value.problem.status == 400


def test_a_body_that_is_not_utf_8_is_a_bad_request_rather_than_a_crash() -> None:
    """`UnicodeDecodeError` is a `ValueError`, which is easy to leave uncaught and turn into a
    500 on input a client fully controls."""
    with pytest.raises(ProblemException) as raised:
        bind(b'{"schema": "\xff\xfe"}')

    assert raised.value.problem.status == 400


def test_a_json_array_at_the_top_level_is_a_schema_violation() -> None:
    assert _refusal([1, 2, 3]).problem.status == 422


def test_a_body_nested_deeper_than_json_itself_will_parse_is_refused_not_crashed() -> None:
    """Within the 64 KiB body cap a client can still nest deeply enough that json's own scanner
    raises `RecursionError` before this service measures anything. The verdict has to be the 422
    the depth cap would have given, not an unhandled 500."""
    body = b"[" * 20_000 + b"]" * 20_000

    with pytest.raises(ProblemException) as raised:
        bind(body)

    assert raised.value.problem.status == 422
    assert str(MAX_DEPTH) in (raised.value.problem.detail or "")


def test_a_report_past_the_depth_cap_is_refused_by_the_structural_check() -> None:
    """The ordinary depth case, well short of what makes json's own scanner give up: `context` is
    an extension point, so a client can nest inside it without a body anywhere near the cap."""
    document = a_report(context={"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}})

    problem = _refusal(document)

    assert problem.problem.status == 422
    assert str(MAX_DEPTH) in (problem.problem.detail or "")


def test_a_report_with_too_many_keys_on_one_node_is_refused() -> None:
    """`error.details` is unbounded server JSON, which is exactly where an unbounded map turns
    up."""
    document = a_report()
    document["error"]["details"] = {str(index): index for index in range(65)}

    assert _refusal(document).problem.status == 422


def test_a_violation_detail_carries_field_pointers() -> None:
    document = a_report()
    del document["error"]["message"]

    detail = _refusal(document).problem.detail or ""

    assert "/error/message" in detail


def test_a_violation_detail_never_echoes_the_offending_value() -> None:
    """A 422 that quotes free text back over an unauthenticated response is exactly the leak this
    endpoint exists to avoid, so the error object is read by name and never serialized whole."""
    secret = "a-prompt-nobody-should-see"
    document = a_report()
    document["client"]["runtime"] = secret

    assert secret not in (_refusal(document).problem.detail or "")


def test_many_violations_are_summarised_rather_than_listed_in_full() -> None:
    """An unbounded detail is an amplification: a small body with hundreds of bad keys would
    return a large problem document."""
    detail = _refusal({f"unknown_{index}": index for index in range(40)}).problem.detail or ""

    assert "and " in detail and " more" in detail


def test_control_characters_are_gone_from_the_bound_report() -> None:
    bound = bind(as_body(a_report(note="clean\x00me")))

    assert bound.document.note == "cleanme"


def test_the_payload_is_truncated_and_the_scanned_mapping_is_not() -> None:
    """The `OME-1007` seam: a classifier reading only `payload` cannot see content that
    truncation removed, which would make truncation a way to smuggle it past the check."""
    tail = "MARKER-AT-THE-END"
    bound = bind(as_body(a_report(note="n" * NOTE_BYTES + tail)))

    assert tail not in bound.payload["note"]
    assert bound.scanned["note"].endswith(tail)


def test_the_document_and_the_payload_agree_after_truncation() -> None:
    """`payload` is what gets persisted and `document` is the typed view of it, so validation runs
    after truncation rather than before — "validated" has to mean the mapping that is stored."""
    document = a_report()
    document["client"]["version"] = "v" * 900

    bound = bind(as_body(document))

    assert bound.document.client.version == bound.payload["client"]["version"]
    assert len(bound.document.client.version.encode("utf-8")) <= CLIENT_CONTEXT_STRING_BYTES

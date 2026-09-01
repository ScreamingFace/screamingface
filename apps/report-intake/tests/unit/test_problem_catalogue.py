"""The catalogue is the contract an SDK codes against.

Spec §2.3's table is what a client switches on, so the set of statuses this service can produce
has to be enumerable — which is the whole reason the constructors live in one module instead of
being written inline at each route.
"""

from __future__ import annotations

import pytest

from report_intake.core.problem_catalogue import (
    PROBLEM_CATALOGUE,
    body_too_large,
    bot_gate_required,
    bot_gate_unverifiable,
    content_rejected,
    loopback_only,
    malformed_body,
    rate_limited,
    schema_violation,
    storage_unavailable,
    unsupported_schema,
)

_EVERY_CONSTRUCTOR = (
    malformed_body("x"),
    unsupported_schema("screamingface.error-report/v2", "screamingface.error-report/v1"),
    body_too_large(65536, 91000),
    schema_violation("x"),
    content_rejected("x"),
    bot_gate_required("x"),
    bot_gate_unverifiable(),
    loopback_only("x"),
    rate_limited(30),
    storage_unavailable(),
)


def test_the_catalogue_holds_exactly_the_statuses_the_spec_documents() -> None:
    """Spec §2.3's table as amended by plan §12, in full. An undocumented status is what turns
    "my retry stopped working" into a support question, so the set is asserted rather than left
    to grow by accident."""
    assert set(PROBLEM_CATALOGUE) == {400, 403, 413, 422, 429, 503}


def test_every_constructor_produces_a_catalogued_status() -> None:
    assert {problem.problem.status for problem in _EVERY_CONSTRUCTOR} <= set(PROBLEM_CATALOGUE)


def test_every_constructor_carries_the_catalogue_title_for_its_status() -> None:
    """A title that drifts from the catalogue makes the mapping a lie for exactly one status,
    which is the one nobody re-reads."""
    for problem in _EVERY_CONSTRUCTOR:
        assert problem.problem.title == PROBLEM_CATALOGUE[problem.problem.status]


def test_every_constructor_says_something_specific() -> None:
    """RFC 9457's `detail` is the member a human reads; a constructor that leaves it empty makes
    the status code the whole message."""
    for problem in _EVERY_CONSTRUCTOR:
        assert problem.problem.detail


def test_a_body_too_large_names_the_cap() -> None:
    """Spec §2.3 requires it by name: without the limit the client cannot know how much to cut."""
    detail = body_too_large(65536, 91000).problem.detail or ""

    assert "65536" in detail and "64 KiB" in detail and "91000" in detail


def test_a_body_too_large_still_names_the_cap_when_the_size_is_unknown() -> None:
    """A chunked body is cut off before its total is known, and inventing a number there would be
    worse than omitting it."""
    detail = body_too_large(65536).problem.detail or ""

    assert "65536" in detail
    assert "None" not in detail


def test_a_rate_limited_problem_carries_retry_after() -> None:
    """A 429 with no backoff hint is answered by an immediate retry, which is the behaviour the
    limit exists to stop."""
    assert rate_limited(30).headers == {"Retry-After": "30"}


def test_the_unsupported_schema_detail_names_both_versions() -> None:
    detail = unsupported_schema("a/v2", "a/v1").problem.detail or ""

    assert "a/v2" in detail and "a/v1" in detail


def test_a_missing_or_rejected_bot_token_is_403_and_an_unevaluable_gate_is_503() -> None:
    """The split is the reason `403` exists at all (plan §2.6). A client fetches a fresh token on
    `403` and retries the same request unchanged on `503`; collapsing them into one status would
    make one of those two behaviours wrong."""
    assert bot_gate_required("x").problem.status == 403
    assert bot_gate_unverifiable().problem.status == 503


def test_an_unevaluable_bot_gate_tells_the_client_to_retry_the_same_request() -> None:
    """Retrying a fresh token would be pointless: the token was never what failed."""
    detail = bot_gate_unverifiable().problem.detail or ""

    assert "keep the report" in detail
    assert "retry the same request" in detail


def test_the_loopback_refusal_names_the_setting_that_causes_it() -> None:
    """The only caller who ever sees it is an operator who deployed the local-only posture, and
    the fix is a setting rather than anything about their request."""
    assert loopback_only("auth_mode=disabled serves loopback only").problem.status == 403


def test_the_storage_problem_tells_the_client_to_keep_the_report() -> None:
    """503 is the one status that means *nothing was stored*, so the client must fall back to
    disk rather than assume delivery (spec §8)."""
    assert "keep the report" in (storage_unavailable().problem.detail or "")


def test_the_catalogue_cannot_be_edited_at_runtime() -> None:
    """A mapping that a module can mutate is not a contract."""
    with pytest.raises(TypeError):
        PROBLEM_CATALOGUE[418] = "I'm a teapot"  # type: ignore[index]

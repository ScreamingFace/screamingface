"""E5 P1 spec D6 and §4.1: the owner key and the Run's own vocabulary.

FEATURE: first-class Runs (OME-1785).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, tzinfo
from typing import cast, get_args

import pytest

from screamingface_engine.runs.model import (
    CandidateState,
    RunQuery,
    RunSpec,
    RunState,
    is_terminal_candidate,
    is_terminal_run,
    owner_key,
)


def test_the_owner_key_is_the_sha256_of_the_normalised_email() -> None:
    expected = hashlib.sha256(b"alice@openmined.org").hexdigest()

    assert owner_key("alice@openmined.org") == expected
    assert owner_key("  Alice@OpenMined.org\n") == expected


def test_local_mode_has_its_own_owner_key() -> None:
    assert owner_key("local") == hashlib.sha256(b"local").hexdigest()


@pytest.mark.parametrize("owner", ["", "   "])
def test_a_blank_owner_is_refused(owner: str) -> None:
    with pytest.raises(ValueError, match="owner"):
        owner_key(owner)


def test_a_run_spec_names_at_least_one_candidate() -> None:
    with pytest.raises(ValueError, match="at least one Candidate"):
        RunSpec(client_key="k", benchmark="b", case_count=1, candidates=(), client_version="1")


def test_candidate_names_are_unique_within_a_run() -> None:
    with pytest.raises(ValueError, match="unique"):
        RunSpec(
            client_key="k", benchmark="b", case_count=1, candidates=("a", "a"), client_version="1"
        )


@pytest.mark.parametrize("field", ["client_key", "benchmark"])
def test_a_run_spec_refuses_blank_identifiers(field: str) -> None:
    values = {"client_key": "k", "benchmark": "b"} | {field: " "}
    with pytest.raises(ValueError, match=field):
        RunSpec(case_count=1, candidates=("a",), client_version="1", **values)


def test_a_run_spec_refuses_a_negative_case_count() -> None:
    with pytest.raises(ValueError, match="case_count"):
        RunSpec(client_key="k", benchmark="b", case_count=-1, candidates=("a",), client_version="1")


def test_the_terminal_candidate_states_are_the_specs() -> None:
    terminal = {state for state in get_args(CandidateState) if is_terminal_candidate(state)}

    assert terminal == {"succeeded", "failed", "timed_out", "stopped", "lost"}


def test_every_run_state_but_running_is_terminal() -> None:
    assert {state for state in get_args(RunState) if not is_terminal_run(state)} == {"running"}


@pytest.mark.parametrize("candidates", [("a", ""), ("a", "  ")])
def test_a_candidate_name_must_not_be_blank(candidates: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="Candidate name"):
        RunSpec(
            client_key="k", benchmark="b", case_count=1, candidates=candidates, client_version="1"
        )


def test_names_differing_only_by_surrounding_space_are_duplicates() -> None:
    with pytest.raises(ValueError, match="unique"):
        RunSpec(
            client_key="k", benchmark="b", case_count=1, candidates=("a", "a "), client_version="1"
        )


def test_a_run_spec_refuses_a_blank_client_version() -> None:
    with pytest.raises(ValueError, match="client_version"):
        RunSpec(client_key="k", benchmark="b", case_count=1, candidates=("a",), client_version=" ")


@pytest.mark.parametrize("limit", [0, -1, 201])
def test_a_run_query_limit_is_bounded(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        RunQuery(limit=limit)


@pytest.mark.parametrize("limit", [1, 50, 200])
def test_a_run_query_accepts_a_limit_in_range(limit: int) -> None:
    assert RunQuery(limit=limit).limit == limit


def test_a_run_query_refuses_a_naive_since() -> None:
    with pytest.raises(ValueError, match="since"):
        RunQuery(since=datetime(2026, 10, 1))  # noqa: DTZ001 - the naive value under test


def test_a_run_query_accepts_an_aware_since() -> None:
    since = datetime(2026, 10, 1, tzinfo=UTC)
    assert RunQuery(since=since).since == since


@pytest.mark.parametrize("cursor", ["xyz", "run_", "run_" + "0" * 31, "run_" + "G" * 32, "0" * 32])
def test_a_run_query_refuses_a_malformed_cursor(cursor: str) -> None:
    with pytest.raises(ValueError, match="cursor"):
        RunQuery(cursor=cursor)


def test_a_run_query_accepts_a_run_id_cursor() -> None:
    assert RunQuery(cursor="run_" + "a" * 32).cursor == "run_" + "a" * 32


def test_a_run_spec_stores_names_and_benchmark_stripped() -> None:
    spec = RunSpec(
        client_key="k",
        benchmark=" mmlu ",
        case_count=1,
        candidates=cast(tuple[str, ...], [" gpt ", "claude"]),  # a list, as JSON decodes it
        client_version="1",
    )

    assert spec.benchmark == "mmlu"
    assert spec.candidates == ("gpt", "claude")


def test_is_terminal_run_refuses_an_unknown_state() -> None:
    with pytest.raises(ValueError, match="unknown Run state"):
        is_terminal_run(cast(RunState, "Running"))


def test_a_run_spec_stores_its_identifiers_stripped() -> None:
    spec = RunSpec(
        client_key=" abc ", benchmark="b", case_count=1, candidates=("a",), client_version=" 1.2 "
    )

    assert (spec.client_key, spec.client_version) == ("abc", "1.2")


def test_a_run_query_refuses_an_unknown_state() -> None:
    with pytest.raises(ValueError, match="state"):
        RunQuery(state=cast(RunState, "done"))


def test_a_run_query_accepts_every_run_state() -> None:
    assert {RunQuery(state=state).state for state in get_args(RunState)} == set(get_args(RunState))


def test_is_terminal_candidate_refuses_an_unknown_state() -> None:
    with pytest.raises(ValueError, match="unknown Candidate state"):
        is_terminal_candidate(cast(CandidateState, "SUCCEEDED"))


class _NoOffset(tzinfo):
    """A tzinfo that is set but gives no offset: still a naive datetime."""

    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None

    def tzname(self, dt: datetime | None) -> None:
        return None


@pytest.mark.parametrize(
    "since", [datetime(2026, 10, 1, tzinfo=_NoOffset()), "2026-10-01", 1_700_000_000]
)
def test_a_run_query_needs_an_aware_datetime_since(since: object) -> None:
    with pytest.raises(ValueError, match="since"):
        RunQuery(since=cast(datetime, since))


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("Jürgen@x.org", "Jürgen@x.org"),  # NFC and NFD forms of the same email
        ("straße@x.org", "STRASSE@x.org"),  # casefold, not lower
    ],
)
def test_one_email_in_different_unicode_forms_is_one_owner(one: str, other: str) -> None:
    assert owner_key(one) == owner_key(other)

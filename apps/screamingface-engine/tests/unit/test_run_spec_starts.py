"""E5 P2 spec D1, D8, D9b, D11: the domain rules of a Run that carries its Candidates' starts.

FEATURE: a detached Run (OME-1837). Request types are the route's to check (E4); these are the
rules a `RunSpec` keeps whoever builds it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from run_registry_support import start, start_spec

from screamingface_engine.runs.records import ContextRef, RunSpec


def _spec(**changes: Any) -> RunSpec:
    # WHY `replace`: it builds a new RunSpec, so `__post_init__` checks the changed one.
    return replace(start_spec("alpha"), **changes)


def test_a_run_of_starts_names_its_candidates_by_their_starts() -> None:
    spec = start_spec("alpha", "beta")

    assert spec.candidates == ("alpha", "beta")
    assert [s.name for s in spec.starts] == ["alpha", "beta"]


def test_starts_that_do_not_match_the_candidates_are_refused() -> None:
    with pytest.raises(ValueError, match="starts"):
        _spec(candidates=("alpha", "beta"))
    with pytest.raises(ValueError, match="starts"):
        _spec(starts=(start("beta"),))


def test_detach_needs_starts() -> None:
    with pytest.raises(ValueError, match="detach"):
        _spec(starts=(), detach=True)


def test_a_deadline_needs_detach() -> None:
    with pytest.raises(ValueError, match="deadline"):
        _spec(deadline=timedelta(hours=1))


@pytest.mark.parametrize("deadline", [timedelta(0), timedelta(seconds=-1)])
def test_a_deadline_must_be_positive(deadline: timedelta) -> None:
    with pytest.raises(ValueError, match="deadline"):
        _spec(detach=True, deadline=deadline)


@pytest.mark.parametrize("url4", ["", "   ", "a\x00b"])
def test_a_start_needs_a_url4_expression(url4: str) -> None:
    with pytest.raises(ValueError, match="url4"):
        start("alpha", url4=url4)


@pytest.mark.parametrize("email", ["", "  ", "a" * 321, "a\x00@b"])
def test_an_owner_email_is_a_short_line_of_text(email: str) -> None:
    with pytest.raises(ValueError, match="owner_email"):
        _spec(owner_email=email)


@pytest.mark.parametrize(
    ("sha256", "size"), [("ab" * 31, 1), ("AB" * 32, 1), ("zz" * 32, 1), ("ab" * 32, -1)]
)
def test_a_context_reference_is_a_lowercase_sha256_and_a_size(sha256: str, size: int) -> None:
    with pytest.raises(ValueError):
        ContextRef(sha256=sha256, size_bytes=size)


def test_a_run_id_given_by_the_route_must_be_a_run_id() -> None:
    with pytest.raises(ValueError, match="run_id"):
        _spec(run_id="not-a-run-id")
    assert _spec(run_id="run_" + "a" * 32).run_id == "run_" + "a" * 32

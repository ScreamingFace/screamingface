"""The jobs port contract — what ``JobRunnerAtCapacity`` means and who raises it.

STORY: OME-1064 recorded a 23-minute silent stall caused by five disagreeing
capacity ceilings. The docstring used to carve out cluster-backed runners ("a
cluster-backed runner lets the scheduler absorb the load and never raises") —
that sentence is false and load-bearing: it was cited as the reason the
503 + ``Retry-After`` backpressure path was disabled for the one runner that
needed it. The contract is the general rule: ANY substrate with a finite
declared ceiling raises it, and the caller maps it to a retry-after response.
"""

from __future__ import annotations

import inspect

import url4.streaming.interfaces.jobs as jobs_module
from url4.streaming.interfaces.jobs import JobRunnerAtCapacity


def test_capacity_docstring_has_no_cluster_backed_carve_out() -> None:
    """The docstring must not exempt any substrate class from raising."""
    doc = JobRunnerAtCapacity.__doc__ or ""
    assert "cluster-backed" not in doc
    assert "never raises" not in doc


def test_capacity_docstring_states_the_general_rule() -> None:
    """The docstring must state the general rule: finite ceiling -> raise, caller retries."""
    doc = JobRunnerAtCapacity.__doc__ or ""
    assert "finite" in doc
    assert "ceiling" in doc
    assert "retry" in doc


def test_capacity_docstring_covers_every_substrate_shape() -> None:
    """The enumeration must be complete enough that no substrate class reads as exempt.

    A substrate SHAPE (shared loop, queue depth, scheduler quota) cannot go stale when an
    adapter is added, renamed, or retired — an adapter CLASS in this list can (the docstring
    once looked exhaustive while omitting the one cluster adapter that existed)."""
    doc = JobRunnerAtCapacity.__doc__ or ""
    assert "event loop" in doc
    assert "queue depth" in doc
    assert "quota" in doc
    # The contract must not enumerate adapter classes by name — shapes only.
    assert "K8s" not in doc


def test_capacity_docstring_states_the_rule_once() -> None:
    """The retry-after mapping is stated once, not pasted into every paragraph.

    A duplicated closing clause reads as if a second, different rule followed; it is the
    same one, and the copy drifts the moment either sentence is edited alone."""
    doc = JobRunnerAtCapacity.__doc__ or ""
    assert doc.count("retry-after response rather than a conflict") == 1


def test_job_status_docstring_records_scheduled_as_queued() -> None:
    """``scheduled`` already means accepted-not-started; no ``queued`` member is needed."""
    # JobStatus is a Literal alias, so its docstring is a module-level string
    # statement after the alias, not an attribute — read it from the source.
    source = inspect.getsource(jobs_module)
    assert "scheduled" in source
    assert "not yet started" in source
    assert "queued" in source


def test_job_status_docstring_scopes_scheduled_to_observable_substrates() -> None:
    """``scheduled`` is what a substrate that CAN observe the acceptance gap reports.

    A substrate that starts a run the moment it accepts it (the in-process runner) reports
    ``running`` from acceptance on — ``scheduled`` is not false there, it is unobservable.
    The docstring must say so, or a caller waits for a frame such an adapter can never emit."""
    source = inspect.getsource(jobs_module)
    assert "adapter-specific" in source
    assert "reports ``running`` from" in source
    assert "nor wait for a" in source

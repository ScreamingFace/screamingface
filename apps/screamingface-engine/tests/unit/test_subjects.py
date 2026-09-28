"""Subject and stream naming.

This file is what survives `test_subjects_contract.py`, which existed because `subjects.py` was
duplicated across two distributions that could not import each other — every test there compared
the two copies, and the merge left nothing to compare. The invariant below is different in kind:
it constrains the shared events stream against the per-run subject it must capture.
"""

from screamingface_engine import subjects
from screamingface_engine.adapters.jetstream import EventsStreamConfig

TOPIC = "run-01JABCDEF"


def test_the_events_stream_captures_every_run_subject() -> None:
    # One stream holds every run: its subject filter must match `subject_for(topic)`, or a run's
    # frames would be published to a subject no stream stores ("no response from stream").
    (pattern,) = EventsStreamConfig().subjects
    assert pattern == f"{subjects.PREFIX}.*"
    assert subjects.subject_for(TOPIC).startswith(pattern.removesuffix("*"))
    assert "." not in TOPIC  # a topic is one subject token, so `*` matches it


def test_neither_the_events_stream_nor_the_queue_is_a_legacy_stream() -> None:
    # `admin purge-legacy-streams` deletes whatever `owns_stream` accepts.
    assert not subjects.owns_stream(subjects.EVENTS_STREAM)
    assert not subjects.owns_stream(subjects.RUN_QUEUE_STREAM)
    assert subjects.owns_stream(f"{subjects.PREFIX}_{TOPIC}")

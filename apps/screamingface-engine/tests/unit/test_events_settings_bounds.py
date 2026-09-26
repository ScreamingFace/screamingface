"""The shared events stream's settings have the same floor every other sized/counted field in
this file declares (`run_queue_replicas`, `local_io_capacity`, ...): a stream has at least one
byte of budget, one message per subject, a positive age, and at least one replica. Refusing at
startup beats a broker error surfacing later as a less legible `EventsStreamConfigError`.

This file pins the boundary for `events_max_bytes` (representative; `events_max_msgs_per_subject`
and `events_replicas` share the same `ge=1` idiom, and `events_max_age_s` the same `gt=0` one).
"""

import pytest
from pydantic import ValidationError

from screamingface_engine.config import Settings


def test_events_max_bytes_defaults_to_eight_gib() -> None:
    assert Settings().events_max_bytes == 8 * 1024**3


def test_a_zero_events_max_bytes_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(events_max_bytes=0)


def test_the_environment_can_still_set_a_valid_events_max_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("URL4_CLOUD_EVENTS_MAX_BYTES", "123")
    assert Settings().events_max_bytes == 123

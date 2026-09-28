"""The fairness knobs are bounded at the boundary, not at the division (OME-1091).

`run_queue_bucket_count` reaches `RunQueue.bucket_subject` as the modulus of
`int(digest, 16) % bucket_count`, so a zero raises `ZeroDivisionError` inside `schedule()`
— a 500 on EVERY run, from a value that looked like ordinary configuration when it was
set. Its two siblings are the same shape: a zero (or negative) depth ceiling refuses every
run, and a zero per-caller in-flight cap admits none. Each is a settings-time refusal in
this file: the process must fail at startup, where the operator is still watching, rather
than at the first request.

Self-contained fixtures rather than imports from a sibling test module: the append-only
rule means each cycle brings its own, so a later edit here cannot break a prior file.
"""

import pytest
from pydantic import ValidationError

from screamingface_engine import runner_queue
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import RunQueue

# The three fairness/admission knobs that are all >= 1 by construction, with the attribute
# name each one carries on `Settings`. Parametrized rather than repeated: the boundary is
# one rule, and a knob added to this family without its bound should be a one-line addition
# here that fails until the bound exists.
BOUNDED_AT_ONE = [
    "run_queue_bucket_count",
    "run_queue_depth_ceiling",
    "run_queue_caller_inflight_cap",
]


@pytest.mark.parametrize("field", BOUNDED_AT_ONE)
@pytest.mark.parametrize("bad", [0, -1])
def test_a_non_positive_value_is_refused_at_startup(field: str, bad: int) -> None:
    """INVARIANT: refused where it is READ, not where it is used. `bucket_count=0` is the
    sharpest case — it divides — but all three describe counts of things, and a
    configuration error must surface while the operator is still watching the rollout."""
    # `model_validate` rather than `Settings(**{...})`: a dynamic kwarg name is unresolvable
    # to the type checker, which then checks the value against EVERY field.
    with pytest.raises(ValidationError):
        Settings.model_validate({field: bad})


@pytest.mark.parametrize("field", BOUNDED_AT_ONE)
def test_one_is_accepted_as_the_floor(field: str) -> None:
    """The bound is a floor, not a minimum-of-two: a single bucket is a legitimate
    (fairness-free) deployment, and so is admitting one run per caller at a time."""
    assert getattr(Settings.model_validate({field: 1}), field) == 1


def test_the_defaults_satisfy_their_own_bound() -> None:
    """A default below its own bound would make the shipped configuration unloadable —
    the failure mode a bound is least expected to introduce."""
    settings = Settings()
    for field in BOUNDED_AT_ONE:
        assert getattr(settings, field) >= 1


def test_a_zero_bucket_count_is_what_the_bound_prevents() -> None:
    """The concrete failure the bound exists for, pinned so the reason cannot be
    refactored away: with no bound, `bucket_subject` divides by the count on the
    scheduling hot path, so every single run 500s."""
    queue = RunQueue("nats://unused:4222", bucket_count=0)

    with pytest.raises(ZeroDivisionError):
        queue.bucket_subject({"X-User-Email": "a@example.com"})


def test_the_default_bucket_count_is_the_modules_own() -> None:
    """The setting must not fork its default from the queue's — the worker builds its
    `RunQueue` from `Settings`, so two defaults that drift would split the App's publish
    buckets from the buckets the worker polls."""
    assert Settings().run_queue_bucket_count == runner_queue.DEFAULT_BUCKET_COUNT

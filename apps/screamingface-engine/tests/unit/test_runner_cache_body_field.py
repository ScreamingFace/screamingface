"""`policy_to_body_field` — url4's cache INTENT translated into aigateway's wire vocabulary
(plan Batch 2, spec §4.1 resolution table / §5.1 / §9.2c).

THE INVARIANT THIS MODULE EXISTS TO PROTECT (spec §1.0). aigateway v2's cache-control grammar is
**CLOSED to exactly one field**, `use-cache`. Any other key inside the request body's `cache`
object makes the WHOLE request bypass the cache — silently, with no error raised anywhere, and
even alongside an otherwise valid `use-cache: true`. So an extra key here is not a style defect:
it costs every cache hit forever and nothing reports it. `test_no_input_ever_produces_a_key_other
_than_use_cache` is that guard, and it is a CORRECTNESS test.

WHY the translation lives in `screamingface_engine` and not in the protocol type:
`packages/url4` ships to SDK users and must not know an adapter's request-body shape
(plan §4). `CachePolicy` speaks intent (`participate`); this module — and only this
module — speaks `use-cache`.

`max_age` is url4-INTERNAL. v2 refuses it (`global_controls.py:79-83`), so it must never reach
the body; it is applied at read-back (Batch 7), where an entry's age can be compared against it.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from screamingface_engine.world.cache import policy_to_body_field
from url4.streaming.protocol import CachePolicy

# The full input space, one tuple per `CachePolicy` field. `_AXES` is asserted against
# `model_fields` below, so a THIRD field added to the policy fails this module loudly instead of
# quietly escaping the property test's coverage.
_AXES: dict[str, tuple[Any, ...]] = {
    "participate": (None, True, False),
    "max_age": (None, 0, 1, 60, 86_400),
}


def _every_policy() -> list[CachePolicy]:
    names = list(_AXES)
    return [
        CachePolicy(**dict(zip(names, values, strict=True)))
        for values in itertools.product(*(_AXES[name] for name in names))
    ]


# --- the two mapped outcomes ---------------------------------------------------------


def test_participate_true_omits_the_field_entirely() -> None:
    """Plan Batch 2 test 1. Participation is expressed by saying NOTHING.

    v2 treats absent, `null` and `{}` identically — all three participate (spec §1.0) — so the
    smallest body is both sufficient and the least exposed to the closed-grammar bypass. Sending
    `{"use-cache": true}` would be equivalent upstream but is deliberately NOT what we emit: it
    would also change a default run's egress body, which spec §9.1 requires stay byte-identical.
    """
    assert policy_to_body_field(CachePolicy(participate=True)) == {}


def test_participate_false_sends_the_opt_out() -> None:
    """Plan Batch 2 test 2. The one thing url4 ever puts on the wire."""
    body = policy_to_body_field(CachePolicy(participate=False))

    assert body == {"cache": {"use-cache": False}}


def test_opt_out_value_is_a_real_bool_not_a_string() -> None:
    """v2 bypasses a non-bool `use-cache` with reason `malformed_controls` rather than honouring
    it (spec §1.0 parse table). `"false"` would opt the caller out for the WRONG reason, and the
    acceptance test that distinguishes `opted_out` from every other bypass would pass by accident.
    """
    body = policy_to_body_field(CachePolicy(participate=False))

    assert body["cache"]["use-cache"] is False


def test_not_stated_is_treated_as_participate() -> None:
    """A resolved policy always states `participate` (convergence, Batch 5) — but `None` must
    still mean participate, not "unknown, so fail". D1's default is ON, so "not stated" and
    "stated True" have the SAME wire answer; making this raise would turn a harmless convergence
    slip into a dead run for no gain.
    """
    assert policy_to_body_field(CachePolicy()) == {}


# --- max_age is url4-internal and never leaves ---------------------------------------


@pytest.mark.parametrize("max_age", _AXES["max_age"])
@pytest.mark.parametrize("participate", _AXES["participate"])
def test_max_age_never_reaches_the_body(participate: bool | None, max_age: int | None) -> None:
    """Spec §3.5 / plan §6. `max_age` is a url4-internal freshness bound: v2's grammar refuses
    it, so forwarding it would bypass the cache with `unsupported_control` — the exact silent
    cost this design exists to avoid. It changes nothing about what is emitted here.
    """
    body = policy_to_body_field(CachePolicy(participate=participate, max_age=max_age))
    without_max_age = policy_to_body_field(CachePolicy(participate=participate))

    assert "max-age" not in body.get("cache", {})
    assert "max_age" not in body.get("cache", {})
    assert body == without_max_age


# --- THE property: the closed grammar, over the whole input space --------------------


def test_the_axes_cover_every_policy_field() -> None:
    """Guards the guard. The property test below is only exhaustive if `_AXES` enumerates every
    field `CachePolicy` has; a field added without extending it would leave the closed-grammar
    invariant untested while the suite stayed green.
    """
    assert set(_AXES) == set(CachePolicy.model_fields)


@pytest.mark.parametrize("policy", _every_policy(), ids=repr)
def test_no_input_ever_produces_a_key_other_than_use_cache(policy: CachePolicy) -> None:
    """Plan Batch 2 test 3 — **the single most important guard in this plan.**

    Under v2 an unrecognised control key does not degrade to "ignored": the request BYPASSES,
    silently, even next to a valid `use-cache: true` (`global_controls.py`). So there is no
    error, no log and no metric to notice — the only symptom is a cache that never hits. This
    asserts the containment over the FULL cartesian product of the policy's fields, not over the
    two happy paths, because the way this breaks is a new field being spread into the object.
    """
    out = policy_to_body_field(policy)

    assert set(out.get("cache", {})) <= {"use-cache"}


@pytest.mark.parametrize("policy", _every_policy(), ids=repr)
def test_the_body_field_is_spreadable_and_carries_at_most_cache(policy: CachePolicy) -> None:
    """The call site is `json={"model": …, "messages": …, **extra, **policy_to_body_field(p)}`
    (Batch 6), so the return value must be a mapping that contributes AT MOST the `cache` key —
    a stray top-level key would land in the chat-completions body, where aigateway's own
    unsupported-fields path would reject or bypass it.
    """
    out = policy_to_body_field(policy)
    merged = {"model": "m", "messages": [], **out}

    assert set(out) <= {"cache"}
    assert set(merged) <= {"model", "messages", "cache"}


def test_each_call_returns_an_independent_object() -> None:
    """No shared module-level literal. Two runs in one process must not be able to contaminate
    each other's egress body — the same isolation Batch 6 test 3 asserts one layer up, enforced
    here at the source so a cached constant can never become the vehicle.
    """
    first = policy_to_body_field(CachePolicy(participate=False))
    second = policy_to_body_field(CachePolicy(participate=False))

    assert first == second
    assert first is not second
    assert first["cache"] is not second["cache"]

    first["cache"]["use-cache"] = True

    assert second == {"cache": {"use-cache": False}}

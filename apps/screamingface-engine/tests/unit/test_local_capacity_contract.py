"""The local admission ceiling as a CONTRACT with the per-caller cap, not as runner behaviour.

`test_inprocess_runner.py` pins how the adapter refuses once it is full. This module pins the
separate question of where "full" is set, because that number is only correct in relation to how
many of one caller's runs the Engine admits at once.
"""

from screamingface_engine.adapters.inprocess import DEFAULT_MAX_CONCURRENT_RUNS
from screamingface_engine.config import Settings
from screamingface_engine.runner_queue import DEFAULT_CALLER_INFLIGHT_CAP

# INVARIANT: the local admission ceiling stays STRICTLY ABOVE the per-caller in-flight cap
# (`run_queue_caller_inflight_cap`; the queue adapter's `DEFAULT_CALLER_INFLIGHT_CAP` when unset),
# how many of one caller's runs the Engine admits at once; the Client starts none (E5 P2). Equal
# values leave ZERO headroom: one caller's full fan-out saturates the runner exactly, so any other
# run turns the next start into `503 the runner is at capacity`. Abandoned runs make that sticky
# rather than momentary: an orphan holds its slot until `job_deadline_s`, 16 hours.


def _fan_out() -> int:
    return max(Settings().run_queue_caller_inflight_cap, DEFAULT_CALLER_INFLIGHT_CAP)


def test_the_local_ceiling_leaves_headroom_above_the_fan_out() -> None:
    assert DEFAULT_MAX_CONCURRENT_RUNS > _fan_out()
    assert Settings().local_max_concurrent_runs > _fan_out()


def test_the_adapter_default_and_the_setting_agree() -> None:
    # WHY: `local.py` builds the runner from the setting, while any caller that omits the keyword
    # gets the adapter default. If the two drift, local capacity depends on which path built the
    # runner — a split that surfaces only as an unreproducible 503.
    assert Settings().local_max_concurrent_runs == DEFAULT_MAX_CONCURRENT_RUNS

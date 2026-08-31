"""OME-1026 F2 — the one place that answers "how long may a caller wait?".

FEATURE: a bounded model listing. A user asking for their model list gets an answer
promptly, whatever an operator configured for a slow provider's dial.

INVARIANT (a hard maximum, not a default): three seconds is a product promise, so it
cannot be a knob. ``AIGW_DISCOVERY_TIMEOUT_SECONDS`` is the operator's per-dial
deadline and accepts any positive value; a deployment that raises it to 30 for a
paginating provider must not thereby make every listing able to hang for 30 seconds.

INVARIANT (a maximum, not an override): a deployment that configures LESS keeps less.
Clamping upward would slow every listing to enforce a bound that already held.

# WHY this is a helper and not a second setting: the owner brief forbids inventing
# another operator knob. Two knobs would also need a documented ordering rule, and the
# only sane rule is exactly the ``min`` below — so the rule is the whole feature and
# the second knob is pure cost.
# AIDEV-NOTE: a budget is not a cancellation. Every caller of this function must use it
# with a waiter that leaves the work running (``BackgroundRefreshManager.wait_up_to``,
# built on ``asyncio.wait``), never with ``asyncio.wait_for``, which CANCELS its target:
# the refresh holds a per-identity lock while it runs, so cancelling the winner would
# turn one upstream fetch into one fetch per waiting request and record no failure.
"""

from __future__ import annotations

MAX_USER_WAIT_S = 3.0
"""The hard ceiling on any user-facing model-listing wait, in seconds."""


def user_wait_budget(configured_timeout_s: float) -> float:
    """How long a request may wait for a model listing, given the configured dial.

    The provider's own refresh keeps its longer aggregate deadline (OpenRouter walks
    pages under a 10-second budget); this bounds only what the CALLER waits for.
    """
    return min(configured_timeout_s, MAX_USER_WAIT_S)

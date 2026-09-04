"""Trap 2: the consumer-config split (OME-1088).

`_consumer_config` used to return `AckPolicy.NONE` unconditionally — correct and load-bearing
for the broadcast replay readers (under EXPLICIT, any run over ~1000 frames truncates
silently), but the opposite of what the run queue needs. The single function is now two named
builders; the event-stream one must be unchanged, the queue's must be EXPLICIT with bounded
redelivery.
"""

from nats.js.api import AckPolicy

from screamingface_engine.adapters.jetstream import _broadcast_consumer_config
from screamingface_engine.runner_queue import _work_queue_consumer_config


def test_the_broadcast_replay_config_still_returns_none() -> None:
    """INVARIANT: the split must not change the event streams' behavior — a broadcast replay
    reader acks nothing, and under EXPLICIT a run over ~1000 frames truncates silently."""
    assert _broadcast_consumer_config(None).ack_policy is AckPolicy.NONE
    assert _broadcast_consumer_config(7).ack_policy is AckPolicy.NONE


def test_the_work_queue_config_is_explicit_with_bounded_redelivery() -> None:
    """The queue's consumer is a WORKER, not a replay reader: it acks each message once
    processed, and a worker that dies mid-run gets the message redelivered (max_deliver) rather
    than silently lost."""
    config = _work_queue_consumer_config(ack_wait_s=60.0, max_deliver=2, max_ack_pending=12)

    assert config.ack_policy is AckPolicy.EXPLICIT
    assert config.max_deliver == 2
    assert config.ack_wait == 60.0
    assert config.max_ack_pending == 12

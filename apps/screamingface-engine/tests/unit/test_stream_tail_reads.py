"""The JetStream tail-read contract: transport failures are typed, never bare.

`last_frame`'s callers guard `QueueReadError` (the supervisor's claim-time gate and
post-exit publish, the queue runner's status/stop). A bare transport error from inside
`last_frame` bypasses all of them — the V-7(b)/pass-1-#11 cascade — so every failure
path a broker blip can take out of this function must wear the typed wrapper.
"""

import nats
import pytest
from nats.errors import Error as NatsError

from screamingface_engine.adapters.jetstream import JetStreamPublisher, QueueReadError

pytestmark = pytest.mark.asyncio


async def test_last_frame_translates_a_failed_connect_into_queue_read_error(
    monkeypatch,
) -> None:
    """V-7(b)/pass-1 #11: `last_frame` called `self._jetstream()` OUTSIDE its own try,
    so a broker that cannot be connected to — the most common shape of a blip — raised a
    bare transport error that no `except QueueReadError` guard catches. The connect path
    now gets the same typed translation as the fetch."""

    async def refused(*args: object, **kwargs: object) -> None:
        raise NatsError("connection refused during the blip")

    monkeypatch.setattr(nats, "connect", refused)
    publisher = JetStreamPublisher("nats://unused:4222")

    try:
        await publisher.last_frame("t-any")
    except QueueReadError:
        return  # the typed guard target — the contract this test pins
    raise AssertionError("a failed connect must surface as QueueReadError, not bare")

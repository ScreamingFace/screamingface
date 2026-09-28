"""Optional activity never prevents an otherwise admissible lifecycle sequence."""

import pytest

from screamingface_engine.runner.executor import (
    EVENT_SIZE_ESTIMATE_BYTES,
    BridgeOverflowError,
    _Bridge,
)
from url4.observe import Log, NodeFinished, NodeStarted, RunFinished, RunStarted, Usage


def _bridge(soft, hard):
    return _Bridge(maxsize=soft, memory_budget=hard * EVENT_SIZE_ESTIMATE_BYTES)


@pytest.mark.parametrize("soft,hard", [(2, 5), (5, 5), (20, 5)])
@pytest.mark.parametrize("status", ["ok", "error", "cancelled"])
@pytest.mark.asyncio
async def test_optional_logs_preserve_identical_authoritative_lifecycle(soft, hard, status):
    lifecycle = [
        RunStarted("a" * 32, "b" * 16, "expression"),
        NodeStarted("c" * 16, "b" * 16, "RelUrlNode", "/operation"),
        Usage("c" * 16, "provider", "model", 2, 1),
        NodeFinished("c" * 16, status, 1),
        RunFinished(status, 2),
    ]
    outputs = []
    for noisy in (False, True):
        bridge = _bridge(soft, hard)
        emitted = 0
        for event in lifecycle:
            if noisy:
                for _ in range(7):
                    bridge.on_event(Log("c" * 16, "INFO", "optional", {"attempt": 2}))
                    emitted += 1
            bridge.on_event(event)
        bridge.close()
        drained = [event async for event in bridge.drain()]
        outputs.append([event for event in drained if not isinstance(event, Log)])
        # INVARIANT: every submitted Log is either delivered or counted exactly once as lost.
        delivered = sum(isinstance(event, Log) for event in drained)
        assert bridge.dropped == emitted - delivered
        assert bridge.high_water <= hard
    assert outputs == [lifecycle, lifecycle]


@pytest.mark.parametrize("soft,hard", [(2, 4), (4, 4), (8, 4)])
def test_authoritative_only_hard_cap_still_fails_and_incoming_log_drops(soft, hard):
    bridge = _bridge(soft, hard)
    for i in range(hard):
        bridge.on_event(NodeStarted(str(i), None, "TextNode", ""))
    bridge.on_event(Log(None, "INFO", "optional"))
    assert bridge.dropped == 1
    assert len(bridge._buf) == hard
    with pytest.raises(BridgeOverflowError):
        bridge.on_event(NodeFinished("0", "ok", 1))


@pytest.mark.asyncio
async def test_eviction_preserves_surviving_log_order_and_counts_loss():
    bridge = _bridge(4, 4)
    logs = [Log(None, "INFO", str(i)) for i in range(4)]
    for log in logs:
        bridge.on_event(log)
    terminal = RunFinished("ok", 1)
    bridge.on_event(terminal)
    bridge.close()
    assert [event async for event in bridge.drain()] == [*logs[1:], terminal]
    assert bridge.dropped == 1

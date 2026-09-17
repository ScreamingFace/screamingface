import pytest
from test_engine_contract import frame

from screamingface._engine.contract import _RunState
from screamingface.errors import ExecutionError


def log(sequence, id=None):
    return frame(
        "ai.url4.log",
        {"body": "", "severity_text": "INFO", "severity_number": 9},
        sequence=sequence,
        event_id=id,
    )


def test_id_window_rolls_without_losing_sequence_replay_protection():
    state = _RunState("url4")
    for i in range(1, 5001):
        assert state.accept(log(i)).event is not None
    assert len(state._event_ids) == 4096
    assert state.accept(log(1)).event is None
    # INVARIANT: eviction limits collision detection, not authoritative event delivery.
    assert state.accept(log(5001, "event_1")).event is not None
    with pytest.raises(ExecutionError, match="reused"):
        state.accept(log(5002, "event_5000"))


def test_id_byte_budget_and_oversize_ids_do_not_reject_valid_events():
    state = _RunState("url4")
    for i in range(1, 20):
        assert state.accept(log(i, str(i) + "x" * 100_000)).event is not None
    assert sum(len(k.encode()) for k in state._event_ids) <= 1024 * 1024
    assert state.accept(log(20, "x" * (1024 * 1024 + 1))).event is not None
    assert len(state._event_ids) <= 10

import json

from test_engine_contract import frame

from screamingface._engine.run_follow import CandidateEvent, _Frames


def log(sequence, id=None):
    event = frame(
        "ai.url4.log",
        {"body": "", "severity_text": "INFO", "severity_number": 9},
        sequence=sequence,
        event_id=id,
    )
    return json.dumps({"type": "candidate.event", "index": 0, "event": json.loads(event)})


def shown(frames, raw):
    accepted = frames.accept(raw)
    return accepted.event if isinstance(accepted, CandidateEvent) else None


def test_a_long_stream_keeps_dropping_a_replayed_sequence():
    frames = _Frames()
    for i in range(1, 5001):
        assert shown(frames, log(i)) is not None
    assert frames._sequences == {0: 5000}
    assert shown(frames, log(1)) is None
    # INVARIANT: the follow keys delivery on the Candidate's sequence, never on the event id.
    assert shown(frames, log(5001, "event_1")) is not None


def test_large_or_oversize_event_ids_do_not_keep_an_event_from_being_shown():
    frames = _Frames()
    for i in range(1, 20):
        assert shown(frames, log(i, str(i) + "x" * 100_000)) is not None
    assert shown(frames, log(20, "x" * (1024 * 1024 + 1))) is not None
    assert frames._sequences == {0: 20}

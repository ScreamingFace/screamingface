"""The text a dropped Run stream reports, cause by cause.

`websocket_disconnected` is raised from one place, so an oversized frame, a drained proxy,
a rolled Pod and a socket that never connected all arrive at the researcher as the same
sentence unless the close code is carried through. These pin that each reads differently.

Self-contained by design (sdlc rule 5), and deliberately free of any server: what is under
test is the message, not the transport that produces the exception.
"""

from __future__ import annotations

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from screamingface._engine.run_follow import _disconnected as _follow_disconnected

RUN_ID = "run_" + "7" * 32


def _disconnected(cause: BaseException, elapsed_s: float):
    """The follow's report of a lost connection (E5 P2: one follow per Run)."""
    return _follow_disconnected(RUN_ID, False, cause, elapsed_s)


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        pytest.param(
            ConnectionClosedError(None, Close(1009, "frame exceeds limit of 1048576 bytes"), None),
            "client sent close 1009 — frame exceeds limit of 1048576 bytes",
            id="oversize-result-refused-by-this-client",
        ),
        pytest.param(
            ConnectionClosedError(Close(1001, "going away"), None, None),
            "engine sent close 1001 — going away",
            id="engine-going-away",
        ),
        pytest.param(
            ConnectionClosedError(None, None, None),
            "close 1006 abnormal closure, no close frame",
            id="dropped-with-no-close-handshake",
        ),
        pytest.param(
            OSError("connection refused"),
            "OSError",
            id="never-reached-the-engine",
        ),
    ],
)
def test_each_cause_of_a_drop_reads_differently(cause: BaseException, expected: str) -> None:
    # STORY: as the engineer triaging a report, the message alone tells me which failure this
    # was, and the four candidates stop being one undifferentiated bucket.
    #
    # `sent` is read as well as `rcvd` on purpose: THIS client is what sends 1009 when a frame
    # exceeds its limit, so reading only the peer's frame would hide the one cause we know we
    # cause ourselves behind a generic "no close frame".
    assert expected in str(_disconnected(cause, 41.2))


def test_the_report_carries_how_long_the_run_had_been_going() -> None:
    # The second discriminator, and the one the close code cannot supply: a size-driven
    # failure moves with the Report, while an idle cut or a drained listener lands on the
    # same second every time.
    message = str(_disconnected(ConnectionClosedError(None, None, None), 300.0))

    assert "after 300.0s" in message


def test_the_diagnostic_does_not_change_the_error_contract() -> None:
    # The text grew; the code and its retryability are what callers branch on, and a caller
    # keying on `permanent` to decide whether to retry must not be affected by any of this.
    error = _disconnected(ConnectionClosedError(None, Close(1009, "too big"), None), 1.0)

    assert error.code == "websocket_disconnected"
    assert error.permanent is False

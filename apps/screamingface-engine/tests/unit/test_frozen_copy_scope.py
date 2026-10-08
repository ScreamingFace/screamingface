"""E14 F-B3 — the request scope carries the frozen-copy mode of a run.

FEATURE: OME-1307 — a run is in capture mode (`capture`) or in replay mode
(`replay_frozen_copy`, the id of the copy it replays). Both default to "a normal run", so every
existing producer keeps its meaning.

A separate module (append-only gate).
"""

from __future__ import annotations

from screamingface_engine.request_scope import RequestScope

_COPY = "6f1c2b0e-4c0a-4d7e-9a53-2f4f0f3a9b11"


def test_a_scope_defaults_to_no_capture_and_no_replay() -> None:
    scope = RequestScope(origin="run")

    assert scope.capture is False
    assert scope.replay_frozen_copy is None


def test_a_scope_can_state_capture_or_a_replay_copy() -> None:
    assert RequestScope(origin="run", capture=True).capture is True
    assert RequestScope(origin="run", replay_frozen_copy=_COPY).replay_frozen_copy == _COPY

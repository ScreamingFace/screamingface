"""Pin the private nats-py surface the queue's depth/age reads depend on (OME-1088).

`RunQueue._state` reads `js._api_request` and `js._prefix` because nats-py's public
`StreamState` dataclass drops `first_ts` (the server sends it; the model ignores it),
and `oldest_age` needs exactly that field. Underscore-prefixed attributes have NO
public contract: a routine dependency bump can rename or remove them with zero
type-checker warning (dynamic attribute access), and the break would surface at
runtime as admission logic silently misbehaving.

These tests fail loudly at CI the moment the private surface moves — or the moment a
nats-py release finally models `first_ts` publicly, at which point `_state` should
switch to the public API and the last test here be deleted with it.
"""

import inspect

from nats.js import JetStreamContext
from nats.js.api import StreamState


def test_the_context_still_exposes_the_raw_api_request() -> None:
    """`_api_request` is the method `_state` issues STREAM.INFO through."""
    assert hasattr(JetStreamContext, "_api_request")


def test_the_context_still_assigns_a_subject_prefix() -> None:
    """`_prefix` is where the request subject is built from — set in `__init__`."""
    assert "_prefix" in inspect.getsource(JetStreamContext.__init__)


def test_stream_state_still_does_not_model_first_ts() -> None:
    """If a future nats-py models `first_ts` on `StreamState`, the private-API detour in
    `_state` is obsolete: switch to the public `stream_info` and delete this pin."""
    assert "first_ts" not in StreamState.__dataclass_fields__

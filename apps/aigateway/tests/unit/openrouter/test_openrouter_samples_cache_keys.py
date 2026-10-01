"""OME-1289 SM-4/SM-9 gateway half — N seeded samples are N cache entries, a replay is one.

FEATURE: ``sf.samples(model, n)`` sends N requests that differ only in an integer ``seed``.
STORY: as a researcher running a vote over samples, I want the gateway response cache to treat
each sample as its own request (so the vote counts N real answers), and to serve the same
sample again on a replay (so the vote is identical).
INVARIANT under test: ``seed`` is a keyed parameter, so samples never collapse into one cache
entry and a replayed request keeps its key. This is a CHAR test: the behavior exists already
(see ``test_openrouter_global_cache_keys.py``) and is pinned here for the samples use.
"""

from __future__ import annotations

import json

from .projection_harness import key as _key


def test_five_seeded_samples_get_five_distinct_cache_keys() -> None:
    assert len({_key(seed=index, temperature=0.7) for index in range(5)}) == 5


def test_a_replayed_sample_request_repeats_its_cache_key() -> None:
    """The Engine's wire body, parsed back, keys the same as the hand-written one.

    The Engine renders ``temperature`` before ``seed`` and the seed travels as a JSON integer;
    a replay therefore reaches the gateway as a parsed body in that key order, and it must land
    on the entry the first run wrote.
    """
    wire = b'{"model":"m","messages":[{"role":"user","content":"hi"}],"temperature":0.7,"seed":3}'
    parsed = json.loads(wire)
    sent = {name: value for name, value in parsed.items() if name not in {"model", "messages"}}

    assert type(sent["seed"]) is int
    assert _key(**sent) == _key(seed=3, temperature=0.7)
    assert _key(**sent) != _key(seed=4, temperature=0.7)

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

from .projection_harness import key as _key


def test_five_seeded_samples_get_five_distinct_cache_keys() -> None:
    assert len({_key(seed=index, temperature=0.7) for index in range(5)}) == 5


def test_a_replayed_sample_request_repeats_its_cache_key() -> None:
    first = [_key(seed=index, temperature=0.7) for index in range(5)]
    replay = [_key(seed=index, temperature=0.7) for index in range(5)]

    assert first == replay

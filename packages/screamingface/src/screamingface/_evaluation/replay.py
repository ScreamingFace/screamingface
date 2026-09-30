"""The pre-run steps of `evaluate(replay=...)`: check the pin, then ask for the grant.

FEATURE: OME-1307 (E14) contract C6. Both steps run BEFORE the benchmark load, the model preflight
and the capability mint, so a pin that does not resolve spends nothing (RP-E1, RP-9).
INVARIANT: no fallback. When the grant cannot be had, the error reaches the caller and no run
starts, so a replay never turns into a plain run (RP-E5).
"""

from __future__ import annotations

from collections.abc import Sequence

from screamingface._evaluation.runner import _evaluation_inputs
from screamingface._scoreboard.replay_pin import _ReplayPin, parse_replay_pin
from screamingface.recipe import Recipe

_ONE_CANDIDATE = "a replay pin applies to one Candidate; pass exactly one Recipe"


def replay_pin(
    replay: object,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
) -> _ReplayPin:
    """The checked pin for one pinned run, after every input check that needs no network.

    INVARIANT: the pin is checked before the candidates, and the caller asks for the grant only
    after this returns, so the grant request is the first network call.
    """
    pin = parse_replay_pin(replay)
    _one_candidate(candidates, benchmark, limit)
    return pin


def _one_candidate(
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
) -> None:
    # WHY the same checks as a run: a bad benchmark or limit must fail here, before the grant call.
    if len(_evaluation_inputs(candidates, benchmark, limit)) != 1:
        raise ValueError(_ONE_CANDIDATE)

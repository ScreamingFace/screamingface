"""The pre-run steps of `evaluate(replay=...)`: check the pin, then ask for the grant.

FEATURE: OME-1307 (E14) contract C6. Both steps run BEFORE the benchmark load, the model preflight
and the capability mint, so a pin that does not resolve spends nothing (RP-E1, RP-9).
INVARIANT: no fallback. When the grant cannot be had, the error reaches the caller and no run
starts, so a replay never turns into a plain run (RP-E5).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from screamingface._core.ports import _ReplayBinding
from screamingface._evaluation.runner import _evaluation_inputs
from screamingface._scoreboard.replay_pin import _ReplayPin, parse_replay_pin
from screamingface.recipe import Recipe

_ONE_CANDIDATE = "a replay pin applies to one Candidate; pass exactly one Recipe"


def prepare_replay_sync(
    replay: object,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    request_grant: Callable[[_ReplayPin, str], _ReplayBinding],
) -> _ReplayBinding:
    """The grant for one pinned run, after every input check that needs no network."""
    pin = parse_replay_pin(replay)
    _one_candidate(candidates, benchmark, limit)
    return request_grant(pin, benchmark)


async def prepare_replay_async(
    replay: object,
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
    request_grant: Callable[[_ReplayPin, str], Awaitable[_ReplayBinding]],
) -> _ReplayBinding:
    """Async twin of `prepare_replay_sync`."""
    pin = parse_replay_pin(replay)
    _one_candidate(candidates, benchmark, limit)
    return await request_grant(pin, benchmark)


def _one_candidate(
    candidates: Recipe | Sequence[Recipe],
    benchmark: str,
    limit: int | None,
) -> None:
    # WHY the same checks as a run: a bad benchmark or limit must fail here, before the grant call.
    if len(_evaluation_inputs(candidates, benchmark, limit)) != 1:
        raise ValueError(_ONE_CANDIDATE)

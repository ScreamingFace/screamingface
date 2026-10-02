"""The url4 route of the deterministic combine call (OME-1289 E4a).

FEATURE: serve ``/ensemble/combine/v1`` on the world's node, backed by the pure combine core.
STORY: as a compiled reducer Candidate, I send one call (the spec as ``intent``, the member
outputs as ``context``, ``binding=synthesis_N`` as the only param) and get one member's text back
byte for byte, or a text built only by the spec's operators. One ``CombineEvidence`` joins the
task-local operation-call record.

WHY an adapter here, not in ``combine/``: the core is pure and imports no ``url4`` module. This
module is the engine-importing half -- it owns the route, the ``ResolutionError`` mapping, and the
one side effect (the task-local record), like ``world/corrective.py``.
INVARIANT: only a ``CombineError`` becomes a ``ResolutionError`` (permanent: a combine step is
pure, so a retry gives the same result). A plugin bug stays loud and records nothing.
INVARIANT: an abstain is a normal output (the empty text, ``finish_reason`` "stop") and is
recorded like any answer; ``NoVotes`` never reaches this module.
INVARIANT: a failed step records no evidence (EV-E1); the handler is sync pure CPU work.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from screamingface_engine.combine.endpoint import COMBINE_ROUTE, run_combine
from screamingface_engine.combine.ports import CallFingerprint, CombineError, MemberSources
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.operation_accounting import SignalAccounting, combine_signal_accounting
from screamingface_engine.operation_calls import (
    OperationCall,
    current_operation_calls,
    record_combine_call,
)
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node

logger = logging.getLogger(__name__)


def install_combine_runtime(node: Url4Node, registry: OperatorRegistry) -> None:
    """Register the combine endpoint once per URL4 world (mirrors install_corrective_runtime)."""
    if COMBINE_ROUTE not in node.processor_routes():
        node.endpoint(COMBINE_ROUTE)(CombineRoute(registry))


class CombineRoute:
    """The combine handler: one request in, one answer out, one evidence recorded."""

    __slots__ = ("_registry",)

    def __init__(self, registry: OperatorRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> OperatorRegistry:
        return self._registry

    def __call__(self, request: Request) -> str:
        try:
            outcome = run_combine(
                self._registry,
                request.params,
                request.context,
                request.intent,
                accounting=_read_member_accounting,
            )
        except CombineError as exc:
            raise ResolutionError(str(exc), code=exc.code, permanent=True) from exc
        record_combine_call(COMBINE_ROUTE, request.params, outcome.output, outcome.evidence)
        return outcome.output


def _read_member_accounting(sources: MemberSources) -> dict[str, dict[str, float | None]]:
    """The accounting signals of each member, from the calls recorded in this case's scope.

    Each source call is looked up by its exact fingerprint (path, params) among the recorded model
    calls; a member's numbers are the fold of its calls. A call that matches zero or several
    recorded calls makes the member's numbers unknown, never a guess. Never raises.

    INVARIANT: warnings carry a count only -- never a path, a param or any member text.
    """
    calls = current_operation_calls()
    if calls is None:
        logger.warning("combine accounting signals unavailable: no operation-call recorder")
        return {}
    index: dict[CallFingerprint, list[OperationCall]] = {}
    for call in calls:
        if call.combine is None:
            index.setdefault((call.path, call.params), []).append(call)
    unmatched = 0
    result: dict[str, dict[str, float | None]] = {}
    for member, member_calls in sources.items():
        known, missed = _member_numbers(member_calls, index)
        unmatched += missed
        result[member] = known.as_signals()
    if unmatched:
        logger.warning(
            "combine accounting signals: %d source call(s) matched zero or several recorded calls",
            unmatched,
        )
    return result


def _member_numbers(
    member_calls: Mapping[str, CallFingerprint],
    index: Mapping[CallFingerprint, list[OperationCall]],
) -> tuple[SignalAccounting, int]:
    """One member's folded numbers and how many of its source calls matched zero or several calls.

    A call with no match, several matches, or a match without signal accounting makes the member's
    numbers unknown (all None): a partial sum would pass as a total.
    """
    rounds: list[SignalAccounting] = []
    unmatched = 0
    complete = True
    for key in sorted(member_calls):
        matches = index.get(member_calls[key], [])
        unmatched += len(matches) != 1
        recorded = matches[0].signal_accounting if len(matches) == 1 else None
        if recorded is None:
            complete = False
        else:
            rounds.append(recorded)
    return (combine_signal_accounting(rounds) if complete else SignalAccounting()), unmatched


__all__ = ["CombineRoute", "install_combine_runtime"]

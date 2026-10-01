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
INVARIANT: a failed step records no evidence (EV-E1); the handler is sync pure CPU work.
"""

from __future__ import annotations

from screamingface_engine.combine.endpoint import COMBINE_ROUTE, run_combine
from screamingface_engine.combine.ports import CombineError
from screamingface_engine.combine.registry import OperatorRegistry
from screamingface_engine.operation_calls import record_combine_call
from url4.core.errors import ResolutionError
from url4.peer.server import Request, Url4Node


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
            outcome = run_combine(self._registry, request.params, request.context, request.intent)
        except CombineError as exc:
            raise ResolutionError(str(exc), code=exc.code, permanent=True) from exc
        record_combine_call(COMBINE_ROUTE, request.params, outcome.output, outcome.evidence)
        return outcome.output


__all__ = ["CombineRoute", "install_combine_runtime"]

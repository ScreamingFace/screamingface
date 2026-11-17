"""Run-level observation bookkeeping for :func:`url4.dag.run`.

Split from :mod:`url4.dag._run` (module-size cap) by reason to change: this module changes
when the run-level observation events (:class:`~url4.observe.RunStarted` /
:class:`~url4.observe.RunFinished`) change; ``_run`` changes when the public ``run()`` API
grows. ``url4.dag._run`` re-exports every name here, so no import path moves.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Literal

from url4.core.nodes import Node as AstNode
from url4.observe import Observer, RunFinished, RunStarted

from url4.dag._context import _ObsState  # isort: skip
from url4.dag.compiler import Graph  # isort: skip
from url4.dag.node import DagNode, ExecutionContext  # isort: skip


def _start_observation(
    run_ctx: ExecutionContext,
    observer: Observer | None,
    target: str | AstNode | Graph | DagNode,
    trace_id: str | None = None,
    root_span_id: str | None = None,
) -> _ObsState | None:
    """Mint the run's ``_ObsState``, wire it onto ``run_ctx``, and emit
    :class:`~url4.observe.RunStarted` — once, here, for the top-level owned
    run only. ``None`` (a no-op run) when no ``observer`` was passed.

    ``trace_id``/``root_span_id``, when supplied, are used verbatim instead of
    minting fresh ones — letting a caller's own run-root identity (e.g. a
    hosting service's ``publish.run``) agree with the engine's."""
    if observer is None:
        return None
    obs = _ObsState(observer, trace_id if trace_id is not None else secrets.token_hex(16))
    run_ctx._obs = obs
    run_ctx._current_span_id = root_span_id if root_span_id is not None else secrets.token_hex(8)
    obs.emit(RunStarted(obs.trace_id, run_ctx._current_span_id, _expression_hash(target)))
    return obs


def _finish_observation(obs: _ObsState | None, status: Literal["ok", "error", "cancelled"]) -> None:
    """Emit :class:`~url4.observe.RunFinished`; a no-op when ``obs`` is ``None``."""
    if obs is not None:
        obs.emit(RunFinished(status, obs.next_seq()))


def _expression_hash(target: str | AstNode | Graph | DagNode) -> str:
    """A short, deterministic fingerprint of ``target`` for
    :class:`~url4.observe.RunStarted` — identifies "which expression" without
    carrying (and potentially leaking) the full source text through the
    observation stream.

    A raw hand-built :class:`DagNode` has no engine-guaranteed ``__repr__`` —
    the default object repr is id-based and differs run to run, which would
    break the "deterministic" contract above. ``str``/``AstNode``/``Graph``
    targets stringify structurally (source text / a dataclass repr), so only
    the ``DagNode`` fallback needs the type-name-only fingerprint.
    """
    if isinstance(target, (str, AstNode, Graph)):
        fingerprint = str(target)
    else:
        fingerprint = type(target).__name__
    return hashlib.sha256(fingerprint.encode()).hexdigest()[:16]


__all__ = ["_expression_hash", "_finish_observation", "_start_observation"]

"""Am I inside a Candidate invocation? — the answering/grading boundary as an ambient flag.

Think of an exam hall with two kinds of people: students writing answers (the Candidate's
own calls) and examiners marking them (benchmark-authored judge calls). Some per-run
directives apply to students only — the answer seed (OME-1038) is one: stamped onto a
judge whose pinned params carry no seed, it would re-key every judge call per sitting
under an unchanged benchmark revision, making grading identity vary with the answer seed.

This module is that boundary, said once: the Candidate adapter raises the flag around the
candidate's inner expression, and any per-run answer-side directive checks it. It lives at
the top level (beside :mod:`screamingface_engine.retrieval_policy`, whose ContextVar
pattern it copies) so both `benchmarks/` and `runner/` may import it without a cycle.

INVARIANT: the flag is task-local (ContextVar), so concurrent runs sharing one event loop
in local mode can never read each other's scope.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_inside: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "screamingface_engine_candidate_invocation", default=False
)


def in_candidate_invocation() -> bool:
    """True while the current task is evaluating a Candidate's own (answering) expression."""
    return _inside.get()


@contextmanager
def candidate_invocation_scope() -> Iterator[None]:
    """Mark the enclosed evaluation as the Candidate's own answering, restoring on exit."""
    token = _inside.set(True)
    try:
        yield
    finally:
        _inside.reset(token)


__all__ = ["candidate_invocation_scope", "in_candidate_invocation"]

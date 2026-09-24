"""Which Case's judge call is this? — grading-call identity as an ambient tag.

Think of the exam hall again (see :mod:`screamingface_engine.candidate_scope`):
students answer, examiners mark. When an examiner (a benchmark's LLM judge) makes a
model call mid-marking, two bystanders want to know WHOSE paper is being marked:

- the judge provider, so it can register the call against that Case's evidence and
  the run's payload-free grading join can attribute tokens/cost to the Case
  (:mod:`screamingface_engine.grading_accounting`, OME-1240);
- the connector's model-call lifecycle log lines, so the engine log can answer
  "what happened to case 7's judge call" by grep alone — the line otherwise names
  only the model, which the candidate may share with the judge.

The grade hook raises the scope around one Case's scorer; both readers check it.
Top-level beside ``candidate_scope`` (whose ContextVar pattern this copies) so
``runner/`` and the benchmark plugins may import it without a cycle.

INVARIANT: task-local (ContextVar) — concurrent runs sharing one event loop in
local mode can never read each other's Case.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

_case: contextvars.ContextVar[int | str | None] = contextvars.ContextVar(
    "screamingface_engine_grading_call_case", default=None
)


def current_grading_case() -> int | str | None:
    """The Case whose grading is running in this task, or None outside grading."""

    return _case.get()


def grading_call_log_suffix() -> str:
    """The log-line tag for the current scope — empty outside grading.

    Leads with a space so lifecycle format strings append it verbatim; carries
    the Case id ONLY (no prompt, no model output — the OME-990 log rule).
    """

    case: int | str | None = _case.get()
    return "" if case is None else f" role=judge case={case}"


@contextmanager
def grading_call_scope(case_id: int | str) -> Iterator[None]:
    """Mark the enclosed calls as one Case's grading, restoring on exit."""

    token: contextvars.Token[int | str | None] = _case.set(case_id)
    try:
        yield
    finally:
        _case.reset(token)


__all__ = ["current_grading_case", "grading_call_log_suffix", "grading_call_scope"]

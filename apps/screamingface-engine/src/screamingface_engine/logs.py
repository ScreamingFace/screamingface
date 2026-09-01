"""Log configuration for both modes of the image.

WHY this module exists at all: `uvicorn.run()` installs handlers for the
`uvicorn*` loggers ONLY and leaves the root logger with none. Every
`screamingface_engine` record therefore fell through to `logging.lastResort`, which
emits at WARNING — so the App's INFO lines were discarded in every deployment that
has ever run. The visible symptom was a control plane whose logs contained nothing
but `uvicorn.access` health checks, which reads as "nothing happened" rather than
"this process cannot say anything".

That mattered most for exactly the evidence hardest to get any other way: the WebSocket
close code. Only the App observes it — a client cannot report a close it never received —
and a dropped Run stream is otherwise indistinguishable from every other dropped Run stream.

Stdlib only, deliberately: the run mode (a Job) needs this as much as the serving mode, and
the layering rule keeps the two import graphs disjoint.

FEATURE (OME-1069): the run-context machinery below is the runner's traceability layer. A
Job's process logs are the operator's only view of a run that is not the CloudEvents stream,
and before this they carried no topic and no trace id — a line could not be attributed to a
run, and a failed Job could not be correlated with the stream that holds its real outcome.
The mechanism is a ContextVar the run mode binds around one run, plus a Filter that renders
it onto every record emitted inside that scope. The control plane never binds the context,
so its lines are byte-identical to before.
"""

import contextvars
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TextIO

APP_LOGGER = "screamingface_engine"
LEVEL_ENV = "URL4_CLOUD_LOG_LEVEL"
DEFAULT_LEVEL = "INFO"

# Matches uvicorn's own column so a deployment's logs read as one stream rather than two.
# `%(run_context)s` is set by `RunContextFilter`; `defaults=` keeps a record that somehow
# reaches the handler without passing the filter (a foreign handler's record, say) from
# raising KeyError in the formatter.
_FORMAT = "%(levelname)s:     %(name)s %(run_context)s%(message)s"


@dataclass(frozen=True, slots=True)
class RunContext:
    """The one run a process log line belongs to, when it belongs to one."""

    topic: str
    trace_id: str | None = None


_run_context: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "screamingface_engine_run_context", default=None
)


@contextmanager
def run_scope(topic: str, trace_id: str | None = None) -> Iterator[None]:
    """Bind one run's identity for the duration of a scope; restore on exit.

    The run mode wraps its whole run in this, so every `screamingface_engine` record emitted
    inside — including the executor's own warnings, which never see the topic — carries the
    run's `topic` and, when known, its W3C `trace_id`. ContextVars propagate across awaits
    within a task and into child tasks, so the executor's `_drive` task inherits the binding.
    """

    token = _run_context.set(RunContext(topic=topic, trace_id=trace_id))
    try:
        yield
    finally:
        _run_context.reset(token)


def current_run_context() -> RunContext | None:
    """The bound run identity, or None outside any run scope."""

    return _run_context.get()


class RunContextFilter(logging.Filter):
    """Render the bound run's identity onto every record that passes through.

    A Filter rather than a per-call argument so the executor's existing warnings and any
    future log call inside a run are attributed without threading the topic through every
    signature. Unbound (the control plane, tests, boot) it is a no-op: `run_context` is
    empty and the line renders exactly as before.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        context = _run_context.get()
        if context is None:
            record.run_context = ""
            return True
        parts = [f"topic={context.topic}"]
        if context.trace_id is not None:
            parts.append(f"trace_id={context.trace_id}")
        record.run_context = " ".join(parts) + " "
        return True


_INSTALLED = "_screamingface_engine_log_handler"
"""Marks the handler THIS module installed.

Idempotence has to be about our own handler, not about the logger being empty: anything
else may have attached one first — a test harness, a sidecar, an embedding process — and
`if not logger.handlers` would then read that as "already configured" and install nothing
at all. The failure is silent and looks exactly like the bug this module exists to fix.
"""


def configure(stream: TextIO | None = None) -> None:
    """Give the `screamingface_engine` logger tree its own handler and level.

    Idempotent: a second call neither stacks handlers nor disturbs anyone else's.
    `propagate` is disabled so that a later root configuration — uvicorn's, a test
    harness's, a sidecar's — cannot turn every record into two.
    """

    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(os.getenv(LEVEL_ENV, DEFAULT_LEVEL).upper())
    if not any(getattr(handler, _INSTALLED, False) for handler in logger.handlers):
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(_FORMAT, defaults={"run_context": ""}))
        handler.addFilter(RunContextFilter())
        setattr(handler, _INSTALLED, True)
        logger.addHandler(handler)
    logger.propagate = False


__all__ = [
    "APP_LOGGER",
    "DEFAULT_LEVEL",
    "LEVEL_ENV",
    "RunContext",
    "RunContextFilter",
    "configure",
    "current_run_context",
    "run_scope",
]

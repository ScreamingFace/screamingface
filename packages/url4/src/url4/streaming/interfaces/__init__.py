"""The streaming ports — the abstract contracts, and nothing that implements them.

Three ports, one per axis of the run:

- :class:`Executor` — how a url4 expression BECOMES a stream of steps.
- :class:`EventPublisher` / :class:`EventConsumer` / :class:`EventStream` — how those steps
  reach a reader.
- :class:`JobRunner` — how a run is scheduled, stopped, and observed.

Each port ships with the contract types its implementers must speak (``ExecStep`` and friends,
``JobStatus``) and the shared rules every implementation must apply the same way
(``validate_from_sequence``, ``job_name``) — a port is its whole contract, not just the class.

WHY a separate package: `url4.streaming` also holds concrete things (the codec, the wire
protocol models, the trace helpers, the `lifecycle.run` driver that DRIVES these ports). Import
depth is not the boundary; this is. Everything here is implemented elsewhere — in the Runner
(`Url4Executor`, `JetStreamPublisher`), the App (`K8sJobRunner`, `JetStreamConsumer`), and the
test doubles — and nothing here may import any of them.

This is the only import path for the names below — `url4.streaming` re-exports nothing, so
`from url4.streaming.interfaces import JobRunner` is both the short way and the honest one.
"""

from url4.streaming.interfaces.executor import (
    Completed,
    ExecStep,
    Executor,
    SpanRef,
    Telemetry,
    TraceContext,
    Traced,
)
from url4.streaming.interfaces.jobs import (
    JobAlreadyExists,
    JobRunner,
    JobRunnerAtCapacity,
    JobStatus,
    job_name,
)
from url4.streaming.interfaces.stream import (
    EventConsumer,
    EventPublisher,
    EventStream,
    StreamNotFoundError,
    validate_from_sequence,
)

__all__ = [
    "Completed",
    "EventConsumer",
    "EventPublisher",
    "EventStream",
    "ExecStep",
    "Executor",
    "JobAlreadyExists",
    "JobRunner",
    "JobRunnerAtCapacity",
    "JobStatus",
    "SpanRef",
    "StreamNotFoundError",
    "Telemetry",
    "TraceContext",
    "Traced",
    "job_name",
    "validate_from_sequence",
]

import hashlib
from abc import ABC, abstractmethod
from typing import Literal

_NAME_HASH_LEN = 16

JobStatus = Literal[
    "scheduled",
    "running",
    "succeeded",
    "failed",
    "timed_out",
    "stopped",
    "not_found",
]
"""The run states (spec §3): ``scheduled → running → {succeeded|failed|stopped|timed_out}``, plus
``not_found`` for an unknown/absent topic. Each adapter maps the substrate state it can observe.

``scheduled`` means the run is accepted but not yet started — i.e. queued. Do not add a
``queued`` member: ``scheduled`` already covers it. Whether a substrate can OBSERVE the gap
between acceptance and start is adapter-specific: one that starts a run the moment it accepts
it — the in-process runner's tasks begin as soon as they are created — reports ``running`` from
acceptance on, because that is the first state it can distinguish. Callers must not read
``running`` as proof that execution has begun on such a substrate, nor wait for a
``scheduled`` frame that its runner can never emit.
"""


class JobAlreadyExists(Exception):
    pass


class JobRunnerAtCapacity(Exception):
    """The substrate refused the run because it is saturated — retry later, unchanged.

    Distinct from :class:`JobAlreadyExists`, which says THIS topic is spent and retrying can never
    help. This one is transient and carries no verdict about the request, so callers map it to a
    retry-after response rather than a conflict.

    Any substrate with a finite declared ceiling raises it: an in-process runner shares one
    event loop across every run it accepts, so admission is its own job; a queue-backed runner
    raises it when its queue depth hits the ceiling; a cluster scheduler raises it when its
    resource quota is exhausted. The port names the substrate SHAPES, not adapter classes — an
    adapter is bound to this contract by its own tests, not by being enumerated here.
    """

    def __init__(self, active: int, limit: int) -> None:
        super().__init__(f"runner at capacity: {active} run(s) in flight, limit {limit}")
        self.active = active
        self.limit = limit


def job_name(topic: str) -> str:
    digest = hashlib.sha256(topic.encode("utf-8")).hexdigest()[:_NAME_HASH_LEN]
    return f"url4-{digest}"


class JobRunner(ABC):
    """Schedules and observes one run per topic on some substrate.

    INVARIANT: every method is async because the production substrate is a REMOTE one — these are
    network round trips to an API server, not local bookkeeping. An adapter whose client library
    is synchronous (the kubernetes one is) must offload the blocking call to a thread rather than
    make it inline; the port is async precisely so that obligation is visible at the signature
    instead of being discovered when one stuck API server freezes the whole control plane. Callers
    run on the same event loop that drives every WebSocket pump and heartbeat in the process.
    """

    @abstractmethod
    async def schedule(
        self,
        topic: str,
        url4: str,
        deadline_s: int,
        *,
        traceparent: str | None = None,
        credential: str | None = None,
        profile: str | None = None,
    ) -> str: ...

    @abstractmethod
    async def stop(self, topic: str) -> None: ...

    @abstractmethod
    async def exists(self, topic: str) -> bool: ...

    @abstractmethod
    async def status(self, topic: str) -> JobStatus: ...

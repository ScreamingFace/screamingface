"""The readiness contract between the event-stream adapters and the `/readyz` probe (OME-942).

WHY a module of its own rather than the check living in `ops.py`: the endpoint must not import
a concrete adapter — the App is handed the PORT (`EventConsumer`) and `create_app_from_env`
already keeps that boundary with `getattr(job_runner, "aclose")` rather than an isinstance.
Putting the exception here lets the JetStream adapter raise something the endpoint can name
without either of them importing the other, and without `ops.py` ever mentioning `nats`.

WHY the check is OPTIONAL on the port rather than an abstract method: the in-process stream
that `--local` runs on has no broker to be unreachable from, and every test fake would have to
grow a method that can only answer "yes". An adapter that can be unreachable says so; one that
cannot stays silent and is ready. This is the same shape as `EventPublisher.flush`, which is
non-abstract for the same reason.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class StreamNotReadyError(RuntimeError):
    """The event stream cannot reach its broker right now.

    Carries the operator-facing reason as its message: the probe's body is the only place a
    reason surfaces, since a kubelet records the failure and not the response.

    INVARIANT: adapters translate their transport's own exceptions into this one. A raw
    `nats.errors.*` or `OSError` reaching the endpoint would answer 500 — which Kubernetes
    treats as a failed probe either way, but an operator reads as a bug in the App rather than
    an outage in the broker.
    """


@runtime_checkable
class ReadinessProbe(Protocol):
    """An event-stream adapter that can report whether its broker is reachable."""

    async def check_ready(self) -> None:
        """Return normally when reachable; raise `StreamNotReadyError` when not."""


async def stream_readiness(stream: object | None) -> str | None:
    """The reason `stream` is not ready to serve, or None when it is.

    INVARIANT: only a stream that CAN report itself unreachable is ever reported unready. A
    `None` stream — no event stream wired at all — is not a broker outage and is not treated as
    one: `create_app_from_env` always wires one, so the unwired shape is a composition-time
    choice (a test App, an embedding host), and failing readiness for it would make the probe
    answer a question it was not asked. The dead-probe defect this fixes is a WIRED stream whose
    broker is gone, which is the case below.
    """

    # Nothing to ask: either no stream at all (see the INVARIANT above), or a brokerless
    # adapter — the in-process stream `--local` runs on has no broker to be unreachable from.
    if stream is None or not isinstance(stream, ReadinessProbe):
        return None
    try:
        await stream.check_ready()
    except StreamNotReadyError as exc:
        return str(exc)
    return None


__all__ = ["ReadinessProbe", "StreamNotReadyError", "stream_readiness"]

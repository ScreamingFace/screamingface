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

import asyncio
import logging
from typing import Protocol, runtime_checkable

_logger = logging.getLogger(__name__)

READINESS_TIMEOUT_S = 4.0
"""Hard bound on the whole readiness check, enforced at the endpoint's boundary.

Sized just BELOW the chart's `readinessProbe.timeoutSeconds` (5s): the App must answer while
the kubelet is still listening, because nothing cancels the handler once it is not. Above the
adapter's own `READINESS_DIAL_TIMEOUT_S` (3s) so the adapter's more specific reason normally
wins and this bound only fires for an adapter that has no bound of its own.
"""

MAX_REASON_CHARS = 120
"""Hard cap on the reason text `/readyz` will render.

Stated as a bound rather than trusted to the adapters, because `/readyz` has no auth
dependency and the chart routes a single `/` PathPrefix to the App: whatever reaches this
string reaches the public internet. 120 characters fits every literal the contract below
allows and leaves an adapter that ignores the contract unable to turn a probe into a
reflector.
"""

_CONTROL_CHARS = {c: " " for c in range(0x20)} | {0x7F: " "}


class StreamNotReadyError(RuntimeError):
    """The event stream cannot reach its broker right now.

    CONTRACT on the message (review round 2, OME-942): a SHORT, FIXED, operator-facing literal
    that names the CLASS of failure and nothing else. It must never carry the broker URL, the
    transport's own exception text, a host, a subject, or a topic. `/readyz` is unauthenticated
    and the chart's HTTPRoute exposes it, so this message is public output — `config.natsUrl`
    is free-form operator input and `nats://user:pass@host:4222` is the standard nats-py auth
    form, which makes the URL a credential. Transport detail belongs in the server-side log
    `stream_readiness` writes, where only the cluster can read it.

    `stream_readiness` additionally caps and scrubs whatever it is given — the contract is
    enforced at the boundary as well as honoured at the raiser, because one adapter forgetting
    it must not become a leak.

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

    INVARIANT: this call is BOUNDED, whatever the adapter does (review round 2). A readiness
    handler that can park indefinitely is worse than the static literal it replaces: Starlette
    does not cancel the handler when the kubelet's `timeoutSeconds` expires, so a probe that
    never returns accumulates one pending handler per `periodSeconds` for the whole outage — on
    the loop that pumps every WebSocket. The JetStream adapter bounds its own dial as well; this
    is the boundary that holds for an adapter that forgets to.
    """

    # Nothing to ask: either no stream at all (see the INVARIANT above), or a brokerless
    # adapter — the in-process stream `--local` runs on has no broker to be unreachable from.
    if stream is None or not isinstance(stream, ReadinessProbe):
        return None
    try:
        await asyncio.wait_for(stream.check_ready(), timeout=READINESS_TIMEOUT_S)
    except TimeoutError:
        _logger.warning("readiness: the event stream check exceeded %ss", READINESS_TIMEOUT_S)
        reason = "event stream readiness check timed out"
    except StreamNotReadyError as exc:
        # Server-side FIRST, unbounded and unscrubbed: withholding detail from an anonymous
        # HTTP caller is not withholding it from the operator, and the log is the only place
        # the full reason (plus the chained transport exception) survives.
        _logger.warning("readiness: event stream is not ready: %s", exc, exc_info=exc)
        reason = _public_reason(str(exc))
    else:
        reason = None
    return reason


def _public_reason(reason: str) -> str:
    """Bound and flatten a reason before it is rendered to an unauthenticated caller.

    WHY here and not only at the raiser: `StreamNotReadyError`'s contract already says the
    message is a short fixed literal, and the one production raiser honours it. This is the
    boundary that holds when a future adapter does not — the same "sanitize where it leaves
    the process" rule OME-941 applied to terminal problem details. Control characters go
    because the reason lands in a JSON body an operator may paste anywhere; the cap goes
    because nothing downstream bounds it.
    """
    flattened = " ".join(reason.translate(_CONTROL_CHARS).split())
    if len(flattened) <= MAX_REASON_CHARS:
        return flattened
    return flattened[: MAX_REASON_CHARS - 1] + "…"


__all__ = [
    "MAX_REASON_CHARS",
    "READINESS_TIMEOUT_S",
    "ReadinessProbe",
    "StreamNotReadyError",
    "stream_readiness",
]

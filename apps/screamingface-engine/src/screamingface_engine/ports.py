"""screamingface-engine's local widening of the ports it does not own.

`url4.streaming.interfaces.JobRunner` is the abstract substrate port, and it lives
in the engine distribution: it describes scheduling a run in terms every substrate
shares. Carrying the CALLER's verified identity to aigateway is not one of those
terms — it is this app's deployment concern (see
:data:`screamingface_engine.job_env.IDENTITY_HEADER_ENV`), and aigateway is not
part of the url4 language.

So the parameter is declared HERE rather than on the engine's port. Adding an
optional keyword-only argument in an override widens the contract — every caller
written against the base port still type-checks — which is what lets the two
adapters accept identity without `packages/url4` gaining a concept that only this
app has.

A shared leaf by construction: it imports nothing from `screamingface_engine` beyond
the abstract port, so both the control plane and the run mode may import it
(`.claude/scripts/check_layering.py`).
"""

from __future__ import annotations

import contextlib
from abc import abstractmethod
from collections.abc import Iterator, Mapping
from datetime import datetime

from screamingface_engine.job_env import RunShape
from url4.streaming.interfaces import JobRunner
from url4.streaming.protocol import CachePolicy


class StoppedBeforeSchedule(Exception):
    """`schedule()` found its topic already stopped by a bound stop (E5 P1 spec D12): nothing
    runs. WHY an error and not a normal return: the start must answer as canceled, and must not
    log or trace the run as scheduled."""


class IdentityAwareJobRunner(JobRunner):
    """A :class:`JobRunner` whose ``schedule`` also carries the caller's verified
    identity and the run's cache policy.

    ``identity`` is canonical header name → value, exactly as
    :func:`screamingface_engine.job_env.identity_from_headers` produces it. An
    adapter serializes it onto the run's environment with
    :func:`screamingface_engine.job_env.identity_to_env`; the Runner reads it back
    and renders it onto its outgoing aigateway request.

    WHY it is not simply forwarded as headers: the App that receives them and the
    Runner Pod that calls aigateway are different processes, and the outgoing
    request does not exist yet when the headers arrive. Identity has to be captured,
    serialized, and re-rendered.

    ``cache`` takes that same path for the same reason, and is declared HERE rather
    than on the engine's port for the same one again: whether a run participates in
    some GATEWAY's response cache is this app's deployment concern, not a term of
    the url4 language. It is the run's RESOLVED policy — both carriers have already
    been reconciled (:mod:`screamingface_engine.rest.cache_policy`) — or ``None``
    when the caller of this port stated nothing at all, which stays distinguishable
    from an explicit opt-out all the way down.

    INVARIANT: per RUN. It must never be folded into world configuration shared by every run in a
    process — in local mode those runs share one event loop, so a policy parked there is one
    caller's directive that another caller's run reads.

    ``capture`` and ``replay_frozen_copy`` (OME-1307) are the run's frozen-copy mode: capture a new
    copy, or replay the copy with that id. Both default to a normal run, are never both set, and
    are per RUN for the same reason; they ride the same path as ``answer_seed``.

    ``enqueued_at`` (E5 P1 spec D12) is when the run's deadline starts; ``None`` means when it is
    queued. A bound start passes its bind moment, which precedes any cancel of it, so the cancel's
    tombstone outlives every moment the run could still start. A substrate that starts the run at
    once has no queue wait and ignores it.
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
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        answer_seed: int | None = None,
        client_version: str | None = None,
        shape: RunShape = "expression",
        capture: bool = False,
        replay_frozen_copy: str | None = None,
        enqueued_at: datetime | None = None,
    ) -> str: ...

    @contextlib.contextmanager
    def start_attempt(self, topic: str) -> Iterator[None]:
        """Wrap one start of `topic`, from before its bind until it has scheduled or failed.

        WHY: a substrate that keeps a stop for a topic not yet scheduled (`stop_bound`) needs
        it only while a start that bound before the cancel can still reach `schedule()`. A
        start that binds after the cancel is refused at the bind (E5 P1 spec R2). The queue
        keeps its stop as a tombstone instead, so the default records nothing.
        """
        yield

    async def stop_bound(self, topic: str) -> None:
        """Stop a topic a Run bound (E5 P1 spec D12): one this App queued, or is about to.

        WHY its own method: the Run registry is the durable record that the topic was meant to
        run, so a substrate that otherwise skips a topic it has no record of scheduling (the
        queue after an App restart, or before its publish lands) must still keep it from
        starting. Any other substrate stops it as usual.
        """
        await self.stop(topic)

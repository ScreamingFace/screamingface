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

from abc import abstractmethod
from collections.abc import Mapping

from url4.streaming.interfaces import JobRunner
from url4.streaming.protocol import CachePolicy


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
    serialized, and re-rendered — the same path ``credential`` and ``profile``
    already take.

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
        identity: Mapping[str, str] | None = None,
        cache: CachePolicy | None = None,
        client_version: str | None = None,
    ) -> str: ...

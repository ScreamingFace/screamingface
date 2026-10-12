"""A Judge retry after an unusable reply asks the Judge again instead of re-reading the cache.

FEATURE (OME-1533). healthbench, gdpval-text and draco nest each Judge call inside a verdict
route. When the Judge answers with something the verdict cannot parse, the route fails with
``judge_reply_invalid`` and the verdict source's ``;retry=`` re-runs the nested Judge call. That
re-run sends the SAME bytes, and the AI Gateway's global request cache stores any successful
reply — the garbled one included — so under the run's own cache policy every retry was served
the same garbled reply from the cache, and the Case failed anyway.

Mental model: a re-sent letter that carries "second notice: your last reply was unreadable"
gets a fresh reply; one with no stamp gets the photocopy on file. Stages, per model call:

1. The connector asks url4 whether this call runs inside a guard's retry, and which failure
   caused it (:func:`url4.dag.current_guard_retry`), and hands that code here. It is read in the
   connector because only the Runner adapters may import the url4 engine (the boundary pinned
   by ``test_only_engine_extensions_import_url4``); this module keeps the Engine's policy.
2. Only when that failure is ``judge_reply_invalid`` — the Judge answered, but unusably — run
   the call under the SAME request scope with ``CachePolicy(participate=False)``. The connector
   already turns that into the body field ``{"cache": {"use-cache": false}}``
   (``world/cache.py``), the one opt-out the gateway understands; nothing new goes on the wire.
3. Every other call keeps the scope it was given: every first send, and a retry after a 429,
   5xx or timeout. Those failures stored nothing, so the cache cannot echo them — and an opt-out
   there would stop the good reply that follows from being stored, which cache-backed replays
   read.

Worked example: a healthbench rubric item, ``;retry=2``. First send: no retry → the run's policy
(for a default run, no ``cache`` field) → the Judge says ``"I think the answer is fine"``, which
the gateway stores and the verdict rejects. Retry 1: ``GuardRetry(1, "judge_reply_invalid")`` →
``use-cache: false`` → a fresh Judge reply, parsed, item graded. The fresh reply is not stored
("participate" is both directions), and the garbled one stays cached.

What does not change: the request's path, params, messages and identity, so the request key that
grading accounting joins on (``request_identity.model_request_key``) is the same on every retry
and the retry's cost books to the same Case and Evidence item.
"""

from __future__ import annotations

from dataclasses import replace

from screamingface_engine.benchmarks.failure_classes import JUDGE_REPLY_INVALID_CODE
from screamingface_engine.request_scope import RequestScope
from url4.streaming.protocol import CachePolicy


def scope_for_this_send(scope: RequestScope, retry_cause: str | None) -> RequestScope:
    """The request scope this model call runs under: the caller's, or the same one opted out
    of the cache when it re-asks a Judge whose last reply was unusable.

    Args:
        scope: the caller's request scope, as bound for this request.
        retry_cause: the error code of the failure that made this send a retry (url4's
            ``GuardRetry.failure_code``), or ``None`` on a first send or outside any guard.

    Returns:
        ``scope`` itself unless ``retry_cause`` is ``judge_reply_invalid``; then a copy whose only
        difference is ``CachePolicy(participate=False)`` (identity, seed, origin and deadline
        unchanged).
    """
    if retry_cause != JUDGE_REPLY_INVALID_CODE:
        return scope
    return replace(scope, cache=CachePolicy(participate=False))


__all__ = ["scope_for_this_send"]

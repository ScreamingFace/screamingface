"""Spec §5's one table. The service has state, but it is a retry queue, not a document store.

Every column plan §2.3 names is here, in `0001_initial`, including the four no code reads yet
(`attempts`, `next_attempt_at`, `lease_expires_at`, `ticket_id`/`ticket_url`). That is deliberate
and is the reason this file is longer than what `OME-1008` alone needs: the table is greenfield
exactly once, and a later item adding a migration for a column this one already knew about is
how two deployments end up on different schemas for the same release.

Two column-level corrections plan §2.3 records, both learned from the drafting pass:

- **There is no `delivered_at`.** `updated_at` plus ``delivery_state='delivered'`` already
  carries the fact, and a second timestamp is a second thing to keep true.
- **`queued` is a real `delivery_state`, not a null timestamp.** The alternative overloaded
  ``next_attempt_at IS NULL`` to mean "nothing further is owed", which inverts between the two
  readers: `QueueSink`'s successes get retried six times and then alarm, while `queue list`
  returns nothing and the queue cannot be drained. A state is a state; a timestamp is a
  timestamp.
"""

from __future__ import annotations

from tortoise import fields
from tortoise.indexes import Index

from .base import BaseReportIntakeModel

REF_MAX_LENGTH = 32
"""`r_` plus 12 hex characters today (`mint_ref`), with room for a longer mint later."""

IDEMPOTENCY_KEY_MAX_LENGTH = 255
"""Matches the scoreboard's `idempotency_keys.key`. A client-supplied value, so it is bounded
at the route as well as at the column — `routes/reports.py` reads this constant, because a value
bounded ONLY here is answered `503` by the ORM's own validator and spec §8 tells the client that
`503` means retry unchanged."""

EMAIL_MAX_LENGTH = 320
"""RFC 5321's maximum path length: 64-octet local part, `@`, 255-octet domain."""


class BaseReport(BaseReportIntakeModel):
    class Meta:
        abstract = True

    ref = fields.CharField(primary_key=True, max_length=REF_MAX_LENGTH)
    """Server-minted, never derived from client input. Being the primary key is what makes that
    property structural: there is no code path that can write a client's string here."""

    idempotency_key = fields.CharField(
        max_length=IDEMPOTENCY_KEY_MAX_LENGTH, null=True, unique=True
    )
    """Spec §5's replay key, and the ONLY dedup key. `request_fingerprint` below is diagnostic.

    The scoreboard deduplicates on a content hash and `OME-970` is what that cost: a resubmission
    returned *another* run's id, because a content hash identifies the content, not the
    submission. Nullable because anonymous clients are not required to send one; unique because
    two rows sharing a key is precisely the state the window exists to prevent.

    NOT the client's header value: `reports.pipeline.scoped_dedup_key` namespaces it to the
    caller first, so what lands here is a digest. `POST /v1/reports` is unauthenticated, so the
    raw string is one a stranger can also choose — and a shared namespace made a guessed key a
    bearer lookup for somebody else's `ref`. The column stays one unique varchar either way.
    """

    payload = fields.JSONField()
    """`BoundedReport.payload` — validated and truncated. Never `scanned`, which is
    pre-truncation and exists only so the classifier cannot be walked around."""

    classification = fields.CharField(max_length=16)
    """The SERVER's verdict (spec §2.2). Only `envelope` is ever stored: `content` is a 422 at
    the route and never reaches a pipeline. The column exists so the response echoes what was
    persisted rather than a literal written in two places."""

    caller_email = fields.CharField(max_length=EMAIL_MAX_LENGTH, null=True)
    """Mesh-injected identity, or null. Written from `Submission.caller_email`, which is null
    until `OME-1011`'s adapter — the one module allowed to read the header it comes from."""

    reply_to = fields.CharField(max_length=EMAIL_MAX_LENGTH, null=True)
    """Self-asserted by the reporter and never identity. It is how a responder answers an SDK
    report at all: the Python client parses only `exp` from its Access token, so it has no email
    of its own."""

    delivery_state = fields.CharField(max_length=16, default="pending", db_index=True)
    """`pending` | `queued` | `delivered` | `failed`. Indexed because `OME-1010`'s due-scan
    filters on it every sweep."""

    attempts = fields.IntField(default=0)

    next_attempt_at = fields.DatetimeField()
    """NOT NULL, set to the insert instant so the first attempt is due immediately. See the
    module docstring for why this is a timestamp and never a state."""

    lease_expires_at = fields.DatetimeField()
    """NOT NULL, set to the insert instant so the row starts unleased. `OME-1010` claims rows by
    conditional UPDATE against this, which is what stops `replicaCount > 1` double-delivering."""

    ticket_id = fields.CharField(max_length=64, null=True)
    ticket_url = fields.CharField(max_length=2048, null=True)

    request_fingerprint = fields.CharField(max_length=64, db_index=True)
    """A digest of the stored payload, for dedup DIAGNOSTICS only.

    INVARIANT: nothing resolves a replay from this column. It answers "did we already see this
    exact report under a different key?" for a human reading the table, and answering a request
    from it would reintroduce `OME-970` — returning another submission's `ref`.
    """

    created_at = fields.DatetimeField()
    """Set explicitly by the store, NOT `auto_now_add`.

    `auto_now_add` would stamp this from a second clock — the ORM's own `datetime.now` at INSERT
    — while every policy that reads it (the idempotency window, the retention cut-off) compares
    against the store's injected clock. Two clocks that agree in production and disagree under
    test is the worst arrangement of the three: the window silently measures something other than
    what its tests assert. One clock, passed in.
    """

    updated_at = fields.DatetimeField(auto_now=True)
    """`auto_now` is right here: nothing compares this against a policy window. It carries "when
    did this row last change", which with `delivery_state` is why plan §2.3 has no
    `delivered_at`."""


class Report(BaseReport):
    class Meta:
        table = "reports"
        indexes = [Index(fields=["delivery_state", "next_attempt_at"])]
        """`OME-1010`'s due-scan predicate, in the order it filters: state first (it is the
        selective half — `queued` and `delivered` rows are terminal and never scanned), then the
        deadline."""

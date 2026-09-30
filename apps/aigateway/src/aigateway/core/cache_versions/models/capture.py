"""The capture tables: the prompt store and the run index (OME-1307, GW-capture).

# FEATURE: OME-1307 (E14) - a traced chat call leaves one thin index row in
# `cache_capture_entry`; the prompt text lives once per key in `request_cache_prompt`.
# INVARIANT (CV-D13): a prompt row is kept for as long as any capture row or live cache row names
# its key. Capture is kept forever; only an operator prune removes rows (`maintenance.py`).
# WHY TEXT and not JSONB: the live cache stores TEXT, and JSONB rewrites number and key forms,
# which could break the reproducible archive digest (plan OD-3).
"""

from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class RequestCachePrompt(Model):
    class Meta:
        table = "request_cache_prompt"

    # INVARIANT: the primary key IS the cache key hash, so a prompt is stored once per key (CV-24).
    key_hash = fields.CharField(max_length=64, primary_key=True)
    # The canonical key material, which is the prompt text. Never logged.
    request_json = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)


class CacheCaptureEntry(Model):
    class Meta:
        table = "cache_capture_entry"
        indexes = (("account_id", "trace_id", "ordinal"), ("key_hash",))

    # WHY a database-generated BIGINT primary key (plan OD-4): exact arrival order across gateway
    # replicas without a clock or a lock.
    ordinal = fields.BigIntField(primary_key=True)
    account_id = fields.CharField(max_length=64)
    trace_id = fields.CharField(max_length=32)
    # NULL for a call with no capture key: a stream, a provider with no projection (plan OD-2).
    key_hash = fields.CharField(max_length=64, null=True)
    outcome = fields.CharField(max_length=16)
    # INVARIANT (CV-D8): set only for the inline outcomes (`unstored`, `bypass`, `version_hit`).
    response_json = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
